"""Import how recipes are learned, and Forever trainer fees, from ForeverDB.net.

    python -m cheapest_skillup.foreverdb

Downloads ForeverDB's free addon data file Data/Recipes.lua (no key needed)
and writes data/foreverdb.json. The planner uses it to:

* correct how each recipe is learned: automatically, from a trainer, or from
  a recipe item (including recipe items whose names Blizzard keeps on its
  servers, which the game files can't link by name);
* leave out recipes with no known way to learn them, and recipes ForeverDB
  marks as probably not in the live game (Season of Discovery leftovers...);
* use trainer fees players saw at Forever trainers.

Data from ForeverDB.net (https://foreverdb.net), GPL-3.0 with an attribution
term: credit "Data from ForeverDB.net (https://foreverdb.net)".
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .gamedata import _get
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


def main(argv: list[str] | None = None) -> int:
    manifest = json.loads(_get(f"{SITE}/downloads/addon-manifest.json"))
    files = {f["path"]: f["url"] for f in manifest["data"]["files"]}
    if "Data/Recipes.lua" not in files:
        print("ForeverDB's addon data no longer has Data/Recipes.lua; nothing imported.", file=sys.stderr)
        return 1
    text = _get(f"{SITE}/{files['Data/Recipes.lua']}").decode("utf-8")
    build, spells = parse_recipes_lua(text)
    data = {
        "credit": CREDIT,
        "license": "GPL-3.0 with an attribution term (see https://foreverdb.net and the ForeverDB addon's NOTICE.txt)",
        "source": f"ForeverDB addon data {manifest['data'].get('version', '')}, Data/Recipes.lua, WoW Forever build {build}",
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
