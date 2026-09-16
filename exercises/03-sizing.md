# Exercise 03 — sizing

Rewrite `src/trading_bot/sizing.py` from its tests. Three classes:
`PositionSizer` (the abstract base), `FullInvestment` (two lines), and
`VolatilityTarget`, which is the exercise.

The smallest module of the five by line count and the densest by idea. A
strategy decides *whether* to hold; a sizer decides *how much*. Keeping them
apart is the reason any sizer composes with any strategy, and that separation
is the thing worth being able to explain.

## Activate

```bash
python exercises/stub.py sizing
```

Undo with `python exercises/stub.py --restore sizing`. Commit your attempt
first if you want to keep it.

## Baseline

`54 failed, 345 passed` — 21 in `tests/test_sizing.py`, 33 elsewhere
(`test_paper.py` 31, `test_preflight.py` 1, `test_multi_backtest.py` 1).

The paper runner carries a frozen rule that names a sizer, which is why 31
tests over there go with it.

```bash
pytest tests/test_sizing.py -q
```

Six of those 21 are `TestBacktestIntegration` — they run a real backtest with
your sizer plugged in. They will stay red until the other fifteen pass, so do
not chase them early. They are checking the seam, not the sizer.

## Rules

1. Do not read the original before you finish.
2. Read `tests/test_sizing.py` first, including the two helpers at the top:
   `feed()` and `steady(daily_move, n)`. `steady` builds a series that moves by
   a fixed fraction every bar, alternating direction — that is how the tests
   produce a known volatility to check your arithmetic against.
3. `models.py` and `backtest.py` are not stubbed. `run_backtest` already knows
   how to call a sizer; you are writing the other side of an interface that
   exists.
4. `math` is available. Nothing else new.

## What the tests are specifying

- **Weight is `target_volatility / realized_volatility`**, capped at
  `max_leverage`. Half the realized volatility means twice the position.
  Double the target means double the position. Both are tested directly.
- **Realized volatility** is the *sample* standard deviation of the last
  `lookback` candle-to-candle returns, annualized by
  `sqrt(periods_per_year)`. Sample, not population — the denominator is
  `n - 1`. `test_weight_is_the_ratio_of_target_to_realized_volatility` will
  tell you if you get that wrong.
- **Warm-up returns 0.0**, and `realized_volatility` reads `None`, until the
  window is full. Not a partial estimate off three bars.
- **A motionless market returns the cap**, not a `ZeroDivisionError`. Zero
  measured risk is not infinite position size.
- **`reset()` clears the estimate** so one instance can be replayed.
- **Construction rejects nonsense**: non-positive target, `lookback` below 2,
  non-positive leverage or periods. The parametrised test names the message
  each one has to contain.

## Hints, in escalating order

1. `weight()` is called on **every** candle, including bars spent flat. That is
   deliberate — the volatility estimate has to stay current while the strategy
   is out of the market, or re-entry would size off stale data. So `weight()`
   both updates state and returns a number.
2. To turn closes into returns you need the previous close, and the first
   candle does not have one. Decide what that first call does before you write
   the loop.
3. `collections.deque(maxlen=lookback)` gives you the rolling window for free.
4. `lookback` returns needs `lookback + 1` closes. Check that against
   `test_asks_for_nothing_until_the_window_fills` before you convince yourself
   of an off-by-one.

## Then, and only then

```bash
SHA=$(sed -n 's/^# STUBBED-FROM: //p' src/trading_bot/sizing.py)
git show "$SHA:src/trading_bot/sizing.py" > /tmp/original_sizing.py
diff -u /tmp/original_sizing.py src/trading_bot/sizing.py
```

## Questions to answer out loud before you call this finished

1. Warm-up returns a weight of 0, so the strategy sits in cash for the first
   `lookback` bars even when it wants to be long. The alternative is to return
   1.0 and size properly once you can. Argue for each. Which one silently
   flatters a backtest, and how would you detect that it had?
2. The class annualizes by `sqrt(periods_per_year)`. What assumption about
   returns does that rest on, and name a market where it is plainly false.
3. `max_leverage` defaults to 1.0 and the docstring calls anything above it
   "aspirational". What actually stops a weight of 2.0 from opening a
   leveraged position, and in which file does that happen?
4. `weight()` mutates state and returns a value. Write down what breaks if a
   caller only calls it on bars where the strategy is long. Then find the line
   in `backtest.py` that makes sure they do not.
5. Sample standard deviation divides by `n - 1`. Explain why, in one sentence,
   without using the word "unbiased" as if it were an explanation.
6. The volatility estimate uses the trailing window equally weighted, so a
   crash 20 bars ago counts exactly as much as yesterday and then vanishes
   entirely. What is the failure mode of that, and what would you replace it
   with?

## Next

[`exercises/04-backtest.md`](04-backtest.md) — the big one.
