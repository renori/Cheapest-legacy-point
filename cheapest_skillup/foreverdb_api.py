"""Fill in recipe sources, vendor prices and trainers from the ForeverDB API.

    $env:FOREVERDB_API_KEY = "<your key>"      # PowerShell (bash: export FOREVERDB_API_KEY=...)
    python -m cheapest_skillup.foreverdb_api

Optional: the free files (python -m cheapest_skillup.foreverdb) already cover
most of this. The API adds, for every recipe: vendors that sell the recipe and
their price, the trainers that teach it on each side, the trainer fee players
saw in Forever, and the skill needed to learn it.

Your key stays yours:
* it is read only from the FOREVERDB_API_KEY environment variable and only
  sent to foreverdb.net; it is never printed or written to any file;
* the API's text is watermarked to the key that fetched it, so only numbers,
  ids, coordinates and flags are kept: no names, notes or descriptions. Names
  come from the game data and ForeverDB's free files instead;
* the output is checked for hidden (zero-width) characters before writing.

Data from ForeverDB.net (https://foreverdb.net): credit it wherever you show the data.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from .gamedata import load_table
from .recipes import DATA_DIR

API = "https://foreverdb.net/api/v1"
SLUGS = {"alchemy": "alchemy", "blacksmithing": "blacksmithing", "cooking": "cooking", "enchanting": "enchanting",
         "engineering": "engineering", "first_aid": "first-aid", "leatherworking": "leatherworking", "tailoring": "tailoring"}
OUT = DATA_DIR / "foreverdb_api.json"
CREDIT = "Data from ForeverDB.net (https://foreverdb.net)"
PAUSE = 2.2  # seconds between requests: the free tier allows 30 a minute
HIDDEN = re.compile("[​-‏‪-‮⁠-⁤﻿]")
SIDE = {"alliance": "a", "horde": "h", "both": "b"}


def _key() -> str:
    key = os.environ.get("FOREVERDB_API_KEY", "").strip()
    if not key:
        sys.exit("Set FOREVERDB_API_KEY to your ForeverDB API key first (see the module help).")
    return key


def _get(path: str, key: str) -> dict:
    req = urllib.request.Request(f"{API}{path}", headers={"X-API-Key": key, "User-Agent": "cheapest-skillup/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(int(e.headers.get("Retry-After", "30")))
                continue
            # Never echo the request (it carries the key); the status is enough.
            raise SystemExit(f"ForeverDB API answered {e.code} for {path.split('?')[0]}") from None
    raise SystemExit("ForeverDB API: too many retries")


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _npc(n: dict, npcs: dict) -> int | None:
    """Keep where an NPC stands (numbers and flags only) and return its id."""
    npc = _num(n.get("npcId"))
    if npc is None:
        return None
    side = SIDE.get(str(n.get("faction") or n.get("side") or "").lower(), "b")
    npcs[str(npc)] = {"side": side, "map": _num(n.get("mapId")), "x": _num(n.get("x")), "y": _num(n.get("y")),
                      "seen": bool(n.get("seenInForever"))}
    return int(npc)


def extract(recipe: dict, npcs: dict) -> dict:
    """The numbers we keep about one recipe."""
    lf = recipe.get("learnedFrom") or {}
    src = lf.get("sources") or {}
    skill = recipe.get("skill") or {}
    out: dict = {"ways": [w for w in src.get("ways", []) if w in ("auto", "trainer", "vendor", "drop", "quest")]}
    if _num(src.get("learnAtSkill")) is not None:
        out["learn_at"] = int(src["learnAtSkill"])
        out["learn_at_classic"] = skill.get("orangeSource") == "classic"
    trainer = lf.get("trainer") or {}
    if _num(trainer.get("cost")) is not None:
        out["trainer_cost"] = int(trainer["cost"])
        out["trainer_cost_seen"] = "seen in forever" in str(trainer.get("source", "")).lower()
    items = [i.get("itemId") for i in (lf.get("recipeItems") or []) + (lf.get("recipeItemsHidden") or []) if isinstance(i, dict)]
    items += [i for i in (lf.get("recipeItemsHidden") or []) if isinstance(i, int)]
    out["recipe_items"] = sorted({int(i) for i in items if _num(i) is not None})
    trainers: dict[str, list[int]] = {}
    for side, lst in (src.get("trainers") or {}).items():
        ids = [_npc(n, npcs) for n in lst if isinstance(n, dict)]
        trainers[SIDE.get(side, "b")] = [i for i in ids if i is not None]
    vendors: dict[str, list[list[int]]] = {}
    for side, lst in (src.get("vendors") or {}).items():
        rows = []
        for n in lst:
            if not isinstance(n, dict) or n.get("costs"):
                continue  # costs besides gold (Merchant's Favor...): not something we can price
            npc, price = _npc(n, npcs), _num(n.get("pricePerItem") or n.get("price"))
            if npc is not None and price is not None:
                rows.append([npc, int(round(price))])
        if rows:
            vendors[SIDE.get(side, "b")] = rows
    if trainers:
        out["trainers"] = trainers
    if vendors:
        out["vendors"] = vendors
    return out


def main(argv: list[str] | None = None) -> int:
    key = _key()
    spells: dict[str, dict] = {}
    npcs: dict[str, dict] = {}
    rank_trainers: dict[str, list[list[int]]] = {}
    calls = 0
    build = None
    for prof, slug in SLUGS.items():
        offset, total = 0, None
        while total is None or offset < total:
            if calls:
                time.sleep(PAUSE)
            page = _get(f"/professions/{slug}?limit=100&offset={offset}", key)
            calls += 1
            meta, data = page.get("meta", {}), page.get("data", {})
            build = build or meta.get("build")
            total = int(meta.get("total") or 0)
            if offset == 0:
                # Trainers of the profession and how far they teach: [npc, up to skill]
                rank_trainers[prof] = [[i, int(_num(t.get("trainsUpToSkill")) or 0)]
                                       for t in data.get("trainers", []) if (i := _npc(t, npcs)) is not None]
            for r in data.get("recipes", []):
                if _num(r.get("spellId")) is not None:
                    spells[str(int(r["spellId"]))] = extract(r, npcs)
            offset += int(meta.get("limit") or 100)
        print(f"  {prof:<15} {sum(1 for _ in spells)} recipes so far", file=sys.stderr)

    # Zone names from the game data, so nothing textual comes from the API.
    try:
        zones = {int(r["ID"]): r["Name_lang"] for r in load_table("UiMap", build)} if build else {}
    except Exception:  # noqa: BLE001 - names are a nicety
        zones = {}
    for n in npcs.values():
        n["zone"] = zones.get(n["map"]) if n.get("map") is not None else None

    data = {"credit": CREDIT, "build": build, "spells": spells, "npcs": npcs, "profession_trainers": rank_trainers}
    text = json.dumps(data, separators=(",", ":"), sort_keys=True)
    if HIDDEN.search(text):
        sys.exit("Refusing to write: hidden characters found in the data (possible watermark).")
    if key and key in text:
        sys.exit("Refusing to write: the output contains the API key.")
    OUT.write_text(text + "\n", encoding="utf-8")
    print(f"{len(spells)} recipes, {len(npcs)} NPCs from {calls} API calls -> {OUT}", file=sys.stderr)
    print(CREDIT, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
