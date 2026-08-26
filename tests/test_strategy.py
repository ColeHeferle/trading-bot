from __future__ import annotations

import pytest

from trading_bot.indicators import sma
from trading_bot.models import Signal
from trading_bot.strategy import SmaCrossover

from tests.helpers import make_candles


def signals(closes, fast=2, slow=4):
    strategy = SmaCrossover(fast_period=fast, slow_period=slow)
    return [strategy.on_candle(candle) for candle in make_candles(closes)]


class TestConstruction:
    def test_rejects_fast_period_at_or_above_slow(self):
        with pytest.raises(ValueError, match="must be less than"):
            SmaCrossover(fast_period=10, slow_period=10)

    def test_rejects_non_positive_periods(self):
        with pytest.raises(ValueError, match="positive"):
            SmaCrossover(fast_period=0, slow_period=5)


class TestSignals:
    def test_holds_until_the_slow_window_fills(self):
        assert signals([1, 2, 3, 4, 5], fast=2, slow=4)[:3] == [Signal.HOLD] * 3

    def test_first_computable_candle_never_signals(self):
        # There is no prior relationship to cross, so nothing has happened yet.
        assert signals([1, 2, 3, 4], fast=2, slow=4)[3] is Signal.HOLD

    def test_buys_when_the_fast_average_crosses_above(self):
        assert signals([10, 10, 10, 10, 20], fast=2, slow=4)[4] is Signal.BUY

    def test_sells_when_the_fast_average_crosses_back_below(self):
        result = signals([10, 10, 10, 10, 20, 20, 1, 1, 1], fast=2, slow=4)
        buy_at = result.index(Signal.BUY)
        assert result[buy_at + 1 :].count(Signal.SELL) == 1

    def test_a_sustained_trend_signals_once(self):
        result = signals([10, 10, 10, 10, *range(11, 40)], fast=2, slow=4)
        assert result.count(Signal.BUY) == 1
        assert result.count(Signal.SELL) == 0

    def test_a_flat_market_never_trades(self):
        assert set(signals([25.0] * 50, fast=5, slow=20)) == {Signal.HOLD}

    def test_reset_clears_accumulated_history(self):
        strategy = SmaCrossover(fast_period=2, slow_period=4)
        for candle in make_candles([10, 10, 10, 10, 20]):
            strategy.on_candle(candle)

        strategy.reset()
        replayed = [strategy.on_candle(c) for c in make_candles([1, 2, 3])]
        assert replayed == [Signal.HOLD] * 3


def reference_signals(closes, fast, slow):
    """Signals recomputed the slow, obvious way, for the running sums to match."""
    fast_avgs, slow_avgs = sma(closes, fast), sma(closes, slow)
    out, was_above = [], None
    for f, s in zip(fast_avgs, slow_avgs):
        if f is None or s is None:
            out.append(Signal.HOLD)
            continue
        is_above = f > s
        if was_above is None or was_above == is_above:
            out.append(Signal.HOLD)
        else:
            out.append(Signal.BUY if is_above else Signal.SELL)
        was_above = is_above
    return out


class TestRollingWindow:
    @pytest.mark.parametrize(
        "closes",
        [
            [10, 12, 11, 15, 14, 9, 8, 13, 20, 21, 19, 7, 6, 11, 14],
            [5, 5, 5, 6, 7, 6, 5, 4, 5, 6, 7, 8, 7, 6, 5],
            [100, 90, 95, 85, 88, 80, 92, 105, 99, 110, 120, 118],
        ],
    )
    def test_running_sums_match_a_naive_recomputation(self, closes):
        assert signals(closes, fast=3, slow=5) == reference_signals(closes, 3, 5)
