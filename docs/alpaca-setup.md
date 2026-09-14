# Connecting to Alpaca paper

A runbook from a fresh Alpaca account to a bot that places orders, in the order
the steps have to happen. Every step is refusable: nothing here places an order
until the last one, and each stage is designed to fail loudly rather than
proceed on a guess.

The concepts behind the adapter — retry-safe order ids, two-way reconciliation,
why the live endpoint is refused by default — are in the README under
[Talking to a broker](../README.md#talking-to-a-broker). This document is the
operational half: what to click, what to export, and what correct output looks
like.

## 1. Get a paper account

Sign up at [alpaca.markets](https://alpaca.markets). The paper sandbox is free,
needs no deposit, and does not require the identity verification that a funded
live account does. You do not have to complete brokerage onboarding to use it.

The sandbox starts with $100,000 of simulated cash.

## 2. Generate paper keys

Paper keys and live keys are **different credentials on different endpoints**.
Generate them from the paper dashboard, not the live one — a live key will not
authenticate against `paper-api.alpaca.markets`, which is the failure in
[§6](#6-when-it-goes-wrong).

In the Alpaca web dashboard, switch to **Paper Trading** (there is a toggle
between live and paper), then find the API keys panel and generate a new key.
You get two strings:

- a **key id**, beginning `PK` for paper keys
- a **secret key**, shown **once** — it cannot be retrieved later, only
  regenerated, which invalidates the old one

Copy both before closing the dialog.

## 3. Put them in the environment

The package reads two variables and nothing else:

```
APCA_API_KEY_ID
APCA_API_SECRET_KEY
```

The simplest durable option is your shell profile (`~/.zshrc` on macOS,
`~/.bashrc` on most Linux):

```bash
export APCA_API_KEY_ID=PK....................
export APCA_API_SECRET_KEY=................................
```

Open a new terminal afterwards, or `source ~/.zshrc` in the current one.

If you prefer to keep them with the project, `.env` is gitignored:

```bash
cat > .env <<'ENV'
APCA_API_KEY_ID=PK....................
APCA_API_SECRET_KEY=................................
ENV

set -a; source .env; set +a      # export everything in it, then stop
```

Nothing in this repo loads `.env` automatically — the package is
dependency-free and has no dotenv reader — so that `source` line is required in
each shell, and in any cron entry that needs the keys.

**Never commit either file.** If a key does reach a commit, regenerate it in
the dashboard rather than trying to scrub history; regeneration invalidates the
leaked key immediately, and rewriting history does not.

## 4. Prove the credentials work

`research/broker_check.py` is read-only. It places no orders and modifies
nothing:

```bash
python research/broker_check.py
```

What correct looks like on a fresh account:

```
endpoint      https://paper-api.alpaca.markets  (paper=True)
cash              100,000.00 USD
equity            100,000.00
buying power      200,000.00
positions     0

reconciling qqq_sma_10_50_vol25.json against the broker
  QQQ: 0 — matches

all positions agree; no orders were placed
```

Exit code 0. Read it as four separate confirmations:

| Line | What it proves |
| --- | --- |
| `endpoint … (paper=True)` | You are pointed at the sandbox, not live money |
| `cash` / `equity` / `buying power` | The credentials authenticated and the account response parsed |
| `positions 0` | The positions endpoint answered in the shape the adapter expects |
| `QQQ: 0 — matches` | The frozen run's intended holding agrees with the broker |

That last line is the one worth caring about. It compares what
`paper/qqq_sma_10_50_vol25.json` believes it holds against what Alpaca actually
holds, **over the union of both sides** — so a position the broker holds that
the run knows nothing about shows up rather than being skipped:

```
positions     1
  AAPL              50 @ 231.10

reconciling qqq_sma_10_50_vol25.json against the broker
  AAPL: run expects 0, broker holds 50 (drift +50)
  QQQ: 0 — matches

1 position(s) disagree. Nothing was changed — reconcile by hand before letting anything trade.
```

Exit code 1. Sell the stray by hand in the dashboard, or start from a clean
paper account; do not let the bot trade on top of a divergence, because every
subsequent order compounds it.

This check matters more than it looks. The endpoint paths and JSON field names
in `broker.py` were written from knowledge of Alpaca's v2 API rather than
verified against the live service, because the environment the adapter was
built in cannot reach it. **This script is where a mismatch surfaces**, and it
surfaces before an order exists rather than after one is wrong.

## 5. The order of operations

Credentials working is not the same as ready to trade. Three gates, in order:

```bash
# a. bars — the rule cannot decide without them
python research/fetch_bars.py --out paper/qqq_bars.csv

# b. preflight — what will it open with, and is that a decision or an accident?
python research/preflight.py paper/qqq_sma_10_50_vol25.json paper/qqq_bars.csv

# c. dry run — what order would that produce against the real account?
python research/trade.py --symbol QQQ
```

Only when (b) exits 0 and (c) prints a plan you agree with does `--execute`
make sense — and the first one will refuse on the notional ceiling until you
raise it deliberately ([§6](#6-when-it-goes-wrong)). See
[Before the first launch](../README.md#before-the-first-launch) for what
preflight refuses and why.

Before the run has recorded any live bars, (c) says so and stops:

```
the paper run has no live bars yet; nothing to act on
```

That is correct, not a failure. The frozen rule holds zero bars until
`paper_trade.py` advances it past the warmup boundary. Once it has bars, a dry
run looks like this:

```
rule          SmaCrossover{'fast_period': 10, 'slow_period': 50} [607d3ec444f322bb]
sizing        VolatilityTarget
decision      LONG at weight 1.00 as of 2026-09-14
last close    518.13 (QQQ)
trading       QQQ  (sized on its live price, not this close)
reconcile     skipped — no live position recorded yet

plan          QQQ: buy 166 — target 1.00, holding 0.00

DRY RUN — nothing was sent. Pass --execute to place this order.
```

Three things in there are worth reading carefully:

- **`weight 1.00`** is the volatility target's answer today, not a constant. It
  asks for `25% / realized volatility` of equity, capped at 1.0 — so in a calm
  market it saturates at fully invested, and in a turbulent one it will ask for
  0.4 and the order will be correspondingly smaller.
- **`sized on its live price, not this close`** — the share count comes from
  QQQ's current price fetched from the broker, never the close the rule decided
  on. Sizing off an index level against an ETF is a tenfold error and a silent
  one.
- **`reconcile skipped`** appears only before the first order. Afterwards,
  `paper/live_position.json` exists and a mismatch halts the run.

## 6. When it goes wrong

| Symptom | Cause | Fix |
| --- | --- | --- |
| `set APCA_API_KEY_ID and APCA_API_SECRET_KEY` | Variables not exported in *this* shell | Re-`source` your profile or `.env`; check with `echo $APCA_API_KEY_ID` |
| 401 / 403 from the endpoint | Live keys against the paper endpoint, or a regenerated secret | Generate fresh keys from the **Paper Trading** dashboard |
| `… is not the paper sandbox` | A base URL pointing at live | Intended. Live trading needs `allow_live=True` passed deliberately in code |
| `N position(s) disagree` | Broker and run hold different things | Reconcile by hand ([§4](#4-prove-the-credentials-work)) |
| `refused: … the feed is behind` | Newest bar older than 4 days | Re-run `fetch_bars.py`. Over a long holiday, raise `--max-bar-age-days` knowingly |
| `over max_order_notional` | Order above the dollar ceiling | See below |

Two ceilings apply to every order, checked before anything is sent:

| Limit | Default | Flag |
| --- | --- | --- |
| `max_order_notional` | $25,000 | `--max-order-notional` |
| `max_order_quantity` | 10,000 shares | code only |

**The default notional ceiling is below a full position on a $100k account, on
purpose.** A fully-invested QQQ order is around $100,000, so the first
`--execute` refuses:

```
plan          QQQ: buy 166 — target 1.00, holding 0.00

order failed: 166.0 QQQ at 601.42 is 99,835.72, over max_order_notional 25,000.00
```

Exit code 1, and nothing was sent. That is the limit working: a rule that has
never traded live is exactly when a sizing bug is most likely, so the cap stops
the order rather than warning about it. Raise it once you have read the number
and agree with it:

```bash
python research/trade.py --symbol QQQ --execute --max-order-notional 150000
```

The price used is the traded instrument's, fetched from the broker at submit
time rather than taken from the caller — an argument you can omit is not a
ceiling. If that lookup fails the order is **refused rather than sent
unchecked**, with one exception: a retry of an order id the broker already
holds is returned as-is, because it adds no exposure and the duplicate-id
protection must survive a data endpoint being down.

## 7. Placing the first real order

```bash
python research/trade.py --symbol QQQ --execute
```

Then check the Alpaca dashboard: the order appears under **Orders**, and once
filled, under **Positions**.

`--symbol` is required rather than defaulted because choosing the instrument
you actually trade is a decision. The rule is frozen on QQQ and QQQ is directly
tradeable, so they coincide here — but the argument stays explicit so that a
rule frozen on an untradeable index cannot silently inherit one.

## 8. Running it daily

```bash
crontab -e
```

```cron
0 22 * * 1-5 cd /path/to/trading-bot && set -a && . .env && set +a && BROKER_SYMBOL=QQQ research/daily.sh >> /tmp/paper.log 2>&1
```

That fetches the day's bar, advances the run, and reports what it *would* do.
It does not trade: order placement needs `TRADE=execute` in the environment as
well, which is a separate and deliberate edit to the same line.

Exercising the whole path daily is what catches bugs — credentials expiring, a
feed going stale, reconciliation drifting — while placing orders stays a
decision you make once and can see in the crontab.

Cron runs with a minimal environment and does not read your shell profile,
which is why the `. .env` is in the line. Check `/tmp/paper.log` after the
first scheduled run rather than assuming it worked.

## 9. Watching it on TradingView

TradingView's own paper trading takes no orders from outside — it is a
simulator inside their UI with no public order API. What does work is the
reverse: connect this Alpaca paper account to TradingView's trading panel, and
the positions the bot opens through Alpaca's API are drawn on the chart.

Alpaca has been available in TradingView's broker list; confirm it is still
there in the panel rather than taking this document's word for it. The bot
talks to Alpaca either way — TradingView is only the window.

Porting the rule to Pine Script would also render its entries and exits, but
that is a *second implementation* of a rule this repo fingerprints precisely to
prevent silent divergence. Fine as a picture, dangerous as a source of truth.

## What none of this covers

The rule decides at a close. A market order fills at the next available price.
That gap is real, it moves with the overnight gap, and it is in no backtest
number in this repository.

Paper fills are also optimistic in a way live fills are not: the sandbox fills
at the quoted price without your order having moved the book or missed it.
