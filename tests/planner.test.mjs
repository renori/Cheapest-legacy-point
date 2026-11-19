// Unit tests for the planner (cheapest_skillup/site/planner.js). Run: node --test tests/
// These replace the Python planner's unit tests (archived in archive/python-app/).
import { test } from "node:test";
import assert from "node:assert/strict";
import { Optimizer, PriceBook, Profession, cheapestPlan, planToDict } from "../cheapest_skillup/site/planner.js";

// A recipe: k = [orange, yellow, green, grey], r = {item: qty}, m = item made.
const rec = (n, k, r, extra = {}) => ({ n, k, r, src: "auto", ...extra });
const prof = (recipes, ranks = []) => new Profession("t", { name: "T", recipes, ranks });
// prices: {item: unit buyout}; items: {item: {va, vh, sell}}
const book = (prices, items = {}, side = null, overrides = {}) =>
  new PriceBook(Object.fromEntries(Object.entries(prices).map(([i, p]) => [i, [p, 1]])), items, side, overrides);
const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-6, `${a} != ${b}`);

// ------------------------------------------------------------ skill-up chance and prices

test("skill-up chance by colour", () => {
  const [r] = prof([rec("Hat", [10, 20, 30, 40], { 1: 1 })]).recipes;
  assert.equal(r.skillupChance(9), 0);   // not learnable yet
  assert.equal(r.skillupChance(15), 1);  // orange
  assert.equal(r.skillupChance(20), 1);  // yellow starts: (40-20)/(40-20)
  assert.equal(r.skillupChance(30), 0.5);
  assert.equal(r.skillupChance(40), 0);  // grey
});

test("vendor items are always bought from the vendor", () => {
  const items = { 2: { va: 10, vh: 10 } };
  assert.deepEqual(book({ 2: 5 }, items).quote(2), { price: 10, source: "vendor" });  // cheaper on the AH: still vendor
  assert.deepEqual(book({ 2: 5 }, {}).quote(2), { price: 5, source: "minBuyout" });  // no vendor sells it
  assert.deepEqual(book({}, {}).quote(2), { price: null, source: "unavailable" });
});

test("vendor prices follow the faction", () => {
  const items = { 2: { va: 10 } };  // only an Alliance vendor
  assert.equal(book({ 2: 50 }, items, "a").quote(2).source, "vendor");
  assert.equal(book({ 2: 50 }, items, "h").quote(2).source, "minBuyout");
});

test("price overrides win", () => {
  assert.deepEqual(book({ 1: 10 }, { 1: { va: 3, vh: 3 } }, null, { 1: 7 }).quote(1), { price: 7, source: "override" });
});

test("sell-back: vendor pays sell price, AH takes 5% cut and a 24h deposit", () => {
  const b = book({ 3: 500 }, { 3: { sell: 100 } });
  assert.equal(b.sellValue(3, "vendor"), 100);
  assert.equal(b.sellValue(3, "ah"), 500 * 0.95 - 100 * 0.05 * 12);
  assert.equal(book({}, { 3: { sell: 100 } }).sellValue(3, "ah"), 0);  // not listed
});

// ------------------------------------------------------------ routes

const bolts = () => prof([
  rec("Make Bolt", [1, 10, 15, 20], { 1: 2 }, { m: 2 }),     // 20c per bolt crafted vs 50c bought
  rec("Hat", [1, 30, 40, 50], { 2: 2, 9: 1 }, { m: 3 }),     // 2 bolts + 5c thread
]);
const boltBook = (items = {}) => book({ 1: 10, 2: 50, 3: 80 }, { 9: { va: 5, vh: 5 }, ...items });

test("crafts intermediates when cheaper", () => {
  const [cost, maker] = new Optimizer(bolts(), boltBook()).unitCost(2, 5);
  assert.equal(cost, 20);
  assert.equal(maker.name, "Make Bolt");
  const [bought, none] = new Optimizer(bolts(), boltBook(), { craftIntermediates: false }).unitCost(2, 5);
  assert.deepEqual([bought, none], [50, null]);
});

test("picks the cheapest recipe per point and totals it", () => {
  const plan = new Optimizer(bolts(), boltBook()).plan(1, 30);
  assert.equal(plan.reached, 30);
  assert.deepEqual(plan.steps.map(s => [s.recipe.name, s.start, s.end]), [["Make Bolt", 1, 16], ["Hat", 16, 30]]);
  let bolt = 0;
  for (let s = 1; s < 16; s++) bolt += 20 / Math.min(1, (20 - s) / 10);
  close(plan.totalCost, bolt + 45 * (30 - 16));
  assert.deepEqual([...plan.craftFirst], [["Make Bolt", 28]]);  // 14 hats x 2 bolts
});

test("stops where nothing skills up any more", () => {
  assert.equal(new Optimizer(bolts(), boltBook()).plan(1, 60).reached, 50);
});

test("selling to a vendor credits the step", () => {
  const plain = new Optimizer(bolts(), boltBook()).plan(1, 30);
  const plan = new Optimizer(bolts(), boltBook({ 3: { sell: 10 } }), { sellBack: "vendor" }).plan(1, 30);
  const hats = plan.steps.filter(s => s.recipe.name === "Hat");
  for (const s of hats) { close(s.credit, 10 * s.expected_crafts); close(s.cost, 45 * s.expected_crafts - s.credit); }
  assert.equal(hats[0].start, 14);  // hats (40c/point with credit + 5c effort) beat bolts (41.7c) from 14
  assert.ok(plan.totalCost < plain.totalCost);
  assert.deepEqual([...plan.noSellPrice], [2]);  // bolts have no vendor price
});

