"""Fetch daily bars and merge them into a CSV, safe to run on a schedule.

    python research/fetch_bars.py --out paper/spx_bars.csv
    python research/fetch_bars.py --out paper/spx_bars.csv --source yfinance

Idempotent: re-running adds nothing. Dates already in the file are never
overwritten — if the vendor now reports different values for a day already
recorded, that is printed as a REVISION and the stored bar is kept, because a
forward test whose past silently changes is not a record of anything. Pass
`--strict` to exit non-zero on a revision so a cron job surfaces it.

Sources, both fetching the S&P 500 index:
    stooq     (default) no dependencies, plain CSV over HTTPS
    yfinance  needs `pip install yfinance`

Neither could be reached from the environment this was written in, so the
network paths are unverified here; the parsing and merging they feed are
covered by tests/test_feed.py.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from trading_bot.feed import format_csv, merge, parse_csv, parse_stooq
from trading_bot.models import Candle

STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"
DEFAULTS = {"stooq": "^spx", "yfinance": "^GSPC"}


def from_stooq(symbol: str, timeout: int) -> list[Candle]:
    url = STOOQ_URL.format(symbol=symbol)
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return parse_stooq(response.read().decode("utf-8", "replace"))


def from_yfinance(symbol: str, start: str | None) -> list[Candle]:
    try:
        import yfinance
    except ImportError as exc:  # pragma: no cover - depends on the user's env
        raise SystemExit(
            "yfinance is not installed; `pip install yfinance` or use "
            "--source stooq"
        ) from exc

    frame = yfinance.download(
        symbol, start=start, auto_adjust=False, progress=False
    )
    if frame.empty:
        raise SystemExit(f"yfinance returned no rows for {symbol!r}")

    # yfinance hands back a MultiIndex when several tickers are requested;
    # flatten so a single-ticker frame looks the same either way.
    if hasattr(frame.columns, "nlevels") and frame.columns.nlevels > 1:
        frame = frame.xs(symbol, axis=1, level=-1)

    bars = []
    for stamp, row in frame.iterrows():
        close = float(row["Close"])
        bars.append(
            Candle(
                stamp.to_pydatetime().replace(tzinfo=None),
                float(row.get("Open", close)),
                float(row.get("High", close)),
                float(row.get("Low", close)),
                close,
                float(row.get("Volume", 0.0) or 0.0),
            )
        )
    return bars


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch daily bars and merge them into a CSV."
    )
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--source", choices=sorted(DEFAULTS), default="stooq")
    parser.add_argument("--symbol", help="defaults to the source's S&P 500 ticker")
    parser.add_argument("--start", help="yfinance only, e.g. 2025-06-01")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if the vendor restated a stored bar",
    )
    args = parser.parse_args(argv)

    symbol = args.symbol or DEFAULTS[args.source]
    try:
        if args.source == "stooq":
            fetched = from_stooq(symbol, args.timeout)
        else:
            fetched = from_yfinance(symbol, args.start)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Runs unattended, so say what failed in one line rather than dumping a
        # stack trace into a log nobody reads. Non-zero stops daily.sh before
        # the run is advanced, which is the point: no fetch, no new bars.
        print(f"could not reach {args.source}: {exc}", file=sys.stderr)
        return 2

    existing = parse_csv(args.out.read_text()) if args.out.exists() else []
    result = merge(existing, fetched)

    if result.changed:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(format_csv(result.bars))

    span = (
        f"{result.bars[0].timestamp.date()} .. {result.bars[-1].timestamp.date()}"
        if result.bars
        else "empty"
    )
    print(f"{symbol} via {args.source}: fetched {len(fetched)}, "
          f"added {len(result.added)}, total {len(result.bars)} ({span})")

    for was, now in result.revised:
        print(
            f"  REVISION {was.timestamp.date()}: stored close {was.close}, "
            f"vendor now says {now.close} — kept the stored bar",
            file=sys.stderr,
        )
    if result.revised:
        print(
            f"  {len(result.revised)} bar(s) restated upstream. Nothing was "
            "changed; look before you decide the vendor is right.",
            file=sys.stderr,
        )
        if args.strict:
            return 1
    return 0


def _run(entry) -> int:
    """Exit quietly when stdout goes away — this gets piped into `head` and
    log rotators, and a traceback there is noise, not information."""
    try:
        return entry()
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0


if __name__ == "__main__":
    raise SystemExit(_run(main))
