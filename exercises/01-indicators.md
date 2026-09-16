# Exercise 01 — indicators

Rewrite `src/trading_bot/indicators.py` from its tests. The bodies have been
replaced with `NotImplementedError`; the signatures, docstrings and the test
suite are untouched.

## Rules

1. **Do not read the original implementation before you finish.** It is in git
   history and it will still be there when you are done. Reading it first turns
   a two-hour exercise into a ten-minute one that teaches nothing.
2. Read `tests/test_indicators.py` first, all 75 lines. The tests are the
   specification. Every behaviour you need is stated there.
3. No `pandas`, no `numpy`, no `talib`. The package is dependency-free on
   purpose and that constraint is the point — you write the loop.
4. Time yourself. Write the number down. It is your baseline.

## Setup

```bash
pip install -e ".[dev]"
```

This module is already stubbed. `python exercises/stub.py --list` shows the
state of every exercise, and `python exercises/stub.py --restore indicators`
puts the original back if you want out — commit your attempt first, because
restore overwrites the file.

## The loop

```bash
pytest tests/test_indicators.py -q      # the 17 tests you are targeting
pytest tests/test_indicators.py -q -x   # stop at the first failure
pytest -q                               # the whole suite
```

## Done when

- `pytest tests/test_indicators.py` — 17 passed.
- `pytest` — the full suite is green, 399 passed.

Three tests in `tests/test_strategy.py` also fail right now
(`TestRollingWindow::test_running_sums_match_a_naive_recomputation`). That is
not a bug you introduced. `SmaCrossover` keeps its own running sums for speed,
and those tests check the fast path against `sma()` recomputed the slow,
obvious way. Your `sma` is the oracle they compare against, so they come back
on their own when it is correct. Notice what that means: a wrong `sma` that
happens to satisfy `test_indicators.py` can still be caught here.

## Hints, in escalating order — take the fewest you can

1. All three return a list the *same length as the input*, with `None` in the
   leading positions. Get the alignment right before you get the maths right.
2. `sma` has an obvious O(n·period) solution and an O(n) one. Write the obvious
   one, make it pass, then make it O(n) and keep it passing. That two-step is
   the habit worth building, not the answer.
3. `ema` is seeded from the simple average of the first `period` values, then
   each step is `prev + (value - prev) * 2/(period + 1)`.
4. `rsi` uses Wilder's smoothing, which is not the same as a plain average:
   `avg = (prev_avg * (period - 1) + this_move) / period`. It needs `period`
   *changes*, so the first non-`None` entry lands at index `period`, not
   `period - 1`. Watch for division by zero when there are no losses.

## Then, and only then

```bash
git show b698645~1:src/trading_bot/indicators.py      # the original
git show b698645~1:src/trading_bot/indicators.py > /tmp/original.py
diff -u /tmp/original.py src/trading_bot/indicators.py
```

`b698645` is the commit that stubbed the module, so `b698645~1` is the last
commit that still had the implementation. That reference stays correct no
matter how many commits you add on top.

For every line that differs, decide which version is better and why. Write the
answer down. Sometimes yours will be better — the original is not a model
solution, it is just the code that was there.

## Questions to answer out loud before you call this finished

These are the questions an interviewer asks after you say "I built a
backtesting engine." If you cannot answer them, you have not finished.

1. What is the time and space complexity of your `sma`? Where exactly does the
   `period` factor disappear in the O(n) version?
2. Your running-sum `sma` adds and subtracts floats thousands of times. What
   goes wrong over a 20-year daily series, and how would you detect it?
3. Why does `rsi` return `None` at index `period - 1` when `sma` returns a
   number there?
4. `rsi` returns exactly `100.0` when there are no losses in the window. Is
   that correct, or is it papering over a division by zero? Argue both sides.
5. The signature says `Sequence[float]` rather than `list[float]`. What does
   that buy, and what would break if you iterated `values` twice with a
   generator passed in?
6. `sma([3, 1, 4], 1)` must return `[3.0, 1.0, 4.0]` — floats, not ints. Where
   in your implementation does that conversion happen, and is it deliberate?

## Next

[`exercises/02-portfolio.md`](02-portfolio.md), activated with
`python exercises/stub.py portfolio` once this one is green. Be warned that it
craters 138 tests rather than 20 — `Portfolio` is the ledger the backtest
loop, the paper runner and the sizers all write through. The brief explains
how to work it without drowning in the noise.

After that: `sizing` (03), `backtest` (04), and `broker` (05) last.
`tests/test_broker.py` is 469 lines and is a week, not a day.
