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

## Correction: the bond results are probably an artifact (2026-09-09)

Every bond number in this document, and the "bonds were the best single asset"
conclusion drawn from it, should be treated as unreliable.

The bond series here is not observed. It is built by `trading_bot.bonds` from
published yields, and those yields — Moody's AAA/BAA, and the Treasury constant
maturity series — are **monthly averages of daily observations**. Yields behave
roughly like a random walk, and averaging a random walk over non-overlapping
blocks induces about +0.25 serial correlation in the changes where the month-end
observation would show none. This is Working's (1960) result, and it is
reproduced as a test in `tests/test_significance.py`.

A trend-following rule reads that manufactured persistence as an edge:

| series | lag-1 | lag-2 | lag-3 |
| --- | --- | --- | --- |
| AAA corporate, built from yields | **+0.325** | −0.037 | −0.024 |
| BAA corporate, built from yields | **+0.310** | +0.028 | −0.083 |
| UST 10y, built from yields | **+0.316** | −0.060 | +0.004 |
| US equity, true month-end | +0.106 | −0.021 | −0.094 |

Three things mark it as an artifact rather than real momentum. The lag-1 is
three times that of a genuinely observed series; lag-2 and lag-3 are ~zero,
where real persistence decays geometrically (about lag-1²); and the best rule
was `TSMOM(1)`, the shortest lookback possible, which is precisely the symptom a
one-lag artifact predicts.

The replication on Moody's corporates — independent issuers, independent credit,
starting 34 years earlier — reproduced the *effect* but shares the *defect*:
same construction, same averaged source. Independent data, common flaw.

The decisive test is a real instrument quoted at month-end close: IEF, TLT, or
Treasury futures. No market-data host is reachable from the environment this was
written in, so it has not been run.

`trading_bot.smoothness` now flags this class of series. Run it on any price
history before trusting a trend result measured on it.

### What survives

On 1,109 months of true month-end US equity returns (1926–2018, Fama-French
market factor), trend-following does **not** reliably beat buy-and-hold on
Sharpe — 0.75 against 0.61 raw, which deflates to p = 0.52 once charged for the
full search. It wins in crashes and loses in rallies:

| period | B&H Sharpe | TSMOM(12) | B&H drawdown | TSMOM(12) |
| --- | --- | --- | --- | --- |
| 1926–49 | 0.36 | **0.49** | 83.7% | **44.1%** |
| 1950–79 | **0.81** | 0.72 | 46.4% | **16.1%** |
| 1980–99 | **1.12** | 1.05 | 29.9% | 29.9% |
| 2000–18 | 0.47 | **0.82** | 50.4% | **17.7%** |

What survives every cut is the drawdown, roughly halved in three of four
independent multi-decade periods, at 0.8 trades a year and near-total
insensitivity to fees. That is a risk control, not an edge — the same conclusion
this document reached on 20 years, now confirmed on 92.

### Confirmed on real data: the same pipeline, two vendors

The correction above rested on a simulation. It can be checked directly,
because the universe contains a controlled comparison. Run
`research/data_quality.py`:

```
series                 bars    lag-1    lag-2   lag-1²  verdict
fx:Australia            668   +0.011   +0.011   +0.000  clean
fx:Canada               668   -0.051   +0.005   +0.003  clean
fx:Euro                 332   +0.041   -0.010   +0.002  clean
fx:Japan                668   +0.052   +0.069   +0.003  clean
fx:Switzerland          668   +0.012   +0.027   +0.000  clean
fx:United Kingdom       668   +0.060   +0.032   +0.004  clean
nasdaq                  240   +0.071   -0.021   +0.005  clean
sp500                   240   +0.073   -0.042   +0.005  clean
ust10y                  879   +0.316   -0.060   +0.100  SUSPICIOUS
wti                     397   +0.122   -0.046   +0.015  clean
```

Every series here goes through the same loader, the same monthly reduction and
the same backtest. Nine are clean and one is not. The difference is upstream of
all of it: `to_monthly` keeps each month's **last** observation, so the daily
currency and equity feeds arrive as month-end closes, while the yield series is
published already averaged over the month.

That removes the innocent explanations. It is not the duration model, not the
monthly sampling, and not the backtest engine, because the clean series share
all three. It is the source data.

