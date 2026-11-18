import json
import tempfile
import unittest
from pathlib import Path

from cheapest_skillup.classic_trainers import estimate, parse_trainer_sql
from cheapest_skillup.gamedata import build_data
from cheapest_skillup.optimizer import Optimizer, cheapest_plan
from cheapest_skillup.prices import PriceBook, parse_csv
from cheapest_skillup.recipes import Profession, Recipe, load_profession

REALM = """itemId,name,marketValue,minBuyout,recent,historical,updatedAt
1,Cloth,10,10,10,10,x
50,Pattern: Cheap Hat,500,500,500,500,x
51,Pattern: Gold Hat,9000000,9000000,9000000,9000000,x
"""


def book():
    return PriceBook(parse_csv(REALM), {}, {})


def hat(name, item, cost=1):
    # Skills up with certainty from 1 to 100 using `cost` cloth.
    return Recipe(name, 1, 100, 100, 101, {1: cost}, source="recipe", recipe_items=[item])


class RecipeItems(unittest.TestCase):
    def test_recipe_items_must_be_on_your_ah(self):
        prof = Profession("t", "T", [hat("Listed", 50), hat("Not listed", 99)])
        opt = Optimizer(prof, book())
        self.assertEqual([r.name for r in opt.recipes], ["Listed"])
        self.assertEqual(opt.learn_cost(opt.recipes[0]), 500)

    def test_disallowing_recipe_items(self):
        prof = Profession("t", "T", [hat("Listed", 50)])
        self.assertEqual(Optimizer(prof, book(), {"trainer"}).recipes, [])

    def test_buys_a_recipe_only_when_it_pays_off(self):
        # Trainer craft costs 3 cloth (30c) per point; the AH recipe saves 20c x 99 points = 19s80c.
        trainer = Recipe("Trainer Hat", 1, 100, 100, 101, {1: 3}, source="trainer", learn_cost=0)
        cheap = cheapest_plan(Profession("t", "T", [trainer, hat("Cheap Hat", 50)]), book(), 1, 100)
        self.assertEqual({s.recipe.name for s in cheap.steps}, {"Cheap Hat"})  # 5s recipe pays off
        self.assertEqual(cheap.learn_total, 500)
        dear = cheapest_plan(Profession("t", "T", [trainer, hat("Gold Hat", 51)]), book(), 1, 100)
        self.assertEqual({s.recipe.name for s in dear.steps}, {"Trainer Hat"})  # 900g recipe doesn't
        self.assertEqual(dear.learn_total, 0)

    def test_unknown_trainer_fee_counts_as_zero_but_is_reported(self):
        r = Recipe("Trainer Hat", 1, 100, 100, 101, {1: 1}, source="trainer", learn_cost=None)
        plan = cheapest_plan(Profession("t", "T", [r]), book(), 1, 10)
        self.assertEqual(plan.learn_costs, [(r, None)])
        self.assertEqual(plan.learn_total, 0)


class TrainerFile(unittest.TestCase):
    def test_trainer_json_sets_fee_and_learn_level(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "recipes").mkdir()
            Path(d, "recipes", "x.json").write_text(json.dumps({"name": "X", "recipes": [
                {"name": "Vest", "spell": 7, "skill": [45, 45, 57, 70], "learn": "trainer", "learn_level_known": False, "reagents": {"1": 1}}]}))
            Path(d, "trainer.json").write_text(json.dumps({"spells": {"7": {"cost": 250, "learn": 10}}}))
            r = load_profession("x", Path(d)).recipes[0]
            self.assertEqual((r.learn_cost, r.orange, r.learn_known), (250, 10, True))
            Path(d, "trainer.json").write_text(json.dumps({"spells": {"7": {"exclude": True}}}))
            self.assertEqual(load_profession("x", Path(d)).recipes, [])

    def test_classic_estimates_apply_unless_you_set_values(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "recipes").mkdir()
            Path(d, "recipes", "x.json").write_text(json.dumps({"name": "X", "recipes": [
                {"name": "Vest", "spell": 7, "skill": [45, 45, 57, 70], "learn": "trainer", "learn_level_known": False, "reagents": {"1": 1}},
                {"name": "Belt", "spell": 8, "skill": [50, 50, 67, 85], "learn": "trainer", "learn_level_known": False, "reagents": {"1": 1}},
                {"name": "Kilt", "spell": 9, "skill": [75, 75, 87, 100], "learn": "trainer", "learn_level_known": False, "reagents": {"1": 1}}]}))
            Path(d, "trainer_classic.json").write_text(json.dumps({"spells": {"7": {"cost": 45, "learn": 10}, "8": {"cost": 45, "learn": 10}}}))
            Path(d, "trainer.json").write_text(json.dumps({"spells": {"8": {"cost": 60, "learn": None}}}))
            vest, belt, kilt = load_profession("x", Path(d)).recipes
            self.assertEqual((vest.learn_cost, vest.fee_from, vest.orange, vest.learn_from, vest.learn_known), (45, "classic", 10, "classic", False))
            self.assertEqual((belt.learn_cost, belt.fee_from, belt.orange, belt.learn_from), (60, "you", 10, "classic"))
            self.assertEqual((kilt.learn_cost, kilt.fee_from, kilt.orange, kilt.learn_from), (None, None, 75, "assumed"))


