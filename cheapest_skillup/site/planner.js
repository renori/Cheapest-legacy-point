// Cheapest Skill-up planner, in the browser. Originally a line-for-line port of the Python planner (archive/python-app/) and
// its pricing rules; tests/test_planner.py runs its unit tests and a route snapshot.
//
// Data (built by `python -m cheapest_skillup.build_site`):
//   professions[key] = {name, recipes: [{n, s, k:[orange,yellow,green,grey], r:{item:qty}, m, q, t, src,
//                         fee, ff, lf, lk, tr:{a,h}, ri, v:{a:[[npc,price]], h}}], ranks: [...]}
//   items[id] = {n, va, vh (vendor price per item, by faction), sell (what a vendor pays you)}
//   npcs[id] = {name, title, side, zone, x, y, seen}
//   prices = {item: [min unit buyout, quantity listed]} for one auction house

export const INF = Infinity;
const LOW_CHANCE_CRAFTS = 3;
const SMOOTH_MIN = 3, SMOOTH_COPPER = 100, SMOOTH_PCT = 0.005, SMOOTH_PASSES = 4;
const CRAFT_EFFORT = 5;
const AH_CUT = 0.05, DEPOSIT_RATE = 0.05, AUCTION_HOURS = 24;

// ---------------------------------------------------------------- recipes and ranks

export class Recipe {
  constructor(d, i) {
    this.i = i;  // stable identity (Python uses id())
    this.name = d.n; this.spell = d.s ?? null;
    [this.orange, this.yellow, this.green, this.grey] = d.k;
    this.reagents = Object.entries(d.r).map(([item, qty]) => [Number(item), qty]);
    this.makes = d.m ?? null; this.makes_qty = d.q ?? 1;
    this.tools = d.t || [];
    this.source = d.src;
    this.learn_cost = d.src === "trainer" ? (d.fee ?? null) : 0;
    this.fee_from = d.ff ?? null; this.learn_from = d.lf || "game"; this.learn_known = d.lk !== false;
    this.trainers = d.tr || {}; this.recipe_items = d.ri || []; this.vendors = d.v || {};
  }
  skillupChance(skill) {
    if (skill < this.orange || skill >= this.grey) return 0;
    if (skill < this.yellow) return 1;
    return (this.grey - skill) / (this.grey - this.yellow);
  }
}

export class Profession {
  constructor(key, d) {
    this.key = key; this.name = d.name;
    this.recipes = d.recipes.map((r, i) => new Recipe(r, i));
    this.ranks = d.ranks.map(k => ({name: k.n, cap: k.cap, skill: k.sk, level: k.lv, cost: k.cost ?? null,
                                    cost_from: k.cf ?? null, how: k.how, item: k.item ?? null, trainers: k.tr || {}}));
  }
  ranksNeeded(start, reached) {
    let have = 0;
    if (start > 1) have = Math.min(...this.ranks.filter(r => r.cap >= start).map(r => r.cap), Infinity);
    if (have === Infinity) have = 0;
    const out = []; let prev = 0;
    for (const r of this.ranks) { if (r.cap > have && prev < reached) out.push(r); prev = r.cap; }
    return out;
  }
}

// ---------------------------------------------------------------- prices

export class PriceBook {
  // prices: {item: [unit buyout, quantity]} from the Blizzard API for one auction house
  constructor(prices, items, side, overrides = {}) {
    this.prices = prices; this.items = items; this.side = side; this.overrides = overrides;
    this._q = new Map();
  }
  name(item) { return this.items[item]?.n ?? null; }
  vendorPrice(item) {
    const it = this.items[item];
    if (!it) return null;
    if (this.side) return it["v" + this.side] ?? null;
    const both = [it.va, it.vh].filter(v => v != null);
    return both.length ? Math.min(...both) : null;
  }
  vendorSell(item) { return this.items[item]?.sell ?? 0; }
  ahPrice(item) {
    if (item in this.overrides) return this.overrides[item];
    const p = this.prices[item];
    return p && p[0] > 0 ? p[0] : null;
  }
  quote(item) {
    if (!this._q.has(item)) this._q.set(item, this._quote(item));
    return this._q.get(item);
  }
  _quote(item) {
    if (item in this.overrides) return {price: this.overrides[item], source: "override"};
    // A vendor on your side sells it in unlimited supply: always buy it there.
    const vendor = this.vendorPrice(item);
    if (vendor != null) return {price: vendor, source: "vendor"};
    const ah = this.ahPrice(item);
    if (ah != null) return {price: ah, source: "minBuyout"};
    return {price: null, source: "unavailable"};
  }
  sellValue(item, mode = "vendor") {
    if (mode === "vendor") return this.vendorSell(item);
    const ah = this.ahPrice(item);
    if (!ah) return 0;
    const deposit = this.vendorSell(item) * DEPOSIT_RATE * AUCTION_HOURS / 2;
    return Math.max(0, Math.trunc(ah * (1 - AH_CUT) - deposit));
  }
}

