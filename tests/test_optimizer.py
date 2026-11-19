import unittest

from cheapest_skillup.optimizer import Optimizer
from cheapest_skillup.prices import PriceBook, parse_csv
import json
import tempfile
from pathlib import Path

from cheapest_skillup.recipes import Profession, Recipe, available_professions, load_profession, load_vendor_sell

REALM_CSV = """itemId,name,marketValue,minBuyout,recent,historical,updatedAt
1,Cloth,10,10,10,10,2026-01-01T00:00:00Z
2,Bolt,50,50,50,50,2026-01-01T00:00:00Z
3,Hat,100,80,100,100,2026-01-01T00:00:00Z
"""
REGION_CSV = """itemId,name,marketValue,historical,avgSalePrice,saleRate,soldPerDay,updatedAt
1,Cloth,12,12,12,0.5,10,2026-01-01T00:00:00Z
4,Rare Gem,999,999,999,0.1,1,2026-01-01T00:00:00Z
"""


def book(**kw):
    return PriceBook(parse_csv(REALM_CSV), parse_csv(REGION_CSV), {9: 5}, **kw)


class SkillupChance(unittest.TestCase):
    def test_colors(self):
        r = Recipe("x", 10, 20, 30, 40, {})
        self.assertEqual(r.skillup_chance(9), 0)  # not learnable yet
        self.assertEqual(r.skillup_chance(10), 1)  # orange
        self.assertEqual(r.skillup_chance(20), 1)  # (40-20)/(40-20)
        self.assertEqual(r.skillup_chance(30), 0.5)
        self.assertEqual(r.skillup_chance(40), 0)  # grey


class Prices(unittest.TestCase):
    def test_min_buyout_then_region_then_vendor(self):
        b = book()
        self.assertEqual(b.quote(3).price, 80)
        self.assertEqual(b.quote(3).source, "minBuyout")
        self.assertEqual(b.quote(4).source, "region marketValue")
        self.assertEqual(b.quote(9).source, "vendor")
        self.assertIsNone(b.quote(12345).price)

    def test_override(self):
        self.assertEqual(book(overrides={3: 1}).quote(3).price, 1)


class Planning(unittest.TestCase):
    def prof(self):
        return Profession("t", "Test", [
            Recipe("Make Bolt", 1, 10, 15, 20, {1: 2}, makes=2),  # 20c per bolt crafted vs 50c bought
            Recipe("Hat", 1, 30, 40, 50, {2: 2, 9: 1}, makes=3),  # 2 bolts + 5c thread
        ])

    def test_crafts_intermediates_when_cheaper(self):
        opt = Optimizer(self.prof(), book())
        cost, maker = opt.unit_cost(2, 5)
        self.assertEqual(cost, 20)
        self.assertEqual(maker.name, "Make Bolt")

    def test_picks_cheapest_per_point_and_totals(self):
        plan = Optimizer(self.prof(), book()).plan(1, 30)
        self.assertEqual(plan.reached, 30)
        # Bolt: 20c per craft, chance (20-s)/10 from skill 10 -> 40c/point at 15, 50c at 16.
        # Hat: 2 crafted bolts + thread = 45c per point (orange until 30).
        self.assertEqual(plan.steps[0].recipe.name, "Make Bolt")
        self.assertEqual((plan.steps[0].start, plan.steps[0].end), (1, 16))
        self.assertEqual(plan.steps[1].recipe.name, "Hat")
        bolt = sum(20 / min(1, (20 - s) / 10) for s in range(1, 16))
        self.assertAlmostEqual(plan.total_cost, bolt + 45 * (30 - 16))
        self.assertEqual(plan.craft_first, {"Make Bolt": 28})  # 14 hats x 2 bolts

    def test_stuck_when_nothing_skills_up(self):
        plan = Optimizer(self.prof(), book()).plan(1, 60)
        self.assertEqual(plan.reached, 50)

    def test_sell_back_to_ah_lowers_cost(self):
        a = Optimizer(self.prof(), book()).plan(1, 30).total_cost
        b = Optimizer(self.prof(), book(), sell_back="ah").plan(1, 30).total_cost
        self.assertLess(b, a)

    def test_sell_back_to_vendor_uses_vendor_sell_prices(self):
        plain = Optimizer(self.prof(), book()).plan(1, 30)
        # Hats vendor for 10c, bolts for nothing known.
        plan = Optimizer(self.prof(), book(vendor_sell={3: 10}), sell_back="vendor").plan(1, 30)
        hat_steps = [s for s in plan.steps if s.recipe.name == "Hat"]
        self.assertTrue(hat_steps)
        for s in hat_steps:
            self.assertAlmostEqual(s.credit, 10 * s.expected_crafts)
            self.assertAlmostEqual(s.cost, 45 * s.expected_crafts - s.credit)  # 45c of mats per hat
        # With the credit and 5c of effort per craft, hats (40c/point) beat bolts (25c/0.6 = 41.7c) from 14.
        self.assertEqual(hat_steps[0].start, 14)
        self.assertLess(plan.total_cost, plain.total_cost)
        self.assertEqual(plan.no_sell_price, {2})  # bolts were crafted and sold, no vendor price
        # Vendor mode never uses the AH price (80c for hats).
        self.assertEqual(book().sell_value(3, "vendor"), 0)
        self.assertEqual(book().sell_value(3, "ah"), 76)

    def test_profit_does_not_make_the_route_grind_low_chances(self):
        # Selling makes "Cheap" a 40c profit per craft, but past 40 it barely skills up; "Plain" costs 3c a craft.
        cheap = Recipe("Cheap", 1, 10, 30, 50, {1: 1}, makes=3)
        plain = Recipe("Plain", 30, 100, 100, 101, {9: 1}, makes=None)
        b = book(vendor_sell={3: 50})
        plan = Optimizer(Profession("t", "T", [cheap, plain]), b, sell_back="vendor").plan(1, 60)
        by_name = {s.recipe.name: s for s in plan.steps}
        self.assertLess(by_name["Cheap"].end, 50)  # switches before Cheap goes near-grey
        self.assertLess(plan.total_cost, 0)  # the reported cost still includes the profit

    def test_bad_sell_back_mode(self):
        with self.assertRaises(ValueError):
            Optimizer(self.prof(), book(), sell_back="banana")


class Data(unittest.TestCase):
    def test_all_profession_files_load_and_are_sane(self):
        for key in available_professions():
            prof = load_profession(key)
            self.assertTrue(prof.recipes, key)
            for r in prof.recipes:
                self.assertTrue(r.orange <= r.yellow <= r.green <= r.grey, f"{key}: {r.name}")
                self.assertTrue(r.reagents, f"{key}: {r.name}")

    def test_vendor_sell_file_skips_unknown_prices(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "vendor_sell.json").write_text(json.dumps(
                {"items": {"2996": {"name": "Bolt of Linen Cloth", "sell": 40}, "2570": {"name": "Linen Cloak", "sell": None}}}))
            self.assertEqual(load_vendor_sell(Path(d)), {2996: 40})
            self.assertEqual(load_vendor_sell(Path(d, "missing")), {})

    def test_shipped_vendor_sell_file_loads(self):
        load_vendor_sell()


if __name__ == "__main__":
    unittest.main()
