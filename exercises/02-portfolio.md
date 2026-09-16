# Exercise 02 — portfolio

Rewrite `src/trading_bot/portfolio.py` from its tests. Six methods:
`__init__`, `position`, `quantity`, `execute`, `equity`, `total_return`.
`execute` is about two thirds of the work; the rest are small.

**Do exercise 01 first.** Both stubbed at once means neither has a clean
signal, and `pytest` is useless as a progress meter.

## Activate

```bash
python exercises/stub.py --list         # what is stubbed right now
python exercises/stub.py portfolio      # replaces the bodies, records the commit
```

To undo, at any point: `python exercises/stub.py --restore portfolio`. It
restores from the commit recorded in the file header, so it keeps working
however many commits you stack on top. Commit your own attempt first if you
want to keep it — restore overwrites the file.

## Expect a much bigger crater than exercise 01

| | exercise 01 | exercise 02 |
| --- | --- | --- |
| target tests | 17 | 20 |
| failures elsewhere | 3 | 118 |
| total red | 20 | 138 |

Stubbing `indicators` broke 3 tests in one other file. Stubbing `portfolio`
breaks 118 across six: `test_paper.py` (30), `test_preflight.py` (25),
`test_multi_backtest.py` (25), `test_metrics.py` (17), `test_backtest.py` (16),
`test_sizing.py` (5).

That is not something going wrong. `Portfolio` is the ledger every other
module writes through — the backtest loop, the paper runner, the preflight
checks and the sizers all hold one and call `execute`. This is what "core
module" means, drawn to scale, and it is worth looking at once before you
start: run `pytest` and read the list of files.

So **ignore the full suite until the targeted file is green.** Work this loop
only:

```bash
pytest tests/test_portfolio.py -q       # 21 tests: 20 yours, 1 free
pytest tests/test_portfolio.py -q -x    # stop at the first failure
```

The free one is `TestOrders::test_rejects_non_positive_quantity`, which tests
`Order` in `models.py`, not your code. It passes from the start.

Only when those 20 pass, run `pytest`. Expect it to go straight to 399, and if
it does not, the remaining failures are telling you something `test_portfolio.py`
was not strict enough to catch — read them rather than patching until they stop.

## Rules

1. **Do not read the original before you finish.** Same rule as exercise 01,
   and it matters more here because `execute` is short enough to memorise.
2. Read all 166 lines of `tests/test_portfolio.py` first. The class names are
   the map: `TestOrders`, `TestBuying`, `TestSelling`, `TestValuation`,
   `TestConstruction`.
3. `models.py` is not stubbed. Read it — `Position` already has `is_flat`,
   `market_value` and `unrealized_pnl`, and `Fill` has the fields `execute`
   must populate. Reuse them; do not reimplement them.
4. No new dependencies.
5. Time yourself and compare against your exercise 01 number.

## What the tests are actually specifying

Worth stating plainly, because it is domain logic rather than programming:

- **Long-only.** A sell beyond the held quantity raises `InsufficientPosition`
  rather than opening a short. A sell with nothing held raises the same.
- **Average entry price.** A second buy blends into `avg_price`, weighted by
  quantity — buy 1 at 100 then 3 at 200 and the position's entry is 175, not
  150. A partial sale leaves `avg_price` alone; closing out resets it to zero.
- **Realized PnL** is booked on the sell, against `avg_price`, for the quantity
  sold. Never on the buy.
- **Fees** are charged on both sides and come out of the same cash that pays
  for the order, which is why `test_fees_can_be_what_pushes_an_order_out_of_reach`
  exists: 100 cash cannot buy 1 unit at 100 when the fee rate is 1%.
- **Equity** is cash plus marked-to-market open positions, and it must not need
  a price for a position that has been closed — `equity({})` is a legal call
  after a round trip.

## Hints, in escalating order — take the fewest you can

1. Get `__init__`, `position` and `quantity` done first; four tests go green
   immediately and you have somewhere to stand. `position()` on an unknown
   symbol returns a flat `Position`, and the test does not say whether that
   gets stored.
2. Write `execute` as two branches on `order.side` that share the fee
   calculation, the `Fill` construction and the append. Get BUY fully green
   before you start SELL.
3. On a buy, the new average is `(old_avg * old_qty + notional) / new_qty`.
   Work out for yourself why using `price` instead of `notional / quantity`
   there is the same thing, and whether that stays true if you ever allow
   partial fills.
4. `test_a_rejected_order_leaves_the_account_untouched` is the one to design
   around, not patch in afterwards. Decide where validation happens relative
   to the first mutation, and make that order deliberate.

## Then, and only then

The header comment at the top of the stubbed file names the commit it came
from. Read it and diff:

```bash
SHA=$(sed -n 's/^# STUBBED-FROM: //p' src/trading_bot/portfolio.py)
git show "$SHA:src/trading_bot/portfolio.py" > /tmp/original_portfolio.py
diff -u /tmp/original_portfolio.py src/trading_bot/portfolio.py
```

(If you already restored the file, the header is gone — the same commit is
whatever `git log --oneline -- src/trading_bot/portfolio.py` shows before your
own work.)

## Questions to answer out loud before you call this finished

1. After a buy that raises `InsufficientFunds` for a symbol never traded
   before, is `portfolio.positions` still empty? Check your version. Then check
   the original. **They differ, and the test suite passes either way.** Work
   out which behaviour you would defend in review and what the consequence of
   the other one is. This is the most valuable question on the page.
2. `realized_pnl` is booked against `avg_price`. What does that make it — FIFO,
   LIFO, or weighted average cost? Which one does a tax authority expect, and
   does this class let you produce that?
3. `equity()` skips positions with zero quantity. What breaks if it does not,
   and which test catches it?
4. Cash is a `float`. Give a concrete sequence of buys and sells where that
   loses money that should exist. How do real ledgers avoid it, and why might
   a backtester reasonably not bother?
5. `execute` both mutates the portfolio and returns a `Fill`. Name one thing
   that gets harder because of that, and one that gets easier.
6. `total_return` guards against `initial_cash == 0` but `equity` does not
   guard against a missing price in the mapping. Is that inconsistent, or is
   one of them the right call and the other wrong?

## Next

[`exercises/03-sizing.md`](03-sizing.md), then
[`04-backtest.md`](04-backtest.md) and [`05-broker.md`](05-broker.md).
Do them in that order; [`exercises/README.md`](README.md) has the table.
`broker` is last and is a week rather than a day.