// ---------------------------------------------------------------- planner

const sum = xs => xs.reduce((a, b) => a + b, 0);

export class Optimizer {
  constructor(prof, prices, {sources = ["trainer", "vendor", "recipe"], sellBack = null, exclude = new Set(),
                             side = null, craftIntermediates = true} = {}) {
    this.prof = prof; this.prices = prices; this.side = side; this.sellBack = sellBack;
    this.craftIntermediates = craftIntermediates;
    this.madeFrom = {}; this.bought = new Map(); this._learn = new Map();
    this.recipes = [];
    const allowed = new Set(sources);
    for (const r of prof.recipes) {
      if (exclude.has(r.i)) continue;
      if (r.source === "auto") this._learn.set(r.i, 0);
      else if (r.source === "trainer" && allowed.has("trainer")) this._learn.set(r.i, r.learn_cost);
      else if (r.source === "recipe") {
        const options = [];
        if (allowed.has("recipe")) for (const it of r.recipe_items) { const p = prices.ahPrice(it); if (p != null) options.push([p, "ah"]); }
        if (allowed.has("vendor")) for (const [s, rows] of Object.entries(r.vendors)) if (side == null || s === side || s === "b") for (const [, p] of rows) options.push([p, "vendor"]);
        if (!options.length) continue;
        let best = options[0];
        for (const o of options) if (o[0] < best[0] || (o[0] === best[0] && o[1] < best[1])) best = o;
        this._learn.set(r.i, best[0]); this.bought.set(r.i, best[1]);
      } else continue;
      this.recipes.push(r);
    }
    this.makers = new Map();
    for (const r of this.recipes) if (r.makes) { if (!this.makers.has(r.makes)) this.makers.set(r.makes, []); this.makers.get(r.makes).push(r); }
    this._unit = new Map(); this._reag = new Map(); this._busy = new Set();
  }

  unitCost(item, skill) {
    const key = item * 1000 + skill;
    if (this._unit.has(key)) return this._unit.get(key);
    const q = this.prices.quote(item);
    let best = [q.price != null ? q.price : INF, null];
    if (this._busy.has(key)) return best;
    this._busy.add(key);
    for (const r of this.craftIntermediates ? (this.makers.get(item) || []) : []) {
      if (r.orange > skill) continue;
      const c = this.reagentCost(r, skill) / r.makes_qty;
      if (c < best[0]) best = [c, r];
    }
    this._busy.delete(key);
    this._unit.set(key, best);
    return best;
  }
  reagentCost(r, skill) {
    const key = r.i * 1000 + skill;
    if (!this._reag.has(key)) this._reag.set(key, sum(r.reagents.map(([item, qty]) => qty * this.unitCost(item, skill)[0])));
    return this._reag.get(key);
  }
  learnCost(r) { return this._learn.has(r.i) ? this._learn.get(r.i) : 0; }
  rankCost(rank) {
    if (rank.how === "book" && rank.item && rank.cost_from !== "you") return this.prices.quote(rank.item).price;
    return rank.cost;
  }
  credit(r) { return !this.sellBack || !r.makes ? 0 : this.prices.sellValue(r.makes, this.sellBack) * r.makes_qty; }
  craftCost(r, skill) { return this.reagentCost(r, skill) - this.credit(r); }
  pointCost(r, skill) { const p = r.skillupChance(skill); return p > 0 ? this.craftCost(r, skill) / p : INF; }
  choiceCost(r, skill) { const p = r.skillupChance(skill); return p > 0 ? (Math.max(this.craftCost(r, skill), 0) + CRAFT_EFFORT) / p : INF; }