The strategy results follow the data quality exactly. On the six currency
series — genuinely observed, six independent markets, 55 years — **none of 66
strategy/lookback combinations survives deflation**:

| data | best rule | vs buy-and-hold | deflated p |
| --- | --- | --- | --- |
| bonds, monthly *averages* | 1.15–1.34 | 0.83–0.98 | **1.000** |
| FX, month-*end*, 6 markets | 0.42 | 0.32 | **0.740** |

The edge appears where the averaging is, and nowhere else.

This does not formally settle bonds: currencies are a different asset class,
and it remains possible that bonds genuinely trend while currencies do not. A
real bond instrument quoted at month-end close would settle it. No market-data
host is reachable from here, and no public mirror carrying one was found.

## Volatility targeting on a fast trend rule (2026-09-09)

The sizing section of the README claimed that volatility targeting stacked on a
trend rule which already goes flat in crashes made things worse. That was drawn
from `SmaCrossover(50, 200)` and stated too broadly. On Nasdaq daily bars with a
faster rule it is the best equity configuration measured in this repo.

All figures 1999-2018 daily, 5 bps per side, 5,031 bars. Both index series pass
`trading_bot.smoothness` (S&P lag-1 -0.071, Nasdaq -0.032), so these are
genuinely observed prices.

| sizing | CAGR | Sharpe | max drawdown | exposure | trades/yr |
| --- | --- | --- | --- | --- | --- |
| buy and hold | 5.66% | 0.34 | 77.9% | 100% | 0.1 |
| SMA(10,50), fully invested | 5.55% | 0.44 | 42.8% | 62% | 5.9 |
| SMA(10,50), 10% target | 3.59% | 0.49 | 14.1% | 60% | 9.4 |
| SMA(10,50), 15% target | 5.01% | 0.53 | 18.7% | 60% | 7.7 |
| SMA(10,50), 20% target | 5.50% | 0.53 | 23.7% | 61% | 6.9 |
| SMA(10,50), 25% target | 5.66% | 0.51 | 30.3% | 61% | 6.6 |

The 25% target matches buy-and-hold's return to two decimal places with a
drawdown of 30.3% against 77.9%. Costs do not break it: Sharpe 0.56 at zero
fees, 0.53 at 5bps, 0.47 at 20bps.

**The Sharpe improvement does not survive deflation.** Charged only against the
five volatility targets it reads p = 0.988; charged against every rule tried on
these two indices in the same sitting it reads p = 0.392, and the second number
is the honest one. Counting only the last five variants of a long search is
precisely the self-flattery the deflated Sharpe exists to prevent.

The drawdown reduction is a separate claim and a sturdier one, because it does
not rest on this backtest at all. Holding `target_vol / realized_vol` of equity
shrinks the position as volatility rises, by construction. That is arithmetic,
and it showed up in every pairing tested in the original study as well.

### Short horizons on the same data

The comparison that produced this started as a search for short-term gains
across US equity indices. The Dow could not be included: it is not in the
bundled data and no market-data host is reachable from here.

Every short-horizon rule lost to doing nothing, on both indices, and the
shorter the horizon the worse the result:

| rule (S&P 500) | CAGR | trades/yr | cost drag |
| --- | --- | --- | --- |
| TSMOM(5) | -4.29% | 52.0 | 2.52% |
| PvSMA(10) | -4.91% | 46.3 | 2.23% |
| SMA(5,20) | -2.32% | 15.9 | 0.78% |
| SMA(20,100) | 2.06% | 3.1 | 0.16% |
| buy and hold | 3.63% | 0 | 0 |

Cost drag tracks turnover almost linearly. At 52 trades a year and 5bps a side
the drag is 2.5% annually against an index returning 3.6% — most of the return
gone before the rule has to be right about anything.

Daily lag-1 autocorrelation is *negative* on both indices, so short-horizon
mean reversion is what the data actually suggests rather than momentum. Buying
1% falls and selling 1% rises on the S&P scored 0.36 against 0.28 for
buy-and-hold, needed 37 trades a year, and deflated to p = 0.78 across 24
variants. It does not survive either.

