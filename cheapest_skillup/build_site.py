"""Build the static website: python -m cheapest_skillup.build_site [--out site]

Copies the web app (cheapest_skillup/site/) to the output folder and writes
its data files, everything the browser planner (planner.js) needs:

* data/professions.json  every recipe and rank, fully resolved: skill colours,
                         reagents, how it is learned and what that costs, and
                         the trainers / vendors on each faction
* data/items.json        item names, what a vendor charges (per faction) and
                         what a vendor pays you, for every item the recipes use
* data/npcs.json         trainers and vendors: name, title, zone, coordinates
* data/meta.json         game build, credits and when the data was built

Prices come separately from the Blizzard API (python -m cheapest_skillup.blizzard),
into data/prices/.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from .recipes import (DATA_DIR, available_professions, load_item_names, load_profession, load_vendor_names,
                      load_vendor_prices, load_vendor_sell, load_trainer_npcs)

SITE_SRC = Path(__file__).resolve().parent / "site"
SIDES = ("a", "h")


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


def recipe_json(prof, r) -> dict:
    out = {
        "n": r.name, "s": r.spell, "k": [r.orange, r.yellow, r.green, r.grey],
        "r": {str(i): q for i, q in r.reagents.items()}, "src": r.source,
        "lk": r.learn_known, "lf": r.learn_from,
    }
    if r.makes:
        out["m"], out["q"] = r.makes, r.makes_qty
    if r.tools:
        out["t"] = r.tools
    if r.source == "trainer":
        out["fee"], out["ff"] = r.learn_cost, r.fee_from
        out["tr"] = {side: [n["id"] for n in prof.trainers_for(r, side)] for side in SIDES}
    if r.source == "recipe":
        out["ri"] = r.recipe_items
        out["v"] = {side: [[n["id"], n["price"]] for n in prof.vendors_for(r, side)] for side in SIDES}
    return out


def rank_json(prof, k) -> dict:
    out = {"n": k.name, "cap": k.cap, "sk": k.skill, "lv": k.level, "cost": k.cost, "cf": k.cost_from, "how": k.how}
    if k.item:
        out["item"] = k.item
    if k.how == "trainer":
        out["tr"] = {side: [n["id"] for n in prof.trainers_for(k, side)] for side in SIDES}
    return out


def build(out: Path) -> dict:
    if out.exists():
        for child in out.iterdir():
            if child.name != "data":
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    shutil.copytree(SITE_SRC, out, dirs_exist_ok=True)

    professions, items, npc_ids = {}, set(), set()
    for key in available_professions():
        prof = load_profession(key)
        recipes = [recipe_json(prof, r) for r in prof.recipes]
        ranks = [rank_json(prof, k) for k in prof.ranks]
        professions[key] = {"name": prof.name, "recipes": recipes, "ranks": ranks}
        for r in recipes:
            items.update(int(i) for i in r["r"])
            items.update(x for x in [r.get("m")] + r.get("t", []) + r.get("ri", []) if x)
            for ids in r.get("tr", {}).values():
                npc_ids.update(ids)
            for rows in r.get("v", {}).values():
                npc_ids.update(n for n, _ in rows)
        for k in ranks:
            if k.get("item"):
                items.add(k["item"])
            for ids in k.get("tr", {}).values():
                npc_ids.update(ids)

    names = {**load_item_names(), **load_vendor_names()}
    vendor = {side: load_vendor_prices(side=side) for side in SIDES}
    sell = load_vendor_sell()
    item_data = {}
    for i in sorted(items):
        row = {"n": names.get(i, f"item {i}")}
        for side in SIDES:
            if i in vendor[side]:
                row["v" + side] = vendor[side][i]
        if sell.get(i):
            row["sell"] = sell[i]
        item_data[str(i)] = row

    all_npcs = load_trainer_npcs()
    npcs = {str(i): {k: all_npcs[i][k] for k in ("name", "title", "side", "zone", "x", "y", "seen")}
            for i in sorted(npc_ids) if i in all_npcs}

    build_info = json.loads((DATA_DIR / "recipes" / "tailoring.json").read_text(encoding="utf-8")).get("build")
    meta = {
        "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "game_build": build_info,
        "credits": {
            "foreverdb": "Data from ForeverDB.net (https://foreverdb.net)",
            "blizzard": "Auction prices from the Blizzard Battle.net API",
            "wago": "Game data via wago.tools",
            "cmangos": "Classic trainer estimates from CMaNGOS classic-db (GPL-3.0)",
        },
    }
    _dump(out / "data" / "professions.json", professions)
    _dump(out / "data" / "items.json", item_data)
    _dump(out / "data" / "npcs.json", npcs)
    _dump(out / "data" / "meta.json", meta)
    return {"professions": len(professions), "recipes": sum(len(p["recipes"]) for p in professions.values()),
            "items": len(item_data), "npcs": len(npcs)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cheapest_skillup.build_site", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("site"))
    args = ap.parse_args(argv)
    stats = build(args.out)
    print(f"Built {args.out}: {stats}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