  choose(start, target) {
    const chosen = [];
    for (let skill = start; skill < target; skill++) {
      let bestCost = INF, best = null;
      for (const r of this.recipes) {
        if (!(r.orange <= skill && skill < r.grey)) continue;
        const c = this.choiceCost(r, skill);
        if (best === null || c < bestCost) { bestCost = c; best = r; }
      }
      if (best === null || bestCost === INF) break;
      chosen.push(best);
    }
    return chosen;
  }

  smooth(start, chosen) {
    chosen = [...chosen];
    const materials = sum(chosen.map((r, i) => this.choiceCost(r, start + i)));
    let tolerance = Math.max(SMOOTH_COPPER, SMOOTH_PCT * materials);
    for (let pass = 0; pass < SMOOTH_PASSES; pass++) {
      const runs = [];
      for (let i = 0; i < chosen.length;) { let j = i; while (j < chosen.length && chosen[j] === chosen[i]) j++; runs.push([i, j]); i = j; }
      let changed = false;
      for (let k = 0; k < runs.length; k++) {
        const [i, j] = runs[k];
        if (j - i >= SMOOTH_MIN || runs.length === 1) continue;
        let current = 0; for (let x = i; x < j; x++) current += this.choiceCost(chosen[x], start + x);
        let best = null;
        for (const n of [k - 1, k + 1]) {
          if (n < 0 || n >= runs.length) continue;
          const alt = chosen[runs[n][0]];
          let alts = 0; for (let x = i; x < j; x++) alts += this.choiceCost(alt, start + x);
          const extra = alts - current;
          if (extra <= tolerance && (best === null || extra < best[0])) best = [extra, alt];
        }
        if (best) { for (let x = i; x < j; x++) chosen[x] = best[1]; tolerance -= best[0]; changed = true; break; }
      }
      if (!changed) break;
    }
    return chosen;
  }

  plan(start, target) {
    const steps = [];
    const chosen = this.smooth(start, this.choose(start, target));
    chosen.forEach((best, i) => {
      const skill = start + i;
      const cost = this.pointCost(best, skill);
      const p = best.skillupChance(skill);
      const credit = this.credit(best) / p;
      const last = steps[steps.length - 1];
      if (last && last.recipe === best) {
        last.end = skill + 1; last.expected_crafts += 1 / p; last.cost += cost; last.credit += credit;
      } else {
        const mats = best.reagents.map(([item, qty]) => [item, qty, ...this.unitCost(item, skill)]);
        for (const [, , , m] of mats) if (m) this.madeFrom[m.name] = m.reagents.map(([it, q]) => [it, q / m.makes_qty, ...this.unitCost(it, skill)]);
        steps.push({recipe: best, start: skill, end: skill + 1, expected_crafts: 1 / p, cost, credit, mats});
      }
    });
    const reached = start + chosen.length;

    const buy = new Map(), craftFirst = new Map(), learn = new Map(), tools = new Set(), unpriced = new Set();
    const expand = (r, crafts, skill) => {
      learn.set(r.name, r);
      for (const t of r.tools) tools.add(t);
      for (const [item, qty] of r.reagents) {
        const need = qty * crafts;
        const [cost, maker] = this.unitCost(item, skill);
        if (maker) { craftFirst.set(maker.name, (craftFirst.get(maker.name) || 0) + need / maker.makes_qty); expand(maker, need / maker.makes_qty, skill); }
        else { buy.set(item, (buy.get(item) || 0) + need); if (cost === INF) unpriced.add(item); }
      }
    };
    for (const s of steps) expand(s.recipe, s.expected_crafts, s.start);

    const toolCosts = new Map();
    for (const tool of [...tools].sort((a, b) => a - b)) {
      const [cost, maker] = this.unitCost(tool, target);
      if (maker) expand(maker, 1 / maker.makes_qty, target);
      const name = this.prices.name(tool) || (maker ? maker.name : null) || (this.prof.recipes.find(r => r.makes === tool)?.name) || `item ${tool}`;
      toolCosts.set(tool, [name, cost]);
    }

    const plan = {
      profession: this.prof, start, target, steps, reached, buy, craftFirst, learn: [...learn.values()],
      tools, totalCost: sum(steps.map(s => s.cost)), unpriced, toolCosts,
      learnCosts: [...learn.values()].map(r => [r, this.learnCost(r)]),
      ranks: this.prof.ranksNeeded(start, reached).map(r => [r, this.rankCost(r)]),
      sellBack: this.sellBack,
      noSellPrice: new Set(steps.filter(s => this.sellBack && s.recipe.makes && !this.prices.sellValue(s.recipe.makes, this.sellBack)).map(s => s.recipe.makes)),
    };
    plan.learnTotal = sum(plan.learnCosts.map(([, c]) => c || 0));
    plan.ranksTotal = sum(plan.ranks.map(([, c]) => c || 0));
    plan.toolsTotal = sum([...toolCosts.values()].map(([, c]) => c === INF ? 0 : c));
    plan.sellCredit = sum(steps.map(s => s.credit));
    plan.grandTotal = plan.totalCost + plan.toolsTotal + plan.learnTotal + plan.ranksTotal;
    return plan;
  }
}