The horizon is the problem, not the index. Nothing at daily frequency on these
markets offers an edge larger than the cost of trading it.

---

# A funded prop account is a different problem (2026-09-15)

Everything above measures strategies against buy-and-hold on daily bars over
decades. None of it transfers to a funded futures account, and it is worth
being precise about why rather than assuming the sizing ideas carry over.

Reproduce with `python research/prop_risk.py`.

## The constraint that replaces every other constraint

A brokerage account dies when it runs out of money. A funded account dies when
equity touches a floor that trails the *peak* — and on an intraday-trailed
account that peak is marked on unrealized equity. A trade that runs $800 your
way and comes back to breakeven earns nothing and costs $800 of room.

`trading_bot.prop.DrawdownFloor` is that state machine. The floor stops rising
once it reaches the starting balance, so the account gets safer as it profits
and is at its most fragile on day one.

On a $100,000 account with a $3,000 limit, the loss budget is **3% of
notional**. The best configuration measured anywhere in this repo — Nasdaq
`SmaCrossover(10, 50)` at a 25% volatility target — has a 30.3% maximum
drawdown. Run against this ruleset it fails the account roughly ten times
over. That is not a tuning problem. Daily-bar trend following and a 3%
trailing floor are incompatible at any parameterization.

## Ruin is the governing number, and it is worse than gambler's ruin

Classical gambler's ruin on a *fixed* floor puts a driftless walk's failure
odds at `target / (target + room)` — 6000/9000 = **66.7%** here. Measured
against a trailing floor the same coin flip ruins **81.1%** of the time. The
14-point gap is what the trail costs a trader with no edge, and it is charged
before any commission.

Add costs and it is settled. 20,000 paths, $6,000 target, MES round-turn fees:

| risk/trade | win | R:R | ruin | reached target |
| ---: | ---: | ---: | ---: | ---: |
| $100 | 50% | 1.0 | **92.0%** | 0.3% |
| $200 | 50% | 1.0 | **95.6%** | 4.2% |
| $300 | 50% | 1.0 | **92.4%** | 7.6% |
| $500 | 50% | 1.0 | **88.4%** | 11.6% |

Note the direction: with no edge, ruin *falls* as risk rises. That is correct
and it is a warning, not a tactic. In an unfavourable game the only route to a
target is to arrive before costs grind you down, which is why bold play is
optimal when the edge is negative. **If sizing up ever looks like it improves
your odds, that is evidence the edge is zero.**

## With a real edge, the numbers are survivable and still not comfortable

Same account, no costs, assuming the stated edge is real and stationary:

| risk/trade | win | R:R | expectancy | ruin | median trades to target |
| ---: | ---: | ---: | ---: | ---: | ---: |
| $200 | 40% | 2.0 | 0.20R | 17.6% | 114 |
| $200 | 50% | 1.5 | 0.25R | **3.6%** | 107 |
| $500 | 40% | 2.0 | 0.20R | **49.2%** | 24 |
| $500 | 55% | 1.0 | 0.10R | **50.8%** | 50 |

$500 is one sixth of the drawdown — a size most would call conservative — and
a genuinely profitable 40%/2:1 system fails the account on a coin flip.

The 55%/1:1 row is the instructive one. A higher win rate ruins *more* often
than the 40% system, because thinner expectancy needs twice as many trades and
every trade is another draw against the floor. **Time in the account is a risk
exposure, not a neutral backdrop.**

## Instrument choice is most of the risk budget

At a 20-tick stop, one contract against a $3,000 limit:

| instrument | loss per contract | % of drawdown | straight losses to failure |
| --- | ---: | ---: | ---: |
| ES | $254.00 | 8.5% | **11.8** |
| NQ | $104.00 | 3.5% | 28.8 |
| MES | $26.00 | 0.9% | 115.4 |
| MNQ | $11.00 | 0.4% | 272.7 |

Twelve consecutive losses is an ordinary run for a 45% system. Trading the
full-size contract on this account makes a normal losing streak terminal
before any strategy question arises. Micros are not a cautious choice here;
minis are an unsized one.

## Withdrawing makes it harder, and income was the point

Compounding to a target once is the easy version. Taking income means
repeating a $2,000 run and resetting. Probability of surviving N cycles:

