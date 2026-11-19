"""Generate cheapest_skillup/site/index.html (static, Blizzard prices, planner.js in the browser)
from cheapest_skillup/web/index.html (the local app served by gui.py), so both share one UI.

    python tools/make_site_page.py
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "cheapest_skillup" / "web" / "index.html"
DST = ROOT / "cheapest_skillup" / "site" / "index.html"

DATA_LAYER = r'''
/* ---------------- Data: static files + the planner, all in the browser ---------------- */
const DATA = {};
const PLAN_CACHE = new Map();
let PRICE_DATA = null, PRICE_KEY = null;

async function loadJSON(path, fresh = false) {
  const r = await fetch(path + (fresh ? `?t=${Date.now()}` : ""), {cache: fresh ? "no-store" : "default"});
  if (!r.ok) throw new Error(`Couldn't load ${path} (HTTP ${r.status}).`);
  return r.json();
}
const houses = region => (DATA.index?.houses || []).filter(h => h.region === region);
const FACTION = {a: "Alliance", h: "Horde", n: "Blackwater"};
// Each ruleset (PvP, Normal, Roleplay, ...) has its own Alliance, Horde and Blackwater house, with its
// own prices. Where the API names the ruleset we use it; otherwise houses are grouped into sets by ID
// order (the n-th Alliance, n-th Horde and n-th Blackwater house belong together).
function houseSets(region) {
  const hs = houses(region), sets = new Map();
  const rank = {};
  for (const f of ["a", "h", "n"]) hs.filter(h => h.faction === f).sort((a, b) => a.id - b.id).forEach((h, i) => rank[h.id] = i);
  for (const h of hs) {
    const key = h.ruleset_name ? `r${h.ruleset}` : `s${rank[h.id]}`;
    if (!sets.has(key)) sets.set(key, {key, name: h.ruleset_name, houses: [], listings: 0});
    const s = sets.get(key); s.houses.push(h); s.listings += h.listings || 0;
  }
  for (const s of sets.values()) s.name ||= `Ruleset (houses ${s.houses.map(h => h.id).sort((a, b) => a - b).join(" / ")})`;
  return [...sets.values()].sort((a, b) => b.listings - a.listings);
}
const houseSet = h => houseSets(h.region).find(s => s.houses.includes(h));
const houseLabel = h => `${houseSet(h)?.name || ""} · ${FACTION[h.faction] || ""}`;
const fmtCount = n => n >= 1000 ? `${Math.round(n / 1000)}k` : String(n);
const currentHouse = () => houses(SETTINGS.region).find(h => String(h.id) === String(SETTINGS.realm));

function parseOverrides(s) {
  const out = {};
  for (const pair of (s || "").split(",")) { const [k, v] = pair.split("="); if (k && v && !isNaN(+k) && !isNaN(+v)) out[+k] = +v; }
  return out;
}

async function api(path, extra) {
  const house = currentHouse();
  if (!house) throw new Error("No auction house prices yet. They're published by the hourly price job.");
  const key = `${SETTINGS.region}/${house.id}`;
  if (refreshNext || PRICE_KEY !== key) {
    if (refreshNext) { DATA.index = await loadJSON("data/prices/index.json", true); PLAN_CACHE.clear(); }
    PRICE_DATA = await loadJSON(`data/prices/${key}.json`, refreshNext);
    PRICE_KEY = key; refreshNext = false;
  }
  const fetched = new Date(DATA.index.fetched);
  $("#scan").textContent = `Blizzard prices fetched ${isNaN(fetched) ? DATA.index.fetched : fetched.toLocaleString()}`;
  const side = house.faction === "n" ? null : house.faction;
  const pb = new PriceBook(PRICE_DATA, DATA.items, side, parseOverrides(SETTINGS.overrides));
  const opts = {sources: SETTINGS.sources, sellBack: SETTINGS.sell_back === "none" ? null : SETTINGS.sell_back,
                side, craftIntermediates: SETTINGS.craft !== "0"};
  const prof = DATA.profs[extra.prof];
  if (!prof) throw new Error(`Unknown profession: ${extra.prof}`);
  const from = +extra.from, to = +extra.to;
  const plan = async (goal) => {
    const k = JSON.stringify([key, SETTINGS.sources, SETTINGS.sell_back, SETTINGS.craft, SETTINGS.overrides, extra.prof, from, goal]);
    if (!PLAN_CACHE.has(k)) {
      await new Promise(r => setTimeout(r));  // keep the page responsive between plans
      PLAN_CACHE.set(k, cheapestPlan(prof, pb, from, goal, opts));
    }
    return PLAN_CACHE.get(k);
  };
  const base = {prices_updated: DATA.index.fetched, auction_house: `${SETTINGS.region.toUpperCase()} ${houseLabel(house)}`,
                price_field: "minBuyout", foreverdb: true};
  if (path === "overview") {
    const goals = [...new Set([...OPT.milestones.filter(m => m > from), ...(to > from ? [to] : [])])].sort((a, b) => a - b);
    const milestones = [];
    for (const g of goals) { const p = await plan(g); milestones.push({to: g, total_copper: Math.round(p.grandTotal), reached: p.reached}); }
    return {...base, prof: extra.prof, from, to, milestones};
  }
  if (from >= to) throw new Error("Target must be above your current skill.");
  return {...base, plan: planToDict(await plan(to), pb, DATA.npcs, side)};
}
'''

INIT = r'''async function init() {
  [DATA.professions, DATA.items, DATA.npcs, DATA.meta] = await Promise.all(
    ["professions", "items", "npcs", "meta"].map(n => loadJSON(`data/${n}.json`)));
  try { DATA.index = await loadJSON("data/prices/index.json", true); } catch { DATA.index = {houses: []}; }
  DATA.profs = Object.fromEntries(Object.entries(DATA.professions).map(([k, p]) => [k, new Profession(k, p)]));
  const regions = [...new Set(DATA.index.houses.map(h => h.region))];
  const busiest = region => [...houses(region)].sort((a, b) => (b.faction === "h") - (a.faction === "h") || b.listings - a.listings)[0];
  const FORDER = {h: 0, a: 1, n: 2};
  OPT = {
    professions: Object.entries(DATA.professions).map(([key, p]) => ({key, name: p.name})).sort((a, b) => a.name.localeCompare(b.name)),
    milestones: [75, 150, 225, 300], max_skill: 300, sources: ["trainer", "vendor", "recipe"],
    defaults: {region: regions.includes("us") ? "us" : regions[0], sources: ["trainer", "vendor", "recipe"], sell_back: "none", target: 150},
  };
  const d = Object.assign({}, OPT.defaults, {wh: "forever"}, store.get("settings") || {});
  if (!regions.includes(d.region)) d.region = OPT.defaults.region;
  const fillHouses = region => {
    const sets = houseSets(region).filter(s => s.listings > 0);  // skip rulesets with no auctions yet
    const hs = sets.flatMap(s => s.houses.filter(h => h.listings > 0));
    $("#realm").innerHTML = sets.map(s => `<optgroup label="${esc(s.name)}">` + [...s.houses]
      .filter(h => h.listings > 0).sort((a, b) => FORDER[a.faction] - FORDER[b.faction])
      .map(h => `<option value="${h.id}">${esc(`${FACTION[h.faction]} (#${h.id}, ${fmtCount(h.listings)} listings)`)}</option>`).join("")
      + `</optgroup>`).join("");
    const keep = hs.find(h => String(h.id) === String(d.realm));
    $("#realm").value = keep ? keep.id : (busiest(region)?.id ?? "");
  };
  fillSelect($("#region"), regions, d.region, {us: "US", eu: "EU", kr: "KR", tw: "TW"});
  fillHouses(d.region);
  const SRC = {trainer: "Trainer", vendor: "Vendor recipes", recipe: "AH recipe items"};
  const srcSel = (d.sources || []).filter(s => OPT.sources.includes(s));
  OPT.sources.forEach(s => chip($("#sources"), s, SRC[s] || s, (srcSel.length ? srcSel : OPT.defaults.sources).includes(s)));
  $("#sellback").value = ["none", "vendor", "ah"].includes(d.sell_back) ? d.sell_back : "none";
  $("#overrides").value = d.overrides || "";
  $("#wh").value = ["forever", "classic"].includes(d.wh) ? d.wh : "forever";
  $("#craft").checked = d.craft !== "0";
  readSettings();
  $("#form").onsubmit = e => { e.preventDefault(); readSettings(); refreshNext = true; route(); };
  $("#region").onchange = () => { d.realm = null; fillHouses($("#region").value); readSettings(); route(); };
  for (const el of ["#realm", "#sellback", "#overrides", "#wh", "#craft"]) $(el).onchange = () => { readSettings(); route(); };
  window.addEventListener("hashchange", route);
  route();
}'''


def main() -> None:
    t = SRC.read_text(encoding="utf-8")

    def swap(old: str, new: str) -> None:
        nonlocal t
        assert old in t, f"not found in web/index.html: {old[:70]!r}"
        t = t.replace(old, new)

    swap("priced from TradeSkillMaster's public data", "priced from Blizzard's auction house data")
    swap('<div class="hint">Trainers and vendors follow this faction.</div>',
         '<div class="hint">Each ruleset (PvP, Normal, Roleplay…) has its own Alliance, Horde and Blackwater auction house with its own prices. Trainers and vendors follow the house\'s faction.</div>')
    swap("""      <label class="f" for="price">Buy at</label>
      <select id="price"></select>
