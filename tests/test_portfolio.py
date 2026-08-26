from __future__ import annotations

from datetime import datetime

import pytest

from trading_bot.models import Order, Side
from trading_bot.portfolio import (
    InsufficientFunds,
    InsufficientPosition,
    Portfolio,
)

NOW = datetime(2024, 1, 1)


def buy(portfolio, quantity, price, symbol="BTC"):
    return portfolio.execute(Order(symbol, Side.BUY, quantity), price, NOW)


def sell(portfolio, quantity, price, symbol="BTC"):
    return portfolio.execute(Order(symbol, Side.SELL, quantity), price, NOW)


class TestOrders:
    def test_rejects_non_positive_quantity(self):
        with pytest.raises(ValueError, match="quantity must be positive"):
            Order("BTC", Side.BUY, 0)


class TestBuying:
    def test_buying_moves_cash_into_the_position(self):
        portfolio = Portfolio(cash=1000.0)
        buy(portfolio, 2, 100.0)

        assert portfolio.cash == pytest.approx(800.0)
        assert portfolio.quantity("BTC") == pytest.approx(2.0)
        assert portfolio.position("BTC").avg_price == pytest.approx(100.0)

    def test_second_buy_averages_the_entry_price(self):
        portfolio = Portfolio(cash=1000.0)
        buy(portfolio, 1, 100.0)
        buy(portfolio, 3, 200.0)

        assert portfolio.quantity("BTC") == pytest.approx(4.0)
        assert portfolio.position("BTC").avg_price == pytest.approx(175.0)

    def test_fees_are_charged_on_top_of_notional(self):
        portfolio = Portfolio(cash=1000.0, fee_rate=0.01)
        fill = buy(portfolio, 2, 100.0)

        assert fill.fee == pytest.approx(2.0)
        assert portfolio.cash == pytest.approx(798.0)
        assert portfolio.total_fees == pytest.approx(2.0)

    def test_cannot_spend_more_cash_than_it_has(self):
        portfolio = Portfolio(cash=100.0)
        with pytest.raises(InsufficientFunds):
            buy(portfolio, 2, 100.0)

    def test_fees_can_be_what_pushes_an_order_out_of_reach(self):
        portfolio = Portfolio(cash=100.0, fee_rate=0.01)
        with pytest.raises(InsufficientFunds):
            buy(portfolio, 1, 100.0)

    def test_a_rejected_order_leaves_the_account_untouched(self):
        portfolio = Portfolio(cash=100.0)
        with pytest.raises(InsufficientFunds):
            buy(portfolio, 5, 100.0)

        assert portfolio.cash == pytest.approx(100.0)
        assert portfolio.quantity("BTC") == 0.0
        assert portfolio.fills == []


class TestSelling:
    def test_selling_returns_cash_and_records_realized_pnl(self):
        portfolio = Portfolio(cash=1000.0)
        buy(portfolio, 2, 100.0)
        sell(portfolio, 2, 150.0)

        assert portfolio.cash == pytest.approx(1100.0)
        assert portfolio.realized_pnl == pytest.approx(100.0)
        assert portfolio.quantity("BTC") == 0.0

    def test_partial_sale_keeps_the_entry_price(self):
        portfolio = Portfolio(cash=1000.0)
        buy(portfolio, 4, 100.0)
        sell(portfolio, 1, 150.0)

        assert portfolio.quantity("BTC") == pytest.approx(3.0)
        assert portfolio.position("BTC").avg_price == pytest.approx(100.0)
        assert portfolio.realized_pnl == pytest.approx(50.0)

    def test_closing_a_position_clears_the_entry_price(self):
        portfolio = Portfolio(cash=1000.0)
        buy(portfolio, 2, 100.0)
        sell(portfolio, 2, 90.0)

        assert portfolio.position("BTC").is_flat
        assert portfolio.position("BTC").avg_price == 0.0
        assert portfolio.realized_pnl == pytest.approx(-20.0)

    def test_cannot_sell_more_than_it_holds(self):
        portfolio = Portfolio(cash=1000.0)
        buy(portfolio, 1, 100.0)
        with pytest.raises(InsufficientPosition):
            sell(portfolio, 2, 100.0)

    def test_cannot_open_a_short(self):
        portfolio = Portfolio(cash=1000.0)
        with pytest.raises(InsufficientPosition):
            sell(portfolio, 1, 100.0)


class TestValuation:
    def test_equity_marks_open_positions_to_market(self):
        portfolio = Portfolio(cash=1000.0)
        buy(portfolio, 2, 100.0)

        assert portfolio.equity({"BTC": 100.0}) == pytest.approx(1000.0)
        assert portfolio.equity({"BTC": 150.0}) == pytest.approx(1100.0)

    def test_equity_ignores_prices_for_positions_it_has_closed(self):
        portfolio = Portfolio(cash=1000.0)
        buy(portfolio, 1, 100.0)
        sell(portfolio, 1, 100.0)

        assert portfolio.equity({}) == pytest.approx(1000.0)

    def test_total_return_is_relative_to_starting_cash(self):
        portfolio = Portfolio(cash=1000.0)
        buy(portfolio, 5, 100.0)

        assert portfolio.total_return({"BTC": 120.0}) == pytest.approx(0.10)

    def test_round_trip_loses_exactly_the_fees(self):
        portfolio = Portfolio(cash=1000.0, fee_rate=0.001)
        buy(portfolio, 2, 100.0)
        sell(portfolio, 2, 100.0)

        assert portfolio.equity({}) == pytest.approx(1000.0 - portfolio.total_fees)
        assert portfolio.total_fees == pytest.approx(0.4)

    def test_unrealized_pnl_tracks_the_mark(self):
        portfolio = Portfolio(cash=1000.0)
        buy(portfolio, 2, 100.0)

        assert portfolio.position("BTC").unrealized_pnl(130.0) == pytest.approx(60.0)


class TestConstruction:
    def test_rejects_negative_cash(self):
        with pytest.raises(ValueError, match="cash"):
            Portfolio(cash=-1.0)

    def test_rejects_negative_fee_rate(self):
        with pytest.raises(ValueError, match="fee_rate"):
            Portfolio(fee_rate=-0.01)

    def test_rejects_non_positive_price(self):
        with pytest.raises(ValueError, match="price must be positive"):
            buy(Portfolio(), 1, 0.0)

    def test_unknown_symbol_reads_as_flat(self):
        assert Portfolio().position("ETH").is_flat
