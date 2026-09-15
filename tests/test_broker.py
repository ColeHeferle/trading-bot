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


# `submit` prices every order to enforce the notional ceiling, so the price
# endpoint is part of the default fake rather than something each test repeats.
# 12 SPY at this price is well under the default ceiling.
PRICE_PATH = "/v2/stocks/SPY/trades/latest"
PRICE_RESPONSE = {"symbol": "SPY", "trade": {"p": 641.23, "s": 100}}


def broker(responses=None, **kw):
    responses = dict(responses or {})
    responses.setdefault(("GET", PRICE_PATH), PRICE_RESPONSE)
    transport = FakeTransport(responses)
    return AlpacaBroker("key", "secret", transport=transport, **kw), transport


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

        # A price lookup precedes the order now, so find the POST rather than
        # assuming it is first.
        _, path, body = next(c for c in transport.calls if c[0] == "POST")
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
        assert sum(1 for m, p, _ in transport.calls if m == "POST") == 1

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

    def test_the_limit_blocks_the_order_before_it_is_sent(self):
        api, transport = broker(limits=RiskLimits(max_order_quantity=5))
        with pytest.raises(RiskLimitExceeded):
            api.submit("SPY", Side.BUY, 50, "x")
        # Pricing the order is allowed; sending it is not.
        assert [c for c in transport.calls if c[0] == "POST"] == []


class TestTheNotionalCeilingReachesTheOrderPath:
    """The dollar ceiling has to bind where orders are actually placed.

    It did not. `submit` called `limits.check(symbol, quantity, None)`, and the
    notional test inside `check` is guarded by `price is not None`, so it never
    ran. Only the share count applied: a fully invested QQQ order — about four
    times the $25,000 default — was sent. `TestRiskLimits` passed throughout,
    because it calls `check` directly with a price the order path never
    supplied.

    So these tests go through `submit`. A unit test of `check` cannot tell the
    difference between this working and this being unreachable.
    """

    def test_an_order_over_the_ceiling_is_refused(self):
        api, transport = broker(
            {("POST", "/v2/orders"): order_payload()},
            limits=RiskLimits(max_order_notional=5_000),
        )
        # 12 x 641.23 = 7,694.76, over the ceiling but only 12 shares.
        with pytest.raises(RiskLimitExceeded, match="max_order_notional"):
            api.submit("SPY", Side.BUY, 12, "tb-big")
        assert [c for c in transport.calls if c[0] == "POST"] == []

    def test_an_order_under_the_ceiling_still_goes(self):
        api, transport = broker(
            {("POST", "/v2/orders"): order_payload()},
            limits=RiskLimits(max_order_notional=50_000),
        )
        api.submit("SPY", Side.BUY, 12, "tb-ok")
        assert [c for c in transport.calls if c[0] == "POST"]

    def test_the_price_is_fetched_rather_than_left_to_the_caller(self):
        """Omitting the argument must not be a way to skip the ceiling."""
        api, transport = broker(
            {("POST", "/v2/orders"): order_payload()},
            limits=RiskLimits(max_order_notional=5_000),
        )
        with pytest.raises(RiskLimitExceeded):
            api.submit("SPY", Side.BUY, 12, "tb-x")
        assert any(PRICE_PATH in path for _, path, _ in transport.calls)

    def test_an_explicit_price_overrides_the_lookup(self):
        api, transport = broker(
            {("POST", "/v2/orders"): order_payload()},
            limits=RiskLimits(max_order_notional=5_000),
        )
        api.submit("SPY", Side.BUY, 12, "tb-cheap", price=1.0)
        assert not any(PRICE_PATH in path for _, path, _ in transport.calls)
        assert [c for c in transport.calls if c[0] == "POST"]

    def test_an_unpriceable_order_is_refused_rather_than_sent_unchecked(self):
        """Failing open here would put the hole back, only intermittently."""
        api, transport = broker({
            ("GET", PRICE_PATH): BrokerError("GET price -> 500: boom"),
            ("POST", "/v2/orders"): order_payload(),
        })
        with pytest.raises(BrokerError, match="500"):
            api.submit("SPY", Side.BUY, 12, "tb-noprice")
        assert [c for c in transport.calls if c[0] == "POST"] == []

    def test_a_retry_is_still_recoverable_when_the_price_lookup_fails(self):
        """Refusing must not cost the duplicate-id protection.

        A retry of an id the broker already holds adds no exposure, so there is
        nothing for the ceiling to protect against — and the alternative is
        leaving a placed order unrecorded because a data endpoint was down.
        """
        api, transport = broker({
            ("GET", PRICE_PATH): BrokerError("GET price -> 500: boom"),
            ("GET", "/v2/orders:by_client_order_id?client_order_id=tb-dup"):
                order_payload(client_order_id="tb-dup", status="filled",
                              filled_qty="12", filled_avg_price="640"),
        })
        placed = api.submit("SPY", Side.BUY, 12, "tb-dup")
        assert placed.is_filled
        assert [c for c in transport.calls if c[0] == "POST"] == []


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


