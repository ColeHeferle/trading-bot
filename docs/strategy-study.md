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