| risk | win | R:R | ruin/cycle | 3 cycles | 6 cycles | 12 cycles |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| $150 | 50% | 1.5 | 0.6% | 98.1% | 96.2% | **92.6%** |
| $150 | 40% | 2.0 | 4.9% | 86.0% | 73.9% | **54.6%** |
| $300 | 50% | 1.5 | 8.0% | 78.0% | 60.8% | **37.0%** |
| $300 | 40% | 2.0 | 17.9% | 55.4% | 30.7% | **9.4%** |

A year of monthly payouts is twelve cycles. At $300 risk on a real 40%/2:1
edge, the account survives that year **9.4%** of the time.

## The ruin surface is a cliff, not a slope

Account spec confirmed against a live account on 2026-09-15: $3,000 limit,
$6,000 target, intraday trail. Ruin at 1.5:1 reward:risk with MES round-turn
costs charged, 25,000 paths per cell:

| risk/trade | losses to fail | 35% | 40% | 45% | 50% | 55% |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| $100 | 30 | 100.0% | 96.6% | 13.9% | **0.2%** | 0.0% |
| $150 | 20 | 100.0% | 94.8% | 29.8% | 2.3% | 0.1% |
| $200 | 15 | 99.9% | 92.7% | 41.1% | 7.1% | 0.9% |
| $300 | 10 | 99.2% | 89.5% | 53.7% | 19.9% | 5.4% |
| $500 | 6 | 96.7% | 85.9% | 63.5% | 37.9% | 18.8% |
| $750 | 4 | 93.4% | 83.2% | 67.8% | 49.3% | 32.4% |

Breakeven after costs is **41.6%**, and the table divides on it:

**Below breakeven, sizing is irrelevant.** The 35% and 40% columns are lost
at every size, and ruin *falls* as risk rises — 100% down to 93.4%. There is
no risk management that rescues a negative edge, only a slower or faster
arrival.

**Above breakeven, sizing is the entire result.** At 45% — barely three
points clear of breakeven — ruin runs from 13.9% to 67.8% purely on position
size. Same edge, same market, a five-fold difference in survival decided by
one number the trader chooses.

The practical consequence is that the interesting quantity is not "does the
strategy work". It is the distance between the measured win rate and 41.6%,
and that distance is unknowable until enough trades exist to estimate it.
Thirty trades give a standard error of about 9 percentage points on a win
rate near 45%, which is wider than the entire distance from breakeven to
comfortable. **A trader cannot locate their own column on this table until
well past a hundred trades**, and until then the only defensible position is
the top row.

## A high win rate is not the number that decides this

An account holder reporting six months at a 70-80% win rate is reporting the
statistic least able to settle the question. Expectancy is `win_rate * R:R -
(1 - win_rate)`, and the second term is invisible in a win count.

What each win rate requires of the loss size, after MES costs:

| win rate | largest average loss, per $1 of average win | i.e. risk this much to make 1 |
| ---: | ---: | ---: |
| 65% | 0.60 | 1.7 |
| 70% | 0.49 | 2.1 |
| 75% | 0.39 | 2.6 |
| 80% | 0.30 | 3.3 |
| 85% | 0.22 | 4.5 |

The bar rises with the win rate, which is the trap. Win rates in this range
are usually produced by taking profit early and giving losers room, and the
looser the losers, the more of them the ratio has to survive. An 80% win rate
risking 4 to make 1 loses money; a 55% win rate risking 1 to make 1.5 does not.

## Tail losses dominate ruin while leaving expectancy nearly intact

The model above assumed every loss is exactly one R. Real records contain
losses that are not: the stop that gapped, the one held through a number, the
one averaged into. A win count cannot show them and an average barely can.

75% win rate at 0.5:1 (risking 2 to make 1) — genuinely profitable, +0.12R
before costs. $300 risk, one loss in ten larger than planned, 20,000 paths:

| oversized loss | expectancy | ruin (Test, EOD) | ruin (PRO, intraday) |
| --- | ---: | ---: | ---: |
| none, every stop holds | 0.08R | 8.9% | 10.4% |
| 2x planned risk | 0.06R | 26.9% | 29.1% |
| 3x planned risk | 0.03R | **52.8%** | **54.4%** |
| 5x planned risk | -0.01R | 83.6% | 84.1% |
| 8x planned risk | -0.09R | 93.6% | 93.9% |

