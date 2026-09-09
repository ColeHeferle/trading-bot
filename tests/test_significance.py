"""The deflated Sharpe ratio, checked against simulation rather than algebra.

A significance test that is merely plausible is worse than none, because it
launders a guess into a number. Every claim here is verified by generating
strategies with a known edge (usually none) and counting how often the test is
fooled.
"""

from __future__ import annotations

import math
import random
import statistics

import pytest

from trading_bot.significance import (
    autocorrelation,
    deflated_sharpe,
    expected_max_sharpe,
    moments,
    probabilistic_sharpe,
    smoothness,
)


def sharpe_of(returns: list[float]) -> float:
    mean, sd, _, _ = moments(returns)
    return mean / sd if sd else 0.0


def noise(n: int, rng: random.Random, edge: float = 0.0) -> list[float]:
    return [rng.gauss(edge, 1.0) for _ in range(n)]


class TestMoments:
    def test_normal_kurtosis_is_three_not_zero(self):
        """The formula expects raw kurtosis; the other convention shifts it."""
        rng = random.Random(3)
        _, _, skew, kurt = moments(noise(20_000, rng))
        assert abs(skew) < 0.1
        assert 2.85 < kurt < 3.15

    def test_a_constant_series_has_no_shape(self):
        mean, sd, skew, kurt = moments([2.0] * 10)
        assert (mean, sd, skew, kurt) == (2.0, 0.0, 0.0, 3.0)

    def test_skew_has_the_expected_sign(self):
        rng = random.Random(4)
        # Squared normals are right-skewed.
        _, _, skew, _ = moments([rng.gauss(0, 1) ** 2 for _ in range(20_000)])
        assert skew > 1.0

    def test_needs_two_points(self):
        with pytest.raises(ValueError):
            moments([1.0])


class TestExpectedMaxSharpe:
    def test_one_trial_clears_no_bar(self):
        assert expected_max_sharpe(1, 0.5) == 0.0

    def test_identical_strategies_clear_no_bar(self):
        """Zero spread means the search explored nothing."""
        assert expected_max_sharpe(500, 0.0) == 0.0

    def test_the_bar_rises_with_the_number_tried(self):
        bars = [expected_max_sharpe(n, 0.1) for n in (2, 10, 100, 1000)]
        assert bars == sorted(bars)

    def test_it_predicts_the_simulated_maximum(self):
        """The claim that matters: this is what worthless strategies reach."""
        rng = random.Random(21)
        for trials in (10, 50, 200):
            gaps = []
            for _ in range(120):
                sharpes = [sharpe_of(noise(240, rng)) for _ in range(trials)]
                predicted = expected_max_sharpe(
                    trials, statistics.pstdev(sharpes)
                )
                gaps.append(max(sharpes) - predicted)
            assert abs(sum(gaps) / len(gaps)) < 0.02

    def test_rejects_nonsense_arguments(self):
        with pytest.raises(ValueError):
            expected_max_sharpe(0, 0.1)
        with pytest.raises(ValueError):
            expected_max_sharpe(10, -0.1)


class TestProbabilisticSharpe:
    def test_zero_sharpe_is_a_coin_flip(self):
        assert probabilistic_sharpe(0.0, 100) == pytest.approx(0.5)

    def test_confidence_grows_with_the_sample(self):
        short = probabilistic_sharpe(0.1, 50)
        long = probabilistic_sharpe(0.1, 500)
        assert 0.5 < short < long

    def test_negative_skew_costs_confidence(self):
        """Grinding gains with rare large losses should be trusted less."""
        symmetric = probabilistic_sharpe(0.2, 200, skew=0.0)
        crash_prone = probabilistic_sharpe(0.2, 200, skew=-1.5)
        assert crash_prone < symmetric

    def test_fat_tails_cost_confidence(self):
        thin = probabilistic_sharpe(0.2, 200, kurtosis=3.0)
        fat = probabilistic_sharpe(0.2, 200, kurtosis=12.0)
        assert fat < thin

    def test_refuses_when_the_correction_breaks_down(self):
        with pytest.raises(ValueError, match="non-positive"):
            probabilistic_sharpe(5.0, 200, skew=3.0, kurtosis=3.0)


class TestDeflatedSharpe:
    def test_it_rejects_the_best_of_a_worthless_search(self):
        """The headline claim, and the reason the module exists.

        Fifty strategies with no edge at all. The naive test is fooled by the
        winner most of the time; the deflated one must not be.
        """
        rng = random.Random(7)
        naive_hits = deflated_hits = 0
        rounds = 150
        for _ in range(rounds):
            strategies = [noise(240, rng) for _ in range(50)]
            sharpes = [sharpe_of(s) for s in strategies]
            best = max(range(50), key=lambda i: sharpes[i])
            spread = statistics.pstdev(sharpes)
            if probabilistic_sharpe(sharpes[best], 240) > 0.95:
                naive_hits += 1
            if deflated_sharpe(sharpes[best], strategies[best], 50, spread) > 0.95:
                deflated_hits += 1
        assert naive_hits / rounds > 0.5, "the naive test should be badly fooled"
        assert deflated_hits / rounds < 0.05, "the deflated test must not be"

    def test_a_large_genuine_edge_still_gets_through(self):
        """A test that never says yes would be useless."""
        rng = random.Random(13)
        hits = 0
        rounds = 60
        for _ in range(rounds):
            strategies = [noise(240, rng) for _ in range(49)]
            strategies.append(noise(240, rng, edge=0.35))
            sharpes = [sharpe_of(s) for s in strategies]
            best = max(range(50), key=lambda i: sharpes[i])
            spread = statistics.pstdev(sharpes)
            if deflated_sharpe(sharpes[best], strategies[best], 50, spread) > 0.95:
                hits += 1
        assert hits / rounds > 0.5

    def test_searching_harder_makes_the_same_result_mean_less(self):
        rng = random.Random(17)
        returns = noise(240, rng, edge=0.15)
        sharpe = sharpe_of(returns)
        few = deflated_sharpe(sharpe, returns, 5, 0.08)
        many = deflated_sharpe(sharpe, returns, 5_000, 0.08)
        assert many < few

    def test_a_single_pre_registered_trial_is_not_penalised(self):
        rng = random.Random(19)
        returns = noise(240, rng, edge=0.15)
        sharpe = sharpe_of(returns)
        _, _, skew, kurt = moments(returns)
        assert deflated_sharpe(sharpe, returns, 1, 0.08) == pytest.approx(
            probabilistic_sharpe(sharpe, 240, skew=skew, kurtosis=kurt)
        )


