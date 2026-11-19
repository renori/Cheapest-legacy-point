import unittest

from cheapest_skillup.blizzard import faction, summarize


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


if __name__ == "__main__":
    unittest.main()