Expectancy falls from 0.08R to 0.03R — still positive, still a system that
"works" on any average-based measure — while ruin goes from one-in-eleven to
worse than a coin flip. **Averages are nearly blind to the tail and survival
is not.** This is why the largest loss in a record is worth more scrutiny than
the win rate, and why a record with no stop discipline cannot be evaluated at
all.

## The Test-to-PRO trail switch costs less than expected

Test phase trails on the closing balance; PRO trails intraday on unrealized
equity. A record built in Test therefore overstates PRO survivability. It does
— but modestly, and it is worth saying so rather than overselling the point:

| risk/trade | ruin in Test | ruin in PRO | penalty |
| ---: | ---: | ---: | ---: |
| $100 | 0.0% | 0.0% | +0.0% |
| $300 | 9.0% | 10.8% | +1.7% |
| $500 | 26.0% | 28.9% | +2.9% |
| $750 | 39.1% | 43.7% | +4.6% |

Four points at the largest size tested. Real, worth carrying, and an order of
magnitude smaller than the tail effect above. The trail mode is not the thing
to worry about; the loss distribution is.

## Passing a $6,000 target in three sessions

Measured against a real edge rather than an assumed one: 51.9% win rate at
1.364 reward:risk, the figures from the only profitable account in a 92-trade
log. EOD trail (Test phase), $3,000 limit, 25,000 paths, capped at the number
of trades three sessions physically allow.

| NQ size | risk/trade | trades needed | pass | ruin | ran out of time |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | $337 | 78 | 46.3% | 25.3% | 28.4% |
| **8** | $505 | 52 | **54.4%** | 42.2% | 3.3% |
| 10 | $674 | 39 | 51.9% | 47.8% | 0.3% |
| 12 (cap) | $842 | 31 | 47.3% | 52.7% | 0.0% |
| 15 | $1,011 | 26 | 41.4% | 58.6% | 0.0% |

**The optimum is interior.** Below it the deadline binds — a quarter of paths
at 5 contracts simply run out of sessions before reaching the target. Above
it ruin climbs faster than the target arrives. Neither the smallest nor the
largest size is right when a deadline and a floor apply at once, which is the
one situation where "trade smaller" stops being universally correct advice.

## The stop is worth more than the size

Same edge, same 5-contract size, the only difference being whether the
measured loss tail is present — one loss in twelve at 5.4x the average, taken
from the log:

| | pass | ruin |
| --- | ---: | ---: |
| hard stop honoured, no tail | **46.3%** | 25.3% |
| tail as actually traded | **16.1%** | 75.2% |

Thirty points of pass probability, and ruin tripled. No sizing decision
anywhere in this table moves the result that far — the best size change is
worth eight points and the stop is worth thirty. **Position sizing is the
second most important decision. Honouring the stop is the first.**

## The pace assumption that undoes all of it

Every row above assumes the edge survives being traded at the frequency the
deadline demands. It measures a trader averaging 5.4 trades per session, and
the 8-contract row needs 52 trades in three sessions — seventeen a day, more
than three times the observed pace.

An edge measured on selective entries in one narrow window is not the same
edge when the trader must take three times as many to finish on schedule. The
additional trades come from outside the conditions that produced the record,
so the true pass probability is below every figure in this table by an amount
that cannot be measured from the log. Treat 54% as a ceiling that assumes
away the most likely failure.

## The evaluation and the funded account want opposite sizes

Removing a self-imposed deadline changes the problem, and measuring each
account's own tail rather than borrowing one changes the conclusion.

Separating the 92-trade log by account number gives two different traders:

| population | win | R:R | tail (share of losses) | tail size | expectancy |
| --- | ---: | ---: | ---: | ---: | ---: |
| all 92 trades | 53.3% | 0.684 | 14.0% | 3.40x | **-0.260R** |
| current account, 52 trades | 51.9% | 1.364 | 8.0% | 2.78x | **+0.159R** |

Applying the first tail to the second population, as an earlier pass here
did, understates a real change in behaviour. The loss discipline improved and
the edge is positive because of it. It is 52 trades, and at that sample the
t-statistic against breakeven is 1.39 — real, not yet established.

