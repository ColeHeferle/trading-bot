from __future__ import annotations

import math

import pytest

from trading_bot.backtest import run_backtest
from trading_bot.portfolio import Portfolio
from trading_bot.sizing import FullInvestment, VolatilityTarget
from trading_bot.strategy import BuyAndHold, SmaCrossover

from tests.helpers import make_candles


def feed(sizer, closes):
    """Push closes through a sizer, returning the weight it asks for each bar."""
    return [sizer.weight(candle) for candle in make_candles(closes)]


def steady(daily_move: float, n: int = 60) -> list[float]:
    """Alternating +/- moves of a fixed size: volatility without drift."""
    price, out = 100.0, []
    for i in range(n):
        price *= (1 + daily_move) if i % 2 else (1 - daily_move)
        out.append(price)
    return out


class TestConstruction:
    @pytest.mark.parametrize(
        "kwargs, message",
        [
            ({"target_volatility": 0}, "target_volatility must be positive"),
            ({"target_volatility": -0.1}, "target_volatility must be positive"),
            ({"lookback": 1}, "lookback must be at least 2"),
            ({"max_leverage": 0}, "max_leverage must be positive"),
            ({"periods_per_year": 0}, "periods_per_year must be positive"),
        ],
    )
    def test_rejects_nonsense_configuration(self, kwargs, message):
        with pytest.raises(ValueError, match=message):
            VolatilityTarget(**kwargs)


class TestWarmup:
    def test_asks_for_nothing_until_the_window_fills(self):
        weights = feed(VolatilityTarget(lookback=10), [100 + i for i in range(10)])
        # 10 candles yield only 9 returns, so the estimate is still incomplete.
        assert weights == [0.0] * 10

    def test_sizes_once_the_window_is_full(self):
        weights = feed(VolatilityTarget(lookback=10), steady(0.01, 20))
        assert weights[9] == 0.0
        assert weights[10] > 0.0

    def test_realized_volatility_is_none_while_warming_up(self):
        sizer = VolatilityTarget(lookback=10)
        feed(sizer, [100, 101, 102])
        assert sizer.realized_volatility is None


class TestWeighting:
    def test_a_calm_market_earns_a_bigger_position_than_a_wild_one(self):
        calm = feed(VolatilityTarget(lookback=20), steady(0.002))[-1]
        wild = feed(VolatilityTarget(lookback=20), steady(0.02))[-1]
        assert calm > wild

    def test_weight_is_the_ratio_of_target_to_realized_volatility(self):
        sizer = VolatilityTarget(target_volatility=0.15, lookback=20, max_leverage=99)
        weights = feed(sizer, steady(0.01))
        assert weights[-1] == pytest.approx(0.15 / sizer.realized_volatility)

    def test_doubling_the_target_doubles_the_position(self):
        closes = steady(0.01)
        modest = feed(VolatilityTarget(0.10, lookback=20, max_leverage=99), closes)[-1]
        bold = feed(VolatilityTarget(0.20, lookback=20, max_leverage=99), closes)[-1]
        assert bold == pytest.approx(2 * modest)

    def test_leverage_cap_binds_in_a_quiet_market(self):
        weights = feed(VolatilityTarget(0.15, lookback=20, max_leverage=1.0), steady(0.0001))
        assert weights[-1] == pytest.approx(1.0)

    def test_a_motionless_market_returns_the_cap_rather_than_dividing_by_zero(self):
        weights = feed(VolatilityTarget(lookback=5, max_leverage=1.0), [50.0] * 20)
        assert weights[-1] == pytest.approx(1.0)

    def test_annualization_uses_periods_per_year(self):
        closes = steady(0.01)
        daily = VolatilityTarget(lookback=20, periods_per_year=252)
        monthly = VolatilityTarget(lookback=20, periods_per_year=12)
        feed(daily, closes)
        feed(monthly, closes)
        assert daily.realized_volatility == pytest.approx(
            monthly.realized_volatility * math.sqrt(252 / 12)
        )

    def test_reset_clears_the_estimate(self):
        sizer = VolatilityTarget(lookback=5)
        feed(sizer, steady(0.01, 30))
        sizer.reset()
        assert sizer.realized_volatility is None
        assert sizer.weight(make_candles([100])[0]) == 0.0


class TestFullInvestment:
    def test_always_asks_for_the_whole_balance(self):
        assert feed(FullInvestment(), [10, 20, 5]) == [1.0, 1.0, 1.0]


class TestBacktestIntegration:
    def test_sizer_and_quantity_are_mutually_exclusive(self):
        with pytest.raises(ValueError, match="not both"):
            run_backtest(
                make_candles([10, 11]),
                BuyAndHold(),
                quantity=1.0,
                sizer=FullInvestment(),
            )

    def test_full_investment_sizer_matches_the_default_path(self):
        closes = [10, 10, 10, 10, 12, 14, 16, 18, 20, 22, 24, 23, 20, 17, 14]
        plain = run_backtest(
            make_candles(closes), SmaCrossover(2, 4), symbol="X",
            portfolio=Portfolio(1000.0),
        )
        sized = run_backtest(
            make_candles(closes), SmaCrossover(2, 4), symbol="X",
            portfolio=Portfolio(1000.0), sizer=FullInvestment(),
        )
        assert sized.final_equity == pytest.approx(plain.final_equity)

    def test_volatility_target_holds_less_than_a_full_position(self):
        closes = steady(0.02, 300)
        result = run_backtest(
            make_candles(closes),
            BuyAndHold(),
            symbol="X",
            portfolio=Portfolio(10_000.0),
            sizer=VolatilityTarget(target_volatility=0.10, lookback=20),
        )
        held_value = result.holdings[-1] * closes[-1]
        assert 0 < held_value < result.final_equity

    def test_a_flat_signal_always_exits_despite_the_band(self):
        # Rally then collapse: the strategy goes flat and the band must not
        # leave a rump position behind.
        closes = [10, 10, 10, 10, 20, 30, 40, 5, 4, 3, 3, 3]
        result = run_backtest(
            make_candles(closes),
            SmaCrossover(2, 4),
            symbol="X",
            portfolio=Portfolio(10_000.0),
            sizer=VolatilityTarget(lookback=3),
        )
        assert result.holdings[-1] == 0.0

    def test_a_wide_band_suppresses_rebalancing_trades(self):
        closes = steady(0.02, 300)
        tight = run_backtest(
            make_candles(closes), BuyAndHold(), symbol="X",
            portfolio=Portfolio(10_000.0),
            sizer=VolatilityTarget(lookback=20), rebalance_threshold=0.01,
        )
        wide = run_backtest(
            make_candles(closes), BuyAndHold(), symbol="X",
            portfolio=Portfolio(10_000.0),
            sizer=VolatilityTarget(lookback=20), rebalance_threshold=0.5,
        )
        assert len(wide.fills) < len(tight.fills)

    def test_never_spends_more_cash_than_it_has(self):
        result = run_backtest(
            make_candles(steady(0.005, 200)),
            BuyAndHold(),
            symbol="X",
            portfolio=Portfolio(1_000.0, fee_rate=0.001),
            sizer=VolatilityTarget(target_volatility=5.0, lookback=20, max_leverage=10),
        )
        assert result.portfolio.cash >= 0.0
