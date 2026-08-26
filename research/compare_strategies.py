"""Score the built-in strategies against buy-and-hold on real market data.

Needs the research extra for its data, which ships inside the `arch` wheel —
no network fetch, so the numbers are reproducible:

    pip install -e ".[research]"
    python research/compare_strategies.py

Data is daily bars: S&P 500 and Nasdaq 1999-2018, WTI crude 1986-2019.
"""

from __future__ import annotations

import math
from datetime import datetime

from trading_bot import (
    BuyAndHold,
    Candle,
    Portfolio,
    PriceVsSma,
    SmaCrossover,
    TimeSeriesMomentum,
    VolatilityTarget,
    run_backtest,
)

FEE_RATE = 0.0005  # 5 bps per side, roughly retail commission plus spread

PERIODS = [
    ("dot-com bust 1999-2002", datetime(1999, 1, 1), datetime(2003, 1, 1)),
    ("recovery 2003-2007", datetime(2003, 1, 1), datetime(2008, 1, 1)),
    ("GFC 2008-2009", datetime(2008, 1, 1), datetime(2010, 1, 1)),
    ("bull 2010-2018", datetime(2010, 1, 1), datetime(2019, 1, 1)),
    ("FULL 1999-2018", datetime(1999, 1, 1), datetime(2019, 1, 1)),
]

# (label, strategy factory, sizer factory or None)
CONTENDERS = [
    ("BuyAndHold (benchmark)", BuyAndHold, None),
    ("BuyAndHold + volTarget", BuyAndHold, lambda: VolatilityTarget(0.15)),
    ("SmaCrossover 10/30", lambda: SmaCrossover(10, 30), None),
    ("SmaCrossover 50/200", lambda: SmaCrossover(50, 200), None),
    ("SmaCrossover 50/200 + volTarget", lambda: SmaCrossover(50, 200),
     lambda: VolatilityTarget(0.15)),
    ("PriceVsSma 200", lambda: PriceVsSma(200), None),
    ("TimeSeriesMomentum 252", lambda: TimeSeriesMomentum(252), None),
    ("TimeSeriesMomentum 252 + volTarget", lambda: TimeSeriesMomentum(252),
     lambda: VolatilityTarget(0.15)),
]


def load(market: str) -> list[Candle]:
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
    raise ValueError(market)


def score(candles, factory, sizer_factory=None):
    return run_backtest(
        candles,
        factory(),
        symbol="X",
        portfolio=Portfolio(cash=10_000.0, fee_rate=FEE_RATE),
        sizer=sizer_factory() if sizer_factory else None,
    )


def main() -> None:
    header = (
        f"{'strategy':<36}{'CAGR':>8}{'Sharpe':>8}{'maxDD':>9}"
        f"{'expo':>7}{'trades':>8}"
    )

    for market in ("sp500", "nasdaq", "wti"):
        candles = load(market)
        print(f"\n{'=' * 64}\n{market.upper()}  "
              f"{candles[0].timestamp.date()} to {candles[-1].timestamp.date()}  "
              f"({len(candles)} bars)\n{'=' * 64}")
        for label, start, end in PERIODS:
            window = [c for c in candles if start <= c.timestamp < end]
            if len(window) < 300:
                continue
            print(f"\n  {label}")
            print("  " + header)
            for name, factory, sizer_factory in CONTENDERS:
                r = score(window, factory, sizer_factory)
                print(
                    f"  {name:<36}{r.cagr:>7.2%}{r.sharpe:>8.2f}"
                    f"{r.max_drawdown:>9.1%}{r.exposure:>7.0%}{len(r.fills):>8}"
                )


if __name__ == "__main__":
    main()
