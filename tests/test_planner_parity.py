"""The browser planner (planner.js) must give the same routes and totals as the Python planner.

Builds the site data, takes one price snapshot, and runs both planners on the same cases.
Skipped when Node.js isn't installed.
"""

import json
import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from cheapest_skillup.build_site import build
from cheapest_skillup.optimizer import cheapest_plan
from cheapest_skillup.prices import PriceBook
from cheapest_skillup.recipes import (available_professions, load_item_names, load_profession, load_vendor_prices,
                                      load_vendor_sell)

HERE = Path(__file__).resolve().parent
NODE = shutil.which("node")


def snapshot(items: list[int], seed: int = 7) -> dict[str, list[int]]:
    """A made-up but realistic auction house: most items listed, at varied prices."""
    rng = random.Random(seed)
    out = {}
    for i in items:
        if rng.random() < 0.8:
            out[str(i)] = [rng.choice([rng.randint(1, 99), rng.randint(100, 9999), rng.randint(10000, 200000)]), rng.randint(1, 500)]
    return out


def python_pricebook(prices: dict, side: str | None) -> PriceBook:
    realm = {int(i): {"minBuyout": str(p[0]), "name": ""} for i, p in prices.items()}
    return PriceBook(realm, {}, load_vendor_prices(side=side), "minBuyout", vendor_sell=load_vendor_sell(),
                     names=load_item_names())


@unittest.skipUnless(NODE, "Node.js not installed")
class Parity(unittest.TestCase):
    def test_same_routes_and_totals(self):
        with tempfile.TemporaryDirectory() as d:
            site = Path(d) / "site"
            build(site)
            items = [int(i) for i in json.loads((site / "data" / "items.json").read_text())]
            prices = snapshot(items)
            (Path(d) / "prices.json").write_text(json.dumps(prices))
            cases = []
            for prof in available_professions():
                for (start, to, sell, side, craft, sources) in [
                    (1, 150, None, "h", True, ["trainer", "vendor", "recipe"]),
                    (1, 300, "vendor", "a", True, ["trainer", "vendor", "recipe"]),
                    (120, 225, "ah", "h", False, ["trainer", "vendor"]),
                    (1, 225, None, None, True, ["trainer"]),
                ]:
                    cases.append({"prof": prof, "from": start, "to": to, "sell_back": sell, "side": side,
                                  "craft": craft, "sources": sources})
            (Path(d) / "cases.json").write_text(json.dumps(cases))
            js = json.loads(subprocess.run([NODE, str(HERE / "parity_runner.mjs"), str(site), str(Path(d) / "prices.json"),
                                            str(Path(d) / "cases.json")], capture_output=True, text=True, check=True).stdout)
            books = {side: python_pricebook(prices, side) for side in ("a", "h", None)}
            for c, j in zip(cases, js):
                with self.subTest(**{k: c[k] for k in ("prof", "from", "to", "sell_back", "side", "craft")}):
                    plan = cheapest_plan(load_profession(c["prof"]), books[c["side"]], c["from"], c["to"], set(c["sources"]),
                                         c["sell_back"], c["side"], craft_intermediates=c["craft"])
                    self.assertEqual([[s.recipe.name, s.start, s.end] for s in plan.steps], j["steps"])
                    self.assertEqual(plan.reached, j["reached"])
                    for key, py in (("grand", plan.grand_total), ("materials", plan.total_cost), ("learn", plan.learn_total),
                                    ("ranks", plan.ranks_total), ("tools", plan.tools_cost)):
                        self.assertAlmostEqual(py, j[key], delta=max(1e-6, abs(py) * 1e-9), msg=key)
                    self.assertEqual({str(k): round(v, 6) for k, v in plan.buy.items()}, {k: round(v, 6) for k, v in j["buy"].items()})


if __name__ == "__main__":
    unittest.main()
