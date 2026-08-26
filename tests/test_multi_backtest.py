from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from trading_bot.backtest import run_backtest, run_multi_backtest
from trading_bot.models import Candle, Side
from trading_bot.portfolio import Portfolio
from trading_bot.sizing import VolatilityTarget
from trading_bot.strategy import BuyAndHold, SmaCrossover

from tests.helpers import make_candles

START = datetime(2024, 1, 1)


def series(closes, start=START, step_days=1):
    return [
        Candle(start + timedelta(days=i * step_days), c, c, c, c)
        for i, c in enumerate(closes)
    ]


class TestUniverse:
    def test_rejects_an_empty_universe(self):
        with pytest.raises(ValueError, match="at least one symbol"):
            run_multi_backtest({}, BuyAndHold)

    def test_one_symbol_matches_the_single_asset_loop(self):
        closes = [10, 11, 12, 11, 13, 14, 12, 15]
        single = run_backtest(
            series(closes), BuyAndHold(), symbol="A", portfolio=Portfolio(1000.0)
        )
        basket = run_multi_backtest(
            {"A": series(closes)}, BuyAndHold, portfolio=Portfolio(1000.0)
        )
        assert basket.final_equity == pytest.approx(single.final_equity)

    def test_each_symbol_gets_its_own_strategy_instance(self):
        # Sharing one stateful strategy across symbols would cross the streams
        # and produce a single entry rather than one per symbol.
        result = run_multi_backtest(
            {"A": series([10] * 6), "B": series([20] * 6)},
            BuyAndHold,
            portfolio=Portfolio(1000.0),
        )
        assert {fill.symbol for fill in result.fills} == {"A", "B"}


class TestAllocation:
    def test_equal_split_by_default(self):
        result = run_multi_backtest(
            {"A": series([10] * 5), "B": series([10] * 5), "C": series([10] * 5)},
            BuyAndHold,
            portfolio=Portfolio(3000.0),
        )
        held = {s: result.portfolio.quantity(s) * 10 for s in ("A", "B", "C")}
        for value in held.values():
            assert value == pytest.approx(1000.0, rel=1e-3)

    def test_custom_weights_are_respected(self):
        result = run_multi_backtest(
            {"A": series([10] * 5), "B": series([10] * 5)},
            BuyAndHold,
            portfolio=Portfolio(1000.0),
            weights={"A": 0.75, "B": 0.25},
        )
        assert result.portfolio.quantity("A") * 10 == pytest.approx(750.0, rel=1e-3)
        assert result.portfolio.quantity("B") * 10 == pytest.approx(250.0, rel=1e-3)

    def test_rejects_weights_that_would_need_borrowing(self):
        with pytest.raises(ValueError, match="cannot borrow"):
            run_multi_backtest(
                {"A": series([10] * 3), "B": series([10] * 3)},
                BuyAndHold,
                weights={"A": 0.8, "B": 0.5},
            )

    def test_rejects_incomplete_weights(self):
        with pytest.raises(ValueError, match="missing for"):
            run_multi_backtest(
                {"A": series([10] * 3), "B": series([10] * 3)},
                BuyAndHold,
                weights={"A": 1.0},
            )

    def test_rejects_weights_for_unknown_symbols(self):
        with pytest.raises(ValueError, match="unknown symbols"):
            run_multi_backtest(
                {"A": series([10] * 3)}, BuyAndHold, weights={"A": 0.5, "Z": 0.5}
            )

    def test_rejects_non_positive_weights(self):
        with pytest.raises(ValueError, match="must be positive"):
            run_multi_backtest(
                {"A": series([10] * 3), "B": series([10] * 3)},
                BuyAndHold,
                weights={"A": 1.0, "B": 0.0},
            )

    def test_a_flat_symbol_leaves_its_share_in_cash(self):
        # B never triggers a 2/4 crossover, so its half must stay uninvested
        # rather than being lent to A.
        data = {
            "A": series([10, 10, 10, 10, 20, 30]),
            "B": series([10.0] * 6),
        }
        result = run_multi_backtest(
            data, lambda: SmaCrossover(2, 4), portfolio=Portfolio(1000.0)
        )
        assert result.portfolio.quantity("B") == 0.0
        assert result.portfolio.cash >= 400.0


