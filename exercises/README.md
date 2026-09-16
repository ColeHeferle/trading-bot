# Exercises

Rewrite this repository's core modules from their tests, one at a time, until
you can defend every line of it.

The rule that makes it work: **read the tests, not the implementation.** The
tests are a complete specification for every module here. The implementation is
one answer to that specification, and it is not always the best one — two of
these briefs end by asking you to find a real defect in the original that the
test suite does not catch.

## The five

Do them in this order. Each one leans on the modules before it.

| # | module | brief | targeted | also reds | total red |
| --- | --- | --- | --- | --- | --- |
| 01 | `indicators` | [01-indicators.md](01-indicators.md) | 17 | 3 | 20 |
| 02 | `portfolio` | [02-portfolio.md](02-portfolio.md) | 20 | 118 | 138 |
| 03 | `sizing` | [03-sizing.md](03-sizing.md) | 21 | 33 | 54 |
| 04 | `backtest` | [04-backtest.md](04-backtest.md) | 63 | 32 | 95 |
| 05 | `broker` | [05-broker.md](05-broker.md) | 53 | 9 | 62 |

"Also reds" is the collateral damage — tests in other files that fail because
they depend on the module you just emptied. It is a rough map of how load
bearing each module is, and it is worth a look before you start: `portfolio`
takes down six other files because it is the ledger everything writes through,
while `broker` sits at the edge and takes down almost nothing.

Rough budget at twenty hours a week: 01 is an evening, 02 and 03 are a weekend
each, 04 is two weeks, 05 is a week.

## Running one

```bash
pip install -e ".[dev]"

python exercises/stub.py --list          # state of every exercise
python exercises/stub.py portfolio       # start one
python exercises/stub.py --restore portfolio
```

`stub.py` replaces every function body in the module with a
`NotImplementedError`, keeping signatures, docstrings, imports and class
definitions. It records the commit it stubbed from in a header comment at the
top of the file, so `--restore` and the diff step stay correct however many
commits you stack on top. It refuses to stub a file with uncommitted changes,
because then the recorded commit would not match what was replaced.

Restore overwrites your work. Commit first if you want to keep it.

## The shape of every brief

1. **Activate** — the one command.
2. **Baseline** — the exact test counts you should see, so you can tell a
   broken setup from an unfinished exercise.
3. **Rules** — chiefly: do not read the original first.
4. **What the tests are specifying** — the domain logic, stated plainly,
   because some of it is finance rather than programming.
5. **Hints, escalating** — take the fewest you can.
6. **The diff step** — compare against the original and decide, line by line,
   which version is better.
7. **Questions** — the ones an interviewer asks after you say "I built a
   backtesting engine". If you cannot answer them, you have not finished.

Step 7 is the actual point. Green tests prove the code works. The questions are
what prove you wrote it.

## Time yourself

Write down how long each one takes. The number is only useful if it is honest,
and the trend across five modules is the clearest evidence you will get that
this is working.
