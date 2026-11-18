"""Import how recipes are learned, and Forever trainer fees, from ForeverDB.net.

    python -m cheapest_skillup.foreverdb

Downloads ForeverDB's free addon data file Data/Recipes.lua (no key needed)
and writes data/foreverdb.json. The planner uses it to:

* correct how each recipe is learned: automatically, from a trainer, or from
  a recipe item (including recipe items whose names Blizzard keeps on its
  servers, which the game files can't link by name);
* leave out recipes with no known way to learn them, and recipes ForeverDB
  marks as probably not in the live game (Season of Discovery leftovers...);
* use trainer fees players saw at Forever trainers;
* charge each profession rank (Journeyman, Expert, Artisan) at ForeverDB's
  fee, from the ForeverDB Helper addon's Data/Professions.lua.

Data from ForeverDB.net (https://foreverdb.net), GPL-3.0 with an attribution
term: credit "Data from ForeverDB.net (https://foreverdb.net)".
"""

from __future__ import annotations

import io
import json
import re
import sys
import zipfile

from .gamedata import _get, load_table
from .recipes import DATA_DIR

SITE = "https://foreverdb.net"
CREDIT = "Data from ForeverDB.net (https://foreverdb.net)"
OUT = DATA_DIR / "foreverdb.json"

_RECIPE = re.compile(
    r'\{(\d+),"((?:[^"\\]|\\.)*)",(-?\d+),(\d+),(\d+),(\d+),(\d+),([\d.]+),"([^"]*)","([^"]*)",(\d+),(\d+),(\d+)')
_INFO_ENTRY = re.compile(r'\[(\d+)\]=\{((?:[^{}]|\{[^{}]*\})*)\}')
_INFO_FIELD = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\{[^{}]*\}|[-\d.]+)')


def parse_recipes_lua(text: str) -> tuple[str, dict[int, dict]]:
    """-> (client build, {spell: learning info}) from ForeverDB's Data/Recipes.lua."""
    m = re.search(r"build (\d[\d.]*\d)", text[:300])
    build = m.group(1) if m else "unknown"
    split = text.find("ns.recipeInfo")
    recipes_part, info_part = (text[:split], text[split:]) if split >= 0 else (text, "")

    info: dict[int, dict[str, str]] = {}
    for m in _INFO_ENTRY.finditer(info_part):
        info[int(m.group(1))] = {k: v.strip('"') for k, v in _INFO_FIELD.findall(m.group(2))}

    out: dict[int, dict] = {}
    for m in _RECIPE.finditer(recipes_part):
        spell, need, learned, need_classic = int(m.group(1)), int(m.group(3)), m.group(10), m.group(13) == "1"
        extra = info.get(spell, {})
        how = {"a": "auto", "t": "trainer"}.get(learned, "recipe" if learned.startswith("i") else "unknown")
        entry: dict = {"name": m.group(2).replace('\\"', '"'), "learn": how}
        if how == "recipe":
            entry["recipe_items"] = [int(i) for i in re.findall(r"i(\d+)", learned)]
        if need > 0:
            entry["learn_level"] = need
            entry["learn_level_classic"] = need_classic
        if "tc" in extra:
            entry["fee"] = int(float(extra["tc"]))
            entry["fee_seen_in_forever"] = extra.get("tf") == "1"
        if "q" in extra:
            entry["quest"] = extra["q"]
        if "sp" in extra:
            entry["speculation"] = extra["sp"]
        out[spell] = entry
    return build, out


RANK_FILE = "ForeverDB_Helper/Data/Professions.lua"
_NPC = re.compile(r'\[(\d+)\]=\{"((?:[^"\\]|\\.)*)","((?:[^"\\]|\\.)*)","([ah])",(\d+),([-\d.]+),([-\d.]+),(\d)\}')
PROFESSION_KEYS = {"first-aid": "first_aid"}