class TestAlignment:
    def test_handles_symbols_with_different_date_ranges(self):
        data = {
            "EARLY": series([10] * 10, start=START),
            "LATE": series([20] * 10, start=START + timedelta(days=5)),
        }
        result = run_multi_backtest(data, BuyAndHold, portfolio=Portfolio(1000.0))

        # Union of both calendars: 15 distinct days.
        assert len(result.equity_curve) == 15
        assert result.equity_curve[0][0] == START

    def test_a_symbol_is_not_traded_before_its_first_bar(self):
        data = {
            "EARLY": series([10] * 10, start=START),
            "LATE": series([20] * 10, start=START + timedelta(days=5)),
        }
        result = run_multi_backtest(data, BuyAndHold, portfolio=Portfolio(1000.0))
        first_late = min(f.timestamp for f in result.fills_for("LATE"))

        assert first_late == START + timedelta(days=5)

    def test_a_gap_marks_the_position_at_its_last_close(self):
        # B is missing the final bar; equity must still count it, at 20.
        data = {
            "A": series([10] * 4),
            "B": series([20] * 3),
        }
        result = run_multi_backtest(data, BuyAndHold, portfolio=Portfolio(1000.0))
        last_equity = result.equity_curve[-1][1]

        assert last_equity == pytest.approx(1000.0, rel=1e-3)


class TestCashDiscipline:
    def test_never_overdraws_the_shared_balance(self):
        data = {
            f"S{i}": series([10 + i, 12 + i, 9 + i, 15 + i, 11 + i, 18 + i])
            for i in range(5)
        }
        result = run_multi_backtest(
            data, BuyAndHold, portfolio=Portfolio(1000.0, fee_rate=0.001)
        )
        assert result.portfolio.cash >= 0.0

    def test_sells_are_executed_before_buys_in_the_same_bar(self):
        # A rides up to well over its target weight (a wide band leaves it
        # untrimmed), then rolls over on the same bar B breaks out. B's target
        # is 812.50 but only 500 sits in cash, so the entry is only fundable
        # if A's exit settles first.
        data = {
            "A": series([10, 10, 10, 10, 20, 40, 60, 50, 45]),
            "B": series([10, 10, 10, 10, 10, 10, 10, 10, 40]),
        }
        result = run_multi_backtest(
            data,
            lambda: SmaCrossover(2, 4),
            portfolio=Portfolio(1000.0),
            rebalance_threshold=0.45,
        )

        by_stamp: dict = {}
        for fill in result.fills:
            by_stamp.setdefault(fill.timestamp, []).append(fill)
        both = [
            fills
            for fills in by_stamp.values()
            if {f.side for f in fills} == {Side.BUY, Side.SELL}
        ]

        assert both, "scenario produced no bar with a sell and a buy together"
        for fills in both:
            sides = [f.side for f in fills]
            assert max(i for i, s in enumerate(sides) if s is Side.SELL) < min(
                i for i, s in enumerate(sides) if s is Side.BUY
            )

    def test_a_buy_reaches_its_full_target_using_cash_freed_that_bar(self):
        data = {
            "A": series([10, 10, 10, 10, 20, 40, 60, 50, 45]),
            "B": series([10, 10, 10, 10, 10, 10, 10, 10, 40]),
        }
        result = run_multi_backtest(
            data,
            lambda: SmaCrossover(2, 4),
            portfolio=Portfolio(1000.0),
            rebalance_threshold=0.45,
        )
        entry = result.fills_for("B")[0]
        equity_then = dict(result.equity_curve)[entry.timestamp]

        # Half of equity, and more than the 500 of cash on hand before the sale.
        assert entry.notional == pytest.approx(0.5 * equity_then, rel=1e-3)
        assert entry.notional > 500.0


