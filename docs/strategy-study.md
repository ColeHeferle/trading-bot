# Which strategy actually works better?

Reproduce with `pip install -e ".[research]" && python research/compare_strategies.py`.

## Setup

Daily bars, real data, bundled in the `arch` wheel so there is no network fetch:
S&P 500 and Nasdaq 1999–2018 (5,031 bars each) and WTI crude 1986–2019 (8,321
bars). Every run is long-only, fully invested when long, and pays **5 bps per
side** in fees. The benchmark is buy-and-hold, which is the number that matters:
a rule that trades more and returns less is not earning its risk.

## Headline

**`SmaCrossover(10, 30)` — the original default — was the weakest rule tested.**
It trailed buy-and-hold on all three markets and lost money outright on crude.
The default is now `SmaCrossover(50, 200)`.

S&P 500, full window 1999–2018:

| strategy | CAGR | Sharpe | max DD | trades |
| --- | ---: | ---: | ---: | ---: |
| BuyAndHold (benchmark) | 3.63% | 0.28 | 56.8% | 1 |
| SmaCrossover 10/30 (old default) | 1.81% | 0.22 | 32.8% | 176 |
| **SmaCrossover 50/200 (new default)** | **5.58%** | **0.53** | **20.6%** | **18** |
| PriceVsSma 200 | 2.57% | 0.29 | 26.4% | 148 |
| TimeSeriesMomentum 252 | 4.34% | 0.44 | 25.5% | 66 |

The 50/200 rule beats 10/30 on all three markets and in both halves of the data,
which is what makes it a real improvement rather than a lucky fit. Much of the
gap is simply cost: 176 trades against 18.

## The catch, which matters more than the headline

**Over 2010–2018 every strategy lost to buy-and-hold**, on the S&P (9.24% vs a
best of 6.79%) and on the Nasdaq (12.46% vs 8.42%). Trend following earns its
keep in crashes and gives it back in rallies:

| S&P 500 regime | BuyAndHold | SmaCrossover 50/200 |
| --- | ---: | ---: |
| dot-com bust 1999–2002 | −8.02% | +0.29% |
| recovery 2003–2007 | +10.08% | +4.04% |
| GFC 2008–2009 | −12.24% | +11.61% |
| bull 2010–2018 | +9.24% | +6.79% |

So the full-window win depends on the window containing two 50%+ drawdowns.
Start the same study in 2010 and buy-and-hold wins outright. What survives in
every cut is the **drawdown** difference — 20.6% against 56.8% — so the honest
claim is that these rules trade return for a much smoother ride, not that they
beat the market.

## Tuning added nothing

Parameters were fitted on 1999–2008 by Sharpe, then judged on 2009–2018. The
fitted choice was worth almost nothing over the textbook 50/200:

| market | in-sample best | its OOS CAGR | 50/200 OOS CAGR |
| --- | --- | ---: | ---: |
| S&P 500 | 40/250 | 6.23% | 6.09% |
| Nasdaq | 5/50 | 7.61% | 7.55% |
| WTI | 5/100 | 5.48% | 1.28% |

Out-of-sample Sharpe across the whole 30–80 × 150–250 neighbourhood sits in a
flat 0.5–0.7 band on equities. There is no peak to find, which is the useful
result: **the parameters barely matter, so treat any finely tuned pair as
noise.** Crude is the exception where tuning appeared to pay, and one instrument
out of three is what a false positive looks like.

## What is not modelled

Slippage beyond the flat 5 bps, market impact, borrowing costs, taxes, dividends
(index price series, so total return is understated for buy-and-hold — which
makes the benchmark *harder* to beat than shown here), and survivorship. Results
are single-asset and long-only. None of this is investment advice.

---

# Does volatility targeting help?

`VolatilityTarget` scales the position so its *risk* stays constant instead of
its size: weight is `target_volatility / realized_volatility`, capped at
`max_leverage`. Realized volatility is the trailing 20-candle standard
deviation, annualized. Rebalancing happens only when the weight has drifted past
`rebalance_threshold`; exits are never banded.

Same data, same 5 bps per side, target volatility 15%.

## What it reliably does: cut drawdown

