"""Does holding a basket beat holding the best single market?

    pip install -e ".[research]"
    python research/compare_baskets.py

Same data and costs as compare_strategies.py, restricted to the window all
three markets share (1999-2018) so the comparison is like for like.
"""

from __future__ import annotations

from datetime import datetime

from compare_strategies import FEE_RATE, load

from trading_bot import (
    BuyAndHold,
    Portfolio,
    PriceVsSma,
    SmaCrossover,
    TimeSeriesMomentum,
    VolatilityTarget,
    run_backtest,
    run_multi_backtest,
)

START, END = datetime(1999, 1, 1), datetime(2019, 1, 1)
MARKETS = ("sp500", "nasdaq", "wti")

HEADER = (
    f"  {'':<40}{'CAGR':>7}{'Sharpe':>8}{'maxDD':>9}{'expo':>7}{'trades':>8}"
)


def row(name, result) -> str:
    return (
        f"  {name:<40}{result.cagr:>7.2%}{result.sharpe:>8.2f}"
        f"{result.max_drawdown:>9.1%}{result.exposure:>7.0%}{len(result.fills):>8}"
    )


def main() -> None:
    data = {
        market: [c for c in load(market) if START <= c.timestamp < END]
        for market in MARKETS
    }

    def alone(market, factory, sizer=None):
        return run_backtest(
            data[market],
            factory(),
            symbol=market,
            portfolio=Portfolio(10_000.0, fee_rate=FEE_RATE),
            sizer=sizer,
        )

    def basket(universe, factory, sizer_factory=None):
        return run_multi_backtest(
            universe,
            factory,
            portfolio=Portfolio(10_000.0, fee_rate=FEE_RATE),
            sizer_factory=sizer_factory,
        )

    print(HEADER)

    print("\n  -- each market alone, buy and hold --")
    for market in MARKETS:
        print(row(f"{market} BuyAndHold", alone(market, BuyAndHold)))

    print("\n  -- each market alone, SMA 50/200 --")
    for market in MARKETS:
        print(row(f"{market} SMA 50/200", alone(market, lambda: SmaCrossover(50, 200))))

    print("\n  -- equal-weight basket of all three --")
    print(row("basket BuyAndHold", basket(data, BuyAndHold)))
    print(row("basket SMA 50/200", basket(data, lambda: SmaCrossover(50, 200))))
    print(row("basket PriceVsSma 200", basket(data, lambda: PriceVsSma(200))))
    print(row("basket TSMOM 252", basket(data, lambda: TimeSeriesMomentum(252))))
    print(
        row(
            "basket SMA 50/200 + volTarget 15%",
            basket(data, lambda: SmaCrossover(50, 200), lambda: VolatilityTarget(0.15)),
        )
    )

    print("\n  -- equities only, dropping the market trend suits worst --")
    equities = {k: v for k, v in data.items() if k != "wti"}
    print(row("sp500+nasdaq BuyAndHold", basket(equities, BuyAndHold)))
    print(
        row("sp500+nasdaq SMA 50/200", basket(equities, lambda: SmaCrossover(50, 200)))
    )


if __name__ == "__main__":
    main()