**Passing the evaluation** trails end-of-day, and failing costs only the fee.
Expected fees to eventually pass, counting failed attempts:

| size | pass | months per attempt | expected fees |
| --- | ---: | ---: | ---: |
| 5 MNQ | 96.0% | 8.5 | $1,506 |
| 10 MNQ | 75.3% | 4.3 | $960 |
| 5 NQ | 45.7% | 1.7 | $633 |
| 8 NQ | 38.4% | 1.1 | **$471** |

**Keeping the funded account** trails intraday, failing costs the account, and
the target repeats forever. Probability of surviving twelve $2,000 payout
cycles — one year:

| size | ruin per cycle | survives 12 cycles | income at 80% split |
| --- | ---: | ---: | ---: |
| 5 MNQ | 2.3% | **75.5%** | $564/mo |
| 10 MNQ | 13.8% | 17.1% | $1,129/mo |
| 5 NQ | 31.0% | 1.2% | $2,822/mo |
| 8 NQ | 35.6% | 0.5% | $4,516/mo |

The two tables point in opposite directions, and that is the finding. The
size that passes cheapest is the size that cannot hold the account it wins.
Optimising the evaluation for speed rehearses precisely the habit that ends
the funded account, and the evaluation's forgiving trail hides the cost until
it is charged in the phase where failure is not refundable.

**No size survives a year comfortably.** The best row is 75.5%, and it earns
$564 a month. That is the arithmetic consequence of extracting income from a
$3,000 buffer on a $100,000 notional: the buffer is 3% of the account being
traded, and a rule that repeatedly takes $2,000 out of it is drawing down two
thirds of its own risk budget every cycle. The constraint is structural, and
no entry signal changes it.

## Two gaps closed, one that would not close (2026-09-15)

Asked what would raise confidence in the sizing plan, three of five stated
gaps were attackable from the log already in hand. The results split.

**Size discipline: closed, favourably.** The concern was that position size
escalates after a loss — the mechanism behind most blown accounts, and the
one this trader's history made plausible. It does not happen here:

| after a... | average position |
| --- | ---: |
| winning trade | 4.67 contracts |
| losing trade | 4.16 contracts |
| loss over 2x average | 3.67 contracts |

Size falls after losses and falls further after bad ones. That is the
opposite of revenge sizing, and it removes the behavioural risk that made the
earlier sizing recommendation a judgement call rather than a calculation.

**Clustering: confirmed.** Session-level loss rates on the current account
vary at a standard deviation of 0.171 where independent trades predict 0.109.
Trades are not independent draws, so `ruin_probability` is optimistic.

**The fix for it did not work, and the failure is the useful part.**
`bootstrap_ruin` resamples whole sessions from the real log, which preserves
clustering exactly and assumes nothing about the distribution. Run on the
current account it returns **0.0% ruin and 100% pass at every position size**,
including sizes the parametric model puts at coin-flip odds.

That is not a discovery. The pool is seven sessions, six of them profitable,
worst one -$435. Reaching a $3,000 floor requires roughly seven consecutive
worst-sessions, probability 1.5e-06. **The resampled account is unkillable by
construction.** Widen the pool to all seventeen sessions and it returns 100%
ruin, because that pool contains the sessions that ended five real accounts.
Two pools, two impossible answers, neither an estimate of anything.

A bootstrap cannot draw a tail it has never seen. At small samples that is not
a caveat, it is the entire output. `bootstrap_ruin` now refuses a pool under
twenty sessions or one containing no losing session, because returning 0% in
those cases is worse than returning nothing.

**What this means for the sample-size problem.** The honest conclusion is that
no amount of analysis closes the gap, because the gap is missing data rather
than missing method. A record of six winning sessions out of seven is
consistent with a strong edge and with a lucky fortnight, and no resampling,
weighting or reparameterisation distinguishes them. What distinguishes them is
a losing session traded under the current discipline — which is the one
observation the record does not contain and the one that would settle it.

## The Phase 1 gate

The conclusion of the work above is that the remaining uncertainty is missing
data rather than missing method, so the deliverable is a threshold rather than
another estimate:

