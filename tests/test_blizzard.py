import unittest

from cheapest_skillup.blizzard import assign_rulesets, faction, ruleset_ref, summarize


class Summarize(unittest.TestCase):
    def test_cheapest_unit_buyout_and_quantity(self):
        auctions = [
            {"item": {"id": 2589}, "buyout": 400, "quantity": 20},  # 20c each
            {"item": {"id": 2589}, "buyout": 30, "quantity": 1},
            {"item": {"id": 2589}, "bid": 5, "quantity": 1},  # bid only: ignored
            {"item": {"id": 7}, "buyout": 999, "quantity": 1},
        ]
        commodities = [{"item": {"id": 2589}, "unit_price": 18, "quantity": 100}, {"item": {"id": 8}, "unit_price": 0, "quantity": 3}]
        got = summarize(auctions, commodities)
        self.assertEqual(got["2589"], [18, 121])
        self.assertEqual(got["7"], [999, 1])
        self.assertNotIn("8", got)

    def test_faction(self):
        self.assertEqual(faction("Alliance Auction House"), "a")
        self.assertEqual(faction("Horde Auction House"), "h")
        self.assertEqual(faction("Blackwater Auction House"), "n")


class Rulesets(unittest.TestCase):
    RS = {1: "PvP", 2: "Normal"}

    def test_reported_rulesets_win(self):
        got = assign_rulesets(self.RS, {1: [110, 111], 2: [110, 111]}, {110: 1, 111: 2})
        self.assertEqual(got, {110: 1, 111: 2})

    def test_distinct_house_lists(self):
        got = assign_rulesets(self.RS, {1: [110], 2: [111]}, {110: 1, 111: 1})
        self.assertEqual(got, {110: 1, 111: 2})

    def test_unknown_when_api_does_not_say(self):
        got = assign_rulesets(self.RS, {1: [110, 111], 2: [110, 111]}, {110: 1, 111: 1})
        self.assertEqual(got, {110: None, 111: None})

    def test_ruleset_ref(self):
        self.assertEqual(ruleset_ref({"id": 2, "name": "Normal"}), (2, "Normal"))
        self.assertEqual(ruleset_ref({"id": 1, "name": {"en_US": "PvP"}}), (1, "PvP"))
        self.assertEqual(ruleset_ref(3), (3, None))
        self.assertEqual(ruleset_ref(None), (None, None))


if __name__ == "__main__":
    unittest.main()
