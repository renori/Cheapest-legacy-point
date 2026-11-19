"""Fetch WoW Forever auction house prices from the Blizzard Battle.net API.

    BLIZZARD_CLIENT_ID=... BLIZZARD_CLIENT_SECRET=... python -m cheapest_skillup.blizzard --out site/data/prices --region us eu

Writes, per region, one file per auction house: prices/<region>/<house>.json =
{item id: [cheapest buyout per item (copper), quantity listed]}, and prices/index.json
describing the houses and when they were fetched.

Forever has no realms: auction houses hang off rulesets (dynamic-forever-<region>
namespace, /data/wow/ruleset/{id}/auctions/), one Alliance, Horde and Blackwater house
per ruleset (PvP, Normal, Roleplay, ...). Each house is fetched once and tagged with its
ruleset where the API says which one it is. The client ID and secret are read from the
environment only and never printed or written anywhere.
"""

from __future__ import annotations

import argparse
import base64
import gzip
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
                                     headers={**UA, "Authorization": f"Bearer {self._token}", "Accept-Encoding": "gzip"})
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    body = r.read()
                    if r.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)  # houses are up to ~10 MB of JSON
                    return json.loads(body)
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


def ruleset_ref(value) -> tuple[int | None, str | None]:
    """The ruleset a house response names: {"id":..,"name":..} or a bare id."""
    if isinstance(value, dict):
        rid = value.get("id")
        name = value.get("name")
        if isinstance(name, dict):  # localized name objects
            name = name.get("en_US") or next(iter(name.values()), None)
        return (int(rid) if rid is not None else None), name
    if isinstance(value, int):
        return value, None
    return None, None


def assign_rulesets(rulesets: dict[int, str], listed: dict[int, list[int]],
                    reported: dict[int, int | None]) -> dict[int, int | None]:
    """Which ruleset each house belongs to.

    1. If house responses name different rulesets, trust them.
    2. Else if the per-ruleset house lists differ, a house belongs to the ruleset(s) that list it
       (only when exactly one does).
    3. Else unknown (None)."""
    houses = sorted({h for hs in listed.values() for h in hs} | set(reported))
    if len({r for r in reported.values() if r is not None}) > 1:
        return {h: reported.get(h) for h in houses}
    lists = {rid: set(hs) for rid, hs in listed.items()}
    if len({frozenset(v) for v in lists.values()}) > 1:
        out = {}
        for h in houses:
            owners = [rid for rid, hs in lists.items() if h in hs]
            out[h] = owners[0] if len(owners) == 1 else None
        return out
    return {h: None for h in houses}


def infer_rulesets(rulesets: dict[int, str], houses: list[dict]) -> dict[int, int]:
    """Guess each house's ruleset when the API doesn't say (so far it never does).

    Houses come in sets of one Alliance, one Horde and one Blackwater house: the n-th house of each
    faction, by ID. Sets were created in ruleset order (US/EU: 110/113/116, 111/114/117, then later
    119/120/121 and 123/124/125), and the busy pair matches PvP and Normal, the quieter pair Roleplay
    and Roleplay PvP. Sets with no auctions at all (112/115/118: a ruleset not live yet) are skipped.
    Returns {house: ruleset} only when the live sets and the rulesets pair up one to one."""
    rank = {}
    for f in ("a", "h", "n"):
        for i, h in enumerate(sorted((h for h in houses if h["faction"] == f), key=lambda h: h["id"])):
            rank[h["id"]] = i
    sets: dict[int, list[dict]] = {}
    for h in houses:
        sets.setdefault(rank[h["id"]], []).append(h)
    live = [hs for _, hs in sorted(sets.items()) if sum(h["listings"] for h in hs) > 0]
    if len(live) != len(rulesets):
        return {}
    return {h["id"]: rid for hs, rid in zip(live, sorted(rulesets)) for h in hs}


def fetch_region(region: str, access_token: str, out: Path) -> list[dict]:
    api = Api(region, access_token)
    index = (api.get("/data/wow/ruleset/index") or {}).get("rulesets", [])
    if not index:
        print(f"{region}: no Forever rulesets", file=sys.stderr)
        return []
    rulesets: dict[int, str] = {}
    for r in index:
        rid, name = ruleset_ref(r)
        if rid is not None:
            rulesets[rid] = name or (api.get(f"/data/wow/ruleset/{rid}") or {}).get("name") or f"Ruleset {rid}"
    # Every ruleset's house list (cheap). Forever has so far listed the same houses under every ruleset.
    listed: dict[int, list[int]] = {}
    names: dict[int, str] = {}
    for rid in rulesets:
        hs = ((api.get(f"/data/wow/ruleset/{rid}/auctions/") or api.get(f"/data/wow/ruleset/{rid}/auctions/index") or {})
              .get("auctions", []))
        listed[rid] = [h["id"] for h in hs]
        for h in hs:
            name = h.get("name") or f"House {h['id']}"
            if isinstance(name, dict):  # localized: {"en_US": ...}
                name = name.get("en_US") or next(iter(name.values()), f"House {h['id']}")
            names[h["id"]] = name
    print(f"{region} rulesets: " + ", ".join(f"{rid}={n} houses={sorted(listed[rid])}" for rid, n in rulesets.items()),
          file=sys.stderr)
    rs = next(iter(rulesets))
    result, reported = [], {}
    for hid in sorted(names):
        data = api.get(f"/data/wow/ruleset/{rs}/auctions/{hid}") or {}
        comm = api.get(f"/data/wow/ruleset/{rs}/auctions/{hid}/commodities") or {}
        reported[hid] = ruleset_ref(data.get("ruleset"))[0]
        prices = summarize(data.get("auctions") or [], comm.get("auctions") or [])
        path = out / region / f"{hid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(prices, separators=(",", ":")), encoding="utf-8")
        result.append({"region": region, "id": hid, "name": names[hid], "faction": faction(names[hid]),
                       "items": len(prices),
                       "listings": len(data.get("auctions") or []) + len(comm.get("auctions") or [])})
        print(f"{region} house {hid} {names[hid]}: ruleset field={data.get('ruleset')!r} "
              f"{result[-1]['listings']} listings, {len(prices)} items", file=sys.stderr)
    owner = assign_rulesets(rulesets, listed, reported)
    inferred = not any(v is not None for v in owner.values())
    if inferred:
        owner = infer_rulesets(rulesets, result)
    for h in result:
        rid = owner.get(h["id"])
        h["ruleset"] = rid
        h["ruleset_name"] = rulesets.get(rid) if rid is not None else None
        h["ruleset_inferred"] = inferred and rid is not None
    print(f"{region} ruleset per house{' (inferred from house IDs)' if inferred else ''}: "
          + ", ".join(f"{h['id']}={h['ruleset_name']}" for h in result), file=sys.stderr)
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
