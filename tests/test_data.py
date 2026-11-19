import json
import tempfile
import unittest
from pathlib import Path

from cheapest_skillup.recipes import available_professions, load_profession, load_vendor_sell


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
