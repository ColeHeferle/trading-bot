from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from trading_bot.broker import BrokerPosition, Reconciliation
from trading_bot.live import (
    NotSafeToTrade,
    check_freshness,
    check_reconciled,
    plan,
    plan_order,
)
from trading_bot.models import Side

NOW = datetime(2026, 9, 8, 22, 0)


class StubBroker:
    def __init__(self, equity=10_000.0, quantity=0.0, symbol="SPY", price=640.0):
        self._equity = equity
        self._price = price
        self._positions = (
            [BrokerPosition(symbol, quantity, 640.0)] if quantity else []
        )

    def latest_price(self, symbol):
        return self._price

    def account(self):
        from trading_bot.broker import Account

        return Account(cash=self._equity, equity=self._equity, buying_power=self._equity)

    def positions(self):
        return list(self._positions)

    def position(self, symbol):
        for held in self._positions:
            if held.symbol == symbol:
                return held
        return BrokerPosition(symbol, 0.0, 0.0)


class TestEntry:
    def test_buys_to_the_target_when_flat(self):
        intent = plan_order("SPY", True, 640.0, 10_000.0, 0.0)
        assert intent.side is Side.BUY
        assert intent.quantity == 15  # floor(10000 / 640)

    def test_rounds_down_so_a_sizing_error_undershoots(self):
        # 10000/640 is 15.625; a rounded-up 16 would overspend.
        assert plan_order("SPY", True, 640.0, 10_000.0, 0.0).quantity == 15

    def test_never_plans_a_partial_share_by_default(self):
        intent = plan_order("SPY", True, 640.0, 10_000.0, 0.0)
        assert intent.quantity == int(intent.quantity)

    def test_fractional_sizing_when_asked(self):
        intent = plan_order("SPY", True, 640.0, 10_000.0, 0.0, whole_shares=False)
        assert intent.quantity == pytest.approx(15.625)

    def test_sizes_against_broker_equity_not_a_simulated_balance(self):
        small = plan_order("SPY", True, 640.0, 1_000.0, 0.0)
        large = plan_order("SPY", True, 640.0, 100_000.0, 0.0)
        assert small.quantity == 1 and large.quantity == 156


class TestExit:
    def test_sells_the_whole_position_when_the_rule_goes_flat(self):
        intent = plan_order("SPY", False, 640.0, 10_000.0, 15.0)
        assert intent.side is Side.SELL
        assert intent.quantity == 15.0

    def test_an_exit_is_never_banded(self):
        # Even a tiny holding is closed: flat means flat.
        intent = plan_order("SPY", False, 640.0, 1_000_000.0, 1.0)
        assert intent.side is Side.SELL and intent.quantity == 1.0

    def test_flat_and_already_flat_does_nothing(self):
        assert not plan_order("SPY", False, 640.0, 10_000.0, 0.0).is_action


class TestBand:
    def test_holds_when_already_near_the_target(self):
        intent = plan_order("SPY", True, 640.0, 10_000.0, 15.0)
        assert not intent.is_action
        assert "band" in intent.reason

    def test_tops_up_when_drift_exceeds_the_band(self):
        intent = plan_order("SPY", True, 640.0, 10_000.0, 5.0)
        assert intent.side is Side.BUY and intent.quantity == 10

    def test_a_sub_share_top_up_is_skipped(self):
        intent = plan_order("SPY", True, 640.0, 10_000.0, 15.4, threshold=0.0)
        assert not intent.is_action
        assert "whole share" in intent.reason


class TestDegenerateInputs:
    @pytest.mark.parametrize("price, equity", [(0.0, 10_000.0), (640.0, 0.0), (-1.0, 5.0)])
    def test_no_price_or_no_equity_means_no_order(self, price, equity):
        assert not plan_order("SPY", True, price, equity, 0.0).is_action