| full window 1999–2018 | max DD without | max DD with | Sharpe without → with |
| --- | ---: | ---: | ---: |
| S&P 500 BuyAndHold | 56.8% | **45.9%** | 0.28 → 0.27 |
| Nasdaq BuyAndHold | 77.9% | **46.7%** | 0.34 → **0.54** |
| WTI BuyAndHold | 82.0% | **51.3%** | 0.36 → 0.29 |
| S&P SmaCrossover 50/200 | 20.6% | **18.7%** | 0.53 → 0.46 |
| Nasdaq SmaCrossover 50/200 | 24.6% | **18.6%** | 0.50 → **0.55** |
| Nasdaq TimeSeriesMomentum | 20.4% | **16.7%** | 0.50 → **0.55** |

Drawdown fell in **every** pairing tested. That is the effect to rely on.

## What it does not reliably do: raise returns

Return usually falls, because a risk-targeted position is smaller on average
than a fully invested one. There is exactly one case here where it improved
both return and risk — Nasdaq buy-and-hold, 5.66% → 6.97% CAGR with drawdown
cut from 77.9% to 46.7% — and it is the most violently volatile equity exposure
in the set. That is the pattern: **the wilder and less managed the exposure, the
more volatility targeting adds.**

## Where it actively hurts

Layered onto a trend rule that already sidesteps crashes by going flat, it can
subtract: S&P `SmaCrossover(50, 200)` drops from 0.53 to 0.46 Sharpe and 5.58%
to 4.20% CAGR. The rule had already cut its own risk, so scaling adds cost
without adding protection. On WTI it is worse — 4.89% to 1.39% CAGR — because
crude's volatility is persistently high, so the sizer holds a small position
throughout and still pays to rebalance it.

**Do not stack it on a strategy that is already flat during crashes.** It pays
where exposure is constant and volatility is not.

## Turnover is the cost, and the band is the dial

Volatility targeting turns a 22-trade strategy into a 70-trade one. The
rebalance band controls that, and it is flat where it matters:

| band | S&P Sharpe | S&P trades | Nasdaq Sharpe | Nasdaq trades |
| ---: | ---: | ---: | ---: | ---: |
| 0.01 | 0.45 | 536 | 0.51 | 764 |
| 0.05 | 0.45 | 211 | 0.52 | 287 |
| 0.10 | 0.44 | 110 | 0.51 | 152 |
| **0.20** | 0.46 | **61** | 0.55 | **70** |
| 0.30 | 0.45 | 36 | 0.51 | 48 |
| 0.50 | 0.45 | 21 | 0.47 | 24 |

Sharpe is unchanged from 0.01 to 0.3 while turnover falls 25×, so the default is
0.2 — chosen from the flat region to cut trading, not because 0.2 scored top.
Read the 0.20 row as "indistinguishable from its neighbours", not as a peak.

---

# Does holding a basket help?

`run_multi_backtest` runs one strategy per symbol over a shared cash balance,
capping each symbol's share of equity (equal split by default). Reproduce with
`python research/compare_baskets.py`. Restricted to 1999–2018, the window all
three markets share.

