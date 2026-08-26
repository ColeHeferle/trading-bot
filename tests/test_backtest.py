from __future__ import annotations

import pytest

from trading_bot.backtest import run_backtest
from trading_bot.models import Side
from trading_bot.portfolio import Portfolio
from trading_bot.strategy import SmaCrossover

from tests.helpers import make_candles

# Flat, a steady rally, then a decline that rolls the averages over: with a 2/4
# crossover this enters at 12 and exits at 20, so the round trip is profitable.
ROUND_TRIP = [10, 10, 10, 10, 12, 14, 16, 18, 20, 22, 24, 23, 20, 17, 14]

# A rally that gaps away before the averages can cross back: the exit lands
# below the entry.
CRASH = [10, 10, 10, 10, 20, 30, 40, 5, 4, 3, 3, 3]


def backtest(closes, fast=2, slow=4, **kwargs):
    return run_backtest(
        make_candles(closes), SmaCrossover(fast, slow), symbol="BTC", **kwargs
    )


class TestExecution:
    def test_trades_a_full_round_trip(self):
        result = backtest(ROUND_TRIP)
        sides = [fill.side for fill in result.fills]

        assert sides == [Side.BUY, Side.SELL]

    def test_fills_at_the_close_of_the_signalling_candle(self):
        result = backtest(ROUND_TRIP)
        candles = {c.timestamp: c for c in make_candles(ROUND_TRIP)}

        for fill in result.fills:
            assert fill.price == candles[fill.timestamp].close

    def test_ends_flat_after_a_sell(self):
        result = backtest(ROUND_TRIP)
        assert result.portfolio.quantity("BTC") == 0.0

    def test_never_buys_twice_without_selling(self):
        result = backtest([10, 10, 10, 10, *range(11, 40)])
        assert [f.side for f in result.fills] == [Side.BUY]

    def test_a_flat_market_never_trades(self):
        result = backtest([50.0] * 40, fast=5, slow=20)

        assert result.fills == []
        assert result.final_equity == pytest.approx(result.portfolio.initial_cash)
        assert result.total_return == pytest.approx(0.0)

    def test_fixed_quantity_sizing_is_respected(self):
        result = backtest(ROUND_TRIP, quantity=1.5, portfolio=Portfolio(cash=10_000.0))
        assert all(fill.quantity == pytest.approx(1.5) for fill in result.fills)

    def test_default_sizing_commits_the_whole_balance(self):
        result = backtest(ROUND_TRIP, portfolio=Portfolio(cash=1000.0))
        entry = result.fills[0]
        equity_at_entry = dict(result.equity_curve)[entry.timestamp]

        assert entry.notional == pytest.approx(1000.0)
        assert equity_at_entry == pytest.approx(1000.0)

    def test_default_sizing_leaves_room_for_fees(self):
        # The order must fit inside cash including its fee, not just its notional.
        result = backtest(ROUND_TRIP, portfolio=Portfolio(cash=1000.0, fee_rate=0.005))
        entry = result.fills[0]

        assert entry.notional + entry.fee == pytest.approx(1000.0)
        assert result.portfolio.cash >= 0.0


class TestResults:
    def test_equity_curve_has_one_point_per_candle(self):
        result = backtest(ROUND_TRIP)
        assert len(result.equity_curve) == len(ROUND_TRIP)

    def test_equity_starts_at_the_opening_balance(self):
        result = backtest(ROUND_TRIP, portfolio=Portfolio(cash=5000.0))
        assert result.equity_curve[0][1] == pytest.approx(5000.0)

    def test_a_profitable_round_trip_grows_equity(self):
        result = backtest(ROUND_TRIP, portfolio=Portfolio(cash=1000.0))

        assert result.final_equity > 1000.0
        assert result.total_return > 0.0
        assert result.portfolio.realized_pnl > 0.0

    def test_buying_before_a_crash_loses_money(self):
        result = backtest(CRASH, portfolio=Portfolio(cash=1000.0))

        assert result.total_return < 0.0
        assert result.portfolio.realized_pnl < 0.0

    def test_max_drawdown_measures_the_worst_peak_to_trough(self):
        result = backtest(ROUND_TRIP, portfolio=Portfolio(cash=1000.0))

        worst, peak = 0.0, float("-inf")
        for _, equity in result.equity_curve:
            peak = max(peak, equity)
            worst = max(worst, 1.0 - equity / peak)

        assert result.max_drawdown == pytest.approx(worst)
        assert 0.0 < result.max_drawdown < 1.0

    def test_max_drawdown_is_zero_when_equity_only_rises(self):
        result = backtest([10, 10, 10, 10, *range(11, 40)])
        assert result.max_drawdown == pytest.approx(0.0)

    def test_fees_drag_on_returns(self):
        free = backtest(ROUND_TRIP, portfolio=Portfolio(cash=1000.0))
        costly = backtest(ROUND_TRIP, portfolio=Portfolio(cash=1000.0, fee_rate=0.01))

        assert costly.total_return < free.total_return

    def test_empty_input_produces_an_empty_result(self):
        result = run_backtest([], SmaCrossover(2, 4), symbol="BTC")

        assert result.equity_curve == []
        assert result.fills == []
        assert result.final_equity == pytest.approx(result.portfolio.initial_cash)
        assert result.max_drawdown == 0.0
