"""The browser planner (cheapest_skillup/site/planner.js).

* tests/planner.test.mjs: unit tests (node --test).
* A route snapshot: 32 plans (every profession, four setups) on a fixed, made-up auction house,
  compared with tests/planner_snapshot.json. The snapshot was recorded when the planner was
  checked line for line against the original Python planner (archive/python-app/).
  If you change the planner on purpose, re-record it:  UPDATE_PLANNER_SNAPSHOT=1 python -m unittest tests.test_planner

Skipped when Node.js isn't installed.
"""

import json
import os
import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from cheapest_skillup.build_site import build
from cheapest_skillup.recipes import available_professions

HERE = Path(__file__).resolve().parent
NODE = shutil.which("node")
SNAPSHOT = HERE / "planner_snapshot.json"
SETUPS = [  # from, to, sell back, side, craft intermediates, recipe sources
    (1, 150, None, "h", True, ["trainer", "vendor", "recipe"]),
    (1, 300, "vendor", "a", True, ["trainer", "vendor", "recipe"]),
    (120, 225, "ah", "h", False, ["trainer", "vendor"]),
    (1, 225, None, None, True, ["trainer"]),
]


def snapshot_prices(items: list[int], seed: int = 7) -> dict[str, list[int]]:
    """A made-up but realistic auction house: most items listed, at varied prices."""
    rng = random.Random(seed)
    out = {}
    for i in items:
        if rng.random() < 0.8:
            out[str(i)] = [rng.choice([rng.randint(1, 99), rng.randint(100, 9999), rng.randint(10000, 200000)]), rng.randint(1, 500)]
    return out


def tidy(result: dict) -> dict:
    r = lambda x: round(x, 4)  # noqa: E731
    return {**result, **{k: r(result[k]) for k in ("grand", "materials", "learn", "ranks", "tools")},
            "buy": {k: r(v) for k, v in sorted(result["buy"].items(), key=lambda kv: int(kv[0]))}}


def run_planner(site: Path, prices: dict, cases: list[dict], tmp: Path) -> list[dict]:
    (tmp / "prices.json").write_text(json.dumps(prices))
    (tmp / "cases.json").write_text(json.dumps(cases))
    out = subprocess.run([NODE, str(HERE / "planner_runner.mjs"), str(site), str(tmp / "prices.json"), str(tmp / "cases.json")],
                         capture_output=True, text=True, check=True).stdout
    return [tidy(x) for x in json.loads(out)]


@unittest.skipUnless(NODE, "Node.js not installed")
class Planner(unittest.TestCase):
    def test_unit_tests(self):
        res = subprocess.run([NODE, "--test", str(HERE / "planner.test.mjs")], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout[-3000:] + res.stderr[-2000:])

    def test_route_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            site = Path(d) / "site"
            build(site)
            cases = [{"prof": p, "from": a, "to": b, "sell_back": s, "side": side, "craft": c, "sources": src}
                     for p in available_professions() for (a, b, s, side, c, src) in SETUPS]
            if os.environ.get("UPDATE_PLANNER_SNAPSHOT") or not SNAPSHOT.exists():
                items = [int(i) for i in json.loads((site / "data" / "items.json").read_text())]
                prices = snapshot_prices(items)
                results = run_planner(site, prices, cases, Path(d))
                SNAPSHOT.write_text(json.dumps({"prices": prices, "cases": cases, "results": results}, separators=(",", ":")))
                self.skipTest("planner snapshot re-recorded")
            snap = json.loads(SNAPSHOT.read_text())
            self.assertEqual(snap["cases"], cases, "the snapshot's cases changed: re-record it")
            for c, want, got in zip(cases, snap["results"], run_planner(site, snap["prices"], cases, Path(d))):
                with self.subTest(**{k: c[k] for k in ("prof", "from", "to", "sell_back", "side", "craft")}):
                    self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
