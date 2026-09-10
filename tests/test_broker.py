from __future__ import annotations

from datetime import datetime

import pytest

from trading_bot.broker import (
    LIVE_URL,
    PAPER_URL,
    AlpacaBroker,
    BrokerError,
    BrokerPosition,
    Reconciliation,
    RiskLimitExceeded,
    RiskLimits,
    client_order_id,
    reconcile,
)
from trading_bot.models import Side


class FakeTransport:
    """Stands in for the network, recording what would have been sent."""

    def __init__(self, responses: dict[tuple[str, str], object] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, str, dict | None]] = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        key = (method, path)
        if key not in self.responses:
            raise BrokerError(f"{method} {path} -> 404: no stub")
        value = self.responses[key]
        if isinstance(value, Exception):
            raise value
        return value


ACCOUNT = {"cash": "10000.5", "equity": "12000.25", "buying_power": "20000", "currency": "USD"}
POSITIONS = [{"symbol": "SPY", "qty": "12", "avg_entry_price": "640.5"}]
# `submit` prices every order so the notional ceiling has something to
# multiply by, so this route is stubbed for every broker built here.
PRICE = {("GET", "/v2/stocks/SPY/trades/latest"): {"trade": {"p": "640.0"}}}


def order_payload(**kw):
    base = {
        "id": "abc-123",
        "client_order_id": "tb-deadbeef",
        "symbol": "SPY",
        "side": "buy",
        "qty": "12",
        "status": "accepted",
        "filled_qty": "0",
        "filled_avg_price": None,
    }
    base.update(kw)
    return base


def broker(responses=None, **kw):
    transport = FakeTransport({**PRICE, **(responses or {})})
    return AlpacaBroker("key", "secret", transport=transport, **kw), transport


def posts(transport):
    return [call for call in transport.calls if call[0] == "POST"]


class TestEndpointGuard:
    def test_defaults_to_the_paper_sandbox(self):
        api, _ = broker()
        assert api.is_paper
        assert api.base_url == PAPER_URL

    def test_refuses_the_live_endpoint_by_default(self):
        with pytest.raises(BrokerError, match="not the paper sandbox"):
            broker(base_url=LIVE_URL)

    def test_live_requires_an_explicit_opt_in(self):
        api, _ = broker(base_url=LIVE_URL, allow_live=True)
        assert not api.is_paper

    def test_an_unknown_host_is_also_refused(self):
        # A typo'd or copied URL must not be assumed safe.
        with pytest.raises(BrokerError, match="not the paper sandbox"):
            broker(base_url="https://api.example.com")


class TestReads:
    def test_parses_the_account(self):
        api, _ = broker({("GET", "/v2/account"): ACCOUNT})
        account = api.account()
        assert (account.cash, account.equity, account.buying_power) == (
            10000.5, 12000.25, 20000.0
        )

    def test_parses_positions(self):
        api, _ = broker({("GET", "/v2/positions"): POSITIONS})
        [held] = api.positions()
        assert (held.symbol, held.quantity, held.avg_price) == ("SPY", 12.0, 640.5)

    def test_keeps_the_sign_of_a_short(self):
        # A negative qty is a position we never meant to open; hiding the sign
        # would make it look like a long.
        api, _ = broker({("GET", "/v2/positions"): [
            {"symbol": "SPY", "qty": "-5", "avg_entry_price": "640"}
        ]})
        assert api.positions()[0].quantity == -5.0

    def test_no_positions_reads_as_flat(self):
        api, _ = broker({("GET", "/v2/positions"): []})
        assert api.position("SPY").quantity == 0.0

    def test_a_null_body_is_treated_as_no_positions(self):
        api, _ = broker({("GET", "/v2/positions"): None})
        assert api.positions() == []


