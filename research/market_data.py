"""Loaders for the research universe: equities, crude, currencies and bonds.

Equities and crude ship inside the `arch` wheel. Currencies and bond yields are
fetched once from public mirrors of US government series and cached under
`research/.data_cache/`, which is gitignored — the raw files are not vendored
into this repository.

    Federal Reserve H.10 daily exchange rates (public domain)
    Federal Reserve H.15 10-year constant-maturity Treasury yield (public domain)
"""

from __future__ import annotations

import csv
import math
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from trading_bot import Candle
from trading_bot.bonds import total_return_index

CACHE = Path(__file__).parent / ".data_cache"

FX_URL = "https://raw.githubusercontent.com/datasets/exchange-rates/main/data/daily.csv"
BOND_URL = (
    "https://raw.githubusercontent.com/datasets/bond-yields-us-10y/main/data/monthly.csv"
)

# Freely floating majors. Pegged or managed rates (China, Hong Kong, Denmark,
# Malaysia, Venezuela) are left out: a pinned rate has almost no volatility, so
# a trend rule on it mostly measures the peg's maintenance schedule.
MAJORS = ("Euro", "Japan", "United Kingdom", "Switzerland", "Canada", "Australia")


def _cached(url: str, name: str) -> Path:
    CACHE.mkdir(exist_ok=True)
    path = CACHE / name
    if not path.exists():
        with urllib.request.urlopen(url, timeout=120) as response:
            path.write_bytes(response.read())
    return path


def load_equity(market: str) -> list[Candle]:
    """Daily OHLC for `sp500` or `nasdaq`, or the WTI crude spot series."""
    if market in ("sp500", "nasdaq"):
        module = __import__(f"arch.data.{market}", fromlist=["load"])
        return [
            Candle(ts.to_pydatetime(), r.Open, r.High, r.Low, r.Close, r.Volume)
            for ts, r in module.load().iterrows()
            if not math.isnan(r.Close)
        ]
    if market == "wti":
        from arch.data import wti

        bars = []
        for ts, row in wti.load().iterrows():
            price = row.DCOILWTICO
            if not math.isnan(price) and price > 0:
                bars.append(Candle(ts.to_pydatetime(), price, price, price, price))
        return bars
    raise ValueError(f"unknown market {market!r}")


def load_fx(currency: str) -> list[Candle]:
    """Daily price of one unit of `currency`, in US dollars.

    The source quotes foreign units per dollar, so every rate is inverted. Left
    as published, "buying" the series would be a long dollar position and every
    result would carry the wrong sign.
    """
    path = _cached(FX_URL, "fx_daily.csv")
    bars = []
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["Country"] != currency or not row["Exchange rate"]:
                continue
            per_dollar = float(row["Exchange rate"])
            if per_dollar <= 0:
                continue
            price = 1.0 / per_dollar
            stamp = datetime.strptime(row["Date"], "%Y-%m-%d")
            bars.append(Candle(stamp, price, price, price, price))
    if not bars:
        raise ValueError(f"no rows for currency {currency!r}")
    return sorted(bars, key=lambda c: c.timestamp)


def load_bond_index(maturity_years: float = 10.0) -> list[Candle]:
    """Monthly total-return index for a constant-maturity Treasury.

    Synthetic: built from published yields, not a price anyone could trade.
    See `trading_bot.bonds.total_return_index` for what the model omits.
    """
    path = _cached(BOND_URL, "bond_10y_monthly.csv")
    stamps, yields = [], []
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if not row["Rate"]:
                continue
            stamps.append(datetime.strptime(row["Date"], "%Y-%m-%d"))
            yields.append(float(row["Rate"]) / 100.0)  # published as percent

    index = total_return_index(yields, maturity_years, periods_per_year=12)
    return [
        Candle(stamp, level, level, level, level)
        for stamp, level in zip(stamps, index)
    ]


def to_monthly(candles: list[Candle]) -> list[Candle]:
    """Keep the last bar of each calendar month, stamped at that bar's date."""
    latest: dict[tuple[int, int], Candle] = {}
    for candle in candles:
        key = (candle.timestamp.year, candle.timestamp.month)
        if key not in latest or candle.timestamp > latest[key].timestamp:
            latest[key] = candle
    return [latest[key] for key in sorted(latest)]


def align_month_starts(candles: list[Candle]) -> list[Candle]:
    """Restamp monthly bars to the first of their month.

    The bond series is published on month starts and everything else is
    resampled to month ends, so without this the basket would see two
    timestamps per month and mark half its legs stale on each.
    """
    return [
        Candle(
            c.timestamp.replace(day=1), c.open, c.high, c.low, c.close, c.volume
        )
        for c in candles
    ]


def universe(start: datetime, end: datetime) -> dict[str, list[Candle]]:
    """Monthly bars for equities, crude, majors and the bond index."""
    data: dict[str, list[Candle]] = {}
    for market in ("sp500", "nasdaq", "wti"):
        data[market] = align_month_starts(to_monthly(load_equity(market)))
    for currency in MAJORS:
        data[f"fx:{currency}"] = align_month_starts(to_monthly(load_fx(currency)))
    data["ust10y"] = load_bond_index()

    return {
        symbol: [c for c in bars if start <= c.timestamp < end]
        for symbol, bars in data.items()
    }
