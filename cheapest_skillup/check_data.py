"""Check recipe data against TSM's item list.

    python -m cheapest_skillup.check_data [--game forever --region us]

Every reagent and product id should appear in TSM's region file (with the
expected name) unless it is a vendor item. Ids that are missing may be wrong
or may not exist in this game version. Recipe ids are printed with the name
TSM has for them so typos are easy to spot.
"""

from __future__ import annotations

import argparse
import sys

from .prices import fetch_csv, parse_csv, region_url
from .recipes import available_professions, load_profession, load_vendor_names


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default="forever")
    ap.add_argument("--region", default="us")
    args = ap.parse_args(argv)

    tsm = parse_csv(fetch_csv(region_url(args.game, args.region)))
    vendor = load_vendor_names()
    problems = 0
    for key in available_professions():
        prof = load_profession(key)
        for r in prof.recipes:
            ids = [("reagent", i) for i in r.reagents] + ([("product", r.makes)] if r.makes else [])
            for kind, item in ids:
                if item in tsm:
                    name = tsm[item].get("name", "")
                    print(f"ok      {prof.name:<15} {r.name:<34} {kind:<8} {item:>6} {name}")
                elif item in vendor:
                    print(f"vendor  {prof.name:<15} {r.name:<34} {kind:<8} {item:>6} {vendor[item]}")
                elif kind == "product":
                    # Soulbound products (e.g. enchanting rods) never reach the AH.
                    print(f"note    {prof.name:<15} {r.name:<34} {kind:<8} {item:>6} (not on AH; fine if soulbound)")
                else:
                    problems += 1
                    print(f"MISSING {prof.name:<15} {r.name:<34} {kind:<8} {item:>6} (not in TSM {args.game}/{args.region})")
    print(f"\n{problems} id(s) not found in TSM data.", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
