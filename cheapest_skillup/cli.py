"""Command line entry point: python -m cheapest_skillup ..."""

from __future__ import annotations

import argparse
import json
import sys

from .optimizer import Plan, ceil, cheapest_plan
from .prices import PriceBook, load_pricebook
from .recipes import (available_professions, load_foreverdb, load_item_names, load_profession, load_vendor_names,
                      load_vendor_prices, load_vendor_sell)

FOREVERDB_CREDIT = "Data from ForeverDB.net (https://foreverdb.net)"

SOURCE_LABEL = {"auto": "known", "trainer": "trainer", "recipe": "AH recipe", "vendor": "vendor"}


def how_of(plan: Plan, r) -> str:
    """auto | trainer | recipe (bought on the AH) | vendor (bought from a vendor)."""
    return "vendor" if r.source == "recipe" and plan.bought.get(r.name) == "vendor" else r.source

PRICE_FIELDS = ("minBuyout", "marketValue", "recent", "historical")


def money(copper: float) -> str:
    if copper == float("inf"):
        return "n/a"
    c = int(round(copper))
    sign = "-" if c < 0 else ""
    c = abs(c)
    g, s, c = c // 10000, (c // 100) % 100, c % 100
    if g:
        return f"{sign}{g}g {s:02d}s {c:02d}c"
    if s:
        return f"{sign}{s}s {c:02d}c"
    return f"{sign}{c}c"


def item_name(item: int, prices: PriceBook, vendor_names: dict[int, str]) -> str:
    return prices.name(item) or vendor_names.get(item) or f"item {item}"


def prev_cap(plan: Plan, rank) -> int:
    caps = [r.cap for r in plan.profession.ranks if r.cap < rank.cap]
    return max(caps, default=0)


def rank_text(rank, cost) -> str:
    if rank.how == "quest":
        return "quest"
    if cost is None:
        return "fee unknown"
    return ("~" if rank.cost_from == "classic" else "") + money(cost) + (" (skill book)" if rank.how == "book" else "")


def side_of(realm: str) -> str | None:
    """'pvp-horde' -> 'h', 'normal-alliance' -> 'a'."""
    return "h" if realm.endswith("horde") else "a" if realm.endswith("alliance") else None


def place(n: dict) -> str:
    """'Orgrimmar 63,50', or just the zone when the coordinates are unknown."""
    if n.get("x") is None or n.get("y") is None:
        return n.get("zone") or "unknown place"
    return f"{n.get('zone') or '?'} {n['x']:.0f},{n['y']:.0f}"


def where_at(trainers: list[dict], n: int = 3) -> str:
    if not trainers:
        return "trainer locations unknown"
    shown = [f"{t['name']} ({place(t)})" for t in trainers[:n]]
    return "at " + ", ".join(shown) + (f" +{len(trainers) - n} more" if len(trainers) > n else "")


def trainer_json(trainers: list[dict]) -> list[dict]:
    return [{"name": t["name"], "title": t["title"], "zone": t["zone"], "x": t["x"], "y": t["y"], "seen": t["seen"]}
            for t in trainers]


def rank_line(rank, cost) -> str:
    need = [f"skill {rank.skill}+"] if rank.skill else []
    if rank.level:
        need.append(f"character level {rank.level}")
    how = {"book": "Learn", "quest": "Quest for"}.get(rank.how, "Train")
    label = f"** {how} {rank.name} (cap {rank.cap})" + (f", needs {', '.join(need)}" if need else "")
    return f"{'':<10} {label:<55} {rank_text(rank, cost):>16}"