class TestResults:
    def test_exposure_reports_the_share_of_capital_deployed(self):
        result = run_multi_backtest(
            {"A": series([10] * 5), "B": series([10] * 5)},
            BuyAndHold,
            portfolio=Portfolio(1000.0),
        )
        assert result.exposure == pytest.approx(1.0, abs=0.01)

    def test_exposure_is_partial_when_only_some_symbols_are_long(self):
        data = {
            "A": series([10, 10, 10, 10, 20, 30, 40, 50]),
            "B": series([10.0] * 8),
        }
        result = run_multi_backtest(
            data, lambda: SmaCrossover(2, 4), portfolio=Portfolio(1000.0)
        )
        assert 0.0 < result.exposure < 0.6

    def test_metrics_match_the_single_asset_implementation(self):
        closes = [100 * 1.01**i * (1 + 0.02 * (i % 3 - 1)) for i in range(120)]
        single = run_backtest(
            series(closes), BuyAndHold(), symbol="A", portfolio=Portfolio(1000.0)
        )
        basket = run_multi_backtest(
            {"A": series(closes)}, BuyAndHold, portfolio=Portfolio(1000.0)
        )
        assert basket.sharpe == pytest.approx(single.sharpe)
        assert basket.cagr == pytest.approx(single.cagr)
        assert basket.max_drawdown == pytest.approx(single.max_drawdown)

    def test_fills_for_filters_by_symbol(self):
        result = run_multi_backtest(
            {"A": series([10] * 4), "B": series([20] * 4)},
            BuyAndHold,
            portfolio=Portfolio(1000.0),
        )
        assert all(f.symbol == "A" for f in result.fills_for("A"))
        assert result.fills_for("A") and result.fills_for("B")
        assert result.fills_for("NOPE") == []


class TestWithSizer:
    def test_a_sizer_is_built_per_symbol_and_shrinks_the_basket(self):
        wild = [100 * (1.2 if i % 2 else 0.85) ** 1 for i in range(80)]
        data = {"A": series(wild), "B": series(wild)}
        plain = run_multi_backtest(data, BuyAndHold, portfolio=Portfolio(10_000.0))
        sized = run_multi_backtest(
            data,
            BuyAndHold,
            portfolio=Portfolio(10_000.0),
            sizer_factory=lambda: VolatilityTarget(0.15, lookback=10),
        )
        assert sized.exposure < plain.exposure


class TestBandScalesWithUniverseSize:
    """A fixed band would reject every entry once the universe got wide.

    With ten symbols each leg targets 0.1 of equity, under a default band of
    0.2 — so an absolute band left the whole basket sitting in cash and
    reporting a flat zero, silently, with no error anywhere.
    """

    @pytest.mark.parametrize("count", [1, 2, 5, 6, 10, 25])
    def test_every_symbol_is_entered_however_wide_the_basket(self, count):
        data = {f"S{i}": series([10, 11, 12, 13, 14, 15]) for i in range(count)}
        result = run_multi_backtest(data, BuyAndHold, portfolio=Portfolio(100_000.0))

        traded = {fill.symbol for fill in result.fills}
        assert traded == set(data)
        assert result.exposure > 0.5

    def test_a_wide_basket_deploys_nearly_all_its_capital(self):
        data = {f"S{i}": series([10] * 6) for i in range(10)}
        result = run_multi_backtest(data, BuyAndHold, portfolio=Portfolio(100_000.0))

        assert result.portfolio.cash == pytest.approx(0.0, abs=1.0)

    def test_the_band_still_suppresses_churn_within_a_leg(self):
        # The legs must move *differently*, or their weights never drift apart
        # and no band setting would ever trigger a rebalance.
        data = {
            f"S{i}": series([10 * (1 + 0.05 * (i + 1) * ((-1) ** (t + i))) for t in range(120)])
            for i in range(10)
        }
        tight = run_multi_backtest(
            data, BuyAndHold, portfolio=Portfolio(100_000.0), rebalance_threshold=0.001
        )
        wide = run_multi_backtest(
            data, BuyAndHold, portfolio=Portfolio(100_000.0), rebalance_threshold=5.0
        )
        assert len(wide.fills) < len(tight.fills)

    def test_single_symbol_band_is_unchanged(self):
        # scale is 1.0 for a lone symbol, so the old behaviour is preserved.
        closes = [10, 10, 10, 10, 12, 14, 16, 18, 20, 22, 24, 23, 20, 17, 14]
        one = run_multi_backtest(
            {"A": series(closes)},
            lambda: SmaCrossover(2, 4),
            portfolio=Portfolio(1000.0),
        )
        direct = run_backtest(
            series(closes),
            SmaCrossover(2, 4),
            symbol="A",
            portfolio=Portfolio(1000.0),
        )
        assert one.final_equity == pytest.approx(direct.final_equity)
