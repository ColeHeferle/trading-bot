# trading-bot

Trading bot for Claude code.

A small, dependency-free Python toolkit for building candle-driven strategies
and backtesting them against a paper account.

## Layout

| Module | Responsibility |
| --- | --- |
| `trading_bot.models` | Value types: `Candle`, `Order`, `Fill`, `Position`, `Side`, `Signal` |
| `trading_bot.indicators` | Rolling `sma`, `ema` and `rsi`, aligned with the input series |
| `trading_bot.strategy` | The `Strategy` interface and an `SmaCrossover` implementation |
| `trading_bot.portfolio` | Cash, positions, fees and realized PnL for a long-only account |
| `trading_bot.backtest` | Replays candles through a strategy and reports the outcome |

Strategies see each candle exactly once, in order, and signals are filled at
the close of the candle that produced them — so a backtest cannot trade on a
price it would not have had at decision time.

## Getting started

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

## Usage

```python
from datetime import datetime, timedelta

from trading_bot import Candle, Portfolio, SmaCrossover, run_backtest

start = datetime(2024, 1, 1)
closes = [10, 10, 10, 10, 12, 14, 16, 18, 20, 22, 24, 23, 20, 17, 14]
candles = [
    Candle(start + timedelta(days=i), c, c, c, c) for i, c in enumerate(closes)
]

result = run_backtest(
    candles,
    SmaCrossover(fast_period=2, slow_period=4),
    symbol="BTC",
    portfolio=Portfolio(cash=1_000.0, fee_rate=0.001),
)

print(f"trades:       {len(result.fills)}")
print(f"final equity: {result.final_equity:,.2f}")
print(f"return:       {result.total_return:.2%}")
print(f"max drawdown: {result.max_drawdown:.2%}")
```

Run it end to end with `.venv/bin/python examples/sma_backtest.py`.

## Writing a strategy

Subclass `Strategy` and return a `Signal` per candle. Keep whatever state you
need on the instance, and clear it in `reset()` so the object can be replayed:

```python
from trading_bot import Candle, Signal, Strategy


class BuyTheDip(Strategy):
    def __init__(self, drop: float = 0.05) -> None:
        self.drop = drop
        self.reset()

    def reset(self) -> None:
        self.previous_close: float | None = None

    def on_candle(self, candle: Candle) -> Signal:
        previous, self.previous_close = self.previous_close, candle.close
        if previous is None:
            return Signal.HOLD
        return Signal.BUY if candle.close < previous * (1 - self.drop) else Signal.HOLD
```

The backtest loop is long-only: it buys when flat on a `BUY`, sells what it
holds on a `SELL`, and ignores anything that would open a short.

## Tests

```bash
.venv/bin/pytest              # whole suite
.venv/bin/pytest -k indicator # one area
```
