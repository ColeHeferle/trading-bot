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
| `trading_bot.broker` | Alpaca paper sandbox: accounts, positions, prices, retry-safe orders |
| `trading_bot.live` | Turning the rule's decision into a sized order, with refusals |

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
it shrinks into turmoil and grows into calm. It **cut drawdown in every pairing
tested** — Nasdaq buy-and-hold went from a 77.9% drawdown to 46.7% while *also*
improving return.

An earlier version of this section said that stacking it on a trend rule which
already goes flat in crashes made things worse. **That was too broad.** It held
for `SmaCrossover(50, 200)` in the original study, but on Nasdaq daily bars with
`SmaCrossover(10, 50)` the pairing is the best equity configuration measured
here:

| sizing | CAGR | Sharpe | max drawdown | trades/yr |
| --- | --- | --- | --- | --- |
| buy and hold | 5.66% | 0.34 | **77.9%** | 0.1 |
| SMA(10,50), fully invested | 5.55% | 0.44 | 42.8% | 5.9 |
| SMA(10,50), 15% target | 5.01% | **0.53** | 18.7% | 7.7 |
| SMA(10,50), 25% target | **5.66%** | 0.51 | **30.3%** | 6.6 |

The 25% row matches buy-and-hold's return with well under half the drawdown, at
under seven trades a year, and holds up to 20bps a side.

Read that as risk control, not as an edge. Charged for every rule tried on these
two indices, the Sharpe improvement deflates to p = 0.39 and does not survive —
see `trading_bot.deflated_sharpe`. What is worth trusting is the drawdown
reduction, and for a reason that does not depend on this backtest: holding
`target_vol / realized_vol` of equity mechanically shrinks the position as
markets get violent. That is arithmetic rather than a pattern found by
searching.

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

Widening further to bonds and currencies splits the same way. Bonds looked like
the best single asset tested (0.69 Sharpe, 9.4% drawdown) and improved every
basket. **Treat that number as unreliable.** The bond series is built here from
published yields, which are monthly *averages* of daily observations, and
averaging a random-walk-like series manufactures serial correlation that trend
rules read as an edge — see `trading_bot.smoothness` and the note in
[`docs/strategy-study.md`](docs/strategy-study.md). The currency result is
spot-only and so omits carry, which is most of what currency strategies earn.

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

**A frozen rule can name a sizer as well as a strategy.** Without one it is
fully invested whenever it is long, which is what every run recorded before
sizers existed did — the hashed payload omits the key entirely when unset, so
adding this could not invalidate a record already being kept.

```python
FrozenRule(
    strategy="SmaCrossover",
    params={"fast_period": 10, "slow_period": 50},
    symbol="QQQ",
    sizer="VolatilityTarget",
    sizer_params={"target_volatility": 0.25},
)
```

The sizer's parameters are part of the freeze, so retuning the target breaks
the fingerprint exactly as retuning the strategy does. `PaperRun.target_weight`
is the fraction of equity the rule wants held right now, and it is what the
live path acts on — reading `journal[-1].quantity > 0` instead would silently
trade full size.

The sizer is fed **every** bar, including warmup and bars the rule is flat for.
Volatility is a property of the market, not of what is held: a sizer fed only
while long is starved through each flat stretch, so the rule would come back
from being flat holding nothing.

A 200-day rule needs 200 bars before it can signal, so backfill history — but
set `warmup_until` when you do. Bars before that date advance the strategy's
averages without trading or entering the record, because they are the same
history the rule was selected on and counting them would pass in-sample data off
as forward evidence. The equity curve and the benchmark both open at the
boundary.

**How much history you backfill can decide whether the bot launches long or
flat.** `SmaCrossover` signals on the *crossing*, not on the state after it, so
it enters only when it observes a transition — the first bar where both averages
exist returns HOLD, whatever their order. Backfill a window whose whole span sits
above the 200-day average and the rule sees no cross and holds nothing; backfill
further, catch the golden cross that started the trend, and it launches long. A
cross seen during warmup does carry over: the position is taken on the first live
bar rather than waiting for a fresh one. Check which case you are in before
launching, rather than discovering it as a month of unexplained flatness.

Nor is "profitable every day" achievable. That rule was up on 36% of days and
its best streak in twenty years was 8 days. A strategy that appeared to win
every day would indicate a bug, not an edge.

## Talking to a broker

`trading_bot.broker` speaks Alpaca's v2 API over the standard library — no SDK,
so the package stays dependency-free. Start with the read-only check, which
places no orders:

```bash
export APCA_API_KEY_ID=...  APCA_API_SECRET_KEY=...
python research/broker_check.py
```

[`docs/alpaca-setup.md`](docs/alpaca-setup.md) is the runbook for getting from
a fresh account to a placed order: generating paper keys, where to put them,
what correct output looks like at each stage, and what each failure means.

**It refuses the live endpoint unless you pass `allow_live=True`.** Paper is not
just the default: a live URL without that flag raises, so a copied config or a
stray environment variable cannot quietly move real money.

**Orders are retry-safe.** `client_order_id` derives a stable id from the rule
fingerprint, the bar date, the symbol and the side — not from the clock or a
random source. If the process dies between sending an order and recording the
response, the retry produces the *same* id, the broker rejects it as a
duplicate, and the adapter returns the original fill instead of opening a second
position.

**`reconcile` checks both directions.** It compares intended holdings against
the broker's over the union of both, so a position the broker holds that the run
knows nothing about — a stray nobody is managing — shows up rather than being
skipped.

