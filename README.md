# Cheapest Skill-up

Finds the cheapest way to level a WoW Forever crafting profession (default 1 → 150), priced with
[TradeSkillMaster's public pricing data](https://tradeskillmaster.com/public-data).

No API key and no dependencies, just Python 3.10+.

## GUI

```sh
python -m cheapest_skillup.gui            # opens http://127.0.0.1:8765/ in your browser
python -m cheapest_skillup.gui --port 9000 --no-browser
```

Pick professions, your auction house (region + Normal/PvP + faction), the price column and the skill
range, then press **Find cheapest route**. You get a cost comparison of all selected professions, and
for each one the route, a step table, a shopping list, intermediates to craft, tools and recipes to
buy. The server listens only on `127.0.0.1`, so only your computer can reach it. Stop it with Ctrl+C.

## Command line

```sh
python -m cheapest_skillup tailoring                       # one profession
python -m cheapest_skillup                                 # all of them, plus a summary
python -m cheapest_skillup alchemy --realm pvp-horde --region eu
python -m cheapest_skillup leatherworking --from 75 --to 150
python -m cheapest_skillup cooking --sources trainer,vendor,quest
python -m cheapest_skillup tailoring --sell-back           # subtract AH value of what you craft
python -m cheapest_skillup tailoring --price marketValue   # if min buyouts are thin
python -m cheapest_skillup tailoring --json
```

Professions: `alchemy`, `blacksmithing`, `cooking`, `enchanting`, `engineering`, `first_aid`,
`leatherworking`, `tailoring`.

## Prices

Downloaded from `https://public-data.tradeskillmaster.com` and cached for 3 hours in
`~/.cache/cheapest-skillup` (`--refresh` ignores the cache).

| Option     | Default           | Meaning                                                             |
|------------|-------------------|---------------------------------------------------------------------|
| `--game`   | `forever`         | TSM game type                                                       |
| `--region` | `us`              | `us`, `eu`, ...                                                     |
| `--realm`  | `normal-alliance` | Forever auction house: `normal-alliance`, `normal-horde`, `pvp-alliance`, `pvp-horde` |
| `--price`  | `minBuyout`       | TSM column used for buying: `minBuyout`, `marketValue`, `recent`, `historical` |

For each reagent the tool uses the cheapest of:

1. the auction-house price (`--price` column) or, if nothing is listed, the region market value;
2. the vendor price from `data/vendor_items.json`;
3. crafting it yourself with a recipe from the same profession (for example, Bolt of Linen Cloth from
   Linen Cloth).

`--price-override 2589=20` forces a price in copper, for example for mats you already own (`=0`).

## How the plan is chosen

At skill `s`, a recipe with colours `[orange, yellow, green, grey]` skills up with probability 1
below yellow, `(grey − s) / (grey − yellow)` from yellow to grey, and 0 at grey. The expected cost of
one point is `craft cost / probability`. Each point is independent, so picking the cheapest recipe
for every point gives the cheapest total. Quantities in the report are expected values, so buy a
little extra.

Not modelled: skill-ups from crafting intermediates (so the estimate errs high), trainer costs,
the items you need to enchant, and the AH order book. Min buyout is the price of the *cheapest*
listing, so large purchases will cost more; compare against `--price marketValue`.

## Recipe data: please verify

`data/recipes/*.json` are **Classic Era** recipes (skill thresholds and reagents) entered by
hand. WoW Forever reworked professions: TSM's Forever item list already shows renamed items
(Gray Leather Boots, Elixir of Minor Strength, Minor Troll's Blood Elixir) and many new crafted
items (Cleric's/Mageblood/Spellblasting elixirs, Teas, Smoothies, new dishes, Pristine Leather,
Sandpaper...) whose recipes are not in the data yet. Fix or add recipes as you confirm them in
game:

```json
{"name": "Bolt of Linen Cloth", "skill": [1, 25, 37, 50], "makes": {"item": 2996, "qty": 1},
 "reagents": {"2589": 2}, "source": "trainer", "tools": []}
```

`skill` is `[orange (learn), yellow, green, grey]`. `source` is `trainer`, `vendor`, `quest` or
`drop`, and `--sources` controls which are allowed (default `trainer,vendor`).

Check every item id against TSM's item names:

```sh
python -m cheapest_skillup.check_data
```

## Tests

```sh
python -m unittest
```
