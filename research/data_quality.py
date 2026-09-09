"""Check every series in the universe for manufactured persistence.

    python research/data_quality.py

Run this before trusting any trend-following result. A price series built from
period-*average* quotes carries autocorrelation the market does not have, and a
momentum rule reads it as an edge — see `trading_bot.smoothness`.

This is not hypothetical. It caught a false result in this repo: trend rules
scored 1.2-1.3 Sharpe on bond indices built from published yields, against 0.98
for buy-and-hold, and the edge was the vendor's monthly averaging.

The universe here happens to contain a controlled comparison, which is what
makes it worth running as a whole rather than series by series. Every series
goes through the same loader, the same monthly sampling and the same backtest.
The only thing that differs is how the *source* was sampled: the currencies are
daily observations reduced to month-end closes, while the bond yields arrive
already averaged over each month. If the effect were in this repo's code, both
would show it.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import market_data as md  # noqa: E402

from trading_bot import smoothness  # noqa: E402


def returns(candles) -> list[float]:
    return [
        candles[i].close / candles[i - 1].close - 1
        for i in range(1, len(candles))
    ]


def main(argv: list[str] | None = None) -> int:
    universe = md.universe(datetime(1900, 1, 1), datetime(2030, 1, 1))

    print(f"{'series':<20}{'bars':>7}{'lag-1':>9}{'lag-2':>9}"
          f"{'lag-1²':>9}  verdict")
    print("-" * 66)
    suspicious = []
    for name, candles in sorted(universe.items()):
        if len(candles) < 30:
            continue
        check = smoothness(returns(candles))
        verdict = "SUSPICIOUS" if check.suspicious else "clean"
        if check.suspicious:
            suspicious.append(name)
        print(f"{name:<20}{len(candles):>7}{check.lag1:>+9.3f}"
              f"{check.lag2:>+9.3f}{check.expected_lag2:>+9.3f}  {verdict}")

    if not suspicious:
        print("\nNothing flagged. That is not proof the data is clean — only "
              "that\nthis particular flaw is absent.")
        return 0

    print(f"\n{len(suspicious)} series flagged: {', '.join(suspicious)}")
    print("""
Genuine persistence decays roughly geometrically, so lag-2 should sit near
lag-1 squared. Where it sits near zero instead, the lag-1 came from averaging
rather than from the market, and any trend result measured on that series is
measuring the vendor's arithmetic.

Fix it at the source: take the period's closing observation rather than its
mean. Failing that, treat every momentum number on these series as unproven.""")
    return 1


def _run(entry) -> int:
    try:
        return entry()
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0


if __name__ == "__main__":
    raise SystemExit(_run(main))
