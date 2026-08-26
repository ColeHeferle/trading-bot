from __future__ import annotations

import pytest

from trading_bot.indicators import ema, rsi, sma


class TestSma:
    def test_leading_values_are_none_until_the_window_fills(self):
        assert sma([1, 2, 3, 4], 3)[:2] == [None, None]

    def test_averages_the_trailing_window(self):
        assert sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]

    def test_window_slides_rather_than_accumulating(self):
        # A jump only affects the periods it is actually inside of.
        assert sma([10, 10, 10, 100], 2) == [None, 10.0, 10.0, 55.0]

    def test_result_is_aligned_with_the_input(self):
        values = [1.5, 2.5, 3.5, 4.5, 5.5, 6.5]
        assert len(sma(values, 4)) == len(values)

    def test_period_of_one_returns_the_series(self):
        assert sma([3, 1, 4], 1) == [3.0, 1.0, 4.0]

    def test_period_longer_than_the_series_yields_no_values(self):
        assert sma([1, 2], 5) == [None, None]

    def test_rejects_non_positive_period(self):
        with pytest.raises(ValueError, match="period must be positive"):
            sma([1, 2, 3], 0)


class TestEma:
    def test_seeds_from_the_simple_average(self):
        assert ema([2, 4, 6], 3)[2] == pytest.approx(4.0)

    def test_weights_recent_values_more_heavily_than_sma(self):
        closes = [10, 10, 10, 20]
        fast = ema(closes, 3)[-1]
        slow = sma(closes, 3)[-1]
        assert fast > slow

    def test_converges_on_a_flat_series(self):
        assert ema([5] * 10, 4)[-1] == pytest.approx(5.0)

    def test_rejects_non_positive_period(self):
        with pytest.raises(ValueError, match="period must be positive"):
            ema([1, 2, 3], -1)


class TestRsi:
    def test_is_none_until_a_full_period_of_changes_exists(self):
        values = list(range(10))
        assert rsi(values, 5)[:5] == [None] * 5
        assert rsi(values, 5)[5] is not None

    def test_unbroken_gains_pin_it_at_one_hundred(self):
        assert rsi(list(range(20)), 14)[-1] == pytest.approx(100.0)

    def test_unbroken_losses_pin_it_at_zero(self):
        assert rsi(list(range(20, 0, -1)), 14)[-1] == pytest.approx(0.0)

    def test_alternating_moves_of_equal_size_stay_near_the_midpoint(self):
        # Wilder's smoothing leans toward whichever move landed last, so this
        # oscillates around 50 rather than settling exactly on it.
        values = [10 + (i % 2) for i in range(40)]
        assert rsi(values, 14)[-1] == pytest.approx(50.0, abs=5.0)

    def test_stays_within_bounds(self):
        values = [10, 12, 11, 15, 14, 20, 18, 25, 19, 30, 22, 21, 26, 24, 31, 28]
        assert all(0.0 <= value <= 100.0 for value in rsi(values, 5) if value is not None)

    def test_short_series_returns_all_none(self):
        assert rsi([1, 2, 3], 14) == [None, None, None]