""", "")
    swap('<button class="go" id="go" type="submit">Re-download prices</button>', '<button class="go" id="go" type="submit">Reload prices</button>')
    swap("<script>\n", '<script type="module">\nimport { Profession, PriceBook, cheapestPlan, planToDict } from "./planner.js";\n')
    s0, s1 = t.index("async function api(path, extra) {"), t.index("function chip(container, value, label, on) {")
    t = t[:s0] + DATA_LAYER.strip() + "\n\n" + t[s1:]
    swap('    region: $("#region").value, realm: $("#realm").value, price: $("#price").value,',
         '    region: $("#region").value, realm: $("#realm").value, price: "minBuyout",')
    s0, s1 = t.index("async function init() {"), t.index("function route() {")
    t = t[:s0] + INIT + "\n\n" + t[s1:]
    swap("Prices: TradeSkillMaster (${esc(d.auction_house)}, ${esc(PRICE_LABEL[d.price_field] || d.price_field)}).",
         "Prices: Blizzard Battle.net API (${esc(d.auction_house)}, cheapest listing).")
    swap("Min buyout is the cheapest single listing, so large orders will cost more.",
         "Prices are each item's cheapest listing, so large orders will cost more.")
    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text(t, encoding="utf-8")
    print(f"wrote {DST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
