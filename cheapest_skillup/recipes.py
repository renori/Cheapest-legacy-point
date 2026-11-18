"""Recipe data model and loader (data/recipes/*.json)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass
class Recipe:
    name: str
    orange: int  # skill needed to learn; always skills up below `yellow`
    yellow: int
    green: int
    grey: int  # no skill-up at or above this
    reagents: dict[int, int]
    makes: int | None = None  # item id produced (None for enchants)
    makes_qty: float = 1.0
    source: str = "trainer"  # auto (free with the profession) | trainer | recipe (taught by a recipe item)
    learn_cost: int | None = 0  # copper for trainer recipes; None = fee unknown
    tools: list[int] = field(default_factory=list)  # needed, not consumed
    note: str = ""
    spell: int | None = None
    learn_known: bool = True  # False: learn level not in game data, assumed = yellow
    recipe_items: list[int] = field(default_factory=list)  # items that teach it (source "recipe")
    trainers: dict[str, list[int]] = field(default_factory=dict)  # {"a"/"h": [npc id]} known to teach it
    fee_from: str | None = None  # trainer fee: "you" (trainer.json), "forever" (seen at a Forever trainer), "classic", None
    learn_from: str = "game"  # learn level origin: "game", "you", "classic", "assumed" (= yellow)

    def skillup_chance(self, skill: int) -> float:
        """Chance one craft raises `skill` by a point (Classic formula)."""
        if skill < self.orange or skill >= self.grey:
            return 0.0
        if skill < self.yellow:
            return 1.0
        return (self.grey - skill) / (self.grey - self.yellow)


@dataclass
class Rank:
    name: str  # Apprentice, Journeyman, Expert, Artisan
    cap: int  # skill cap it raises you to
    skill: int  # skill needed to train it
    level: int  # character level needed
    cost: int | None  # copper; None = unknown
    cost_from: str | None = None  # "you", "forever" (ForeverDB), "classic"
    how: str = "trainer"  # trainer | book (buy `item`, priced at vendor/AH) | quest
    item: int | None = None  # the skill book, for how == "book"
    trainers: dict[str, list[int]] = field(default_factory=dict)  # {"a"/"h": [npc id]} who teach this rank


RANK_NAMES = {75: "Apprentice", 150: "Journeyman", 225: "Expert", 300: "Artisan"}
RANK_DEFAULTS = {75: (0, 5), 150: (50, 10), 225: (125, 20), 300: (200, 35)}  # cap: (skill, character level)
# Ranks not learned from a trainer in WoW Forever: (profession, cap) -> (how, skill book item)
RANK_SPECIAL = {
    ("cooking", 225): ("book", 16072),  # Expert Cookbook
    ("cooking", 300): ("quest", None),
    ("first_aid", 225): ("book", 16084),  # Expert First Aid - Under Wraps
    ("first_aid", 300): ("quest", None),
}


@dataclass
class Profession:
    key: str
    name: str
    recipes: list[Recipe]
    note: str = ""
    ranks: list[Rank] = field(default_factory=list)

    def trainers_for(self, r: Recipe | Rank, side: str | None) -> list[dict]:
        """Where to train a recipe or rank: ForeverDB's trainers for it, else those of the rank that covers it."""
        lists = dict(r.trainers)
        if isinstance(r, Recipe):
            covering = next((k for k in self.ranks if r.orange < k.cap), None)
            for s, ids in (covering.trainers if covering else {}).items():
                lists.setdefault(s, ids)  # no named trainer on this side: any trainer of that rank
        ids = [i for s, ids in lists.items() if side in (None, s) for i in ids]
        npcs = load_trainer_npcs()
        found = [dict(npcs[i], id=i) for i in dict.fromkeys(ids) if i in npcs]
        return sorted(found, key=lambda n: (not n["seen"], n["zone"], n["name"]))

    def ranks_needed(self, start: int, reached: int) -> list[Rank]:
        """Ranks to train to go from `start` to `reached` (from 1: Apprentice too)."""
        have = 0 if start <= 1 else min((r.cap for r in self.ranks if r.cap >= start), default=0)
        prev = 0
        out = []
        for r in self.ranks:
            if r.cap > have and prev < reached:
                out.append(r)
            prev = r.cap
        return out


