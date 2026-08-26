from __future__ import annotations

import pytest

from trading_bot.models import Signal
from trading_bot.strategy import BuyAndHold, PriceVsSma, TimeSeriesMomentum

from tests.helpers import make_candles


def run(strategy, closes):
    return [strategy.on_candle(candle) for candle in make_candles(closes)]


class TestBuyAndHold:
    def test_buys_once_on_the_first_candle(self):
        assert run(BuyAndHold(), [10, 20, 5, 30]) == [
            Signal.BUY,
            Signal.HOLD,
            Signal.HOLD,
            Signal.HOLD,
        ]

    def test_never_sells_however_far_price_falls(self):
        assert Signal.SELL not in run(BuyAndHold(), [100, 50, 25, 1])

    def test_reset_allows_a_second_entry(self):
        strategy = BuyAndHold()
        run(strategy, [10, 20])
        strategy.reset()
        assert run(strategy, [10])[0] is Signal.BUY


class TestPriceVsSma:
    def test_holds_until_the_window_fills(self):
        assert run(PriceVsSma(5), [10, 11, 12, 13])[:4] == [Signal.HOLD] * 4

    def test_first_computable_candle_only_sets_the_baseline(self):
        assert run(PriceVsSma(4), [10, 10, 10, 10])[3] is Signal.HOLD

    def test_buys_when_price_pushes_above_its_average(self):
        assert run(PriceVsSma(4), [10, 10, 10, 10, 20])[4] is Signal.BUY

    def test_sells_when_price_drops_back_below(self):
        result = run(PriceVsSma(4), [10, 10, 10, 10, 20, 20, 1])
        assert result[4] is Signal.BUY
        assert Signal.SELL in result[5:]

    def test_a_steady_climb_signals_once(self):
        result = run(PriceVsSma(4), [10, 10, 10, 10, *range(11, 40)])
        assert result.count(Signal.BUY) == 1
        assert result.count(Signal.SELL) == 0

    def test_a_flat_market_never_trades(self):
        assert set(run(PriceVsSma(10), [42.0] * 40)) == {Signal.HOLD}

    def test_rejects_non_positive_period(self):
        with pytest.raises(ValueError, match="period must be positive"):
            PriceVsSma(0)

    def test_reset_clears_history(self):
        strategy = PriceVsSma(4)
        run(strategy, [10, 10, 10, 10, 20])
        strategy.reset()
        assert run(strategy, [5, 6, 7]) == [Signal.HOLD] * 3


class TestTimeSeriesMomentum:
    def test_holds_until_the_lookback_is_available(self):
        assert run(TimeSeriesMomentum(3), [10, 11, 12]) == [Signal.HOLD] * 3

    def test_compares_against_the_price_that_many_candles_back(self):
        # Candle 3 is the first with a full lookback; it only sets the baseline.
        result = run(TimeSeriesMomentum(3), [10, 1, 1, 20, 0.5])
        assert result[3] is Signal.HOLD  # 20 > 10, but this only sets the baseline
        assert result[4] is Signal.SELL  # 0.5 is below the 1 from three candles back

    def test_buys_when_price_rises_above_the_old_level(self):
        result = run(TimeSeriesMomentum(2), [10, 10, 9, 20])
        assert Signal.BUY in result

    def test_a_steady_climb_signals_once(self):
        result = run(TimeSeriesMomentum(3), [10, 10, 10, 9, *range(11, 40)])
        assert result.count(Signal.BUY) == 1
        assert result.count(Signal.SELL) == 0

    def test_a_flat_market_never_trades(self):
        assert set(run(TimeSeriesMomentum(5), [7.0] * 30)) == {Signal.HOLD}

    def test_rejects_non_positive_lookback(self):
        with pytest.raises(ValueError, match="lookback must be positive"):
            TimeSeriesMomentum(0)

    def test_reset_clears_history(self):
        strategy = TimeSeriesMomentum(2)
        run(strategy, [10, 5, 20, 30])
        strategy.reset()
        assert run(strategy, [1, 2]) == [Signal.HOLD] * 2