def render(plan: Plan, prices: PriceBook, vendor_names: dict[int, str], side: str | None = None) -> str:
    out: list[str] = []
    title = f"{plan.profession.name}: {plan.start} -> {plan.target}"
    out += [title, "=" * len(title)]
    out.append(f"{'Skill':<10} {'Recipe':<38} {'Learn':<10} {'Crafts':>6} {'Cost':>14}")
    pending = list(plan.ranks)
    for s in plan.steps:
        while pending and (s.end > prev_cap(plan, pending[0][0]) or pending[0][0].cap <= 75):
            rank, cost = pending.pop(0)
            out.append(rank_line(rank, cost))
            if rank.how == "trainer":
                out.append(f"{'':<14}{where_at(plan.profession.trainers_for(rank, side))}")
        flag = "  (low chance: ~%.1f crafts per point)" % s.crafts_per_point if s.low_chance else ""
        out.append(f"{s.start:>3}-{s.end:<6} {s.recipe.name:<38} {SOURCE_LABEL.get(how_of(plan, s.recipe), s.recipe.source):<10} "
                   f"{ceil(s.expected_crafts):>6} {money(s.cost):>14}{flag}")
    for rank, cost in pending:
        out.append(rank_line(rank, cost))
        if rank.how == "trainer":
            out.append(f"{'':<14}{where_at(plan.profession.trainers_for(rank, side))}")
    if plan.reached < plan.target:
        out.append(f"!! Stuck at {plan.reached}: no allowed recipe can skill up from here with known prices.")

    if plan.craft_first:
        out += ["", "Craft these intermediates yourself (cheaper than buying):"]
        for name, n in sorted(plan.craft_first.items()):
            out.append(f"  {ceil(n):>5} x {name}")

    out += ["", "Shopping list (expected quantities):"]
    rows = []
    for item, qty in plan.buy.items():
        q = prices.quote(item)
        each = q.price if q.price is not None else float("inf")
        rows.append((each * qty, item, qty, q))
    for total, item, qty, q in sorted(rows, key=lambda r: -r[0]):
        out.append(
            f"  {ceil(qty):>5} x {item_name(item, prices, vendor_names):<32} "
            f"@ {money(q.price) if q.price else 'n/a':>12} ({q.source}) = {money(total)}"
        )

    if plan.tool_costs:
        out += ["", "Tools needed once (not consumed):"]
        for name, cost in plan.tool_costs.values():
            out.append(f"  {name:<40} {money(cost):>14}")
    to_learn = [(r, c) for r, c in plan.learn_costs if r.source != "auto"]
    if to_learn:
        out += ["", "Recipes to learn:"]
        for r, c in sorted(to_learn, key=lambda rc: (rc[0].orange, rc[0].name)):
            if r.source == "recipe" and plan.bought.get(r.name) == "vendor":
                vs = plan.profession.vendors_for(r, side)
                where = "buy from " + (", ".join(f"{v['name']} ({place(v)})" for v in vs[:3]) or "a vendor")
            elif r.source == "recipe":
                where = f"buy {' / '.join(item_name(i, prices, vendor_names) for i in r.recipe_items)} on the AH"
            else:
                level = {"classic": f"learn at ~{r.orange} (Classic estimate)", "assumed": f"learn level unknown, assumed {r.orange}",
                         "you": f"learn at {r.orange}", "game": f"learn at {r.orange}", "forever": f"learn at {r.orange}"}[r.learn_from]
                fee_note = {"forever": ", fee seen in Forever", "you": ", your fee"}.get(r.fee_from or "", "")
                where = f"trainer, {level}{fee_note}"
            fee = "fee unknown" if c is None else ("~" if r.fee_from == "classic" else "") + money(c)
            out.append(f"  {r.name:<38} {fee:>14}  ({where})")
            if r.source == "trainer":
                out.append(f"  {'':<38} {'':>14}  {where_at(plan.profession.trainers_for(r, side))}")

    if plan.sell_back:
        how = "to a vendor" if plan.sell_back == "vendor" else "on the AH"
        out += ["", f"Materials (expected): {money(plan.total_cost + plan.sell_credit)}",
                f"Selling crafted items {how}: -{money(plan.sell_credit)}"]
        if plan.no_sell_price:
            names = ", ".join(item_name(i, prices, vendor_names) for i in sorted(plan.no_sell_price))
            out.append(f"  (no {'vendor' if plan.sell_back == 'vendor' else 'AH'} price for: {names}; counted as 0)")
    out += [f"Total (expected): {money(plan.total_cost)}" if plan.sell_back else f"Total materials (expected): {money(plan.total_cost)}"]
    if plan.tools_cost:
        out.append(f"Tools: {money(plan.tools_cost)}")
    if plan.learn_total:
        out.append(f"Learning recipes: {money(plan.learn_total)}")
    if plan.ranks_total:
        out.append(f"Profession ranks: {money(plan.ranks_total)}")
    unknown = sum(1 for r, c in plan.learn_costs if c is None)
    estimated = sum(1 for r, c in plan.learn_costs if c is not None and r.fee_from == "classic")
    notes = ([f"{estimated} trainer fee(s) are Classic estimates"] if estimated else []) + \
            ([f"{unknown} unknown, counted as 0"] if unknown else [])
    out.append(f"Grand total: {money(plan.grand_total)}" + (f"  ({'; '.join(notes)} - see data/trainer.json)" if notes else ""))
    if plan.unpriced:
        out.append("Warning: no price found for " + ", ".join(item_name(i, prices, vendor_names) for i in plan.unpriced))
    return "\n".join(out)


