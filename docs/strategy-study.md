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

## Buy-and-hold: yes, clearly

| 1999–2018 | CAGR | Sharpe | max DD |
| --- | ---: | ---: | ---: |
| sp500 alone | 3.63% | 0.28 | 56.8% |
| nasdaq alone | 5.66% | 0.34 | 77.9% |
| wti alone | 6.67% | 0.36 | 82.0% |
| **equal-weight basket** | **7.24%** | **0.45** | 58.4% |

The basket beat **every one of its own constituents** on both return and
Sharpe. That is not a rounding artifact: rebalancing back to equal weight sells
whatever ran up and buys whatever lagged, and across three imperfectly
correlated markets that harvesting is worth more than the cash drag of the
rebalance band. Drawdown lands between the best and worst leg rather than below
both — diversification smooths the path, it does not abolish the 2008 problem
when everything falls together.

## Trend following: no, not with this universe

| 1999–2018 | CAGR | Sharpe | max DD | trades |
| --- | ---: | ---: | ---: | ---: |
| sp500 alone, SMA 50/200 | 5.58% | **0.53** | **20.6%** | 18 |
| basket of three, SMA 50/200 | 5.93% | 0.52 | 24.3% | 66 |
| **sp500+nasdaq, SMA 50/200** | 5.77% | **0.54** | **19.9%** | 40 |

Adding crude to the trend basket bought nothing: the three-market basket is no
better than the S&P alone, because `SmaCrossover(50, 200)` on WTI is a poor
strategy in its own right (0.32 Sharpe, 55% drawdown) and equal weighting hands
it a third of the capital regardless. Drop it and the equity pair edges ahead of
either leg on its own.

**A basket is not automatically better than its best member.** It is better than
its *average* member, which is only useful if the members are individually
sound. Diversification dilutes a bad strategy into a portfolio; it does not fix
it.

## The costs that scale with breadth

Turnover multiplies with the universe: `PriceVsSma(200)` across three markets
trades 468 times against 148 on the S&P alone, and its 3.42% CAGR is the worst
trend result here. Every symbol pays the band's rebalancing on top of its own
entries and exits.

## What this does not show

Three markets, two of them equity indices that fell together in 2000 and 2008,
is a thin universe — real trend-following programmes run dozens of markets
across equities, bonds, currencies and commodities, and that breadth is most of
where their diversification comes from. This study is evidence about *these*
three series, not a verdict on multi-asset trend following.
