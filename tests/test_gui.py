import unittest

from cheapest_skillup import gui


class GuiApi(unittest.TestCase):
    def test_options_lists_professions_and_auction_houses(self):
        o = gui.options()
        self.assertIn("tailoring", [p["key"] for p in o["professions"]])
        self.assertIn("pvp-horde", o["realms"])
        self.assertEqual(o["defaults"]["price"], "minBuyout")

    def test_bad_input_is_rejected_before_downloading(self):
        with self.assertRaises(ValueError):
            gui.make_plan({"professions": ["nope"]})
        with self.assertRaises(ValueError):
            gui.make_plan({"professions": ["tailoring"], "price": ["bogus"]})
        with self.assertRaises(ValueError):
            gui.make_plan({"professions": ["tailoring"], "from": ["150"], "to": ["100"]})


if __name__ == "__main__":
    unittest.main()
