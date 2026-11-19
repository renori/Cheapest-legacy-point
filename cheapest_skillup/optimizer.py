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
from .recipes import Profession, Rank, Recipe

INF = float("inf")
LOW_CHANCE_CRAFTS = 3  # more expected crafts per point than this: flag the step
# Smoothing: a run of fewer than SMOOTH_MIN points between other recipes is folded into a
# neighbour's recipe when that costs at most max(SMOOTH_COPPER, SMOOTH_PCT of materials) more.
SMOOTH_MIN = 3
SMOOTH_COPPER = 100
SMOOTH_PCT = 0.005
SMOOTH_PASSES = 4


@dataclass
class Step:
    recipe: Recipe
    start: int  # skill at the start of this step
    end: int  # skill after this step
    expected_crafts: float
    cost: float  # copper, expected, after any sell-back credit
    credit: float = 0.0  # copper recovered by selling what this step crafts
    # Per craft: (item, quantity, cost each, recipe that crafts it or None if bought)
    mats: list[tuple[int, float, float, Recipe | None]] = field(default_factory=list)

    @property
    def crafts_per_point(self) -> float:
        return self.expected_crafts / max(1, self.end - self.start)

    @property
    def low_chance(self) -> bool:
        return self.crafts_per_point > LOW_CHANCE_CRAFTS


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
    ranks: list[tuple[Rank, int | None]] = field(default_factory=list)  # ranks to get on the way, with their cost
    bought: dict[str, str] = field(default_factory=dict)  # recipe name -> "vendor" | "ah" (recipe items)

    @property
    def learn_total(self) -> float:
        return sum(c for _, c in self.learn_costs if c)

    @property
    def ranks_total(self) -> float:
        return sum(c for _, c in self.ranks if c)

    @property
    def grand_total(self) -> float:
        return self.total_cost + self.tools_cost + self.learn_total + self.ranks_total

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
        allowed_sources: set[str] = frozenset({"trainer", "vendor", "recipe"}),
        sell_back: str | None = None,  # None, "vendor" or "ah"
        exclude: frozenset[int] = frozenset(),  # id() of recipes to leave out
        side: str | None = None,  # "a" or "h": your faction, for vendor recipes
    ):
        self.side = side
        self.bought: dict[int, str] = {}  # id(recipe) -> "vendor" | "ah" for recipe items
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
            elif r.source == "recipe":
                options = []
                if "recipe" in allowed_sources:
                    options += [(p, "ah") for p in (prices.ah_price(i) for i in r.recipe_items) if p is not None]
                if "vendor" in allowed_sources:
                    options += [(p, "vendor") for s, rows in r.vendors.items() if side in (None, s, "b") for _, p in rows]
                if not options:
                    continue  # no vendor on your side and not on your AH (or bind-on-pickup): not available
                price, how = min(options)
                self._learn[id(r)] = price
                self.bought[id(r)] = how
            else:
                continue
            self.recipes.append(r)
        self.sell_back = sell_back
        self._makers: dict[int, list[Recipe]] = defaultdict(list)
        for r in self.recipes:
            if r.makes:
                self._makers[r.makes].append(r)
        self._unit_memo: dict[tuple[int, int], tuple[float, Recipe | None]] = {}
        self._reagent_memo: dict[tuple[int, int], float] = {}
        self._busy: set[tuple[int, int]] = set()

    # -- costs ---------------------------------------------------------------

    def unit_cost(self, item: int, skill: int) -> tuple[float, Recipe | None]:
        """Cheapest cost of one `item` at `skill`, and the recipe to craft it (None = buy)."""
        key = (item, skill)
        if key in self._unit_memo:
            return self._unit_memo[key]
        q = self.prices.quote(item)
        best: tuple[float, Recipe | None] = (q.price if q.price is not None else INF, None)
        if key in self._busy:
            return best  # crafting loop (A from B from A): just buy
        self._busy.add(key)
        for r in self._makers.get(item, []):
            if r.orange > skill:
                continue
            c = self.reagent_cost(r, skill) / r.makes_qty
            if c < best[0]:
                best = (c, r)
        self._busy.discard(key)
        self._unit_memo[key] = best
        return best

    def reagent_cost(self, r: Recipe, skill: int) -> float:
        key = (id(r), skill)
        if key not in self._reagent_memo:
            self._reagent_memo[key] = sum(qty * self.unit_cost(item, skill)[0] for item, qty in r.reagents.items())
        return self._reagent_memo[key]

    def learn_cost(self, r: Recipe) -> int | None:
        """Copper to learn `r`: 0 for auto, trainer fee (None if unknown), AH price of its recipe item."""
        return self._learn.get(id(r), 0)

    def rank_cost(self, rank: Rank) -> int | None:
        """Copper to get a profession rank: its trainer fee, or the skill book's vendor/AH price."""
        if rank.how == "book" and rank.item and rank.cost_from != "you":
            return self.prices.quote(rank.item).price
        return rank.cost

    def credit(self, r: Recipe) -> float:
        """Copper recovered per craft by selling what it makes."""
        if not self.sell_back or not r.makes:
            return 0.0
        return self.prices.sell_value(r.makes, self.sell_back) * r.makes_qty

    def craft_cost(self, r: Recipe, skill: int) -> float:
        return self.reagent_cost(r, skill) - self.credit(r)

    def point_cost(self, r: Recipe, skill: int) -> float:
        p = r.skillup_chance(skill)
        return self.craft_cost(r, skill) / p if p > 0 else INF

    # -- planning ------------------------------------------------------------

    def choose(self, start: int, target: int) -> list[Recipe]:
        """Cheapest recipe for each point from `start` (stops early if nothing can skill up)."""
        chosen: list[Recipe] = []
        for skill in range(start, target):
            options = [(self.point_cost(r, skill), r) for r in self.recipes if r.orange <= skill < r.grey]
            cost, best = min(options, key=lambda o: o[0], default=(INF, None))
            if best is None or cost == INF:
                break
            chosen.append(best)
        return chosen

    def smooth(self, start: int, chosen: list[Recipe]) -> list[Recipe]:
        """Fold short runs (A A B A A) into a neighbouring recipe when that costs next to nothing more."""
        chosen = list(chosen)
        materials = sum(self.point_cost(r, start + i) for i, r in enumerate(chosen))
        tolerance = max(SMOOTH_COPPER, SMOOTH_PCT * materials)
        for _ in range(SMOOTH_PASSES):
            runs, i = [], 0
            while i < len(chosen):
                j = i
                while j < len(chosen) and chosen[j] is chosen[i]:
                    j += 1
                runs.append((i, j))
                i = j
            changed = False
            for k, (i, j) in enumerate(runs):
                if j - i >= SMOOTH_MIN or len(runs) == 1:
                    continue
                current = sum(self.point_cost(chosen[x], start + x) for x in range(i, j))
                best = None
                for n in (k - 1, k + 1):
                    if not 0 <= n < len(runs):
                        continue
                    alt = chosen[runs[n][0]]
                    extra = sum(self.point_cost(alt, start + x) for x in range(i, j)) - current
                    if extra <= tolerance and (best is None or extra < best[0]):
                        best = (extra, alt)
                if best:
                    for x in range(i, j):
                        chosen[x] = best[1]
                    tolerance -= best[0]
                    changed = True
                    break
            if not changed:
                break
        return chosen

    def plan(self, start: int, target: int) -> Plan:
        steps: list[Step] = []
        chosen = self.smooth(start, self.choose(start, target))
        for i, best in enumerate(chosen):
            skill = start + i
            cost = self.point_cost(best, skill)
            p = best.skillup_chance(skill)
            credit = self.credit(best) / p
            if steps and steps[-1].recipe is best:
                s = steps[-1]
                s.end, s.expected_crafts, s.cost = skill + 1, s.expected_crafts + 1 / p, s.cost + cost
                s.credit += credit
            else:
                mats = [(item, qty, *self.unit_cost(item, skill)) for item, qty in best.reagents.items()]
                steps.append(Step(best, skill, skill + 1, 1 / p, cost, credit, mats))
        skill = start + len(chosen)

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
            ranks=[(r, self.rank_cost(r)) for r in self.prof.ranks_needed(start, skill)],
            sell_back=self.sell_back,
            no_sell_price={s.recipe.makes for s in steps if self.sell_back and s.recipe.makes
                           and not self.prices.sell_value(s.recipe.makes, self.sell_back)},
        )


