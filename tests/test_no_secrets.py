"""Guard: no API key or key-identifying watermark may end up in the repository."""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = re.compile(r"fdb_[A-Za-z0-9_\-]{8,}")  # ForeverDB API keys look like fdb_...
HIDDEN = re.compile("[​-‏‪-‮⁠-⁤﻿]")  # zero-width watermark characters


def tracked_files():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        files = [ROOT / f for f in out.splitlines()]
    except (OSError, subprocess.CalledProcessError):
        files = [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [f for f in files if f.exists() and f.suffix not in (".png", ".jpg", ".gz", ".zip")]


class NoSecrets(unittest.TestCase):
    def test_no_api_key_in_any_file(self):
        for f in tracked_files():
            text = f.read_text(encoding="utf-8", errors="ignore")
            self.assertIsNone(KEY.search(text), f"possible API key in {f.relative_to(ROOT)}")
            if f.name != "test_no_secrets.py":
                self.assertNotIn("proxy-injected", text, f"placeholder key in {f.relative_to(ROOT)}")

    def test_no_watermark_characters_in_data(self):
        for f in (ROOT / "data").rglob("*.json"):
            self.assertIsNone(HIDDEN.search(f.read_text(encoding="utf-8")), f"hidden characters in {f.relative_to(ROOT)}")


if __name__ == "__main__":
    unittest.main()
