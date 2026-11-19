import unittest

from cheapest_skillup import gui


class GuiApi(unittest.TestCase):
    def test_options_lists_professions_and_auction_houses(self):
        o = gui.options()
        self.assertIn("tailoring", [p["key"] for p in o["professions"]])
        self.assertIn("pvp-horde", o["realms"])
        self.assertEqual(o["defaults"]["price"], "minBuyout")
        self.assertEqual((o["defaults"]["region"], o["defaults"]["realm"]), ("us", "pvp-horde"))
        self.assertEqual(o["milestones"], [75, 150, 225, 300])

    def test_bad_input_is_rejected_before_downloading(self):
        for q in ({"prof": ["nope"]}, {"prof": ["tailoring"], "price": ["bogus"]},
                  {"prof": ["tailoring"], "sell_back": ["1"]}, {"prof": ["tailoring"], "from": ["150"], "to": ["100"]},
                  {"prof": ["tailoring"], "to": ["999"]}):
            with self.assertRaises(ValueError):
                gui.make_plan(q)

if __name__ == "__main__":
    unittest.main()
