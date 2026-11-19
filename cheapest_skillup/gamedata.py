"""Import WoW Forever recipes from the game's own data tables.

    python -m cheapest_skillup.gamedata            # latest WoW Forever build
    python -m cheapest_skillup.gamedata --build 1.60.1.70959

Downloads the client's DB2 tables as CSV from wago.tools (product "wowf")
and regenerates:

* data/recipes/<profession>.json  every craft with its reagents, product and
  skill-up colours (yellow/grey from the game, green halfway between)
* data/vendor_sell.json           vendor sell price of every crafted item
* data/item_names.json            names of every item the recipes mention
* data/vendor_items.json          refreshed vendor buy prices of trade supplies

How a recipe is learned:

* "auto"    learned with the profession (free, from skill 1)
* "recipe"  taught by a recipe item (Pattern:/Recipe:/Plans:/...); the item's
            required skill is the learn level. The planner uses it only when
            the item is listed on your auction house, at its AH price.
            Bind-on-pickup recipe items (quest rewards, BoP drops) never are.
* "trainer" everything else. The game files hold neither the trainer's fee
            nor the skill needed to train it; enter them in data/trainer.json.
            Until then the planner assumes you can train it at its yellow level
            (never too early) and that it is free.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

from .prices import default_cache_dir
from .recipes import DATA_DIR

WAGO = "https://wago.tools"
PRODUCT = "wowf"  # WoW Forever
TABLES = ["SkillLineAbility", "SpellName", "SpellReagents", "SpellEffect", "SpellTotems", "ItemSparse"]
PROFESSIONS = {
    171: ("alchemy", "Alchemy"),
    164: ("blacksmithing", "Blacksmithing"),
    185: ("cooking", "Cooking"),
    333: ("enchanting", "Enchanting"),
    202: ("engineering", "Engineering"),
    129: ("first_aid", "First Aid"),
    165: ("leatherworking", "Leatherworking"),
    197: ("tailoring", "Tailoring"),
}
CREATE_ITEM = 24
RECIPE_ITEM = re.compile(r"^(?:Pattern|Recipe|Plans|Schematic|Formula|Manual|Design|Technique): (.+)$")
BIND_ON_PICKUP = 1


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "cheapest-skillup"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def latest_build() -> str:
    builds = json.loads(_get(f"{WAGO}/api/builds"))
    return builds[PRODUCT][0]["version"]


def load_table(name: str, build: str) -> list[dict[str, str]]:
    path = default_cache_dir() / "gamedata" / build / f"{name}.csv"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"  downloading {name}...", file=sys.stderr)
        path.write_bytes(_get(f"{WAGO}/db2/{name}/csv?build={build}"))
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))


def _i(v: str | None) -> int:
    try:
        return int(float(v or 0))
    except ValueError:
        return 0


def build_data(t: dict[str, list[dict[str, str]]]) -> tuple[dict[str, dict], dict[int, dict], dict[int, str]]:
    spell_name = {_i(r["ID"]): r["Name_lang"] for r in t["SpellName"]}
    items = {_i(r["ID"]): r for r in t["ItemSparse"]}

    reagents: dict[int, dict[int, int]] = {}
    for r in t["SpellReagents"]:
        reagents[_i(r["SpellID"])] = {
            _i(r[f"Reagent_{k}"]): _i(r[f"ReagentCount_{k}"]) for k in range(8) if _i(r[f"Reagent_{k}"]) > 0 and _i(r[f"ReagentCount_{k}"]) > 0
        }
    makes: dict[int, tuple[int, int]] = {}
    for r in t["SpellEffect"]:
        if _i(r["Effect"]) == CREATE_ITEM and _i(r["EffectItemType"]):
            makes.setdefault(_i(r["SpellID"]), (_i(r["EffectItemType"]), max(1, _i(r["EffectBasePointsF"]))))

    # Tools: specific items, or a totem category (e.g. "Runed Copper Rod" category) -> lowest-level item in it.
    by_category: dict[int, int] = {}
    for iid, it in sorted(items.items(), key=lambda kv: (_i(kv[1]["ItemLevel"]), kv[0])):
        cat = _i(it["TotemCategoryID"])
        if cat and cat not in by_category:
            by_category[cat] = iid
    tools: dict[int, list[int]] = defaultdict(list)
    for r in t["SpellTotems"]:
        sid = _i(r["SpellID"])
        for k in (0, 1):
            if _i(r[f"Totem_{k}"]):
                tools[sid].append(_i(r[f"Totem_{k}"]))
            cat = _i(r[f"RequiredTotemCategoryID_{k}"])
            if cat and cat in by_category:
                tools[sid].append(by_category[cat])

    # Recipe items: "Pattern: Bolt of Woolen Cloth" teaches the craft named "Bolt of Woolen Cloth".
    teachers: dict[tuple[int, str], list[int]] = defaultdict(list)
    for iid, it in items.items():
        m = RECIPE_ITEM.match(it["Display_lang"])
        if m and _i(it["RequiredSkill"]) in PROFESSIONS and _i(it["Bonding"]) != BIND_ON_PICKUP:
            teachers[(_i(it["RequiredSkill"]), m.group(1))].append(iid)
    bop_taught: set[tuple[int, str]] = set()
    for iid, it in items.items():
        m = RECIPE_ITEM.match(it["Display_lang"])
        if m and _i(it["RequiredSkill"]) in PROFESSIONS and _i(it["Bonding"]) == BIND_ON_PICKUP:
            bop_taught.add((_i(it["RequiredSkill"]), m.group(1)))

    professions: dict[str, dict] = {}
    seen: set[int] = set()
    used_items: set[int] = set()
    for line, (key, title) in PROFESSIONS.items():
        recipes = []
        for r in t["SkillLineAbility"]:
            if _i(r["SkillLine"]) != line:
                continue
            sid = _i(r["Spell"])
            yellow, grey = _i(r["TrivialSkillLineRankLow"]), _i(r["TrivialSkillLineRankHigh"])
            if sid in seen or grey <= 0 or _i(r["NumSkillUps"]) == 0 or not reagents.get(sid):
                continue  # profession rank spells, crafts that never skill up, or no reagents
            seen.add(sid)
            name = spell_name.get(sid, f"spell {sid}")
            teach = teachers.get((line, name), [])
            if _i(r["AcquireMethod"]) == 1:
                how, learn, known = "auto", 1, True
            elif teach:
                how = "recipe"
                learn, known = min(_i(items[i]["RequiredSkillRank"]) for i in teach), True
            elif (line, name) in bop_taught:
                continue  # only from a bind-on-pickup item: quest reward or BoP drop
            else:
                how = "trainer"
                learn, known = (_i(r["MinSkillLineRank"]), True) if _i(r["MinSkillLineRank"]) > 1 else (max(1, yellow), False)
            learn = max(1, min(learn, grey - 1))
            yellow = max(yellow, learn)
            entry = {
                "name": name,
                "spell": sid,
                "skill": [learn, yellow, (yellow + grey) // 2, grey],
                "learn": how,
                "learn_level_known": known,
                "reagents": {str(k): v for k, v in reagents[sid].items()},
            }
            if teach:
                entry["recipe_items"] = sorted(teach)
                used_items.update(teach)
            if sid in makes:
                item, qty = makes[sid]
                entry["makes"] = {"item": item, "qty": qty}
                used_items.add(item)
            if tools.get(sid):
                entry["tools"] = sorted(set(tools[sid]))
                used_items.update(tools[sid])
            used_items.update(reagents[sid])
            recipes.append(entry)
        recipes.sort(key=lambda e: (e["skill"][1], e["skill"][3], e["name"]))
        professions[key] = {"name": title, "recipes": recipes}

    names = {i: items[i]["Display_lang"] for i in sorted(used_items) if i in items}
    # What a vendor pays you for each item the recipes use or make (0 = vendors won't buy it).
    sell = {i: {"name": items[i]["Display_lang"], "sell": _i(items[i]["SellPrice"])} for i in sorted(used_items) if i in items}
    return professions, sell, names


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cheapest_skillup.gamedata", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", help=f"game build (default: latest {PRODUCT} build on wago.tools)")
    args = ap.parse_args(argv)

    build = args.build or latest_build()
    print(f"WoW Forever build {build}", file=sys.stderr)
    tables = {name: load_table(name, build) for name in TABLES}
    professions, sell, names = build_data(tables)

    note = (f"Generated from WoW Forever build {build} game data (wago.tools) by "
            "'python -m cheapest_skillup.gamedata'. Do not edit by hand; put corrections in data/trainer.json.")
    (DATA_DIR / "recipes").mkdir(parents=True, exist_ok=True)
    for old in (DATA_DIR / "recipes").glob("*.json"):
        if old.stem not in professions:
            old.unlink()
    for key, prof in professions.items():
        out = {"name": prof["name"], "note": note, "build": build, "recipes": prof["recipes"]}
        (DATA_DIR / "recipes" / f"{key}.json").write_text(
            "{\n" + f'  "name": {json.dumps(out["name"])},\n  "note": {json.dumps(note)},\n  "build": {json.dumps(build)},\n'
            + '  "recipes": [\n' + ",\n".join("    " + json.dumps(r) for r in prof["recipes"]) + "\n  ]\n}\n",
            encoding="utf-8")
        print(f"  {prof['name']:<15} {len(prof['recipes']):>4} recipes", file=sys.stderr)

    # data/trainer.json: one entry per trainer recipe for you to fill in. Keep what is already there.
    tpath = DATA_DIR / "trainer.json"
    trainer = json.loads(tpath.read_text(encoding="utf-8")) if tpath.exists() else {}
    spells = trainer.get("spells", {})
    for prof in professions.values():
        for r in prof["recipes"]:
            if r["learn"] == "trainer":
                cur = spells.setdefault(str(r["spell"]), {"name": r["name"], "profession": prof["name"], "cost": None, "learn": None})
                cur["name"], cur["profession"] = r["name"], prof["name"]
    trainer = {
        "note": ("Trainer fees and learn levels are not in the game files. Fill in what the trainer shows: "
                 "'cost' in copper (1s 25c = 125), 'learn' = skill needed to train it. null = unknown "
                 "(fee counted as 0 and flagged; learn level assumed to be the recipe's yellow level)."),
        "spells": dict(sorted(spells.items(), key=lambda kv: (kv[1].get("profession", ""), kv[1].get("name", ""), int(kv[0])))),
    }
    tpath.write_text("{\n" + f'  "note": {json.dumps(trainer["note"])},\n  "spells": {{\n'
                     + ",\n".join(f"    {json.dumps(k)}: {json.dumps(v)}" for k, v in trainer["spells"].items())
                     + "\n  }\n}\n", encoding="utf-8")

    (DATA_DIR / "vendor_sell.json").write_text(json.dumps(
        {"note": f"What a vendor pays you (copper) for each item the recipes use or make, from build {build}.",
         "items": {str(k): v for k, v in sell.items()}}, indent=1) + "\n", encoding="utf-8")
    (DATA_DIR / "item_names.json").write_text(json.dumps(
        {"note": f"Item names from build {build}.", "items": {str(k): v for k, v in names.items()}}, indent=1) + "\n", encoding="utf-8")

    # Refresh vendor buy prices of the trade supplies we already list.
    vpath = DATA_DIR / "vendor_items.json"
    vendor = json.loads(vpath.read_text(encoding="utf-8"))
    items = {_i(r["ID"]): r for r in tables["ItemSparse"]}
    for k, v in vendor["items"].items():
        it = items.get(int(k))
        if it and _i(it["BuyPrice"]):
            # BuyPrice is for one purchase of VendorStackCount items (Empty Vial: 20c for 5); store per item.
            v["price"] = round(_i(it["BuyPrice"]) / max(1, _i(it.get("VendorStackCount")) or 1), 2)
            v["name"] = it["Display_lang"]
    vendor["note"] = (f"Reagents sold by trade-supply vendors; price per item, from build {build}. "
                      "The planner uses whichever is cheaper: this price or the AH.")
    vpath.write_text(json.dumps(vendor, indent=2) + "\n", encoding="utf-8")
    print("Done.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