```bash
python research/analyze_log.py --gate --only-account <id> trades.csv
```

Seven criteria, all floors, all of which must clear. It exits non-zero on any
failure. Against the 52-trade account that prompted it:

```
  [FAIL]  sample size             52 trades              need 108 for t=2
  [FAIL]  edge established        t = 1.39               need t >= 2.00
  [PASS]  reward:risk             1.364                  need > 0.926
  [PASS]  loss tail               2.78x average          need <= 2.78x
  [PASS]  no size escalation      -0.64 after a loss     need <= 0.00
  [FAIL]  sessions                7 sessions             need 20
  [PASS]  a losing session exists 1                      cannot falsify without one
```

Two of these are worth defending because they are unusual.

**A losing session is required.** A record with none has not been tested, and
every statistic computed from it measures a market that happened to cooperate.
The gate refuses an unbroken winning record even when everything else passes —
which is the one case where a trader is most certain they are ready.

**The thresholds are code, not intentions.** The decision they gate is whether
to trade larger, and that is the decision a good run makes tempting and a bad
run makes urgent. A threshold agreed in advance and re-examined in the moment
is not a threshold. This one is a process exit code.

## Income is a purchasing decision, not a trading one (2026-09-16)

The earlier conclusion — that a $3,000 buffer produces about $564 a month and
no signal changes it — was correct about the account and wrong about the
constraint. Scale the drawdown, the per-trade risk and the payout target
together by the same factor and every survival figure is unchanged:

| k | drawdown | risk/trade | payout | ruin/cycle | survives 12 cycles | income/mo |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1.0 | $3,000 | $67 | $2,000 | 2.3% | 75.7% | $565 |
| 1.5 | $4,500 | $101 | $3,000 | 2.3% | 75.7% | $847 |
| 3.0 | $9,000 | $202 | $6,000 | 2.3% | 75.7% | $1,694 |
| 7.5 | $22,500 | $506 | $15,000 | 2.3% | 75.7% | $4,235 |

Ruin is invariant to four significant figures because nothing about the
problem changes — the floor, the position and the target all move together, so
the same paths breach and the same paths finish. **Income is linear in
deployed drawdown at fixed survival.** The ceiling is therefore set by how
much drawdown can be bought, which is a purchasing decision, and the earlier
figure was the answer for one account rather than a law about the strategy.

TPT150 carries $4,500 against a $9,000 target for $360 a month, and up to five
funded accounts may run simultaneously with a trader copying their own trades
across them. That caps deployable drawdown at $22,500 and income near $4,200 a
month at the same 75.7% annual survival.

**Funded accounts carry no monthly fee** — a one-time $130 activation — so the
recurring cost applies only while evaluating. That changes which route is
cheaper.

| route | to first income | income reached | cumulative at month 15 |
| --- | ---: | --- | ---: |
| five evaluations in parallel | $8,390 | $4,235/mo immediately | — |
| one evaluation, add from income | $1,678 | $2,541/mo by month 15 | +$6,915 |

The ramp is cash-positive by month 10 and reaches the parallel route's
drawdown without ever risking $8,390 on an edge measured over 52 trades.

## What correlated accounts actually buy

Five accounts copy-traded from one signal are not five independent bets. Their
equity curves are proportional, so their floors are proportional, and they
breach on the same trade. Combined survival equals single-account survival —
which is why income scales without survival falling, and is also the whole
risk:

```
annual survival of the operation       75.7%
probability of losing all five         24.3%
capital lost in that event             $22,500 of drawdown
```

Independent accounts would lose roughly one in five. Correlated accounts lose
five of five. The scaling result and the concentration risk are the same fact
seen from two sides, and any account of the upside that omits the second half
is selling something.

## What this does not model

Trades are independent draws with a fixed win rate and a fixed R. Real losing
streaks cluster, real traders raise size after losses, and a real edge decays.
Every one of those makes the measured ruin optimistic. Slippage, gaps through
stops, news halts, the flat-by-close requirement and platform outages are all
absent. Treat these figures as the **best case for a stated edge**, not a
forecast.

Nothing here supplies an edge. `ruin_probability` takes the win rate as an
argument because this repo has never measured one that survived deflation.
