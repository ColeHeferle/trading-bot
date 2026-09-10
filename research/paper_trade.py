"""Advance a frozen paper run with any new bars, then report.

    python research/paper_trade.py paper/qqq_sma_10_50_vol25.json bars.csv

`bars.csv` needs a header and one row per bar, oldest first:

    date,open,high,low,close,volume
    2026-08-26,6420.1,6441.0,6410.5,6438.2,0

Bars already recorded are skipped, so re-running with an appended file is safe
and is the intended way to use this: append, run, commit the updated JSON.

This deliberately has no market-data connection. Whatever feed you use — a
broker API, a vendor download, a hand-typed close — becomes the CSV. Keeping
the fetch outside means the run cannot be silently re-driven by a data source
that changed its history underneath you.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from trading_bot import PaperRun, parse_csv, years_to_detect


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2

    state_path, bars_path = Path(argv[1]), Path(argv[2])
    run = PaperRun.load(state_path)
    seen = run.bars[-1].timestamp if run.bars else None

    added = warmed = 0
    for candle in parse_csv(bars_path.read_text()):
        if seen is not None and candle.timestamp <= seen:
            continue
        if run.step(candle) is None:
            warmed += 1
        else:
            added += 1

    run.save(state_path)
    report = run.report

    print(f"rule          {report.rule.strategy}{report.rule.params}")
    print(f"fingerprint   {report.rule.fingerprint}")
    print(f"symbol        {report.rule.symbol}")
    print(f"new bars      {added} live, {warmed} warmup  "
          f"(total {report.bars} live, {report.warmup_bars} warmup)")
    if report.rule.warmup_until:
        print(f"record opens  {report.rule.warmup_until}")
    if report.started:
        print(f"window        {report.started.date()} .. {report.latest.date()}"
              f"  ({report.elapsed_years:.2f} years)")
    else:
        print("window        still warming up — nothing counted yet")
        print()
        print("Backfilled bars fill the strategy's windows but stay out of the")
        print("record: they are history the rule was chosen against, and "
              "counting")
        print("them would dress up in-sample data as forward evidence.")
        return 0
    print()
    print(f"equity        {report.equity:>12,.2f}   {report.total_return:>8.2%}")
    print(f"buy and hold  {report.benchmark_equity:>12,.2f}   "
          f"{report.benchmark_return:>8.2%}")
    print(f"excess        {report.excess:>21.2%}")
    print(f"trades        {report.trades}")

    # The number that keeps this honest.
    needed = years_to_detect(0.046)
    print()
    print(f"On the backtested edge over buy-and-hold (IR 0.046), separating this")
    print(f"from luck at 95% confidence needs ~{needed:,.0f} years. After "
          f"{report.elapsed_years:.2f}, this")
    print("result carries no statistical weight. It is a bug-detector and a "
          "record, not a verdict.")
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
    raise SystemExit(_run(lambda: main(sys.argv)))