def cheapest_plan(
    profession: Profession,
    prices: PriceBook,
    start: int,
    target: int,
    allowed_sources: set[str] = frozenset({"trainer", "vendor", "recipe"}),
    sell_back: str | None = None,
    side: str | None = None,
) -> Plan:
    """Plan including what it costs to learn the recipes.

    The per-point planner ignores one-off learning costs. Afterwards, for each
    paid recipe the plan uses, estimate what doing its points with the next-best
    recipe would cost; if that is less than the recipe's price, re-plan without
    it and keep the change when the grand total really drops.
    """
    exclude: set[int] = set()
    kept: set[int] = set()

    def run() -> tuple[Plan, Optimizer]:
        opt = Optimizer(profession, prices, allowed_sources, sell_back, frozenset(exclude), side)
        plan = opt.plan(start, target)
        plan.bought = {r.name: opt.bought[id(r)] for r, _ in plan.learn_costs if id(r) in opt.bought}
        return plan, opt

    best, opt = run()
    while True:
        used_points: dict[int, list[int]] = {}
        for s in best.steps:
            used_points.setdefault(id(s.recipe), []).extend(range(s.start, s.end))
        candidates = []
        for r, fee in best.learn_costs:
            if not fee or id(r) in kept:
                continue
            points = used_points.get(id(r), [])
            # Extra cost of doing r's points with the best other recipe (intermediate-only recipes: unknown, test them).
            extra = 0.0
            for sk in points:
                alts = [opt.point_cost(a, sk) for a in opt.recipes if a is not r and a.orange <= sk < a.grey]
                extra += min(alts, default=INF) - opt.point_cost(r, sk)
            if extra < fee:
                candidates.append((fee - extra, r))
        if not candidates:
            return best
        _, r = max(candidates, key=lambda c: c[0])
        exclude.add(id(r))
        trial, trial_opt = run()
        if trial.reached >= best.reached and trial.grand_total < best.grand_total:
            best, opt = trial, trial_opt
        else:
            exclude.discard(id(r))
            kept.add(id(r))


def ceil(x: float) -> int:
    return math.ceil(x - 1e-9)
