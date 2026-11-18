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
    source: str = "trainer"  # trainer | vendor | quest | drop
    learn_cost: int = 0  # copper, approximate
    tools: list[int] = field(default_factory=list)  # needed, not consumed
    note: str = ""

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
        source=d.get("source", "trainer"),
        learn_cost=d.get("learn_cost", 0),
        tools=[int(t) for t in d.get("tools", [])],
        note=d.get("note", ""),
    )


def load_profession(key: str, data_dir: Path = DATA_DIR) -> Profession:
    path = data_dir / "recipes" / f"{key}.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    return Profession(key=key, name=d["name"], recipes=[_recipe(r) for r in d["recipes"]], note=d.get("note", ""))


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
    return {int(k): int(v["sell"]) for k, v in d.get("items", {}).items()}
