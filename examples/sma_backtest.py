"""Backtest an SMA crossover over a hand-written price series."""

from __future__ import annotations

from datetime import datetime, timedelta

from trading_bot import Candle, Portfolio, SmaCrossover, run_backtest

CLOSES = [10, 10, 10, 10, 12, 14, 16, 18, 20, 22, 24, 23, 20, 17, 14]


def main() -> None:
    start = datetime(2024, 1, 1)
    candles = [
        Candle(start + timedelta(days=i), close, close, close, close)
        for i, close in enumerate(CLOSES)
    ]

    result = run_backtest(
        candles,
        SmaCrossover(fast_period=2, slow_period=4),
        symbol="BTC",
        portfolio=Portfolio(cash=1_000.0, fee_rate=0.001),
    )

    for fill in result.fills:
        date = fill.timestamp.date()
        print(f"{date}  {fill.side.value:<4} {fill.quantity:>8.4f} @ {fill.price:,.2f}")

    print()
    print(f"final equity: {result.final_equity:,.2f}")
    print(f"return:       {result.total_return:.2%}")
    print(f"max drawdown: {result.max_drawdown:.2%}")
    print(f"fees paid:    {result.portfolio.total_fees:,.2f}")


if __name__ == "__main__":
    main()