def _ids(s: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", s)]


def _faction_lists(s: str) -> dict[str, list[int]]:
    """'a={1,2},h={3}' -> {"a": [1, 2], "h": [3]}."""
    return {side: _ids(ids) for side, ids in re.findall(r"\b([ah])=\{([\d,]*)\}", s)}


def parse_trainers_lua(text: str) -> tuple[dict[str, dict[str, list[int]]], dict[int, dict], dict[int, dict]]:
    """From ForeverDB Helper's Data/Professions.lua:
    rank trainers {profession: {cap: {"a": [npc], "h": [npc]}}},
    recipe trainers {spell: {"a": [npc], "h": [npc]}} for the recipes on ForeverDB's routes,
    trainers {npc: {name, title, side, map, x, y, seen}}."""
    rank_tr: dict[str, dict[str, list[int]]] = {}
    recipe_tr: dict[int, dict[str, list[int]]] = {}
    for m in re.finditer(r'\["([\w-]+)"\]=\[=\[(.*?)\]=\]', text, re.S):
        key = PROFESSION_KEYS.get(m.group(1), m.group(1))
        body = m.group(2)
        i = body.find("ranks={")
        if i >= 0 and key not in rank_tr:
            j = body.find("steps", i)
            part = body[i:j if j > 0 else None]
            caps = {}
            for cap, tr in re.findall(r'max=(\d+),sk=\d+,lv=\d+,cost=\d+,tr=\{((?:[ah]=\{[\d,]*\},?)*)\}', part):
                caps[cap] = _faction_lists(tr)
            rank_tr[key] = caps
        for side_m in re.finditer(r'\b([ah])=\{steps=', body):
            side = side_m.group(1)
            end = body.find("},h={steps=", side_m.end()) if side == "a" else len(body)
            part = body[side_m.end():end]
            starts = [(s.start(), int(s.group(1))) for s in re.finditer(r'\{s=(\d+),', part)]
            for n, (pos, spell) in enumerate(starts):
                step = part[pos:starts[n + 1][0] if n + 1 < len(starts) else len(part)]
                learn = re.search(r'L=\{how="([a-z]*)"[^{}]*?tr=\{([\d,]*)\}', step)
                if learn and "t" in learn.group(1):
                    recipe_tr.setdefault(spell, {})[side] = _ids(learn.group(2))
    npcs: dict[int, dict] = {}
    k = text.find("ns.profNpcSrc")
    if k >= 0:
        for m in _NPC.finditer(text[k:]):
            npcs[int(m.group(1))] = {"name": m.group(2), "title": m.group(3), "side": m.group(4), "map": int(m.group(5)),
                                     "x": float(m.group(6)), "y": float(m.group(7)), "seen": m.group(8) == "1"}
    return rank_tr, recipe_tr, npcs


def parse_ranks_lua(text: str) -> dict[str, list[dict]]:
    """{profession: [{name, cap, skill, level, cost}]} from ForeverDB Helper's Data/Professions.lua."""
    out: dict[str, list[dict]] = {}
    for m in re.finditer(r'\["([\w-]+)"\]=\[=\[(.*?)\]=\]', text, re.S):
        body = m.group(2)
        i = body.find("ranks={")
        if i < 0:
            continue
        j = body.find("steps", i)
        ranks = [{"name": r, "cap": int(cap), "skill": int(sk), "level": int(lv), "cost": int(cost)}
                 for r, cap, sk, lv, cost in re.findall(
                     r'\{r="(\w+)",max=(\d+),sk=(\d+),lv=(\d+),cost=(\d+)', body[i:j if j > 0 else None])]
        key = PROFESSION_KEYS.get(m.group(1), m.group(1))
        if ranks and key not in out:
            out[key] = ranks
    return out


def main(argv: list[str] | None = None) -> int:
    manifest = json.loads(_get(f"{SITE}/downloads/addon-manifest.json"))
    files = {f["path"]: f["url"] for f in manifest["data"]["files"]}
    if "Data/Recipes.lua" not in files:
        print("ForeverDB's addon data no longer has Data/Recipes.lua; nothing imported.", file=sys.stderr)
        return 1
    text = _get(f"{SITE}/{files['Data/Recipes.lua']}").decode("utf-8")
    build, spells = parse_recipes_lua(text)
    ranks: dict[str, list[dict]] = {}
    rank_tr: dict = {}
    recipe_tr: dict = {}
    npcs: dict = {}
    try:
        with zipfile.ZipFile(io.BytesIO(_get(f"{SITE}/{manifest['addon']['url']}"))) as z:
            helper = z.read(RANK_FILE).decode("utf-8")
        ranks = parse_ranks_lua(helper)
        rank_tr, recipe_tr, npcs = parse_trainers_lua(helper)
    except (KeyError, zipfile.BadZipFile) as e:
        print(f"No rank data in the ForeverDB addon ({e}); rank fees fall back to Classic.", file=sys.stderr)
    for key, rs in ranks.items():
        for r in rs:
            r["trainers"] = rank_tr.get(key, {}).get(str(r["cap"]), {})
    # Zone names for the trainers' maps, from the game's UiMap table.
    zones = {}
    try:
        zones = {int(r["ID"]): r["Name_lang"] for r in load_table("UiMap", build)}
    except Exception as e:  # noqa: BLE001 - names are a nicety
        print(f"Could not load zone names ({e}).", file=sys.stderr)
    for n in npcs.values():
        n["zone"] = zones.get(n["map"], f"map {n['map']}")
    data = {
        "credit": CREDIT,
        "license": "GPL-3.0 with an attribution term (see https://foreverdb.net and the ForeverDB addon's NOTICE.txt)",
        "source": f"ForeverDB addon data {manifest['data'].get('version', '')}, Data/Recipes.lua, WoW Forever build {build}",
        "ranks": ranks,
        "trainers": {str(k): v for k, v in sorted(npcs.items())},
        "recipe_trainers": {str(k): v for k, v in sorted(recipe_tr.items())},
        "spells": {str(k): v for k, v in sorted(spells.items())},
    }
    OUT.write_text("{\n" + "".join(f'  {json.dumps(k)}: {json.dumps(v)},\n' for k, v in data.items() if k != "spells")
                   + '  "spells": {\n' + ",\n".join(f"    {json.dumps(k)}: {json.dumps(v)}" for k, v in data["spells"].items())
                   + "\n  }\n}\n", encoding="utf-8")
    seen = sum(1 for v in spells.values() if v.get("fee_seen_in_forever"))
    print(f"{len(spells)} recipes ({seen} with fees seen at Forever trainers) -> {OUT}", file=sys.stderr)
    print(CREDIT, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