test("a profitable recipe doesn't make the route grind low chances", () => {
  const p = prof([rec("Cheap", [1, 10, 30, 50], { 1: 1 }, { m: 3 }), rec("Plain", [30, 100, 100, 101], { 9: 1 })]);
  const plan = new Optimizer(p, boltBook({ 3: { sell: 50 } }), { sellBack: "vendor" }).plan(1, 60);
  const cheap = plan.steps.find(s => s.recipe.name === "Cheap");
  assert.ok(cheap.end < 50);
  assert.ok(plan.totalCost < 0);  // the reported cost still includes the profit
});

test("smoothing folds short runs into a neighbour", () => {
  const p = prof([rec("A", [1, 100, 100, 101], { 1: 10 }), rec("B", [40, 100, 100, 101], { 1: 10 })]);
  const opt = new Optimizer(p, boltBook());
  const [a, b] = p.recipes;
  const chosen = [...Array(39).fill(a), b, b, ...Array(9).fill(a)];
  assert.ok(opt.smooth(1, chosen).every(r => r === a));
});

test("low-chance steps are flagged", () => {
  const p = prof([rec("Grey-ish", [1, 1, 50, 60], { 1: 1 })]);
  const pb = boltBook();
  const d = planToDict(cheapestPlan(p, pb, 55, 59), pb, {}, null);
  assert.equal(d.steps[0].low_chance, true);
});

// ------------------------------------------------------------ learning recipes

const hatBook = () => book({ 1: 10, 50: 500, 51: 9000000 });
const hat = (n, item, cost = 1) => rec(n, [1, 100, 100, 101], { 1: cost }, { src: "recipe", ri: [item] });

test("recipe items must be on your auction house", () => {
  const opt = new Optimizer(prof([hat("Listed", 50), hat("Not listed", 99)]), hatBook());
  assert.deepEqual(opt.recipes.map(r => r.name), ["Listed"]);
  assert.equal(opt.learnCost(opt.recipes[0]), 500);
  assert.deepEqual(new Optimizer(prof([hat("Listed", 50)]), hatBook(), { sources: ["trainer"] }).recipes, []);
});

test("buys a recipe only when it pays off", () => {
  const trainer = rec("Trainer Hat", [1, 100, 100, 101], { 1: 3 }, { src: "trainer", fee: 0 });
  const cheap = cheapestPlan(prof([trainer, hat("Cheap Hat", 50)]), hatBook(), 1, 100);
  assert.deepEqual(new Set(cheap.steps.map(s => s.recipe.name)), new Set(["Cheap Hat"]));
  assert.equal(cheap.learnTotal, 500);
  const dear = cheapestPlan(prof([trainer, hat("Gold Hat", 51)]), hatBook(), 1, 100);
  assert.deepEqual(new Set(dear.steps.map(s => s.recipe.name)), new Set(["Trainer Hat"]));
  assert.equal(dear.learnTotal, 0);
});

test("an unknown trainer fee counts as zero but is reported", () => {
  const plan = cheapestPlan(prof([rec("Trainer Hat", [1, 100, 100, 101], { 1: 1 }, { src: "trainer", fee: null })]), hatBook(), 1, 10);
  assert.deepEqual(plan.learnCosts.map(([r, c]) => [r.name, c]), [["Trainer Hat", null]]);
  assert.equal(plan.learnTotal, 0);
});

// ------------------------------------------------------------ ranks

const rank = (n, cap, sk, lv, cost, extra = {}) => ({ n, cap, sk, lv, cost, cf: "forever", how: "trainer", ...extra });
const ranks = () => [rank("Apprentice", 75, 0, 5, 10), rank("Journeyman", 150, 50, 10, 500),
                     rank("Expert", 225, 125, 20, 5000), rank("Artisan", 300, 200, 35, 50000)];

test("ranks needed for a stretch", () => {
  const p = prof([], ranks());
  const names = (a, b) => p.ranksNeeded(a, b).map(r => r.name);
  assert.deepEqual(names(1, 150), ["Apprentice", "Journeyman"]);
  assert.deepEqual(names(1, 75), ["Apprentice"]);
  assert.deepEqual(names(75, 150), ["Journeyman"]);
  assert.deepEqual(names(120, 225), ["Expert"]);
  assert.deepEqual(names(120, 300), ["Expert", "Artisan"]);
});

test("rank fees are in the grand total", () => {
  const plan = cheapestPlan(prof([rec("Hat", [1, 300, 300, 301], { 1: 1 })], ranks()), hatBook(), 120, 300);
  assert.deepEqual(plan.ranks.map(([r]) => r.name), ["Expert", "Artisan"]);
  assert.equal(plan.ranksTotal, 55000);
  close(plan.grandTotal, plan.totalCost + 55000);
});

test("a skill-book rank is priced like an item; a quest rank is free", () => {
  const p = prof([], [rank("Expert", 225, 125, 0, null, { cf: null, how: "book", item: 16084 }),
                      rank("Artisan", 300, 200, 0, 0, { cf: null, how: "quest" })]);
  const opt = new Optimizer(p, book({ 16084: 9000 }, { 16084: { va: 10000, vh: 10000 } }));
  assert.equal(opt.rankCost(p.ranks[0]), 10000);  // a vendor sells the book: its price, not the cheaper AH listing
  assert.equal(opt.rankCost(p.ranks[1]), 0);
});