export function cheapestPlan(prof, prices, start, target, opts = {}) {
  const exclude = new Set(), kept = new Set();
  const run = () => {
    const opt = new Optimizer(prof, prices, {...opts, exclude: new Set(exclude)});
    const plan = opt.plan(start, target);
    plan.bought = new Map(plan.learnCosts.filter(([r]) => opt.bought.has(r.i)).map(([r]) => [r.name, opt.bought.get(r.i)]));
    plan.madeFrom = opt.madeFrom;
    return [plan, opt];
  };
  let [best, opt] = run();
  for (;;) {
    const usedPoints = new Map();
    for (const s of best.steps) { if (!usedPoints.has(s.recipe.i)) usedPoints.set(s.recipe.i, []); for (let x = s.start; x < s.end; x++) usedPoints.get(s.recipe.i).push(x); }
    const candidates = [];
    for (const [r, fee] of best.learnCosts) {
      if (!fee || kept.has(r.i)) continue;
      let extra = 0;
      for (const sk of usedPoints.get(r.i) || []) {
        let alt = INF;
        for (const a of opt.recipes) if (a !== r && a.orange <= sk && sk < a.grey) alt = Math.min(alt, opt.pointCost(a, sk));
        extra += alt - opt.pointCost(r, sk);
      }
      if (extra < fee) candidates.push([fee - extra, r]);
    }
    if (!candidates.length) return best;
    let pick = candidates[0];
    for (const c of candidates) if (c[0] > pick[0]) pick = c;
    const r = pick[1];
    exclude.add(r.i);
    const [trial, trialOpt] = run();
    if (trial.reached >= best.reached && trial.grandTotal < best.grandTotal) { best = trial; opt = trialOpt; }
    else { exclude.delete(r.i); kept.add(r.i); }
  }
}

// ---------------------------------------------------------------- output for the page (same shape as the old JSON API)

const colourAt = (r, skill) => skill < r.yellow ? "orange" : skill < r.green ? "yellow" : skill < r.grey ? "green" : "grey";
const round = x => Math.round(x);