def plan_to_dict(plan: Plan, prices: PriceBook, vendor_names: dict[int, str], side: str | None = None) -> dict:
    return {
        "profession": plan.profession.key,
        "name": plan.profession.name,
        "data_note": plan.profession.note,
        "tools": [{"item_id": i, "name": n, "cost_copper": None if c == float("inf") else round(c)} for i, (n, c) in plan.tool_costs.items()],
        "unpriced": [item_name(i, prices, vendor_names) for i in plan.unpriced],
        "start": plan.start,
        "target": plan.target,
        "reached": plan.reached,
        "total_cost_copper": round(plan.total_cost),
        "tools_cost_copper": round(plan.tools_cost),
        "learn_cost_copper": round(plan.learn_total),
        "ranks_cost_copper": round(plan.ranks_total),
        "ranks": [{"name": r.name, "cap": r.cap, "skill": r.skill, "level": r.level, "how": r.how, "cost_copper": c,
                   "cost_from": r.cost_from, "before": prev_cap(plan, r),
                   "trainers": trainer_json(plan.profession.trainers_for(r, side)) if r.how == "trainer" else []}
                  for r, c in plan.ranks],
        "grand_total_copper": round(plan.grand_total),
        "learn": [
            {"recipe": r.name, "spell": r.spell, "how": how_of(plan, r), "cost_copper": c,
             "vendors": [{"name": v["name"], "title": v["title"], "zone": v["zone"], "x": v["x"], "y": v["y"],
                          "seen": v["seen"], "price_copper": v["price"]} for v in plan.profession.vendors_for(r, side)]
             if how_of(plan, r) == "vendor" else [], "learn_level": r.orange,
             "learn_level_known": r.learn_known, "learn_from": r.learn_from, "fee_from": r.fee_from,
             "trainers": trainer_json(plan.profession.trainers_for(r, side)) if r.source == "trainer" else [], "recipe_items": [{"item_id": i, "name": item_name(i, prices, vendor_names)} for i in r.recipe_items]}
            for r, c in plan.learn_costs if r.source != "auto"
        ],
        "sell_back": plan.sell_back,
        "sell_credit_copper": round(plan.sell_credit),
        "no_sell_price": [item_name(i, prices, vendor_names) for i in sorted(plan.no_sell_price)],
        "steps": [
            {"recipe": s.recipe.name, "how": how_of(plan, s.recipe), "crafts_per_point": round(s.crafts_per_point, 2),
             "low_chance": s.low_chance, "from": s.start, "to": s.end, "expected_crafts": round(s.expected_crafts, 2), "cost_copper": round(s.cost), "credit_copper": round(s.credit)}
            for s in plan.steps
        ],
        "craft_first": {k: round(v, 2) for k, v in plan.craft_first.items()},
        "buy": [
            {"item_id": i, "name": item_name(i, prices, vendor_names), "quantity": round(q, 2), "unit_price_copper": prices.quote(i).price, "price_source": prices.quote(i).source}
            for i, q in plan.buy.items()
        ],
    }