> **Corrected.** The numbers first published here were computed with a
> rebalancing band that did not scale with the number of symbols, so every
> multi-symbol basket was rebalanced far too loosely — and a three-symbol
> basket needed a 60% relative drift before it corrected. Fixing that
> (`rebalance_threshold` is now scaled by each symbol's weight) changed the
> figures below and **reversed the trend-following conclusion**. The original
> claim, that a basket beats its average member but not its best one, was an
> artifact of that bug.

## Buy-and-hold: diversification wins

| 1999–2018 | CAGR | Sharpe | max DD |
| --- | ---: | ---: | ---: |
| sp500 alone | 3.63% | 0.28 | 56.8% |
| nasdaq alone | 5.66% | 0.34 | 77.9% |
| wti alone | 6.67% | 0.36 | 82.0% |
| **equal-weight basket** | **7.48%** | **0.46** | 51.3% |

The basket beat every one of its own constituents on both return and Sharpe.
Rebalancing back to equal weight sells whatever ran up and buys whatever
lagged, and across three imperfectly correlated markets that harvesting is
worth more than the cash drag of the band. Drawdown lands just below the best
single leg — diversification smooths the path, it does not abolish 2008.

## Trend following: it wins too, at a wider drawdown

| 1999–2018, SMA 50/200 | CAGR | Sharpe | max DD | trades |
| --- | ---: | ---: | ---: | ---: |
| sp500 alone | 5.58% | 0.53 | **20.6%** | 18 |
| nasdaq alone | 5.81% | 0.50 | 24.6% | 22 |
| wti alone | 4.89% | 0.32 | 55.0% | 26 |
| **basket of three** | **6.28%** | **0.57** | 24.3% | 79 |
| sp500+nasdaq | 5.77% | 0.54 | **19.9%** | 40 |

The three-market basket beat every leg on return and Sharpe, crude included —
even though crude is the worst of them on its own. That is the point of
diversifying: a leg does not have to be good alone to be worth holding
alongside others, so long as it is not merely a worse copy of them. It does
carry the wider drawdown, and the equity-only pair remains the smoothest ride.

## The costs that scale with breadth

Turnover multiplies with the universe: `PriceVsSma(200)` across three markets
trades 478 times against 148 on the S&P alone, and its 3.84% CAGR is the worst
trend result here. Every symbol pays the band's rebalancing on top of its own
entries and exits — and the tighter, correctly-scaled band charges more for it
than the buggy one did.

## What this does not show

Three markets, two of them equity indices that fell together in 2000 and 2008,
is a thin universe — see the next section, which widens it to bonds and
currencies.

---

# Adding bonds and currencies

`python research/compare_universe.py`. Monthly bars, 1999–2018, ten symbols:
S&P 500, Nasdaq, WTI, a synthetic 10-year Treasury total-return index, and six
freely floating currencies (EUR, JPY, GBP, CHF, CAD, AUD).

Monthly, not daily, because the only US 10-year yield series reachable offline
is monthly — and dropping a monthly leg into a daily basket would leave the bond
mark stale for weeks and corrupt every daily statistic. Trend parameters are
monthly equivalents: a 10-month filter, not a 200-day one.

## Two things had to be built before this could run at all

**A yield is not a price.** Buying a series quoted in yields gets the sign
backwards, since yields rise when prices fall. `trading_bot.bonds` converts
yields into a constant-maturity par-bond total-return index: carry each period,
minus duration times the change in yield. It is a model, not a traded price —
it omits convexity, roll-down and financing.

**The exchange-rate source quotes foreign units per dollar**, uniformly, for
every currency including EUR and GBP. Used as published, "buying" would have
been a long *dollar* position and every currency result would have carried the
wrong sign. `load_fx` inverts to dollars per unit.

## Bonds: the best single asset in the study

| 1999–2018, monthly | CAGR | Sharpe | max DD |
| --- | ---: | ---: | ---: |
| **ust10y (synthetic)** | 4.17% | **0.69** | **9.4%** |
| sp500 | 3.43% | 0.31 | 52.6% |
| nasdaq | 5.01% | 0.33 | 75.0% |
| wti | 6.53% | 0.36 | 76.6% |

Adding bonds improved every basket tested, and equities-plus-bonds under a
10-month trend filter is the best risk-adjusted result anywhere in this study:

| 10-month trend | CAGR | Sharpe | max DD |
| --- | ---: | ---: | ---: |
| equities only | 5.66% | 0.64 | 16.7% |
| + crude | 6.16% | 0.66 | 18.2% |
| + bonds | 5.58% | 0.78 | 12.7% |
| **equities + bonds only** | 5.05% | **0.81** | **9.6%** |
| + currencies (all ten) | 2.80% | 0.62 | 9.0% |

Bear in mind *why* 1999–2018 flatters bonds: yields fell from 4.65% to 2.7%
across the window, so the duration term paid out for twenty years. This is a
sample containing one long bond bull market, and it will not repeat from a
starting yield near zero.

## Currencies: they diluted the basket

Spot currency returns were close to nothing over this window — EUR +0.04% a
year, JPY +0.28%, GBP −1.27%, CHF +1.85%, CAD +0.51%, AUD +0.57%. Equal
weighting hands six such legs 60% of the capital, and the full ten-symbol
basket falls to 2.80% CAGR from the four-symbol basket's 5.58%.

Two caveats before concluding currencies are useless:

**This is spot only, and spot is not the whole return.** Holding a currency
earns the interest-rate differential — the carry — which is most of what
currency strategies actually harvest. A spot series omits it entirely, so these
numbers understate real currency returns by an amount that varies by pair and
period. The right fix is short-rate data per currency, which is not reachable
here.

**Equal weighting is doing much of the damage.** The finding is as much about
handing 60% of capital to six near-zero-return legs as about currencies. Drawdown
did fall — 12.7% to 9.0% — which is what diversification into uncorrelated,
low-volatility assets is supposed to do. What sank the return was the
allocation, not the diversification.

## The monthly caveat

Monthly sampling cannot see intra-month drawdowns, so every max drawdown here
is understated and every Sharpe flattered relative to the daily figures earlier
in this document. Compare monthly against monthly, not against the daily study.

---

# Can a forward test prove this makes money?

No. Not for these rules, and the arithmetic says so before the test starts.

## The number that settles it

A t-statistic on mean return grows as `IR × √years`, so reaching `t = 2` needs
`(2 / IR)²` years. Measured on 1999–2018 S&P 500 data, `SmaCrossover(50, 200)`
scored an **information ratio of 0.046 against buy-and-hold**.

| what you want to show | information ratio | years to t = 2 |
| --- | ---: | ---: |
| the rule's return is above zero | 0.53 | **14** |
| the rule beats buy-and-hold | 0.046 | **~1,900** |

Fourteen years to establish that a rule with a 0.53 Sharpe makes money at all.
Nineteen centuries to establish that it beats simply holding the index. No
amount of patience closes that gap, because the edge is not small — it is
indistinguishable from zero.

`trading_bot.paper.years_to_detect` computes this. Run it on a strategy before
committing to forward-test it; if the answer exceeds a working lifetime, the
test cannot answer the question and a different question is needed.

## "Profitable every day" is the wrong target

On the same data, `SmaCrossover(50, 200)`:

- was up on **36%** of days (it sits in cash a third of the time, and a flat day
  is not a winning one),
- beat buy-and-hold on **45%** of days,
- and its longest winning streak in twenty years was **8 days**.

Any real strategy loses on a large fraction of days; that is what taking risk
means. A rule that appeared to win every day would signal a bug — lookahead,
a stale mark, a fee that never got charged — not a discovery.

## What a forward test is still worth doing for

Three things, none of them proof:

1. **Bugs a backtest hides.** Lookahead, survivorship, a fill at a price that
   was never available. Live bars arriving one at a time expose these.
2. **Regime breaks.** Not "is there an edge" but "is this behaving the way it
   did historically" — position count, exposure, trade frequency drifting from
   the backtest is a real signal, and it shows up in months, not centuries.
3. **A tamper-evident record.** `FrozenRule.fingerprint` hashes the strategy,
   its parameters, the instrument and the costs. Commit it before the data
   exists, and any later edit changes the hash. This is the whole value: it
   makes it impossible to quietly tune the rule after seeing the results and
   then present the outcome as a forward test.

## Running one

`paper/spx_sma_50_200.json` is a rule frozen at fingerprint `f209ac9a054c6df9`
before any forward data existed. Advance it by appending bars to a CSV and
running:

```bash
research/daily.sh                                          # fetch, then advance
python research/paper_trade.py paper/spx_sma_50_200.json bars.csv   # advance only
```

`fetch_bars.py` pulls daily bars from Stooq (no dependencies) or yfinance and
merges them into the CSV. It never overwrites a date already stored: a vendor
restatement is reported as a REVISION and the recorded bar is kept, because
deciding the vendor is right is not something a cron job should do at 10pm.

Only `date` and `close` are required; open, high, low and volume fall back to
the close. The state file holds every bar it has seen and replays them on load,
so the run survives restarts and a tampered rule refuses to load at all. There
is no market data connection on purpose: whatever feed you use becomes the CSV,
and keeping the fetch outside means the run cannot be silently re-driven by a
vendor that revised its history underneath you.

## Warmup, and why backfilled bars do not count

A 200-day rule needs 200 bars before it can signal at all, so a run started cold
sits in cash for roughly ten months. Backfilling history fixes that — but those
bars are the same history the rule was *selected* on, and letting them into the
equity curve would dress up in-sample data as forward evidence.

`warmup_until` separates the two. Bars before it advance the strategy's averages
and its long/flat state but do not trade and do not enter the record; the equity
curve opens at the boundary, and so does the benchmark. A rule that crossed into
"long" during warmup takes its position on the first live bar rather than
waiting for a fresh cross.

```
new bars      20 live, 250 warmup  (total 20 live, 250 warmup)
record opens  2026-09-01
window        2026-09-01 .. 2026-09-20  (0.05 years)
```

The elapsed window reads 0.05 years, not the 0.74 the bar count would suggest.
That number feeds the honesty line, so warmup cannot quietly inflate how long a
result has been running.
