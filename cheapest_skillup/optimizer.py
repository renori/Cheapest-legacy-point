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
    cost: float  # copper, expected, after any sell-back credit
    credit: float = 0.0  # copper recovered by selling what this step crafts


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
    sell_back: str | None = None  # None, "vendor" or "ah"
    no_sell_price: set[int] = field(default_factory=set)  # crafted items with no sell price known
    learn_costs: list[tuple[Recipe, int | None]] = field(default_factory=list)  # (recipe, copper or None=unknown)

    @property
    def learn_total(self) -> float:
        return sum(c for _, c in self.learn_costs if c)

    @property
    def grand_total(self) -> float:
        return self.total_cost + self.tools_cost + self.learn_total

    @property
    def sell_credit(self) -> float:
        return sum(s.credit for s in self.steps)

    @property
    def tools_cost(self) -> float:
        return sum(c for _, c in self.tool_costs.values() if c != INF)


class Optimizer:
    def __init__(
        self,
        profession: Profession,
        prices: PriceBook,
        allowed_sources: set[str] = frozenset({"trainer", "recipe"}),
        sell_back: str | None = None,  # None, "vendor" or "ah"
        exclude: frozenset[int] = frozenset(),  # id() of recipes to leave out
    ):
        if sell_back not in (None, "vendor", "ah"):
            raise ValueError(f"sell_back must be None, 'vendor' or 'ah', not {sell_back!r}")
        self.prof = profession
        self.prices = prices
        self._learn: dict[int, int | None] = {}
        self.recipes = []
        for r in profession.recipes:
            if id(r) in exclude:
                continue
            if r.source == "auto":
                self._learn[id(r)] = 0
            elif r.source == "trainer" and "trainer" in allowed_sources:
                self._learn[id(r)] = r.learn_cost
            elif r.source == "recipe" and "recipe" in allowed_sources:
                listed = [p for p in (prices.ah_price(i) for i in r.recipe_items) if p is not None]
                if not listed:
                    continue  # recipe item not on your AH (or bind-on-pickup): not available
                self._learn[id(r)] = min(listed)
            else:
                continue
            self.recipes.append(r)
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

    def learn_cost(self, r: Recipe) -> int | None:
        """Copper to learn `r`: 0 for auto, trainer fee (None if unknown), AH price of its recipe item."""
        return self._learn.get(id(r), 0)

    def credit(self, r: Recipe) -> float:
        """Copper recovered per craft by selling what it makes."""
        if not self.sell_back or not r.makes:
            return 0.0
        return self.prices.sell_value(r.makes, self.sell_back) * r.makes_qty

    def craft_cost(self, r: Recipe, skill: int) -> float:
        return self.reagent_cost(r, skill, frozenset({r.name})) - self.credit(r)

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
            credit = self.credit(best) / p
            if steps and steps[-1].recipe is best:
                s = steps[-1]
                s.end, s.expected_crafts, s.cost = skill + 1, s.expected_crafts + 1 / p, s.cost + cost
                s.credit += credit
            else:
                steps.append(Step(best, skill, skill + 1, 1 / p, cost, credit))
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
            if maker is not None:
                expand(maker, 1 / maker.makes_qty, target)  # crafting the tool: learn it, buy its mats
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
            learn_costs=[(r, self.learn_cost(r)) for r in learn.values()],
            sell_back=self.sell_back,
            no_sell_price={s.recipe.makes for s in steps if self.sell_back and s.recipe.makes
                           and not self.prices.sell_value(s.recipe.makes, self.sell_back)},
        )


def cheapest_plan(
    profession: Profession,
    prices: PriceBook,
    start: int,
    target: int,
    allowed_sources: set[str] = frozenset({"trainer", "recipe"}),
    sell_back: str | None = None,
) -> Plan:
    """Plan including what it costs to learn the recipes.

    The per-point planner ignores one-off learning costs, so afterwards try
    leaving out each paid recipe it used (most expensive first) and keep the
    change whenever the grand total drops.
    """
    exclude: set[int] = set()

    def run() -> Plan:
        return Optimizer(profession, prices, allowed_sources, sell_back, frozenset(exclude)).plan(start, target)

    best = run()
    improved = True
    while improved:
        improved = False
        paid = sorted(((r, c) for r, c in best.learn_costs if c), key=lambda rc: -rc[1])
        for r, _ in paid:
            exclude.add(id(r))
            trial = run()
            if trial.reached >= best.reached and trial.grand_total < best.grand_total:
                best, improved = trial, True
                break
            exclude.discard(id(r))
    return best


def ceil(x: float) -> int:
    return math.ceil(x - 1e-9)
