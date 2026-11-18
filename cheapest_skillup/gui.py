"""Browser GUI: python -m cheapest_skillup.gui

Starts a small web server on 127.0.0.1 (only this computer can reach it)
and opens the planner in your default browser. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import traceback
import urllib.error
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .cli import PRICE_FIELDS, plan_to_dict, side_of
from .optimizer import cheapest_plan
from .prices import CACHE_TTL_SECONDS, load_pricebook
from .recipes import (available_professions, load_foreverdb, load_item_names, load_profession, load_vendor_names, load_vendor_prices,
                      load_vendor_sell)

PAGE = Path(__file__).resolve().parent / "web" / "index.html"
REALMS = ["normal-alliance", "normal-horde", "pvp-alliance", "pvp-horde"]
REGIONS = ["us", "eu"]
MILESTONES = [75, 150, 225, 300]
MAX_SKILL = 300
_lock = threading.Lock()  # one price download at a time
_books: dict[tuple, tuple] = {}  # settings -> (PriceBook, updated, loaded at)
_plans: dict[tuple, dict] = {}  # (settings, profession, from, to) -> plan dict
PLAN_CACHE = 256


def options() -> dict:
    profs = [{"key": k, "name": load_profession(k).name} for k in available_professions()]
    return {
        "professions": profs,
        "regions": REGIONS,
        "realms": REALMS,
        "price_fields": list(PRICE_FIELDS),
        "sources": ["trainer", "vendor", "recipe"],
        "milestones": MILESTONES,
        "max_skill": MAX_SKILL,
        "defaults": {"game": "forever", "region": "us", "realm": "pvp-horde", "price": "minBuyout",
                     "sources": ["trainer", "vendor", "recipe"], "sell_back": "none", "target": 150},
    }


def _settings(q: dict[str, list[str]]) -> tuple:
    get = lambda k, d: (q.get(k) or [d])[0]  # noqa: E731
    price = get("price", "minBuyout")
    if price not in PRICE_FIELDS:
        raise ValueError(f"Unknown price field: {price}")
    sell_back = get("sell_back", "none")
    if sell_back not in ("none", "vendor", "ah"):
        raise ValueError(f"Unknown sell-back mode: {sell_back}")
    overrides = []
    for pair in get("overrides", "").split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            overrides.append((int(k), int(v)))
    sources = tuple(sorted(s for s in get("sources", "trainer,vendor,recipe").split(",") if s))
    return (get("game", "forever"), get("region", "us"), get("realm", "pvp-horde"), price, sources,
            None if sell_back == "none" else sell_back, tuple(sorted(overrides)))


def _pricebook(settings: tuple, refresh: bool):
    game, region, realm, price, _, _, overrides = settings
    key = (game, region, realm, price, overrides)
    with _lock:
        hit = _books.get(key)
        if refresh or not hit or time.time() - hit[2] > CACHE_TTL_SECONDS:
            prices, updated = load_pricebook(game, region, realm, load_vendor_prices(), price, refresh=refresh,
                                             overrides=dict(overrides), vendor_sell=load_vendor_sell(),
                                             names=load_item_names())
            hit = (prices, updated, time.time())
            _books[key] = hit
            for k in [k for k in _plans if k[0][:4] + (k[0][6],) == key]:
                del _plans[k]  # new prices: re-plan
        return hit[0], hit[1]


def _profession(q: dict[str, list[str]]) -> str:
    prof = (q.get("prof") or [""])[0]
    if prof not in available_professions():
        raise ValueError(f"Unknown profession: {prof}")
    return prof


def _skill(q: dict[str, list[str]], name: str, default: int) -> int:
    try:
        v = int((q.get(name) or [default])[0])
    except ValueError:
        raise ValueError(f"{name} must be a number") from None
    if not 1 <= v <= MAX_SKILL:
        raise ValueError(f"{name} must be between 1 and {MAX_SKILL}")
    return v


def _plan(settings: tuple, prof: str, start: int, target: int, prices, updated) -> dict:
    key = (settings, prof, start, target)
    if key not in _plans:
        _, _, realm, _, sources, sell_back, _ = settings
        plan = cheapest_plan(load_profession(prof), prices, start, target, set(sources), sell_back, side_of(realm))
        vendor_names = {**load_item_names(), **load_vendor_names()}
        if len(_plans) >= PLAN_CACHE:
            _plans.pop(next(iter(_plans)))
        _plans[key] = plan_to_dict(plan, prices, vendor_names, side_of(realm))
    return _plans[key]


def make_overview(q: dict[str, list[str]]) -> dict:
    """Cost from your skill to each milestone (and your target) for one profession."""
    settings, prof = _settings(q), _profession(q)
    start, target = _skill(q, "from", 1), _skill(q, "to", 150)
    prices, updated = _pricebook(settings, (q.get("refresh") or ["0"])[0] == "1")
    goals = sorted({m for m in MILESTONES if m > start} | ({target} if target > start else set()))
    rows = []
    for goal in goals:
        p = _plan(settings, prof, start, goal, prices, updated)
        rows.append({"to": goal, "total_copper": p["grand_total_copper"], "reached": p["reached"]})
    return {"prof": prof, "from": start, "to": target, "milestones": rows, "prices_updated": updated,
            "auction_house": "/".join(settings[:3])}


def make_plan(q: dict[str, list[str]]) -> dict:
    """The full route for one profession."""
    settings, prof = _settings(q), _profession(q)
    start, target = _skill(q, "from", 1), _skill(q, "to", 150)
    if start >= target:
        raise ValueError("Target must be above your current skill.")
    prices, updated = _pricebook(settings, (q.get("refresh") or ["0"])[0] == "1")
    return {"prices_updated": updated, "auction_house": "/".join(settings[:3]), "price_field": settings[3],
            "plan": _plan(settings, prof, start, target, prices, updated), "foreverdb": bool(load_foreverdb())}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        try:
            if url.path in ("/", "/index.html"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/options":
                self._json(200, options())
            elif url.path == "/api/overview":
                self._json(200, make_overview(parse_qs(url.query)))
            elif url.path == "/api/plan":
                self._json(200, make_plan(parse_qs(url.query)))
            else:
                self._json(404, {"error": "not found"})
        except urllib.error.HTTPError as e:
            msg = "TSM has no data for that auction house (check region/realm)." if e.code == 404 else f"TSM download failed: {e}"
            self._json(502, {"error": msg})
        except urllib.error.URLError as e:
            self._json(502, {"error": f"Could not reach TSM: {e.reason}"})
        except ValueError as e:
            self._json(400, {"error": str(e)})
        except Exception as e:  # pragma: no cover
            traceback.print_exc()
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def log_message(self, fmt: str, *args) -> None:  # keep the terminal quiet
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cheapest_skillup.gui", description="Open the planner in your browser.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    args = ap.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Cheapest Skill-up is running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
