import unittest

from cheapest_skillup.blizzard import assign_rulesets, faction, infer_rulesets, ruleset_ref, summarize


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

    def test_infer_from_house_ids(self):
        listings = {110: 9, 111: 9, 112: 0, 113: 9, 114: 9, 115: 0, 116: 9, 117: 9, 118: 0,
                    119: 5, 120: 5, 121: 1, 123: 5, 124: 5, 125: 1}
        fac = lambda i: "a" if i in (110, 111, 112, 119, 123) else "h" if i in (113, 114, 115, 120, 124) else "n"  # noqa: E731
        houses = [{"id": i, "faction": fac(i), "listings": n} for i, n in listings.items()]
        rs = {1: "PvP", 2: "Normal", 3: "Roleplay", 15: "Roleplay PvP"}
        got = infer_rulesets(rs, houses)
        self.assertEqual([got[i] for i in (110, 113, 116)], [1, 1, 1])
        self.assertEqual([got[i] for i in (111, 114, 117)], [2, 2, 2])
        self.assertNotIn(112, got)  # the empty set
        self.assertEqual([got[i] for i in (119, 120, 121)], [3, 3, 3])
        self.assertEqual([got[i] for i in (123, 124, 125)], [15, 15, 15])
        self.assertEqual(infer_rulesets({1: "PvP"}, houses), {})  # sets and rulesets don't pair up: no guess

    def test_ruleset_ref(self):
        self.assertEqual(ruleset_ref({"id": 2, "name": "Normal"}), (2, "Normal"))
        self.assertEqual(ruleset_ref({"id": 1, "name": {"en_US": "PvP"}}), (1, "PvP"))
        self.assertEqual(ruleset_ref(3), (3, None))
        self.assertEqual(ruleset_ref(None), (None, None))


if __name__ == "__main__":
    unittest.main()