def test_twenty_years_of_monthly_data_cannot_resolve_a_realistic_edge():
    """Why the equity search was doomed, as a test rather than a claim.

    A Sharpe near 0.5 a year is what good systematic strategies actually earn.
    Over 240 monthly bars, after searching 50 rules, it is almost never
    detectable — so a search of that shape cannot answer the question, whatever
    it returns. The failure is in the sample size, not the test.
    """
    rng = random.Random(23)
    monthly_edge = 0.5 / math.sqrt(12)
    hits = 0
    rounds = 60
    for _ in range(rounds):
        strategies = [noise(240, rng) for _ in range(49)]
        strategies.append(noise(240, rng, edge=monthly_edge))
        sharpes = [sharpe_of(s) for s in strategies]
        best = max(range(50), key=lambda i: sharpes[i])
        spread = statistics.pstdev(sharpes)
        if deflated_sharpe(sharpes[best], strategies[best], 50, spread) > 0.95:
            hits += 1
    assert hits / rounds < 0.25


class TestSmoothness:
    """Telling averaged data apart from genuine persistence.

    This exists because it caught a false result in this repo. Trend rules
    scored 1.2-1.3 Sharpe on bond indices built from published yields, and the
    edge was the vendor's monthly averaging rather than the market's.
    """

    def test_white_noise_is_not_flagged(self):
        rng = random.Random(31)
        assert not smoothness(noise(1200, rng)).suspicious

    def test_averaged_data_is_flagged(self):
        """A two-period mean of noise: lag-1 lifts, lag-2 stays at zero."""
        rng = random.Random(33)
        raw = noise(1200, rng)
        averaged = [(raw[i] + raw[i - 1]) / 2 for i in range(1, len(raw))]
        check = smoothness(averaged)
        assert check.suspicious
        assert check.lag1 > 0.4
        assert abs(check.lag2) < 0.1

    def test_genuine_persistence_is_not_flagged(self):
        """The distinction that makes this useful rather than a noise alarm.

        An AR(1) series has real, tradeable momentum and a large lag-1. It must
        not be confused with an averaging artifact, or the check would condemn
        exactly the series worth trading.
        """
        rng = random.Random(37)
        rho, value, series = 0.5, 0.0, []
        for _ in range(4000):
            value = rho * value + rng.gauss(0, 1)
            series.append(value)
        check = smoothness(series)
        assert check.lag1 > 0.4, "the AR(1) should show strong lag-1"
        assert not check.suspicious, "but it is real persistence, not smoothing"
        assert check.lag2 > 0.15, "which decays geometrically rather than to zero"

    def test_it_reproduces_the_finding_that_prompted_it(self):
        """The exact mechanism behind the false bond result.

        Yields behave roughly like a random walk. Published monthly yield
        series are the *mean* of the month's business days, and averaging a
        random walk over non-overlapping blocks induces about +0.25 serial
        correlation in the changes (Working, 1960) where the month-end
        observation would show none. The real data showed +0.31 to +0.33.
        """
        rng = random.Random(41)
        days, months = 21, 900
        level, daily = 0.0, []
        for _ in range(days * months):
            level += rng.gauss(0, 1)
            daily.append(level)

        month_end = [daily[i] for i in range(days - 1, len(daily), days)]
        observed = [
            month_end[i] - month_end[i - 1] for i in range(1, len(month_end))
        ]
        assert not smoothness(observed).suspicious, (
            "the same market, observed rather than averaged, is clean"
        )

        month_avg = [
            sum(daily[i:i + days]) / days
            for i in range(0, len(daily) - days + 1, days)
        ]
        published = [
            month_avg[i] - month_avg[i - 1] for i in range(1, len(month_avg))
        ]
        check = smoothness(published)
        assert check.suspicious
        assert 0.15 < check.lag1 < 0.40, "Working's coefficient, near +0.25"

    def test_autocorrelation_rejects_nonsense(self):
        with pytest.raises(ValueError):
            autocorrelation([0.1, 0.2, 0.3], lag=0)
        with pytest.raises(ValueError):
            autocorrelation([0.1, 0.2], lag=2)

    def test_a_constant_series_has_no_autocorrelation(self):
        assert autocorrelation([1.0] * 50) == 0.0

    def test_describe_names_the_problem(self):
        rng = random.Random(43)
        raw = noise(1200, rng)
        averaged = [(raw[i] + raw[i - 1]) / 2 for i in range(1, len(raw))]
        assert "averaged rather than observed" in smoothness(averaged).describe()
        assert "no averaging signature" in smoothness(noise(1200, rng)).describe()
