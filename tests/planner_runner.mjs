// Runs the browser planner (cheapest_skillup/site/planner.js) on built site data, for tests/test_planner.py.
// Usage: node parity_runner.mjs <site dir> <prices.json> <cases.json>  -> JSON results on stdout
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [siteDir, pricesFile, casesFile] = process.argv.slice(2);
const { Profession, PriceBook, cheapestPlan } = await import(pathToFileURL(join(siteDir, "planner.js")).href);
const read = f => JSON.parse(readFileSync(f, "utf8"));
const professions = read(join(siteDir, "data", "professions.json"));
const items = read(join(siteDir, "data", "items.json"));
const prices = read(pricesFile);
const out = [];
for (const c of read(casesFile)) {
  const prof = new Profession(c.prof, professions[c.prof]);
  const pb = new PriceBook(prices, items, c.side);
  const plan = cheapestPlan(prof, pb, c.from, c.to, {sources: c.sources, sellBack: c.sell_back, side: c.side, craftIntermediates: c.craft});
  out.push({
    reached: plan.reached, grand: plan.grandTotal, materials: plan.totalCost, learn: plan.learnTotal, ranks: plan.ranksTotal,
    tools: plan.toolsTotal, steps: plan.steps.map(s => [s.recipe.name, s.start, s.end]),
    buy: Object.fromEntries([...plan.buy].map(([i, q]) => [i, q])),
  });
}
process.stdout.write(JSON.stringify(out));