def main(argv: list[str] | None = None) -> int:
    profs = available_professions()
    ap = argparse.ArgumentParser(
        prog="cheapest_skillup",
        description="Cheapest path to level a WoW profession, priced with TSM's public auction data.",
    )
    ap.add_argument("professions", nargs="*", help=f"one or more of: {', '.join(profs)} (default: all)")
    ap.add_argument("--game", default="forever", help="TSM game type (default: forever)")
    ap.add_argument("--region", default="us", help="TSM region slug, e.g. us, eu (default: us)")
    ap.add_argument("--realm", default="pvp-horde", help="TSM auction house slug, e.g. normal-alliance, pvp-horde")
    ap.add_argument("--price", choices=PRICE_FIELDS, default="minBuyout", help="TSM price column to buy at (default: minBuyout)")
    ap.add_argument("--from", dest="start", type=int, default=1, help="current skill (default: 1)")
    ap.add_argument("--to", dest="target", type=int, default=150, help="target skill (default: 150)")
    ap.add_argument("--sources", default="trainer,vendor,recipe",
                    help="how you're willing to learn recipes: trainer, vendor (recipes sold by vendors on your side), "
                         "recipe (recipe items on your AH, at their AH price)")
    ap.add_argument("--sell-back", nargs="?", const="vendor", choices=("vendor", "ah"), default=None,
                    help="subtract what you get for selling what you craft: 'vendor' (default) uses vendor sell "
                         "prices from data/vendor_sell.json, 'ah' uses the AH price after the 5%% cut")
    ap.add_argument("--price-override", action="append", default=[], metavar="ITEM=COPPER", help="force a price, e.g. 2589=20 (repeatable)")
    ap.add_argument("--refresh", action="store_true", help="ignore the 3-hour download cache")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a report")
    args = ap.parse_args(argv)

    chosen = args.professions or profs
    unknown = [p for p in chosen if p not in profs]
    if unknown:
        ap.error(f"unknown profession(s): {', '.join(unknown)}. Choose from: {', '.join(profs)}")
    overrides = {}
    for o in args.price_override:
        k, _, v = o.partition("=")
        overrides[int(k)] = int(v)

    vendor_prices = load_vendor_prices()
    vendor_names = {**load_item_names(), **load_vendor_names()}
    try:
        prices, updated = load_pricebook(args.game, args.region, args.realm, vendor_prices, args.price, refresh=args.refresh,
                                         overrides=overrides, vendor_sell=load_vendor_sell(), names=load_item_names())
    except Exception as e:  # network / 404 for a wrong realm slug
        print(f"Could not download TSM prices for {args.game}/{args.region}/{args.realm}: {e}", file=sys.stderr)
        print("Check the slugs in your realm's URL on tradeskillmaster.com.", file=sys.stderr)
        return 2

    sources = {s.strip() for s in args.sources.split(",") if s.strip()}
    results = []
    for key in chosen:
        prof = load_profession(key)
        plan = cheapest_plan(prof, prices, args.start, args.target, sources, args.sell_back, side_of(args.realm))
        results.append(plan)

    if args.json:
        print(json.dumps({"prices_updated": updated, "auction_house": f"{args.game}/{args.region}/{args.realm}", "price_field": args.price,
                          "plans": [plan_to_dict(p, prices, vendor_names, side_of(args.realm)) for p in results]}, indent=2))
    else:
        print(f"Prices: TSM {args.price} for {args.game}/{args.region}/{args.realm}, scanned {updated}\n")
        print("\n\n".join(render(p, prices, vendor_names, side_of(args.realm)) for p in results))
        if load_foreverdb():
            print(f"\nRecipe sources and trainer fees: {FOREVERDB_CREDIT}")
        if len(results) > 1:
            print("\nSummary")
            for p in sorted(results, key=lambda p: p.grand_total):
                print(f"  {p.profession.name:<16} {money(p.grand_total):>14}" + ("" if p.reached >= p.target else f"  (stuck at {p.reached})"))
    return 0
