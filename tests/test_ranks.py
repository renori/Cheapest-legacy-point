import json
import tempfile
import unittest
from pathlib import Path

from cheapest_skillup.foreverdb import parse_ranks_lua, parse_trainers_lua
from cheapest_skillup.recipes import Profession, Rank, load_ranks

def ranks():
    return [Rank("Apprentice", 75, 0, 5, 10), Rank("Journeyman", 150, 50, 10, 500),
            Rank("Expert", 225, 125, 20, 5000), Rank("Artisan", 300, 200, 35, 50000)]


class Ranks(unittest.TestCase):
    def test_ranks_needed(self):
        prof = Profession("t", "T", [], ranks=ranks())
        names = lambda a, b: [r.name for r in prof.ranks_needed(a, b)]  # noqa: E731
        self.assertEqual(names(1, 150), ["Apprentice", "Journeyman"])
        self.assertEqual(names(1, 75), ["Apprentice"])
        self.assertEqual(names(75, 150), ["Journeyman"])  # at the Apprentice cap
        self.assertEqual(names(120, 225), ["Expert"])
        self.assertEqual(names(120, 300), ["Expert", "Artisan"])

    def test_load_ranks_priority_and_special_ranks(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "trainer_classic.json").write_text(json.dumps({"ranks": {"first_aid": [
                {"cap": 75, "skill": 0, "level": 0, "cost": 100}, {"cap": 150, "skill": 50, "level": 0, "cost": 500}]}}))
            Path(d, "foreverdb.json").write_text(json.dumps({"ranks": {"first_aid": [
                {"name": "Apprentice", "cap": 75, "skill": 0, "level": 0, "cost": 120, "trainers": {"h": [1]}}]}}))
            rs = {r.cap: r for r in load_ranks("first_aid", Path(d))}
            self.assertEqual((rs[75].cost, rs[75].cost_from, rs[75].trainers), (120, "forever", {"h": [1]}))
            self.assertEqual((rs[150].cost, rs[150].cost_from), (500, "classic"))
            self.assertEqual((rs[225].how, rs[225].item), ("book", 16084))
            self.assertEqual((rs[300].how, rs[300].cost), ("quest", 0))


HELPER = '''["first-aid"]=[=[return {ranks={{r="Apprentice",max=75,sk=0,lv=0,cost=100,tr={a={5150},h={3373}}}},a={steps={{s=3275,a=1,b=40,n="Linen Bandage",L={how="tf",tr={5150,2326}}}}},h={steps={{s=3275,a=1,b=40,n="Linen Bandage",L={how="tf",tr={3373}}}}}}]=],
ns.profNpcSrc = [=[return {[5150]={"Nissa Firestone","First Aid Trainer","a",1455,54.8,58.6,1},[3373]={"Arnok","First Aid Trainer","h",1454,34.0,84.6,0}}]=]'''


class TrainerData(unittest.TestCase):
    def test_parse_helper(self):
        self.assertEqual(parse_ranks_lua(HELPER)["first_aid"][0]["cost"], 100)
        rank_tr, recipe_tr, npcs = parse_trainers_lua(HELPER)
        self.assertEqual(rank_tr["first_aid"]["75"], {"a": [5150], "h": [3373]})
        self.assertEqual(recipe_tr[3275], {"a": [5150, 2326], "h": [3373]})
        self.assertEqual(npcs[3373]["name"], "Arnok")
        self.assertFalse(npcs[3373]["seen"])


if __name__ == "__main__":
    unittest.main()
