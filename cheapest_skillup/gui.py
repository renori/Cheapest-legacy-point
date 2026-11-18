"""Browser GUI: python -m cheapest_skillup.gui

Starts a small web server on 127.0.0.1 (only this computer can reach it)
and opens the planner in your default browser. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import threading
import traceback
import urllib.error
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .cli import PRICE_FIELDS, plan_to_dict
from .optimizer import Optimizer
from .prices import load_pricebook
from .recipes import available_professions, load_profession, load_vendor_names, load_vendor_prices, load_vendor_sell

PAGE = Path(__file__).resolve().parent / "web" / "index.html"
REALMS = ["normal-alliance", "normal-horde", "pvp-alliance", "pvp-horde"]
REGIONS = ["us", "eu"]
_lock = threading.Lock()  # one plan at a time keeps the download cache simple


def options() -> dict:
    profs = []
    for key in available_professions():
        p = load_profession(key)
        profs.append({"key": key, "name": p.name})
    return {
        "professions": profs,
        "regions": REGIONS,
        "realms": REALMS,
        "price_fields": list(PRICE_FIELDS),
        "sources": ["trainer", "vendor", "quest", "drop"],
        "defaults": {"game": "forever", "region": "us", "realm": "pvp-horde", "price": "minBuyout",
                     "from": 1, "to": 150, "sources": ["trainer", "vendor"], "sell_back": "none"},
    }


def make_plan(q: dict[str, list[str]]) -> dict:
    get = lambda k, d: (q.get(k) or [d])[0]  # noqa: E731
    profs = [p for p in get("professions", "").split(",") if p] or available_professions()
    known = set(available_professions())
    bad = [p for p in profs if p not in known]
    if bad:
        raise ValueError(f"Unknown profession: {', '.join(bad)}")
    price = get("price", "minBuyout")
    if price not in PRICE_FIELDS:
        raise ValueError(f"Unknown price field: {price}")
    start, target = int(get("from", "1")), int(get("to", "150"))
    if not (1 <= start < target <= 450):
        raise ValueError("Skill range must satisfy 1 <= from < to.")
    game, region, realm = get("game", "forever"), get("region", "us"), get("realm", "pvp-horde")
    sources = {s for s in get("sources", "trainer,vendor").split(",") if s}
    sell_back = get("sell_back", "none")
    if sell_back not in ("none", "vendor", "ah"):
        raise ValueError(f"Unknown sell-back mode: {sell_back}")
    sell_back = None if sell_back == "none" else sell_back
    overrides = {}
    for pair in get("overrides", "").split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            overrides[int(k)] = int(v)

    vendor_names = load_vendor_names()
    with _lock:
        prices, updated = load_pricebook(game, region, realm, load_vendor_prices(), price,
                                         refresh=get("refresh", "0") == "1", overrides=overrides,
                                         vendor_sell=load_vendor_sell())
    plans = [Optimizer(load_profession(k), prices, sources, sell_back).plan(start, target) for k in profs]
    return {
        "prices_updated": updated,
        "auction_house": f"{game}/{region}/{realm}",
        "price_field": price,
        "plans": [plan_to_dict(p, prices, vendor_names) for p in plans],
    }


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
