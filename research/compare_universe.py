"""Does adding bonds and currencies to the basket help?

    pip install -e ".[research]"
    python research/compare_universe.py

Monthly bars, 1999-2018. Monthly rather than daily because the only US 10-year
yield series reachable here is monthly, and mixing a monthly leg into a daily
basket would leave the bond mark stale for weeks at a time and corrupt every
daily-frequency statistic. Strategy parameters are monthly equivalents: a
10-month trend filter is the usual tactical-allocation rule, not a 200-day one.
"""

from __future__ import annotations

from datetime import datetime

from market_data import MAJORS, universe

from trading_bot import (
    BuyAndHold,
    Portfolio,
    PriceVsSma,
    TimeSeriesMomentum,
    run_backtest,
    run_multi_backtest,
)

START, END = datetime(1999, 1, 1), datetime(2019, 1, 1)
FEE_RATE = 0.0005
MONTHLY = 12

EQUITIES = ("sp500", "nasdaq")
COMMODITY = ("wti",)
CURRENCIES = tuple(f"fx:{c}" for c in MAJORS)
BONDS = ("ust10y",)


def row(name, result) -> str:
    return (
        f"  {name:<34}{result.cagr:>7.2%}{result.sharpe:>8.2f}"
        f"{result.max_drawdown:>9.1%}{result.exposure:>7.0%}{len(result.fills):>8}"
    )


HEADER = f"  {'':<34}{'CAGR':>7}{'Sharpe':>8}{'maxDD':>9}{'expo':>7}{'trades':>8}"


def main() -> None:
    data = universe(START, END)

    def alone(symbol, factory):
        return run_backtest(
            data[symbol],
            factory(),
            symbol=symbol,
            portfolio=Portfolio(10_000.0, fee_rate=FEE_RATE),
            periods_per_year=MONTHLY,
        )

    def basket(symbols, factory):
        return run_multi_backtest(
            {s: data[s] for s in symbols},
            factory,
            portfolio=Portfolio(10_000.0, fee_rate=FEE_RATE),
            periods_per_year=MONTHLY,
        )

    trend = lambda: PriceVsSma(10)  # noqa: E731 - the 10-month filter
    momentum = lambda: TimeSeriesMomentum(12)  # noqa: E731

    print(HEADER)
    print("\n  -- each asset alone, buy and hold --")
    for symbol in EQUITIES + COMMODITY + BONDS + CURRENCIES:
        print(row(symbol, alone(symbol, BuyAndHold)))

    print("\n  -- each asset alone, 10-month trend --")
    for symbol in EQUITIES + COMMODITY + BONDS + CURRENCIES:
        print(row(symbol, alone(symbol, trend)))

    ladder = [
        ("equities only", EQUITIES),
        ("+ crude", EQUITIES + COMMODITY),
        ("+ bonds", EQUITIES + COMMODITY + BONDS),
        ("+ currencies (full universe)", EQUITIES + COMMODITY + BONDS + CURRENCIES),
        ("equities + bonds only", EQUITIES + BONDS),
    ]

    print("\n  -- widening the basket, buy and hold --")
    for label, symbols in ladder:
        print(row(f"{label} ({len(symbols)})", basket(symbols, BuyAndHold)))

    print("\n  -- widening the basket, 10-month trend --")
    for label, symbols in ladder:
        print(row(f"{label} ({len(symbols)})", basket(symbols, trend)))

    print("\n  -- widening the basket, 12-month momentum --")
    for label, symbols in ladder:
        print(row(f"{label} ({len(symbols)})", basket(symbols, momentum)))


if __name__ == "__main__":
    main()
