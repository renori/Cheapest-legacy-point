"""Find the cheapest way to raise a profession from one skill level to another.

Model
-----
* At skill `s`, a recipe skills you up with probability
  1 (orange), (grey - s) / (grey - yellow) (yellow/green), or 0 (grey).
  The expected number of crafts to gain one point is therefore 1 / p.
* The expected cost of one point with recipe r is cost(r) / p(r, s).
  Each point is independent of the others, so choosing the cheapest recipe
  for every point separately gives the cheapest total.
* A reagent's cost is the cheaper of buying it (TSM min buyout, region value
  as fallback, vendor price) and crafting it yourself from a recipe in the
  same profession (e.g. Bolt of Linen Cloth from Linen Cloth). Skill-ups you
  might get while crafting those intermediates are not counted, so the
  estimate errs on the expensive side.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from .prices import PriceBook
from .recipes import Profession, Recipe

INF = float("inf")


@dataclass
class Step:
    recipe: Recipe
    start: int  # skill at the start of this step
    end: int  # skill after this step
    expected_crafts: float
    cost: float  # copper, expected


@dataclass
class Plan:
    profession: Profession
    start: int
    target: int
    steps: list[Step]
    reached: int  # highest skill the plan reaches (< target when stuck)
    buy: dict[int, float]  # item id -> expected quantity to buy
    craft_first: dict[str, float]  # intermediate recipe name -> crafts
    learn: list[Recipe]
    tools: set[int]
    total_cost: float  # copper, materials for the skill-ups
    unpriced: set[int] = field(default_factory=set)
    tool_costs: dict[int, tuple[str, float]] = field(default_factory=dict)  # item -> (name, cost of one)

    @property
    def tools_cost(self) -> float:
        return sum(c for _, c in self.tool_costs.values() if c != INF)

    @property
    def learn_cost(self) -> int:
        return sum(r.learn_cost for r in self.learn)


class Optimizer:
    def __init__(
        self,
        profession: Profession,
        prices: PriceBook,
        allowed_sources: set[str] = frozenset({"trainer", "vendor"}),
        sell_back: bool = False,
    ):
        self.prof = profession
        self.prices = prices
        self.recipes = [r for r in profession.recipes if r.source in allowed_sources]
        self.sell_back = sell_back
        self._makers: dict[int, list[Recipe]] = defaultdict(list)
        for r in self.recipes:
            if r.makes:
                self._makers[r.makes].append(r)
        self._unit_memo: dict[tuple[int, int], tuple[float, Recipe | None]] = {}

    # -- costs ---------------------------------------------------------------

    def unit_cost(self, item: int, skill: int, _stack: frozenset = frozenset()) -> tuple[float, Recipe | None]:
        """Cheapest cost of one `item` at `skill`, and the recipe to craft it (None = buy)."""
        key = (item, skill)
        if key in self._unit_memo:
            return self._unit_memo[key]
        q = self.prices.quote(item)
        best: tuple[float, Recipe | None] = (q.price if q.price is not None else INF, None)
        for r in self._makers.get(item, []):
            if r.orange > skill or r.name in _stack:
                continue
            c = self.reagent_cost(r, skill, _stack | {r.name}) / r.makes_qty
            if c < best[0]:
                best = (c, r)
        if not _stack:
            self._unit_memo[key] = best
        return best

    def reagent_cost(self, r: Recipe, skill: int, _stack: frozenset = frozenset()) -> float:
        return sum(qty * self.unit_cost(item, skill, _stack)[0] for item, qty in r.reagents.items())

    def craft_cost(self, r: Recipe, skill: int) -> float:
        c = self.reagent_cost(r, skill, frozenset({r.name}))
        if self.sell_back and r.makes:
            c -= self.prices.sell_value(r.makes) * r.makes_qty
        return c

    def point_cost(self, r: Recipe, skill: int) -> float:
        p = r.skillup_chance(skill)
        return self.craft_cost(r, skill) / p if p > 0 else INF

    # -- planning ------------------------------------------------------------

    def plan(self, start: int, target: int) -> Plan:
        steps: list[Step] = []
        skill = start
        while skill < target:
            options = [(self.point_cost(r, skill), r) for r in self.recipes]
            cost, best = min(options, key=lambda o: o[0], default=(INF, None))
            if best is None or cost == INF:
                break
            p = best.skillup_chance(skill)
            if steps and steps[-1].recipe is best:
                s = steps[-1]
                s.end, s.expected_crafts, s.cost = skill + 1, s.expected_crafts + 1 / p, s.cost + cost
            else:
                steps.append(Step(best, skill, skill + 1, 1 / p, cost))
            skill += 1

        buy: dict[int, float] = defaultdict(float)
        craft_first: dict[str, float] = defaultdict(float)
        learn: dict[str, Recipe] = {}
        tools: set[int] = set()
        unpriced: set[int] = set()

        def expand(r: Recipe, crafts: float, skill: int) -> None:
            learn[r.name] = r
            tools.update(r.tools)
            for item, qty in r.reagents.items():
                need = qty * crafts
                cost, maker = self.unit_cost(item, skill)
                if maker is not None:
                    craft_first[maker.name] += need / maker.makes_qty
                    expand(maker, need / maker.makes_qty, skill)
                else:
                    buy[item] += need
                    if cost == INF:
                        unpriced.add(item)

        for s in steps:
            expand(s.recipe, s.expected_crafts, s.start)

        # Tools (e.g. Runed Copper Rod) are needed once; buy or craft the cheaper way.
        tool_costs: dict[int, tuple[str, float]] = {}
        for tool in sorted(tools):
            cost, maker = self.unit_cost(tool, target)
            name = self.prices.name(tool) or (maker.name if maker else None) or next(
                (r.name for r in self.prof.recipes if r.makes == tool), f"item {tool}")
            tool_costs[tool] = (name, cost)

        return Plan(
            profession=self.prof,
            start=start,
            target=target,
            steps=steps,
            reached=skill,
            buy=dict(buy),
            craft_first=dict(craft_first),
            learn=list(learn.values()),
            tools=tools,
            total_cost=sum(s.cost for s in steps),
            unpriced=unpriced,
            tool_costs=tool_costs,
        )


def ceil(x: float) -> int:
    return math.ceil(x - 1e-9)