def load_ranks(key: str, data_dir: Path = DATA_DIR) -> list[Rank]:
    """Ranks with fees: your trainer.json, else ForeverDB, else Classic, else unknown."""
    def ranks_in(name: str) -> dict[int, dict]:
        path = data_dir / name
        if not path.exists():
            return {}
        d = json.loads(path.read_text(encoding="utf-8")).get("ranks", {})
        return {int(r["cap"]): r for r in d.get(key, [])} if isinstance(d.get(key), list) else \
               {int(k): v for k, v in d.get(key, {}).items()}

    classic, fdb, yours = ranks_in("trainer_classic.json"), ranks_in("foreverdb.json"), ranks_in("trainer.json")
    out = []
    for cap, (skill, level) in RANK_DEFAULTS.items():
        cost, cost_from = None, None
        for src, origin in ((classic, "classic"), (fdb, "forever"), (yours, "you")):
            r = src.get(cap)
            if r and r.get("cost") is not None:
                cost, cost_from = int(r["cost"]), origin
            if r and r.get("skill") is not None and origin != "classic":
                skill = int(r["skill"])
            if r and r.get("level"):
                level = int(r["level"])
        if key == "first_aid":
            level = 0
        how, item = RANK_SPECIAL.get((key, cap), ("trainer", None))
        if how == "quest" and cost_from != "you":
            cost, cost_from = 0, None
        trainers = (fdb.get(cap) or {}).get("trainers", {}) if how == "trainer" else {}
        out.append(Rank(RANK_NAMES[cap], cap, skill, level, cost, cost_from, how, item, trainers))
    return out


def _recipe(d: dict) -> Recipe:
    o, y, g, gr = d["skill"]
    makes = d.get("makes")
    return Recipe(
        name=d["name"],
        orange=o,
        yellow=y,
        green=g,
        grey=gr,
        reagents={int(k): int(v) for k, v in d.get("reagents", {}).items()},
        makes=(makes or {}).get("item"),
        makes_qty=(makes or {}).get("qty", 1),
        source=d.get("learn") or d.get("source", "trainer"),
        learn_cost=d.get("learn_cost", 0 if (d.get("learn") or d.get("source")) != "trainer" else None),
        tools=[int(t) for t in d.get("tools", [])],
        note=d.get("note", ""),
        spell=d.get("spell"),
        learn_known=d.get("learn_level_known", True),
        recipe_items=[int(i) for i in d.get("recipe_items", [])],
    )


def load_trainer(data_dir: Path = DATA_DIR, name: str = "trainer.json") -> dict[int, dict]:
    """Trainer fees and learn levels by spell id: data/trainer.json (yours) or trainer_classic.json."""
    path = data_dir / name
    if not path.exists():
        return {}
    d = json.loads(path.read_text(encoding="utf-8"))
    return {int(k): v for k, v in d.get("spells", {}).items()}


@lru_cache(maxsize=4)
def _foreverdb_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_foreverdb(data_dir: Path = DATA_DIR) -> dict[int, dict]:
    """How each recipe is learned, from ForeverDB.net (data/foreverdb.json), by spell id."""
    d = _foreverdb_file(data_dir / "foreverdb.json")
    return {int(k): v for k, v in d.get("spells", {}).items()}


def load_trainer_npcs(data_dir: Path = DATA_DIR) -> dict[int, dict]:
    """Trainers: {npc: {name, title, side, zone, x, y, seen}} (ForeverDB.net)."""
    return {int(k): v for k, v in _foreverdb_file(data_dir / "foreverdb.json").get("trainers", {}).items()}


def load_recipe_trainers(data_dir: Path = DATA_DIR) -> dict[int, dict[str, list[int]]]:
    return {int(k): v for k, v in _foreverdb_file(data_dir / "foreverdb.json").get("recipe_trainers", {}).items()}


