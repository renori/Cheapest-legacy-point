# Archived: the local Python app

This is the original version of Cheapest Skill-up: a Python planner with a local web GUI
(`python -m cheapest_skillup.gui`) and a command line (`python -m cheapest_skillup tailoring --to 300`),
priced with TradeSkillMaster's public data. It has been replaced by the website in the repository root,
whose planner (`cheapest_skillup/site/planner.js`) is a port of `optimizer.py` and was checked against it
route for route (that check now lives on as `tests/planner_snapshot.json`).

It is kept for reference and is **not maintained**: it isn't run in CI and won't get new features.
It reads the repository's `data/` folder, so it keeps working while that data's format stays the same.

To run it, from this folder:

```sh
python -m cheapest_skillup.gui          # local app on http://127.0.0.1:8765/
python -m cheapest_skillup tailoring    # command line
python -m unittest                      # its own tests
```

On Windows, double-click `start_gui.bat`.
