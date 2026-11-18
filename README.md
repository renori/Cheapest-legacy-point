# Cheapest Skill-up

Finds the cheapest way to level a WoW Forever crafting profession (default 1 → 150), priced with
[TradeSkillMaster's public pricing data](https://tradeskillmaster.com/public-data).

No API key and no dependencies, just Python 3.10+.

## GUI

On Windows, double-click **`start_gui.bat`** in this folder. Or open a terminal **in this folder**
(the one that contains `cheapest_skillup`) and run:

```sh
python -m cheapest_skillup.gui            # opens http://127.0.0.1:8765/ in your browser
python -m cheapest_skillup.gui --port 9000 --no-browser
```

Pick professions, your auction house (region + Normal/PvP + faction), the price column and the skill
range, then press **Find cheapest route**. You get a cost comparison of all selected professions, and
for each one the route, a step table (with how each recipe is learned), a shopping list, intermediates
to craft, tools, and the recipes to learn with their cost. The server listens only on `127.0.0.1`, so only your computer can reach it. Stop it with Ctrl+C.

## Command line

```sh
python -m cheapest_skillup tailoring                       # one profession
python -m cheapest_skillup                                 # all of them, plus a summary
python -m cheapest_skillup alchemy --realm pvp-horde --region eu
python -m cheapest_skillup leatherworking --from 75 --to 150
python -m cheapest_skillup cooking --sources trainer           # don't buy recipe items
python -m cheapest_skillup tailoring --sell-back           # subtract vendor value of what you craft
python -m cheapest_skillup tailoring --sell-back ah        # ...or its AH value (optimistic)
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
| `--realm`  | `pvp-horde`       | Forever auction house: `normal-alliance`, `normal-horde`, `pvp-alliance`, `pvp-horde` |
| `--price`  | `minBuyout`       | TSM column used for buying: `minBuyout`, `marketValue`, `recent`, `historical` |

For each reagent the tool uses the cheapest of:

1. the auction-house price (`--price` column) or, if nothing is listed, the region market value;
2. the vendor price from `data/vendor_items.json`;
3. crafting it yourself with a recipe from the same profession (for example, Bolt of Linen Cloth from
   Linen Cloth).

`--price-override 2589=20` forces a price in copper, for example for mats you already own (`=0`).

## Selling crafted items back

With `--sell-back` (GUI: *Crafted items → Sell to a vendor*), each craft is credited with the vendor
sell price of what it makes (from the game data, `data/vendor_sell.json`), and the route is
re-optimised with that credit.

`--sell-back ah` uses the AH min buyout minus the 5% cut instead. That assumes everything sells at the
lowest listing, so treat it as a best case.

## How the plan is chosen

At skill `s`, a recipe with colours `[orange, yellow, green, grey]` skills up with probability 1
below yellow, `(grey − s) / (grey − yellow)` from yellow to grey, and 0 at grey. The expected cost of
one point is `craft cost / probability`. Each point is independent, so picking the cheapest recipe
for every point gives the cheapest total. Quantities in the report are expected values, so buy a
little extra.

Learning costs are included: after planning, each paid recipe the plan uses is tried without it, and
dropped whenever that lowers the grand total.

Not modelled: skill-ups from crafting intermediates (so the estimate errs high), the items you need to
enchant, and the AH order book. Min buyout is the price of the *cheapest*
listing, so large purchases will cost more; compare against `--price marketValue`.

## Recipes

`data/recipes/*.json` are generated from WoW Forever's own game data: every craft, its reagents and
product, and its skill-up colours (yellow and grey from the game; green halfway between). To update
after a game patch:

```sh
python -m cheapest_skillup.gamedata                         # latest Forever build on wago.tools
python -m cheapest_skillup.gamedata --build 1.60.1.70959    # a specific build
```

This downloads the client tables from [wago.tools](https://wago.tools) and also refreshes
`data/vendor_sell.json`, `data/item_names.json` and the vendor buy prices in `data/vendor_items.json`.

How each recipe is learned (the *Learn* column):

| Learn       | Meaning | Cost counted |
|-------------|---------|--------------|
| `known`     | Learned with the profession | free |
| `trainer`   | Taught by a profession trainer | fee from `data/trainer.json` |
| `AH recipe` | Taught by a recipe item (Pattern:, Recipe:, Plans:...) | that item's price on your AH |

* Recipe items are used **only when listed on your auction house** at the time of the price scan.
* Recipes taught only by bind-on-pickup items (quest rewards, BoP drops) are left out entirely, since
  they can never be bought.
* `--sources trainer` (GUI: untick *AH recipe items*) plans without buying any recipe items.

### Trainer fees and learn levels: `data/trainer.json`

The game files don't contain trainer fees or the skill a trainer requires; the server sends those.
`data/trainer.json` lists every trainer recipe with `"cost": null, "learn": null`. Fill in what your
trainer shows:

```json
"2385": {"name": "Brown Linen Vest", "profession": "Tailoring", "cost": 50, "learn": 10},
```

`cost` is in copper (1s 25c = `125`), `learn` is the skill needed to train it. Until you do, unknown
fees count as 0 (the report says how many) and the learn level is assumed to be the recipe's yellow
level (marked *est.*), which never schedules a recipe before you can train it. Re-running the importer
keeps what you entered.

The route only goes through recipes the game data marks as craftable profession recipes. A few
trainer recipes may not actually be offered by trainers (event or removed recipes); if the plan uses
one you can't learn, add `"exclude": true` to its entry in `data/trainer.json`.

## Tests

```sh
python -m unittest
```