def _apply_foreverdb(r: Recipe, info: dict) -> bool:
    """Correct how `r` is learned from ForeverDB. False = leave the recipe out."""
    if info.get("speculation") or info["learn"] == "unknown":
        return False  # probably not in the live game, or no known way to learn it
    how = info["learn"]
    level = info.get("learn_level")
    if how == "auto":
        r.source, r.learn_cost, r.recipe_items = "auto", 0, []
        r.orange, r.learn_known, r.learn_from = 1, True, "game"
    elif how == "recipe":
        r.source, r.learn_cost, r.recipe_items = "recipe", 0, info.get("recipe_items", [])
        if level:
            r.orange, r.learn_known, r.learn_from = max(1, min(level, r.grey - 1)), True, "game"
    else:  # trainer
        if r.source != "trainer":
            r.source, r.recipe_items, r.learn_cost = "trainer", [], None
            r.orange, r.learn_known, r.learn_from = max(1, min(r.yellow, r.grey - 1)), False, "assumed"
        if level:
            r.orange = max(1, min(level, r.grey - 1))
            r.learn_known = not info.get("learn_level_classic")
            r.learn_from = "classic" if info.get("learn_level_classic") else "forever"
        if info.get("fee") is not None:
            r.learn_cost = info["fee"]
            r.fee_from = "forever" if info.get("fee_seen_in_forever") else "classic"
    r.yellow = max(r.yellow, r.orange)
    r.green = max(r.green, r.yellow)
    return True


def _apply_trainer(r: Recipe, info: dict | None, origin: str) -> None:
    if r.source != "trainer" or not info:
        return
    if info.get("cost") is not None:
        r.learn_cost = int(info["cost"])
        r.fee_from = origin
    if info.get("learn") is not None:
        r.orange = max(1, min(int(info["learn"]), r.grey - 1))
        r.learn_known = origin == "you"
        r.learn_from = origin
        r.yellow = max(r.yellow, r.orange)
        r.green = max(r.green, r.yellow)


def load_profession(key: str, data_dir: Path = DATA_DIR) -> Profession:
    path = data_dir / "recipes" / f"{key}.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    yours = load_trainer(data_dir)
    classic = load_trainer(data_dir, "trainer_classic.json")
    fdb = load_foreverdb(data_dir)
    named_trainers = load_recipe_trainers(data_dir)
    recipes = []
    for raw in d["recipes"]:
        r = _recipe(raw)
        if r.source == "trainer" and not r.learn_known:
            r.learn_from = "assumed"
        info = yours.get(r.spell) if r.spell else None
        if info and info.get("exclude"):
            continue  # you marked it as not available
        # Lowest priority first: Classic estimates, then ForeverDB, then your own values.
        _apply_trainer(r, classic.get(r.spell) if r.spell else None, "classic")
        if r.spell in fdb and not _apply_foreverdb(r, fdb[r.spell]):
            continue
        _apply_trainer(r, info, "you")
        if r.source == "trainer":
            r.trainers = named_trainers.get(r.spell, {})
        recipes.append(r)
    return Profession(key=key, name=d["name"], recipes=recipes, note=d.get("note", ""), ranks=load_ranks(key, data_dir))


def load_item_names(data_dir: Path = DATA_DIR) -> dict[int, str]:
    path = data_dir / "item_names.json"
    if not path.exists():
        return {}
    d = json.loads(path.read_text(encoding="utf-8"))
    return {int(k): v for k, v in d.get("items", {}).items()}


def available_professions(data_dir: Path = DATA_DIR) -> list[str]:
    return sorted(p.stem for p in (data_dir / "recipes").glob("*.json"))


def load_vendor_prices(data_dir: Path = DATA_DIR) -> dict[int, int]:
    d = json.loads((data_dir / "vendor_items.json").read_text(encoding="utf-8"))
    return {int(k): v["price"] for k, v in d["items"].items()}


def load_vendor_names(data_dir: Path = DATA_DIR) -> dict[int, str]:
    d = json.loads((data_dir / "vendor_items.json").read_text(encoding="utf-8"))
    return {int(k): v["name"] for k, v in d["items"].items()}


def load_vendor_sell(data_dir: Path = DATA_DIR) -> dict[int, int]:
    """Vendor sell prices (copper) of crafted items, from data/vendor_sell.json."""
    path = data_dir / "vendor_sell.json"
    if not path.exists():
        return {}
    d = json.loads(path.read_text(encoding="utf-8"))
    return {int(k): int(v["sell"]) for k, v in d.get("items", {}).items() if v.get("sell") is not None}
