"""cheapest_skillup/site/index.html is generated from web/index.html by tools/make_site_page.py; keep them in step."""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class SitePage(unittest.TestCase):
    def test_generated_page_is_up_to_date(self):
        page = ROOT / "cheapest_skillup" / "site" / "index.html"
        before = page.read_text(encoding="utf-8")
        try:
            subprocess.run([sys.executable, str(ROOT / "tools" / "make_site_page.py")], check=True, capture_output=True)
            self.assertEqual(page.read_text(encoding="utf-8"), before,
                             "site/index.html is stale: run python tools/make_site_page.py and commit it")
        finally:
            page.write_text(before, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