class ClassicTrainers(unittest.TestCase):
    SQL = ("INSERT INTO `npc_trainer_template` VALUES (1,9001,45,197,10,5,NULL,NULL,NULL,0),(2,9001,60,197,10,5,NULL,NULL,NULL,0),"
           "(1,9002,100,197,90,0,NULL,NULL,NULL,0),(1,9003,10,171,1,0,NULL,NULL,NULL,0);\n"
           "INSERT INTO `npc_trainer` VALUES (5,9004,500,164,40,0,NULL,NULL,NULL,0);\n")

    def test_parse_and_estimate(self):
        rows = parse_trainer_sql(self.SQL)
        self.assertEqual(len(rows), 5)
        recipes = {
            100: {"name": "Vest", "learn": "trainer", "skill": [45, 45, 57, 70]},  # taught by 9001
            200: {"name": "Shirt", "learn": "trainer", "skill": [60, 60, 70, 80]},  # taught by 9002, Forever made it easier
            300: {"name": "Potion", "learn": "recipe", "skill": [1, 20, 30, 40]},  # not a trainer recipe in Forever
        }
        est = estimate(rows, {9001: 100, 9002: 200, 9003: 300}, recipes)
        self.assertEqual(est[100], {"name": "Vest", "cost": 45, "learn": 10})  # cheapest of two trainers
        self.assertEqual(est[200]["learn"], 60)  # capped at Forever's yellow level
        self.assertNotIn(300, est)


def row(**kw):
    return {k: str(v) for k, v in kw.items()}


class GameData(unittest.TestCase):
    def tables(self):
        ra = lambda spell, line, low, high, acq=0: row(Spell=spell, SkillLine=line, TrivialSkillLineRankLow=low, TrivialSkillLineRankHigh=high,
                                                       AcquireMethod=acq, NumSkillUps=1, MinSkillLineRank=1)
        reag = lambda spell, item, n: row(SpellID=spell, **{f"Reagent_{k}": (item if k == 0 else 0) for k in range(8)},
                                         **{f"ReagentCount_{k}": (n if k == 0 else 0) for k in range(8)})
        item = lambda i, name, skill=0, rank=0, bond=0, sell=0: row(ID=i, Display_lang=name, RequiredSkill=skill, RequiredSkillRank=rank,
                                                                   Bonding=bond, SellPrice=sell, BuyPrice=0, TotemCategoryID=0, ItemLevel=1)
        return {
            "SkillLineAbility": [ra(1, 197, 25, 50, acq=1), ra(2, 197, 60, 95), ra(3, 197, 80, 100), ra(4, 197, 90, 110)],
            "SpellName": [row(ID=1, Name_lang="Bolt"), row(ID=2, Name_lang="Cape"), row(ID=3, Name_lang="Robe"), row(ID=4, Name_lang="Quest Hat")],
            "SpellReagents": [reag(s, 2589, 2) for s in (1, 2, 3, 4)],
            "SpellEffect": [row(SpellID=1, Effect=24, EffectItemType=2996, EffectBasePointsF=1)],
            "SpellTotems": [],
            "ItemSparse": [item(2589, "Linen Cloth"), item(2996, "Bolt of Linen Cloth", sell=40),
                           item(700, "Pattern: Robe", 197, 55), item(701, "Pattern: Quest Hat", 197, 70, bond=1)],
        }

    def test_build(self):
        profs, sell, names = build_data(self.tables())
        rec = {r["name"]: r for r in profs["tailoring"]["recipes"]}
        self.assertEqual(rec["Bolt"]["learn"], "auto")
        self.assertEqual(rec["Bolt"]["skill"], [1, 25, 37, 50])
        self.assertEqual(rec["Bolt"]["makes"], {"item": 2996, "qty": 1})
        self.assertEqual((rec["Cape"]["learn"], rec["Cape"]["learn_level_known"], rec["Cape"]["skill"][0]), ("trainer", False, 60))
        self.assertEqual((rec["Robe"]["learn"], rec["Robe"]["skill"][0], rec["Robe"]["recipe_items"]), ("recipe", 55, [700]))
        self.assertNotIn("Quest Hat", rec)  # only taught by a bind-on-pickup item (quest reward)
        self.assertEqual(sell[2996]["sell"], 40)
        self.assertEqual(names[2589], "Linen Cloth")


if __name__ == "__main__":
    unittest.main()
