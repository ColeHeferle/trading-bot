# trading-bot

Trading bot for Claude code.

A small, dependency-free Python toolkit for building candle-driven strategies
and backtesting them against a paper account.

## Layout

| Module | Responsibility |
| --- | --- |
| `trading_bot.models` | Value types: `Candle`, `Order`, `Fill`, `Position`, `Side`, `Signal` |
| `trading_bot.indicators` | Rolling `sma`, `ema` and `rsi`, aligned with the input series |
| `trading_bot.strategy` | The `Strategy` interface, `BuyAndHold`, `SmaCrossover`, `PriceVsSma`, `TimeSeriesMomentum` |
| `trading_bot.portfolio` | Cash, positions, fees and realized PnL for a long-only account |
| `trading_bot.sizing` | Position sizers: `FullInvestment`, `VolatilityTarget` |
| `trading_bot.bonds` | Yields to a tradeable constant-maturity total-return index |
| `trading_bot.backtest` | Replays candles through a strategy — one symbol or a basket |
| `trading_bot.feed` | Reading, writing and merging bar CSVs, with revision detection |
| `trading_bot.paper` | Forward testing: a frozen, tamper-evident rule fed bars as they arrive |

Strategies see each candle exactly once, in order, and signals are filled at
the close of the candle that produced them — so a backtest cannot trade on a
price it would not have had at decision time.

## Which strategy should I use?

Start with `BuyAndHold`. It is in the library because it is the benchmark every
other rule has to beat, and on real data most of them don't.

Measured on S&P 500, Nasdaq and WTI daily bars with 5 bps of fees per side,
`SmaCrossover(50, 200)` beat the other built-ins over the full 1999–2018 window
and is the default. But over 2010–2018 alone, **every** strategy here lost to
buy-and-hold — trend rules earn their keep in crashes and give it back in
rallies. What holds up in every cut is the drawdown: 20.6% against 56.8% on the
S&P. Treat these as a smoother ride, not free return.

[`docs/strategy-study.md`](docs/strategy-study.md) has the full tables, the
out-of-sample test showing that parameter tuning added nothing, and what the
backtest does not model.

## Sizing the position

A strategy decides *whether* to hold; a sizer decides *how much*. Pass one to
`run_backtest` and the position is rebalanced toward that weight:

```python
from trading_bot import SmaCrossover, VolatilityTarget, run_backtest

result = run_backtest(
    candles,
    SmaCrossover(50, 200),
    sizer=VolatilityTarget(target_volatility=0.15),
)
```

`VolatilityTarget` holds `target_volatility / realized_volatility` of equity, so
it shrinks into turmoil and grows into calm. In the study it **cut drawdown in
every pairing tested** — Nasdaq buy-and-hold went from a 77.9% drawdown to 46.7%
while *also* improving return — but it usually costs some return, and stacking
it on a trend rule that already goes flat in crashes made things worse, not
better. It is a risk control, not a return booster.

## Trading a basket

`run_multi_backtest` runs one strategy per symbol over a shared cash balance.
Symbols may cover different date ranges; the loop walks the union of their
timestamps, trades a symbol only on bars it has, and marks the rest at their
last close. Sells settle before buys within a bar, so cash freed by an exit can
fund an entry the same day.

```python
from trading_bot import SmaCrossover, run_multi_backtest

result = run_multi_backtest(
    {"SPX": spx_candles, "NDX": ndx_candles, "WTI": wti_candles},
    lambda: SmaCrossover(50, 200),          # one instance per symbol
    weights={"SPX": 0.4, "NDX": 0.4, "WTI": 0.2},   # default: equal split
)
```

Weights cap each symbol's share of equity and must not sum past 1.0 — the
account cannot borrow, so an over-allocated basket would starve whichever legs
traded last. A symbol that is flat leaves its share in cash rather than lending
it to the others, which keeps each leg's risk budget fixed.

On the study data an equal-weight basket beat **every one of its constituents**
— 7.48% CAGR under buy-and-hold against a best single market of 6.67%, and 0.57
Sharpe under a trend rule against 0.53 for the best leg. A leg does not have to
be good on its own to earn its place, so long as it is not merely a worse copy
of what is already there: crude was the weakest single market and still improved
the basket.

Widening further to bonds and currencies splits the same way. Bonds were the
best single asset tested (0.69 Sharpe, 9.4% drawdown) and improved every basket;
currencies diluted them, though that result is spot-only and so omits carry,
which is most of what currency strategies earn. See
[`docs/strategy-study.md`](docs/strategy-study.md).

## Trading bonds

Bonds arrive as yields, and a yield is not a price — buying a yield series gets
the sign backwards. `trading_bot.bonds` converts one into a constant-maturity
par-bond total-return index, which the engine then treats as any other symbol:

```python
from trading_bot import total_return_index

index = total_return_index(monthly_yields, maturity_years=10, periods_per_year=12)
```

Each period earns carry minus duration times the change in yield. It is a proxy
for a bond index, not a bond you could have bought: no convexity, roll-down or
financing.

## Forward testing, and what it can prove

`trading_bot.paper` runs a rule that was pinned down *before* the data existed.
`FrozenRule.fingerprint` hashes the strategy, parameters, instrument and costs,
so any later edit changes the hash and the saved run refuses to load.

```bash
research/daily.sh                    # fetch today's bar, then advance the run
```

That wrapper is two idempotent steps — `fetch_bars.py` merges new bars into a
CSV, `paper_trade.py` feeds them to the frozen rule — so it is safe on a cron
schedule and a double-run or market holiday is a no-op:

```
0 22 * * 1-5 /path/to/trading-bot/research/daily.sh >> /tmp/paper.log 2>&1
```

**Dates already recorded are never overwritten.** If the vendor restates a bar
you have already stored, it is reported as a REVISION and the stored value is
kept — a forward test whose past silently changes is not a record of anything.
`--strict` makes that exit non-zero so cron surfaces it. A failed fetch also
exits non-zero, which stops the wrapper before the run is advanced: no fetch,
no new bars.

**It cannot prove profitability, and it is worth being precise about why.** A
t-statistic grows as `IR × √years`. `SmaCrossover(50, 200)` scored an
information ratio of 0.046 against buy-and-hold, so telling it apart from luck
at 95% confidence would take roughly **1,900 years**. Showing merely that its
return is above zero would take 14. `years_to_detect` computes this for any
edge — run it before committing to a forward test.

What forward testing *is* good for: catching bugs a backtest hides, noticing
when a rule stops behaving as it did historically, and keeping an honest record
that nobody tuned after the fact.

A 200-day rule needs 200 bars before it can signal, so backfill history — but
set `warmup_until` when you do. Bars before that date advance the strategy's
averages without trading or entering the record, because they are the same
history the rule was selected on and counting them would pass in-sample data off
as forward evidence. The equity curve and the benchmark both open at the
boundary.

Nor is "profitable every day" achievable. That rule was up on 36% of days and
its best streak in twenty years was 8 days. A strategy that appeared to win
every day would indicate a bug, not an edge.

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

`BacktestResult` also exposes `cagr`, `sharpe` (annualized via
`periods_per_year`, default 252) and `exposure` — the fraction of candles spent
holding — so a rule that only looks good because it is barely ever invested is
visible rather than flattering.

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
