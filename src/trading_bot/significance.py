"""Whether a backtest result survives the search that produced it.

The Sharpe ratio of the best strategy out of many is not evidence about that
strategy. It is mostly evidence about how many were tried. Test enough rules on
one price series and something will look excellent, and the more thorough the
search, the more certain that is.

This module makes that cost explicit. `expected_max_sharpe` says what the best
of N *worthless* strategies scores by luck alone; `deflated_sharpe` asks whether
an observed Sharpe beats that bar, correcting also for the short samples and
fat, skewed return distributions that flatter the usual t-test.

Follows Bailey and Lopez de Prado, "The Deflated Sharpe Ratio" (2014). Ratios
here are per-period — deflate the raw Sharpe before annualizing, since the
correction is about the number of observations, not the calendar.
"""

from __future__ import annotations

import math
from statistics import NormalDist

__all__ = [
    "expected_max_sharpe",
    "probabilistic_sharpe",
    "deflated_sharpe",
    "moments",
]

_NORMAL = NormalDist()
_EULER = 0.5772156649015329  # Euler-Mascheroni


def moments(returns: list[float]) -> tuple[float, float, float, float]:
    """Mean, standard deviation, skewness and kurtosis of `returns`.

    Kurtosis is the raw fourth standardized moment: 3.0 for a normal
    distribution, not 0.0. That is the convention the deflation formula below
    expects, and mixing the two conventions silently shifts the answer.
    """
    n = len(returns)
    if n < 2:
        raise ValueError("need at least two returns")
    mean = sum(returns) / n
    deviations = [r - mean for r in returns]
    variance = sum(d * d for d in deviations) / n
    if variance <= 0:
        # A constant series has no risk, so no Sharpe and no shape.
        return mean, 0.0, 0.0, 3.0
    sd = math.sqrt(variance)
    skew = sum(d ** 3 for d in deviations) / (n * sd ** 3)
    kurt = sum(d ** 4 for d in deviations) / (n * sd ** 4)
    return mean, sd, skew, kurt


def expected_max_sharpe(trials: int, sharpe_sd: float) -> float:
    """The Sharpe the best of `trials` worthless strategies reaches by luck.

    `sharpe_sd` is the spread of Sharpes *across the strategies tried* — a
    search over near-identical rules has a small spread and a low bar, one over
    genuinely different rules a wider spread and a higher bar. This is the
    number to beat before a result means anything.
    """
    if trials < 1:
        raise ValueError("trials must be at least 1")
    if sharpe_sd < 0:
        raise ValueError("sharpe_sd must not be negative")
    if trials == 1 or sharpe_sd == 0:
        return 0.0
    # Expected maximum of `trials` standard normals, to the usual two terms.
    first = _NORMAL.inv_cdf(1 - 1 / trials)
    second = _NORMAL.inv_cdf(1 - 1 / (trials * math.e))
    return sharpe_sd * ((1 - _EULER) * first + _EULER * second)


def probabilistic_sharpe(
    sharpe: float,
    n_obs: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    benchmark: float = 0.0,
) -> float:
    """Probability the true Sharpe exceeds `benchmark`, given the sample.

    Corrects the usual t-test for the two ways return distributions break it:
    negative skew and fat tails both make a given Sharpe less trustworthy than
    the normal case implies. A strategy that grinds out small gains and
    occasionally loses badly is exactly the shape that flatters a naive Sharpe.
    """
    if n_obs < 2:
        raise ValueError("need at least two observations")
    denominator = 1 - skew * sharpe + (kurtosis - 1) / 4 * sharpe ** 2
    if denominator <= 0:
        # The correction has broken down; refuse rather than return a number
        # that looks like a probability.
        raise ValueError(
            f"the skew/kurtosis correction is non-positive ({denominator:.4f}); "
            "the sample is too extreme for this approximation"
        )
    z = (sharpe - benchmark) * math.sqrt(n_obs - 1) / math.sqrt(denominator)
    return _NORMAL.cdf(z)


def deflated_sharpe(
    sharpe: float,
    returns: list[float],
    trials: int,
    sharpe_sd: float,
) -> float:
    """Probability `sharpe` is real, given that `trials` strategies were tried.

    Below about 0.95 the result is not distinguishable from the best of a
    search. A strategy scoring 0.5 here is a coin flip dressed as a discovery.
    """
    _, _, skew, kurt = moments(returns)
    bar = expected_max_sharpe(trials, sharpe_sd)
    return probabilistic_sharpe(
        sharpe, len(returns), skew=skew, kurtosis=kurt, benchmark=bar
    )
