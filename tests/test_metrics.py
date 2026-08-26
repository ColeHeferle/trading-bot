from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from trading_bot.backtest import run_backtest
from trading_bot.models import Candle
from trading_bot.portfolio import Portfolio
from trading_bot.strategy import BuyAndHold, SmaCrossover

from tests.helpers import make_candles


def held_through(closes, days_per_candle=1):
    """Buy-and-hold over `closes`, so equity tracks price exactly."""
    start = datetime(2020, 1, 1)
    candles = [
        Candle(start + timedelta(days=i * days_per_candle), c, c, c, c)
        for i, c in enumerate(closes)
    ]
    return run_backtest(candles, BuyAndHold(), symbol="X", portfolio=Portfolio(1000.0))


class TestReturns:
    def test_one_entry_per_candle_after_the_first(self):
        result = held_through([10, 11, 12, 13])
        assert len(result.returns) == 3

    def test_tracks_the_price_path_when_fully_invested(self):
        result = held_through([10, 20])
        assert result.returns == [pytest.approx(1.0)]

    def test_empty_backtest_has_no_returns(self):
        assert run_backtest([], BuyAndHold(), symbol="X").returns == []


class TestCagr:
    def test_doubling_over_one_year_is_one_hundred_percent(self):
        # 366 daily candles spanning exactly one year.
        closes = [100.0 + 100.0 * i / 365 for i in range(366)]
        result = held_through(closes)
        assert result.cagr == pytest.approx(1.0, abs=0.02)

    def test_doubling_over_two_years_is_the_compounded_rate(self):
        closes = [100.0 + 100.0 * i / 730 for i in range(731)]
        result = held_through(closes)
        assert result.cagr == pytest.approx(math.sqrt(2.0) - 1.0, abs=0.02)

    def test_flat_equity_has_no_growth(self):
        assert held_through([50.0] * 400).cagr == pytest.approx(0.0, abs=1e-9)

    def test_too_short_to_annualize_returns_zero(self):
        assert run_backtest([], BuyAndHold(), symbol="X").cagr == 0.0
        assert held_through([10]).cagr == 0.0


def wobbly(drift: float, wobble: float = 0.02, n: int = 250) -> list[float]:
    """A drifting series with genuine variance — a smooth curve makes Sharpe
    a division by float noise rather than a meaningful ratio."""
    return [
        100 * (1 + drift) ** i * (1 + wobble * math.sin(i * 1.7)) for i in range(n)
    ]


class TestSharpe:
    def test_zero_when_equity_never_moves(self):
        assert held_through([25.0] * 50).sharpe == 0.0

    def test_positive_for_a_rising_curve(self):
        assert held_through(wobbly(0.001)).sharpe > 0

    def test_negative_for_a_falling_curve(self):
        assert held_through(wobbly(-0.001)).sharpe < 0

    def test_steadier_gains_score_higher_than_choppy_ones(self):
        steady = held_through(wobbly(0.001, wobble=0.005))
        choppy = held_through(wobbly(0.001, wobble=0.05))
        assert steady.sharpe > choppy.sharpe

    def test_annualization_follows_periods_per_year(self):
        candles = make_candles(wobbly(0.001))
        daily = run_backtest(candles, BuyAndHold(), symbol="X")
        monthly = run_backtest(
            candles, BuyAndHold(), symbol="X", periods_per_year=12
        )
        assert daily.sharpe == pytest.approx(monthly.sharpe * math.sqrt(252 / 12))

    def test_too_short_to_measure_returns_zero(self):
        assert held_through([10, 11]).sharpe == 0.0


class TestExposure:
    def test_buy_and_hold_is_invested_from_the_first_candle(self):
        assert held_through([10, 11, 12, 13]).exposure == pytest.approx(1.0)

    def test_a_strategy_that_never_trades_has_no_exposure(self):
        result = run_backtest(
            make_candles([10.0] * 50), SmaCrossover(2, 4), symbol="X"
        )
        assert result.fills == []
        assert result.exposure == pytest.approx(0.0)

    def test_partial_exposure_counts_only_the_held_candles(self):
        # Flat for 4 candles, enters on the 5th, holds to the end.
        result = run_backtest(
            make_candles([10, 10, 10, 10, 20, 30]), SmaCrossover(2, 4), symbol="X"
        )
        assert result.exposure == pytest.approx(2 / 6)

    def test_empty_backtest_has_no_exposure(self):
        assert run_backtest([], BuyAndHold(), symbol="X").exposure == 0.0
