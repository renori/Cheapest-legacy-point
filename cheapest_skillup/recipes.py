"""Recipe data model and loader (data/recipes/*.json)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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
class Profession:
    key: str
    name: str
    recipes: list[Recipe]
    note: str = ""


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


def load_foreverdb(data_dir: Path = DATA_DIR) -> dict[int, dict]:
    """How each recipe is learned, from ForeverDB.net (data/foreverdb.json), by spell id."""
    path = data_dir / "foreverdb.json"
    if not path.exists():
        return {}
    d = json.loads(path.read_text(encoding="utf-8"))
    return {int(k): v for k, v in d.get("spells", {}).items()}


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
        recipes.append(r)
    return Profession(key=key, name=d["name"], recipes=recipes, note=d.get("note", ""))


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
