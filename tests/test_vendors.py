import json
import tempfile
import unittest
from pathlib import Path

from cheapest_skillup.foreverdb import parse_vendor_stock
from cheapest_skillup.recipes import load_vendor_prices

NPCS = '''ns.npcs = {[1]={"Alliance Supplier","Trade Supplies",1453,1,1,"A",1},[2]={"Horde Supplier","Trade Supplies",1454,1,1,"H",1},[3]={"Goblin","Trade Supplies",1446,1,1,"",1}}
ns.sold = {[100]={1,20,5,0,2,30,5,0},[200]={3,50,1,1},[300]={1,10,1,1,2,40,1,0}}
ns.soldNames = {}'''


class VendorPrices(unittest.TestCase):
    def setUp(self):
        stock, sides = parse_vendor_stock(NPCS)
        self.dir = tempfile.TemporaryDirectory()
        d = Path(self.dir.name)
        (d / "vendor_items.json").write_text(json.dumps({"items": {"200": {"name": "x", "price": 77}, "400": {"name": "y", "price": 9}}}))
        (d / "foreverdb.json").write_text(json.dumps({"npc_sides": {str(k): v for k, v in sides.items()},
                                                     "vendor_stock": {str(k): v for k, v in stock.items()}}))
        self.d = d

    def tearDown(self):
        self.dir.cleanup()

    def test_price_per_item_and_faction(self):
        self.assertEqual(load_vendor_prices(self.d, "a")[100], 4)  # 20c for a stack of 5
        self.assertEqual(load_vendor_prices(self.d, "h")[100], 6)  # the Horde vendor's 30c for 5

    def test_limited_supply_is_never_a_vendor_price(self):
        a = load_vendor_prices(self.d, "a")
        self.assertNotIn(200, a)  # only sold in limited supply (and ForeverDB's data overrides the hand list)
        self.assertNotIn(300, a)  # Alliance stock is limited; the Horde one isn't on your side
        self.assertEqual(load_vendor_prices(self.d, "h")[300], 40)
        self.assertEqual(a[400], 9)  # not in ForeverDB's data: hand list


if __name__ == "__main__":
    unittest.main()
