import unittest

from cheapest_skillup.vendor_sell import crafted_items, parse_saved_variables

SAVED = '''
CheapestSkillupExportDB = {
	["exported"] = "2026-11-18 20:00",
	["names"] = {
		[2996] = "Bolt of Linen Cloth",
		[4314] = "Double-Stitched \\\\"Woolen\\\\" Shoulders",
	},
	["sell"] = {
		[2996] = 40,
		[4314] = 0,
	},
}
'''


class SavedVariables(unittest.TestCase):
    def test_parse(self):
        got = parse_saved_variables(SAVED)
        self.assertEqual(got[2996], ("Bolt of Linen Cloth", 40))
        self.assertEqual(got[4314][1], 0)

    def test_crafted_items_cover_recipe_products(self):
        items = crafted_items()
        self.assertIn(2996, items)  # Bolt of Linen Cloth
        self.assertNotIn(2589, items)  # Linen Cloth is a reagent only


if __name__ == "__main__":
    unittest.main()