export function planToDict(plan, prices, npcs, side) {
  const pb = prices;
  const name = i => pb.name(i) || `item ${i}`;
  const howOf = r => r.source === "recipe" && plan.bought.get(r.name) === "vendor" ? "vendor" : r.source;
  const npcList = ids => (ids || []).map(id => npcs[id] && {id, ...npcs[id]}).filter(Boolean)
    .sort((a, b) => (a.seen === b.seen ? 0 : a.seen ? -1 : 1) || (a.zone || "").localeCompare(b.zone || "") || a.name.localeCompare(b.name));
  const trainersOf = x => npcList(side ? x.trainers[side] : [...(x.trainers.a || []), ...(x.trainers.h || [])]);
  const vendorsOf = r => (side ? (r.vendors[side] || []) : [...(r.vendors.a || []), ...(r.vendors.h || [])])
    .map(([id, price]) => npcs[id] && {id, ...npcs[id], price_copper: price}).filter(Boolean)
    .sort((a, b) => a.price_copper - b.price_copper || (a.seen === b.seen ? 0 : a.seen ? -1 : 1));
  const prevCap = r => Math.max(0, ...plan.profession.ranks.filter(k => k.cap < r.cap).map(k => k.cap));
  return {
    profession: plan.profession.key, name: plan.profession.name, start: plan.start, target: plan.target, reached: plan.reached,
    total_cost_copper: round(plan.totalCost), tools_cost_copper: round(plan.toolsTotal), learn_cost_copper: round(plan.learnTotal),
    ranks_cost_copper: round(plan.ranksTotal), grand_total_copper: round(plan.grandTotal),
    sell_back: plan.sellBack, sell_credit_copper: round(plan.sellCredit),
    no_sell_price: [...plan.noSellPrice].sort((a, b) => a - b).map(name),
    unpriced: [...plan.unpriced].map(name),
    tools: [...plan.toolCosts].map(([id, [n, c]]) => ({item_id: id, name: n, cost_copper: c === INF ? null : round(c)})),
    ranks: plan.ranks.map(([r, c]) => ({name: r.name, cap: r.cap, skill: r.skill, level: r.level, how: r.how, cost_copper: c,
                                         cost_from: r.cost_from, before: prevCap(r), trainers: r.how === "trainer" ? trainersOf(r) : []})),
    learn: plan.learnCosts.filter(([r]) => r.source !== "auto").map(([r, c]) => ({
      recipe: r.name, spell: r.spell, how: howOf(r), cost_copper: c, learn_level: r.orange, learn_level_known: r.learn_known,
      learn_from: r.learn_from, fee_from: r.fee_from,
      trainers: r.source === "trainer" ? trainersOf(r) : [],
      vendors: howOf(r) === "vendor" ? vendorsOf(r) : [],
      recipe_items: r.recipe_items.map(i => ({item_id: i, name: name(i)})),
    })),
    steps: plan.steps.map(s => {
      const r = s.recipe;
      return {
        recipe: r.name, spell: r.spell, makes: r.makes, how: howOf(r),
        crafts_per_point: s.expected_crafts / Math.max(1, s.end - s.start),
        skill: [r.orange, r.yellow, r.green, r.grey],
        chance_from: r.skillupChance(s.start), chance_to: r.skillupChance(s.end - 1),
        colour_from: colourAt(r, s.start), colour_to: colourAt(r, s.end - 1),
        low_chance: s.expected_crafts / Math.max(1, s.end - s.start) > LOW_CHANCE_CRAFTS,
        from: s.start, to: s.end, expected_crafts: s.expected_crafts, cost_copper: round(s.cost), credit_copper: round(s.credit),
        materials: s.mats.map(([item, qty, each, maker]) => ({
          item_id: item, name: name(item), per_craft: qty, total: qty * s.expected_crafts,
          unit_copper: each === INF ? null : each, source: maker ? `craft: ${maker.name}` : pb.quote(item).source,
          ah_copper: pb.ahPrice(item), vendor_sell_copper: pb.vendorSell(item) || null,
          made_from: !maker ? [] : (plan.madeFrom[maker.name] || []).map(([i, q, c, m2]) => ({
            item_id: i, name: name(i), qty: q, unit_copper: c === INF ? null : c, source: m2 ? `craft: ${m2.name}` : pb.quote(i).source})),
        })),
        product: !r.makes ? null : {
          item_id: r.makes, name: name(r.makes), per_craft: r.makes_qty, total: r.makes_qty * s.expected_crafts,
          ah_copper: pb.ahPrice(r.makes), vendor_sell_copper: pb.vendorSell(r.makes) || null,
          credit_each_copper: plan.sellBack ? pb.sellValue(r.makes, plan.sellBack) : 0,
        },
      };
    }),
    craft_first: Object.fromEntries(plan.craftFirst),
    buy: [...plan.buy].map(([i, q]) => ({item_id: i, name: name(i), quantity: q, unit_price_copper: pb.quote(i).price, price_source: pb.quote(i).source})),
  };
}