class TestFreshness:
    def test_a_recent_bar_passes(self):
        check_freshness(NOW - timedelta(days=1), NOW)

    def test_a_long_weekend_still_passes(self):
        check_freshness(NOW - timedelta(days=4), NOW)

    def test_a_stale_bar_refuses(self):
        with pytest.raises(NotSafeToTrade, match="the feed is behind"):
            check_freshness(NOW - timedelta(days=9), NOW)

    def test_the_limit_is_configurable(self):
        with pytest.raises(NotSafeToTrade):
            check_freshness(NOW - timedelta(days=2), NOW, max_age_days=1)

    def test_rejects_a_nonsense_limit(self):
        with pytest.raises(ValueError, match="max_age_days must be positive"):
            check_freshness(NOW, NOW, max_age_days=0)


class TestReconciliationGate:
    def test_agreement_passes(self):
        check_reconciled([Reconciliation("SPY", 15.0, 15.0)])

    def test_disagreement_refuses(self):
        with pytest.raises(NotSafeToTrade, match="positions disagree"):
            check_reconciled([Reconciliation("SPY", 15.0, 8.0)])

    def test_the_message_names_both_sides(self):
        with pytest.raises(NotSafeToTrade) as caught:
            check_reconciled([Reconciliation("SPY", 15.0, 8.0)])
        assert "run expects 15" in str(caught.value)
        assert "broker holds 8" in str(caught.value)


class TestPlanEndToEnd:
    def test_plans_an_entry_through_every_gate(self):
        intent = plan(
            StubBroker(), "SPY", True, NOW - timedelta(days=1), NOW,
            expected_quantity=0.0,
        )
        assert intent.side is Side.BUY and intent.quantity == 15

    def test_a_stale_bar_stops_it_before_any_broker_call(self):
        with pytest.raises(NotSafeToTrade, match="feed is behind"):
            plan(
                StubBroker(), "SPY", True, NOW - timedelta(days=30), NOW,
                expected_quantity=0.0,
            )

    def test_a_divergent_position_stops_it(self):
        broker = StubBroker(quantity=8.0)
        with pytest.raises(NotSafeToTrade, match="positions disagree"):
            plan(
                broker, "SPY", True, NOW - timedelta(days=1), NOW,
                expected_quantity=15.0,
            )

    def test_skipping_the_gate_is_possible_but_explicit(self):
        # Only appropriate before the first order has ever been placed.
        broker = StubBroker(quantity=8.0)
        intent = plan(
            broker, "SPY", True, NOW - timedelta(days=1), NOW,
            expected_quantity=None,
        )
        assert intent.side is Side.BUY

    def test_an_unmanaged_position_trips_the_gate(self):
        broker = StubBroker(quantity=3.0, symbol="TSLA")
        with pytest.raises(NotSafeToTrade, match="TSLA"):
            plan(
                broker, "SPY", True, NOW - timedelta(days=1), NOW,
                expected_quantity=0.0,
            )


class TestSizesOnTheTradedInstrument:
    """The rule may decide on an index it cannot buy.

    Sizing off that index's level buys the wrong amount by whatever ratio
    separates it from the tradeable instrument — an S&P level near 6,400
    against an ETF near 640 is a tenfold error, and it is silent.
    """

    def test_uses_the_broker_price_not_the_index_level(self):
        broker = StubBroker(equity=10_000.0, price=640.0)
        intent = plan(broker, "SPY", True, NOW - timedelta(days=1), NOW,
                      expected_quantity=0.0)
        # 10000/640 = 15, not 10000/6400 = 1.
        assert intent.quantity == 15

    def test_an_explicit_price_can_override_the_lookup(self):
        broker = StubBroker(equity=10_000.0, price=640.0)
        intent = plan(broker, "SPY", True, NOW - timedelta(days=1), NOW,
                      expected_quantity=0.0, price=1_000.0)
        assert intent.quantity == 10

    def test_the_index_level_would_have_sized_it_wrong(self):
        # Guards the exact bug: pricing a 640 instrument at an index near 6400
        # under-buys by a factor of ten.
        broker = StubBroker(equity=10_000.0, price=640.0)
        correct = plan(broker, "SPY", True, NOW - timedelta(days=1), NOW,
                       expected_quantity=0.0)
        as_index = plan(broker, "SPY", True, NOW - timedelta(days=1), NOW,
                        expected_quantity=0.0, price=6_400.0)
        assert correct.quantity == 15 and as_index.quantity == 1
