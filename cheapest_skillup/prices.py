"""Download and read TSM's public pricing CSVs.

TSM publishes static CSV files (no API key) at
https://public-data.tradeskillmaster.com/{gameType}/{region}/realm/{realm}/items.csv
and .../{gameType}/{region}/region/items.csv. All prices are in copper.
"""

from __future__ import annotations

import csv
import io
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

BASE_URL = "https://public-data.tradeskillmaster.com"
CACHE_TTL_SECONDS = 3 * 60 * 60  # realm files refresh roughly every 3 hours


def realm_url(game: str, region: str, realm: str) -> str:
    return f"{BASE_URL}/{game}/{region}/realm/{realm}/items.csv"


def region_url(game: str, region: str) -> str:
    return f"{BASE_URL}/{game}/{region}/region/items.csv"


def default_cache_dir() -> Path:
    root = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(root) / "cheapest-skillup"


def fetch_csv(url: str, cache_dir: Path | None = None, refresh: bool = False) -> str:
    """Return the CSV text at `url`, using an on-disk cache for a few hours."""
    cache_dir = cache_dir or default_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    name = url.removeprefix(BASE_URL + "/").replace("/", "_")
    path = cache_dir / name
    if not refresh and path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL_SECONDS:
        return path.read_text(encoding="utf-8")
    req = urllib.request.Request(url, headers={"User-Agent": "cheapest-skillup"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = resp.read().decode("utf-8")
    path.write_text(text, encoding="utf-8")
    return text


def parse_csv(text: str) -> dict[int, dict[str, str]]:
    rows: dict[int, dict[str, str]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            rows[int(row["itemId"])] = row
        except (KeyError, ValueError):
            continue
    return rows


def _int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        n = int(float(value))
    except ValueError:
        return None
    return n if n > 0 else None


@dataclass
class Quote:
    item_id: int
    price: int | None  # copper; None = cannot be bought
    source: str  # "minBuyout", "region marketValue", "vendor", ...


class PriceBook:
    """Looks up a buy price for an item.

    Order: the realm (auction house) price field you chose, then the region
    market value as a fallback for items with no current listing, and the
    vendor price whenever the item is sold by a vendor for less.
    """

    def __init__(
        self,
        realm_rows: dict[int, dict[str, str]],
        region_rows: dict[int, dict[str, str]],
        vendor_prices: dict[int, int],
        price_field: str = "minBuyout",
        overrides: dict[int, int] | None = None,
        vendor_sell: dict[int, int] | None = None,
    ):
        self.realm_rows = realm_rows
        self.region_rows = region_rows
        self.vendor_prices = vendor_prices
        self.price_field = price_field
        self.overrides = overrides or {}
        self.vendor_sell = vendor_sell or {}

    def name(self, item_id: int) -> str | None:
        for rows in (self.realm_rows, self.region_rows):
            row = rows.get(item_id)
            if row and row.get("name"):
                return row["name"]
        return None

    def quote(self, item_id: int) -> Quote:
        if item_id in self.overrides:
            return Quote(item_id, self.overrides[item_id], "override")
        candidates: list[Quote] = []
        realm = self.realm_rows.get(item_id)
        ah = _int(realm.get(self.price_field)) if realm else None
        if ah is not None:
            candidates.append(Quote(item_id, ah, self.price_field))
        else:
            region = self.region_rows.get(item_id)
            mv = _int(region.get("marketValue")) if region else None
            if mv is not None:
                candidates.append(Quote(item_id, mv, "region marketValue"))
        if item_id in self.vendor_prices:
            candidates.append(Quote(item_id, self.vendor_prices[item_id], "vendor"))
        if not candidates:
            return Quote(item_id, None, "unavailable")
        return min(candidates, key=lambda q: q.price)

    def sell_value(self, item_id: int, mode: str = "vendor") -> int:
        """What one crafted item is worth when sold back.

        mode "vendor": the vendor sell price (data/vendor_sell.json, exported
        from the game). mode "ah": the AH price after the 5% cut.
        """
        if mode == "vendor":
            return self.vendor_sell.get(item_id, 0)
        realm = self.realm_rows.get(item_id)
        ah = _int(realm.get(self.price_field)) if realm else None
        return int(ah * 0.95) if ah else 0


def load_pricebook(
    game: str,
    region: str,
    realm: str,
    vendor_prices: dict[int, int],
    price_field: str = "minBuyout",
    cache_dir: Path | None = None,
    refresh: bool = False,
    overrides: dict[int, int] | None = None,
    vendor_sell: dict[int, int] | None = None,
) -> tuple[PriceBook, str]:
    realm_text = fetch_csv(realm_url(game, region, realm), cache_dir, refresh)
    region_text = fetch_csv(region_url(game, region), cache_dir, refresh)
    realm_rows = parse_csv(realm_text)
    region_rows = parse_csv(region_text)
    updated = next(iter(realm_rows.values()), {}).get("updatedAt", "unknown")
    return PriceBook(realm_rows, region_rows, vendor_prices, price_field, overrides, vendor_sell), updated
