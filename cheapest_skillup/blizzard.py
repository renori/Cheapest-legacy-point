"""Fetch WoW Forever auction house prices from the Blizzard Battle.net API.

    BLIZZARD_CLIENT_ID=... BLIZZARD_CLIENT_SECRET=... python -m cheapest_skillup.blizzard --out site/data/prices --region us eu

Writes, per region, one file per auction house: prices/<region>/<house>.json =
{item id: [cheapest buyout per item (copper), quantity listed]}, and prices/index.json
describing the houses and when they were fetched.

Forever has no realms: auction houses hang off rulesets (dynamic-forever-<region>
namespace, /data/wow/ruleset/{id}/auctions/). Every ruleset currently lists the same
houses, so one ruleset is enough. The client ID and secret are read from the
environment only and never printed or written anywhere.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "cheapest-skillup/1.0"}


def token() -> str:
    cid, secret = os.environ.get("BLIZZARD_CLIENT_ID", ""), os.environ.get("BLIZZARD_CLIENT_SECRET", "")
    if not cid or not secret:
        sys.exit("Set BLIZZARD_CLIENT_ID and BLIZZARD_CLIENT_SECRET (a Battle.net API client).")
    basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    req = urllib.request.Request("https://oauth.battle.net/token", data=b"grant_type=client_credentials",
                                 headers={**UA, "Authorization": f"Basic {basic}",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["access_token"]
    except urllib.error.HTTPError as e:
        sys.exit(f"Battle.net refused the client ID/secret (HTTP {e.code}).")


class Api:
    def __init__(self, region: str, access_token: str):
        self.region, self._token = region, access_token

    def get(self, path: str, retries: int = 3) -> dict | None:
        q = urllib.parse.urlencode({"namespace": f"dynamic-forever-{self.region}", "locale": "en_US"})
        req = urllib.request.Request(f"https://{self.region}.api.blizzard.com{path}?{q}",
                                     headers={**UA, "Authorization": f"Bearer {self._token}"})
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise SystemExit(f"Blizzard API answered {e.code} for {path}") from None
        return None


def faction(name: str) -> str:
    n = name.lower()
    return "a" if "alliance" in n else "h" if "horde" in n else "n"  # n: neutral (Blackwater)


def summarize(auctions: list[dict], commodities: list[dict]) -> dict[str, list[int]]:
    """{item: [cheapest buyout per item, total quantity listed]} (bid-only auctions are skipped)."""
    best: dict[int, list[int]] = {}
    for a in auctions:
        qty = a.get("quantity") or 1
        if "buyout" not in a or not a["buyout"]:
            continue
        item, unit = a["item"]["id"], a["buyout"] // qty if qty else a["buyout"]
        cur = best.setdefault(item, [unit, 0])
        cur[0] = min(cur[0], unit)
        cur[1] += qty
    for c in commodities:
        item, unit, qty = c["item"]["id"], c.get("unit_price"), c.get("quantity") or 0
        if not unit:
            continue
        cur = best.setdefault(item, [unit, 0])
        cur[0] = min(cur[0], unit)
        cur[1] += qty
    return {str(k): v for k, v in sorted(best.items())}


def fetch_region(region: str, access_token: str, out: Path) -> list[dict]:
    api = Api(region, access_token)
    rulesets = (api.get("/data/wow/ruleset/index") or {}).get("rulesets", [])
    if not rulesets:
        print(f"{region}: no Forever rulesets", file=sys.stderr)
        return []
    rs = rulesets[0]["id"]  # every ruleset lists the same houses for now
    houses = (api.get(f"/data/wow/ruleset/{rs}/auctions/") or {}).get("auctions", [])
    result = []
    for h in houses:
        hid = h["id"]
        data = api.get(f"/data/wow/ruleset/{rs}/auctions/{hid}") or {}
        comm = api.get(f"/data/wow/ruleset/{rs}/auctions/{hid}/commodities") or {}
        prices = summarize(data.get("auctions") or [], comm.get("auctions") or [])
        path = out / region / f"{hid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(prices, separators=(",", ":")), encoding="utf-8")
        result.append({"region": region, "id": hid, "name": h.get("name", f"House {hid}"),
                       "faction": faction(h.get("name", "")), "items": len(prices),
                       "listings": len(data.get("auctions") or []) + len(comm.get("auctions") or [])})
        print(f"{region} {hid} {h.get('name')}: {len(prices)} items", file=sys.stderr)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cheapest_skillup.blizzard", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("site/data/prices"))
    ap.add_argument("--region", nargs="+", default=["us", "eu"])
    args = ap.parse_args(argv)
    t = token()
    houses = []
    for region in args.region:
        houses += fetch_region(region, t, args.out)
    if not houses:
        sys.exit("No auction houses fetched.")
    index = {"fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "houses": houses}
    (args.out / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(f"{len(houses)} auction houses -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