The rule is frozen on `QQQ`, running `SmaCrossover(10, 50)` sized by a 25%
volatility target — fingerprint `607d3ec444f322bb`. It named `SPX` until
2026-09-08, which was a mistake worth naming: an index cannot be bought, so the
record and the position described different instruments. It then named `SPY`
until 2026-09-10, when it moved to the configuration measured as the best in
this repo.

**That is two re-freezes, and it should be the last.** Both were free only
because the run held zero bars each time. Re-freezing whenever a better
backtest appears is the overfitting loop spread over weeks; once bars are
recorded the rule is locked, whatever a later backtest says.

It is frozen for the **drawdown**, not the return: 30.3% against buy-and-hold's
77.9% for the same 5.66% CAGR. The Sharpe improvement does not survive
deflation (p = 0.39) and is not the reason. Acting on the rule is the next
section.

## Before the first launch

`research/preflight.py` says what the bot will do on its first live bar, before
it does it. It reads only — no broker, no orders, and it does not advance the
run:

```bash
python research/preflight.py paper/qqq_sma_10_50_vol25.json paper/qqq_bars.csv
```

It answers one question that is otherwise unanswerable until a month of
flatness has gone by: **does the rule open long or flat, and is that a decision
or an accident of where the history starts?**

Those two flats look identical everywhere else. `SmaCrossover` signals on the
crossing, not the state after it, so a backfill window sitting entirely above
the 200-day average contains no transition and the rule holds nothing through a
rally it can see perfectly well. Backfill further, catch the cross that began
the trend, and the same rule on the same day opens long instead. Preflight
separates the two:

```
opens         FLAT — SELL on 2025-11-18 is the rule's last word     # a decision
opens         FLAT — but no crossing was ever witnessed             # an accident
```

The second exits non-zero, with the two averages printed so you can see the
trend it is declining to trade. Pass `--accept-flat-start` to launch that way
deliberately. It also blocks on too little history, a warmup boundary with too
few bars behind it, a stale file, and bars dated in the future — which no feed
legitimately produces, and which usually means a timezone bug.

**A window that clears the minimum bar count can still be too thin.** Having
enough bars to compute the slow average is not the same as having enough
history for the last crossing to mean anything: a window holding two or three
of them opens long or flat depending on nothing but where the download happens
to start. `--min-crossings` (default 5) flags that, and it is the crossing
count rather than the bar count because that is what measures the evidence
behind the position. Fetch deeper history, or pass `--min-crossings 0` to
accept the thin window.

This was added because the bar-count check under-warned on real data: 128 QQQ
bars cleared the 50-bar minimum, passed, and held three crossings.

Exit 0 means ready. Run it again after any change to the backfill.

## Acting on the rule

`research/trade.py` reads the frozen rule's current decision and brings the
broker position to match. **It is a dry run unless `--execute` is passed**, and
`daily.sh` runs it in that mode every day when `BROKER_SYMBOL` is set:

```bash
BROKER_SYMBOL=QQQ research/daily.sh              # fetch, advance, report
BROKER_SYMBOL=QQQ TRADE=execute research/daily.sh  # …and place the order
```

Exercising the whole path daily is what catches bugs; placing orders is a
separate decision, so it takes a deliberate environment variable.

`--symbol` is required rather than defaulted. The rule is frozen on an index
you cannot buy, so choosing the instrument you actually trade is a decision.

**Sizing uses the traded instrument's own price**, fetched from the broker —
never the index level the rule watched. An S&P level near 6,400 against an ETF
near 640 is a tenfold sizing error, and a silent one.

Three things refuse to trade rather than guessing:

- a **stale bar** (older than `--max-bar-age-days`, default 4) means the feed is
  behind, and acting on a price that may be days old is worse than doing nothing;
- a **position that disagrees** with `paper/live_position.json` halts everything,
  because trading on top of a divergence compounds it;
- an order over the **risk limits** is rejected before it is sent. The dollar
  ceiling is priced from the traded instrument at submit time rather than
  trusted to the caller, and defaults to $25,000 — below a full position, so
  the first live order refuses until `--max-order-notional` raises it
  deliberately.

Buys round *down* to whole shares so a sizing error undershoots. Exits sell the
entire position and are never banded: flat means flat.

One gap no code closes: the rule decides at a close, and a market order fills at
the next available price. That slippage is in no backtest number here.

## Running it without a machine of your own

`.github/workflows/daily.yml` runs the whole loop on GitHub's runners: fetch
the day's bar, advance the frozen run, commit both back to `main`, and report
what the broker leg would do. Weekdays at 22:00 UTC, after the US close.

**It never places an order.** The broker step is a dry run with no way to pass
`--execute` — a schedule nobody is watching is the wrong place to decide to
trade. Wiring execution in is a separate, deliberate change.

Each run writes its output to the workflow summary, so the Actions tab shows
what happened without opening a log. The broker step is skipped entirely until
`APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` exist as repository secrets.

Two things to know before relying on it:

- **The vendor may refuse.** Data providers often block cloud IP ranges, and
  whether Stooq answers a GitHub runner cannot be established from anywhere
  else — the first run is the experiment. If it refuses, run the workflow by
  hand from the Actions tab with **source** set to `yfinance`.
- **It pushes to `main`.** Branch protection requiring pull requests will
  reject that, and the fix is an exception for the Actions bot rather than a
  change to the workflow.

Commits it makes are authored by `github-actions[bot]` and do not re-trigger
CI, so there is no loop to worry about.

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