class TestWhatA401Says:
    """A rejected credential and a wrong one look identical from the response.

    Alpaca answers `{"message": "unauthorized."}` either way, which is true and
    useless — it cost a round trip of guessing. The transport holds the key id
    and the endpoint, so two of the three usual causes are checkable rather
    than guessable, and it should say which one it found.
    """

    def transport(self, key="PKTEST", secret="s", url=PAPER_URL):
        return __import__(
            "trading_bot.broker", fromlist=["HttpTransport"]
        ).HttpTransport(url, key, secret)

    def reject(self, monkeypatch, transport, code=401):
        """Make urlopen raise the HTTPError Alpaca would return."""
        import io
        import urllib.error
        import urllib.request

        def urlopen(request, timeout=None):
            raise urllib.error.HTTPError(
                request.full_url, code, "Unauthorized", {},
                io.BytesIO(b'{"message": "unauthorized."}'),
            )

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        with pytest.raises(BrokerError) as caught:
            transport.request("GET", "/v2/positions")
        return str(caught.value)

    def test_a_live_key_against_paper_is_named_as_such(self, monkeypatch):
        """The single most diagnostic character: PK for paper, AK for live."""
        message = self.reject(monkeypatch, self.transport(key="AKLIVE123"))
        assert "401" in message and "unauthorized." in message
        assert "'AK'" in message and "'PK'" in message
        assert "Paper Trading" in message

    def test_whitespace_is_named_ahead_of_everything_else(self, monkeypatch):
        """It survives a save, is invisible on screen, and always 401s."""
        message = self.reject(monkeypatch, self.transport(key="PKTEST ", secret="s"))
        assert "whitespace" in message
        message = self.reject(monkeypatch, self.transport(key="PKTEST", secret=" s"))
        assert "whitespace" in message

    def test_a_plausible_key_points_at_the_mismatched_pair(self, monkeypatch):
        """Nothing checkable is wrong, so say the thing that usually is."""
        message = self.reject(monkeypatch, self.transport())
        assert "same generation" in message
        assert "whitespace" not in message and "'PK'" not in message

    def test_the_paper_prefix_rule_is_not_applied_to_the_data_host(
        self, monkeypatch
    ):
        """Market data takes the same keys on a different host."""
        from trading_bot.broker import DATA_URL

        message = self.reject(
            monkeypatch, self.transport(key="AKLIVE123", url=DATA_URL)
        )
        assert "'PK'" not in message

    def test_other_statuses_are_left_alone(self, monkeypatch):
        """A 404 means a wrong path, and credential advice would mislead."""
        message = self.reject(monkeypatch, self.transport(), code=404)
        assert "404" in message
        assert "whitespace" not in message and "same generation" not in message

    def test_a_newline_is_refused_before_it_is_sent(self):
        """urllib rejects such a header, which was a bare traceback before."""
        with pytest.raises(BrokerError, match="newline"):
            self.transport(key="PKTEST\n").request("GET", "/v2/account")
