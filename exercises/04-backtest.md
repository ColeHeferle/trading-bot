# Exercise 04 — backtest

Rewrite `src/trading_bot/backtest.py` from its tests. This is the largest
exercise: two result classes, a shared metrics base, two public entry points
and five helpers, against 63 targeted tests in three files.

Budget two weeks, not two days. Do **not** try to make all 63 go green at once.

## Activate

```bash
python exercises/stub.py backtest
```

## Baseline

`95 failed, 304 passed`.

| file | tests | what it covers |
| --- | --- | --- |
| `tests/test_metrics.py` | 17 | `EquityMetrics` — returns, CAGR, Sharpe, exposure |
| `tests/test_backtest.py` | 16 | `run_backtest`, single symbol |
| `tests/test_multi_backtest.py` | 30 | `run_multi_backtest`, a shared cash balance |
| elsewhere | 32 | `test_paper.py` 26, `test_sizing.py` 6 |

## Work it in three sittings

The module has three layers and they stack. Take them in order and you always
have a green floor under you.

```bash
# 1. metrics — pure functions over an equity curve, no trading at all
pytest tests/test_metrics.py -q

# 2. the single-symbol loop
pytest tests/test_metrics.py tests/test_backtest.py -q

# 3. the basket
pytest tests/test_metrics.py tests/test_backtest.py tests/test_multi_backtest.py -q
```

Sitting 1 is genuinely easy and worth doing first even though it feels like a
detour: `max_drawdown`, `cagr` and `sharpe` are arithmetic over a list, and
having them right means that when the trading loop is wrong you can trust the
numbers telling you so.

## Rules

1. Do not read the original before you finish. This one is long enough that
   the temptation is real; the payoff for resisting is proportional.
2. `portfolio.py`, `sizing.py`, `strategy.py` and `models.py` are not stubbed.
   `Portfolio.execute` already handles cash, fees and refusals. You are writing
   the thing that decides *what orders to send*, not what happens to them.
3. Read `tests/test_backtest.py` lines 1–26 and `tests/test_multi_backtest.py`
   lines 1–24 first — the candle builders there define the fixtures every test
   in the file leans on.

## The one invariant that matters more than the rest

`test_fills_at_the_close_of_the_signalling_candle`.

A signal computed from a candle is filled at **that candle's close** — the
earliest price a live bot could actually have traded at. Get this wrong in the
other direction, filling at the next open or peeking at the next close, and
every number the module produces is fiction. It is the single most common way
a backtest lies, it is worth exactly one line of code, and you should be able
to point at that line.

## What the basket adds

`run_multi_backtest` is not "run_backtest in a loop". Four things are genuinely
different, and each has its own test class:

- **A shared cash balance.** One `Portfolio`, many symbols. Legs compete for
  the same money, and `TestCashDiscipline` checks it is never overdrawn.
- **Order within a bar.** Sells run before buys so a buy can spend cash freed
  by a sale in the same bar. `test_sells_are_executed_before_buys_in_the_same_bar`
  and `test_a_buy_reaches_its_full_target_using_cash_freed_that_bar` pin it.
- **Unaligned histories.** Symbols may start and end on different dates and may
  have gaps. Walk the union of timestamps; only trade a symbol on bars it
  actually has; mark everything else at its last known close.
- **A rebalance band that scales.** The band is `threshold * weight`, not a flat
  `threshold`. `TestBandScalesWithUniverseSize` is the class that explains why:
  work out for yourself what a flat 0.2 band does to a ten-symbol basket where
  each leg targets 0.1, before you read the answer in the test names.

## Hints, in escalating order

1. `EquityMetrics` is shared by both result classes, which is why the metrics
   tests can pass before any trading works. Write it as a base class with the
   curve as its only real input.
2. The rebalance band exists so a sizer that drifts a little every day does not
   trade every day. Exits are never banded — a strategy that says flat gets
   flat, whatever the drift.
3. `equity` is passed *into* the rebalance helper rather than read from the
   portfolio. For one symbol that is pointless. For a basket it is the whole
   ballgame: work out what happens to leg four's target if legs one to three
   have already moved the denominator.
4. Buying with "all the cash" and a fee rate will overdraw by a rounding error.
   You will hit this and it will be maddening. The fix is one multiplication,
   and question 4 below is about whether it is a fix or a symptom.

## Then, and only then

```bash
SHA=$(sed -n 's/^# STUBBED-FROM: //p' src/trading_bot/backtest.py)
git show "$SHA:src/trading_bot/backtest.py" > /tmp/original_backtest.py
diff -u /tmp/original_backtest.py src/trading_bot/backtest.py
```

Expect this diff to be long and expect to lose some of the arguments. Read the
original's comments on `_rebalance`, `_worth_trading` and `_affordable` — each
one is a scar from a specific failure.

## Questions to answer out loud before you call this finished

1. Point at the line that prevents look-ahead bias. Now describe the smallest
   edit that would reintroduce it, and say which test catches that edit. If the
   answer is "none", you have found a gap worth filling.
2. `exposure` means "fraction of bars spent holding" for one symbol and
   "average share of capital deployed" for a basket. Same attribute name, two
   definitions. Defend it, or say what you would rename them to.
3. `sharpe` annualizes with `periods_per_year`, which assumes every candle
   covers the same span. Name two real data sets where that is false and say
   what the reported Sharpe does on each.
4. `_affordable` multiplies by `(1.0 - 1e-12)` so float rounding cannot push an
   order past the balance. Is that a fix or a symptom? What would the same
   problem look like in a system that had to reconcile to the cent, and what do
   those systems do instead?
5. `_worth_trading` ignores orders below `equity * 1e-9`. Where does that dust
   come from, and what happens to a basket of 10,000 symbols under that rule?
6. CAGR divides by `(end - start).days / 365.25`. What does that return for a
   backtest of two candles one day apart, and is the guard around it the right
   guard?
7. A strategy object is stateful, so `run_multi_backtest` takes a
   `strategy_factory` rather than a strategy. What is the bug that API choice
   prevents, and which test would catch it if you passed one shared instance?

## Next

[`exercises/05-broker.md`](05-broker.md) — the last one, and the one that
matters most for getting hired.
