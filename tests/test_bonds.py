from __future__ import annotations

import pytest

from trading_bot.bonds import modified_duration, par_bond_returns, total_return_index


class TestModifiedDuration:
    def test_matches_the_textbook_ten_year_par_bond(self):
        # A 10-year par bond at 5% has a modified duration of about 7.72 years.
        assert modified_duration(0.05, 10) == pytest.approx(7.7217, abs=1e-3)

    def test_is_shorter_than_the_bond_itself(self):
        assert modified_duration(0.04, 10) < 10

    def test_longer_maturity_carries_more_duration(self):
        assert modified_duration(0.04, 30) > modified_duration(0.04, 10)

    def test_higher_yields_shorten_duration(self):
        assert modified_duration(0.10, 10) < modified_duration(0.02, 10)

    def test_zero_yield_falls_back_to_the_maturity(self):
        # Undiscounted cash flows, so the closed form's division by y is skipped.
        assert modified_duration(0.0, 10) == pytest.approx(10.0)

    def test_rejects_non_positive_maturity(self):
        with pytest.raises(ValueError, match="maturity_years must be positive"):
            modified_duration(0.05, 0)


class TestParBondReturns:
    def test_one_fewer_return_than_observations(self):
        assert len(par_bond_returns([0.03, 0.03, 0.03], periods_per_year=12)) == 2

    def test_unchanged_yields_earn_pure_carry(self):
        returns = par_bond_returns([0.06, 0.06, 0.06], periods_per_year=12)
        assert all(r == pytest.approx(0.005) for r in returns)

    def test_rising_yields_cost_money(self):
        # A 50bp rise on ~7.7 years of duration is a ~3.9% capital loss.
        [ret] = par_bond_returns([0.05, 0.055], periods_per_year=12)
        assert ret < 0
        assert ret == pytest.approx(0.05 / 12 - 7.7217 * 0.005, abs=1e-4)

    def test_falling_yields_beat_carry(self):
        [ret] = par_bond_returns([0.05, 0.045], periods_per_year=12)
        assert ret > 0.05 / 12

    def test_longer_maturities_swing_harder_on_the_same_move(self):
        short = par_bond_returns([0.04, 0.045], maturity_years=2)[0]
        long = par_bond_returns([0.04, 0.045], maturity_years=30)[0]
        assert long < short < 0

    def test_annual_steps_earn_a_full_year_of_carry(self):
        [ret] = par_bond_returns([0.04, 0.04], periods_per_year=1)
        assert ret == pytest.approx(0.04)

    def test_too_short_a_series_has_no_returns(self):
        assert par_bond_returns([0.03]) == []
        assert par_bond_returns([]) == []

    def test_rejects_non_positive_frequency(self):
        with pytest.raises(ValueError, match="periods_per_year must be positive"):
            par_bond_returns([0.03, 0.03], periods_per_year=0)


class TestTotalReturnIndex:
    def test_starts_at_the_given_level(self):
        assert total_return_index([0.03, 0.03], start=100.0)[0] == 100.0

    def test_is_the_same_length_as_the_yield_series(self):
        yields = [0.03, 0.031, 0.029, 0.032]
        assert len(total_return_index(yields)) == len(yields)

    def test_flat_yields_compound_the_carry(self):
        index = total_return_index([0.03] * 13, periods_per_year=12)
        assert index[-1] == pytest.approx(100.0 * 1.0025**12, rel=1e-9)

    def test_a_sustained_selloff_loses_money(self):
        # Yields marching from 2% to 6% over a year: duration losses swamp carry.
        yields = [0.02 + 0.04 * i / 12 for i in range(13)]
        assert total_return_index(yields, periods_per_year=12)[-1] < 100.0

    def test_a_rally_makes_money(self):
        yields = [0.06 - 0.04 * i / 12 for i in range(13)]
        assert total_return_index(yields, periods_per_year=12)[-1] > 100.0

    def test_a_single_observation_is_just_the_start(self):
        assert total_return_index([0.03]) == [100.0]

    def test_rejects_non_positive_start(self):
        with pytest.raises(ValueError, match="start must be positive"):
            total_return_index([0.03, 0.03], start=0.0)


class TestAgainstExactRepricing:
    def test_duration_approximation_tracks_exact_par_bond_pricing(self):
        """The index uses duration rather than repricing the bond exactly.

        Check the shortcut against a full discounted-cash-flow reprice for a
        one-year step, where the fractional-period complications vanish.
        """

        def price(coupon_rate: float, yield_: float, years: int) -> float:
            coupon = 100.0 * coupon_rate
            pv = sum(coupon / (1 + yield_) ** t for t in range(1, years + 1))
            return pv + 100.0 / (1 + yield_) ** years

        start_yield, end_yield, maturity = 0.05, 0.055, 10
        # Hold a 10y par bond for a year, then mark the 9 years that remain.
        exact = (price(start_yield, end_yield, maturity - 1) + 100.0 * start_yield) / 100.0 - 1.0
        approx = par_bond_returns(
            [start_yield, end_yield], maturity_years=maturity, periods_per_year=1
        )[0]

        # Within 60bp on a 50bp move: convexity and the shortening maturity are
        # the whole gap, and both are second order for the monthly steps used.
        assert approx == pytest.approx(exact, abs=0.006)