class TestSubmit:
    def test_sends_a_day_market_order_with_the_given_id(self):
        api, transport = broker({("POST", "/v2/orders"): order_payload()})
        api.submit("SPY", Side.BUY, 12, "tb-deadbeef")

        _, path, body = posts(transport)[0]
        assert path == "/v2/orders"
        assert body == {
            "symbol": "SPY",
            "qty": "12",
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
            "client_order_id": "tb-deadbeef",
        }

    def test_parses_a_fill(self):
        api, _ = broker({("POST", "/v2/orders"): order_payload(
            status="filled", filled_qty="12", filled_avg_price="641.25"
        )})
        placed = api.submit("SPY", Side.BUY, 12, "tb-deadbeef")
        assert placed.is_filled and not placed.is_open
        assert placed.filled_quantity == 12.0
        assert placed.filled_price == 641.25

    def test_an_unfilled_order_is_open(self):
        api, _ = broker({("POST", "/v2/orders"): order_payload(status="new")})
        assert api.submit("SPY", Side.BUY, 12, "x").is_open

    @pytest.mark.parametrize("status", ["canceled", "expired", "rejected"])
    def test_terminal_failures_are_dead_not_open(self, status):
        api, _ = broker({("POST", "/v2/orders"): order_payload(status=status)})
        placed = api.submit("SPY", Side.BUY, 12, "x")
        assert placed.is_dead and not placed.is_open and not placed.is_filled

    def test_a_duplicate_id_returns_the_existing_order_instead_of_resending(self):
        # The whole point of the deterministic id: a retry after a crash must
        # not open a second position.
        api, transport = broker({
            ("POST", "/v2/orders"): BrokerError("POST /v2/orders -> 422: duplicate"),
            ("GET", "/v2/orders:by_client_order_id?client_order_id=tb-dup"):
                order_payload(client_order_id="tb-dup", status="filled",
                              filled_qty="12", filled_avg_price="640"),
        })
        placed = api.submit("SPY", Side.BUY, 12, "tb-dup")

        assert placed.is_filled
        assert len(posts(transport)) == 1

    def test_a_422_with_no_recoverable_order_still_raises(self):
        api, _ = broker({
            ("POST", "/v2/orders"): BrokerError("POST /v2/orders -> 422: bad qty"),
        })
        with pytest.raises(BrokerError, match="422"):
            api.submit("SPY", Side.BUY, 12, "tb-missing")

    def test_other_errors_are_not_swallowed(self):
        api, _ = broker({
            ("POST", "/v2/orders"): BrokerError("POST /v2/orders -> 500: boom"),
        })
        with pytest.raises(BrokerError, match="500"):
            api.submit("SPY", Side.BUY, 12, "x")

    def test_a_missing_order_lookup_returns_none(self):
        api, _ = broker()
        assert api.order_by_client_id("tb-nope") is None


class TestClientOrderId:
    def test_is_stable_for_the_same_intent(self):
        args = ("fp123", datetime(2026, 9, 8, 21, 30), "SPY", Side.BUY)
        assert client_order_id(*args) == client_order_id(*args)

    def test_ignores_the_time_of_day(self):
        # A retry later the same day is the same intent, so it must collide.
        morning = client_order_id("fp", datetime(2026, 9, 8, 9, 0), "SPY", Side.BUY)
        evening = client_order_id("fp", datetime(2026, 9, 8, 23, 0), "SPY", Side.BUY)
        assert morning == evening

    @pytest.mark.parametrize(
        "changed",
        [
            {"fingerprint": "other"},
            {"stamp": datetime(2026, 9, 9)},
            {"symbol": "QQQ"},
            {"side": Side.SELL},
        ],
    )
    def test_any_different_intent_gets_a_different_id(self, changed):
        base = dict(
            fingerprint="fp", stamp=datetime(2026, 9, 8), symbol="SPY", side=Side.BUY
        )
        assert client_order_id(**base) != client_order_id(**{**base, **changed})

    def test_is_short_enough_for_the_field_and_recognisable(self):
        made = client_order_id("fp", datetime(2026, 9, 8), "SPY", Side.BUY)
        assert made.startswith("tb-") and len(made) <= 48


class TestRiskLimits:
    def test_allows_an_ordinary_order(self):
        RiskLimits().check("SPY", 10, 640.0)

    def test_rejects_a_non_positive_quantity(self):
        with pytest.raises(RiskLimitExceeded, match="non-positive"):
            RiskLimits().check("SPY", 0, 640.0)

    def test_rejects_too_many_shares(self):
        with pytest.raises(RiskLimitExceeded, match="max_order_quantity"):
            RiskLimits(max_order_quantity=100).check("SPY", 101, None)

    def test_rejects_too_much_notional(self):
        with pytest.raises(RiskLimitExceeded, match="max_order_notional"):
            RiskLimits(max_order_notional=1000).check("SPY", 10, 640.0)

    def test_the_default_admits_a_full_size_entry_but_not_a_tenfold_error(self):
        # The two cases the notional default is chosen between, pinned as
        # behaviour rather than as a number: a paper account fully invested in
        # the ETF must go through, and the same account sized off the index
        # level it was watching — 6,400 where 640 belonged — must not.
        equity = 100_000.0
        RiskLimits().check("QQQ", equity // 640.0, 640.0)
        with pytest.raises(RiskLimitExceeded, match="max_order_notional"):
            RiskLimits().check("QQQ", equity // 640.0, 6_400.0)

    def test_the_limit_blocks_the_order_before_it_is_sent(self):
        api, transport = broker(limits=RiskLimits(max_order_quantity=5))
        with pytest.raises(RiskLimitExceeded):
            api.submit("SPY", Side.BUY, 50, "x")
        assert posts(transport) == []

    def test_the_notional_ceiling_binds_on_a_real_submit(self):
        # This is the check that matters: a share count alone cannot tell a
        # rounding error from the whole account, because the same 16 shares is
        # either one depending on the instrument. It was dead for a while —
        # `submit` passed None for the price, so the ceiling had nothing to
        # multiply by and never fired on any order this account could place.
        api, transport = broker(limits=RiskLimits(max_order_notional=1_000))
        with pytest.raises(RiskLimitExceeded, match="max_order_notional"):
            api.submit("SPY", Side.BUY, 12, "x")  # 12 x 640 = 7,680
        assert posts(transport) == []

    def test_a_supplied_price_is_used_instead_of_a_second_lookup(self):
        # The planner already priced this order; re-fetching invites a
        # different number than the arithmetic actually used.
        api, transport = broker(
            {("POST", "/v2/orders"): order_payload()},
            limits=RiskLimits(max_order_notional=1_000),
        )
        with pytest.raises(RiskLimitExceeded, match="max_order_notional"):
            api.submit("SPY", Side.BUY, 12, "x", price=500.0)
        assert transport.calls == []  # no price read, no order

    def test_an_unpriceable_order_is_refused_rather_than_sent_unchecked(self):
        api, transport = broker({
            ("GET", "/v2/stocks/SPY/trades/latest"): BrokerError("500: no data"),
            ("POST", "/v2/orders"): order_payload(),
        })
        with pytest.raises(BrokerError):
            api.submit("SPY", Side.BUY, 12, "x")
        assert posts(transport) == []


class StubBroker:
    def __init__(self, positions):
        self._positions = positions

    def positions(self):
        return self._positions

    def position(self, symbol):
        for held in self._positions:
            if held.symbol == symbol:
                return held
        return BrokerPosition(symbol, 0.0, 0.0)


class TestReconcile:
    def test_agreement_matches(self):
        [row] = reconcile({"SPY": 12.0}, StubBroker([BrokerPosition("SPY", 12.0, 640)]))
        assert row.matches and row.drift == 0

    def test_reports_a_shortfall(self):
        [row] = reconcile({"SPY": 12.0}, StubBroker([BrokerPosition("SPY", 8.0, 640)]))
        assert not row.matches
        assert row.drift == -4.0
        assert "run expects 12" in row.describe()

    def test_catches_a_position_the_run_knows_nothing_about(self):
        # The dangerous half: something is held that nobody is managing.
        rows = reconcile({}, StubBroker([BrokerPosition("TSLA", 3.0, 400)]))
        assert [r.symbol for r in rows] == ["TSLA"]
        assert not rows[0].matches and rows[0].expected == 0.0

    def test_checks_the_union_of_both_sides(self):
        rows = reconcile(
            {"SPY": 1.0, "QQQ": 2.0}, StubBroker([BrokerPosition("TSLA", 3.0, 400)])
        )
        assert [r.symbol for r in rows] == ["QQQ", "SPY", "TSLA"]
        assert not any(r.matches for r in rows)

    def test_a_flat_expectation_against_a_flat_broker_matches(self):
        assert reconcile({}, StubBroker([])) == []

    def test_tolerates_float_dust(self):
        row = Reconciliation("SPY", 12.0, 12.0 + 1e-9)
        assert row.matches

    def test_a_real_difference_is_not_dust(self):
        assert not Reconciliation("SPY", 12.0, 12.01).matches


class TestLatestPrice:
    def test_reads_the_last_trade(self):
        api, _ = broker({
            ("GET", "/v2/stocks/SPY/trades/latest"): {
                "symbol": "SPY", "trade": {"p": 641.23, "s": 100}
            }
        })
        assert api.latest_price("SPY") == 641.23

    def test_rejects_a_shape_it_cannot_read(self):
        api, _ = broker({("GET", "/v2/stocks/SPY/trades/latest"): {"oops": True}})
        with pytest.raises(BrokerError, match="could not read a latest price"):
            api.latest_price("SPY")

    def test_rejects_a_non_positive_price(self):
        api, _ = broker({
            ("GET", "/v2/stocks/SPY/trades/latest"): {"trade": {"p": 0}}
        })
        with pytest.raises(BrokerError, match="latest price for SPY was 0"):
            api.latest_price("SPY")
