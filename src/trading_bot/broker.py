"""Talking to a broker, starting with Alpaca's paper sandbox.

Everything except the socket is separable: `AlpacaBroker` takes a `Transport`,
so the request shapes, the retry-safety and the reconciliation are all testable
without a network. `HttpTransport` is the only part that touches one.

The endpoint paths and JSON field names here were written from knowledge of
Alpaca's v2 API rather than against the live service, because the environment
this was built in cannot reach it. Run `research/broker_check.py` first: it is
read-only and will surface any mismatch before an order is ever placed.

Nothing here is wired into the daily loop. This adapter can place an order when
asked; it is not yet asked by anything.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .models import Side

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"

# Alpaca's terminal and in-flight order states.
FILLED = "filled"
DEAD = frozenset({"canceled", "expired", "rejected", "done_for_day", "suspended"})


class BrokerError(RuntimeError):
    """The broker refused, or answered something we cannot act on."""


class RiskLimitExceeded(BrokerError):
    """An order was larger than the configured ceiling, so it was not sent."""


@dataclass(frozen=True)
class Account:
    cash: float
    equity: float
    buying_power: float
    currency: str = "USD"


@dataclass(frozen=True)
class BrokerPosition:
    symbol: str
    quantity: float
    avg_price: float


@dataclass(frozen=True)
class BrokerOrder:
    id: str
    client_order_id: str
    symbol: str
    side: Side
    quantity: float
    status: str
    filled_quantity: float = 0.0
    filled_price: float | None = None

    @property
    def is_filled(self) -> bool:
        return self.status == FILLED

    @property
    def is_dead(self) -> bool:
        return self.status in DEAD

    @property
    def is_open(self) -> bool:
        return not self.is_filled and not self.is_dead


@dataclass(frozen=True)
class RiskLimits:
    """Ceilings checked before anything is sent.

    A rule that has never traded live is exactly when a sizing bug is most
    likely, so the cap is a hard stop rather than a warning.
    """

    max_order_notional: float = 25_000.0
    max_order_quantity: float = 10_000.0

    def check(self, symbol: str, quantity: float, price: float | None) -> None:
        if quantity <= 0:
            raise RiskLimitExceeded(f"refusing a non-positive order: {quantity}")
        if quantity > self.max_order_quantity:
            raise RiskLimitExceeded(
                f"{quantity} {symbol} exceeds max_order_quantity "
                f"{self.max_order_quantity}"
            )
        if price is not None and quantity * price > self.max_order_notional:
            raise RiskLimitExceeded(
                f"{quantity} {symbol} at {price} is "
                f"{quantity * price:,.2f}, over max_order_notional "
                f"{self.max_order_notional:,.2f}"
            )


def client_order_id(fingerprint: str, stamp: datetime, symbol: str, side: Side) -> str:
    """A stable id for one intent, so a retry cannot double-send.

    Derived from the rule, the bar and the direction — not from the clock or a
    random source — so a crash between sending and recording the response
    produces the *same* id next time. The broker then rejects the duplicate
    instead of opening a second position, which is the failure this exists to
    prevent.
    """
    seed = f"{fingerprint}|{stamp.date().isoformat()}|{symbol}|{side.value}"
    return f"tb-{hashlib.sha256(seed.encode()).hexdigest()[:24]}"


class Transport(Protocol):
    """The seam. Only `HttpTransport` touches a network."""

    def request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> Any: ...


class HttpTransport:
    def __init__(
        self, base_url: str, key_id: str, secret_key: str, timeout: int = 30
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._headers = {
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
            "Content-Type": "application/json",
        }

    def request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, method=method, headers=self._headers
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            # Carry the status so callers can tell "no such position" (404)
            # from "duplicate order" (422) from a real outage.
            raise BrokerError(f"{method} {path} -> {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise BrokerError(f"{method} {path} failed: {exc}") from exc
        return json.loads(raw) if raw.strip() else None


class Broker(ABC):
    @abstractmethod
    def account(self) -> Account: ...

    @abstractmethod
    def positions(self) -> list[BrokerPosition]: ...

    @abstractmethod
    def submit(
        self, symbol: str, side: Side, quantity: float, order_id: str
    ) -> BrokerOrder: ...

    def position(self, symbol: str) -> BrokerPosition:
        for held in self.positions():
            if held.symbol == symbol:
                return held
        return BrokerPosition(symbol, 0.0, 0.0)


class AlpacaBroker(Broker):
    """Alpaca v2, pointed at the paper sandbox unless told otherwise.

    Pointing this at live money takes an explicit `allow_live=True`. The
    default is not merely paper — a live URL without that flag is refused, so
    a copied config or a stray environment variable cannot quietly move real
    money.
    """

    def __init__(
        self,
        key_id: str,
        secret_key: str,
        base_url: str = PAPER_URL,
        transport: Transport | None = None,
        limits: RiskLimits | None = None,
        allow_live: bool = False,
    ) -> None:
        if base_url.rstrip("/") != PAPER_URL and not allow_live:
            raise BrokerError(
                f"{base_url} is not the paper sandbox ({PAPER_URL}). Pass "
                "allow_live=True to trade real money — deliberately, not by "
                "inheriting a config."
            )
        self.base_url = base_url.rstrip("/")
        self.is_paper = self.base_url == PAPER_URL
        self.limits = limits or RiskLimits()
        self._transport = transport or HttpTransport(base_url, key_id, secret_key)

    def account(self) -> Account:
        payload = self._transport.request("GET", "/v2/account")
        return Account(
            cash=float(payload["cash"]),
            equity=float(payload["equity"]),
            buying_power=float(payload["buying_power"]),
            currency=payload.get("currency", "USD"),
        )

    def positions(self) -> list[BrokerPosition]:
        payload = self._transport.request("GET", "/v2/positions") or []
        return [
            BrokerPosition(
                symbol=row["symbol"],
                # Alpaca reports a short as a negative qty; keep the sign so a
                # position we never meant to open is visible rather than hidden.
                quantity=float(row["qty"]),
                avg_price=float(row["avg_entry_price"]),
            )
            for row in payload
        ]

    def submit(
        self, symbol: str, side: Side, quantity: float, order_id: str
    ) -> BrokerOrder:
        """Place a market order, or return the one this id already placed.

        The duplicate case is not an error: it means a previous attempt got
        further than we recorded, and re-sending would double the position.
        """
        self.limits.check(symbol, quantity, None)
        body = {
            "symbol": symbol,
            "qty": str(quantity),
            "side": side.value,
            "type": "market",
            "time_in_force": "day",
            "client_order_id": order_id,
        }
        try:
            return _order(self._transport.request("POST", "/v2/orders", body))
        except BrokerError as exc:
            if "422" not in str(exc):
                raise
            existing = self.order_by_client_id(order_id)
            if existing is None:
                raise
            return existing

    def order_by_client_id(self, order_id: str) -> BrokerOrder | None:
        try:
            payload = self._transport.request(
                "GET", f"/v2/orders:by_client_order_id?client_order_id={order_id}"
            )
        except BrokerError as exc:
            if "404" in str(exc):
                return None
            raise
        return _order(payload) if payload else None


def _order(payload: dict[str, Any]) -> BrokerOrder:
    filled_price = payload.get("filled_avg_price")
    return BrokerOrder(
        id=payload["id"],
        client_order_id=payload["client_order_id"],
        symbol=payload["symbol"],
        side=Side(payload["side"]),
        quantity=float(payload["qty"]),
        status=payload["status"],
        filled_quantity=float(payload.get("filled_qty") or 0.0),
        filled_price=float(filled_price) if filled_price else None,
    )


@dataclass(frozen=True)
class Reconciliation:
    """What the run thinks it holds against what the broker says it holds."""

    symbol: str
    expected: float
    actual: float
    tolerance: float = 1e-6

    @property
    def drift(self) -> float:
        return self.actual - self.expected

    @property
    def matches(self) -> bool:
        return abs(self.drift) <= self.tolerance

    def describe(self) -> str:
        if self.matches:
            return f"{self.symbol}: {self.actual:g} — matches"
        return (
            f"{self.symbol}: run expects {self.expected:g}, broker holds "
            f"{self.actual:g} (drift {self.drift:+g})"
        )


def reconcile(
    expected: dict[str, float], broker: Broker, tolerance: float = 1e-6
) -> list[Reconciliation]:
    """Compare intended holdings against the broker's, both directions.

    A symbol the broker holds that the run knows nothing about is the more
    dangerous half — a stray position nobody is managing — so the union is
    checked rather than only what was expected.
    """
    held = {p.symbol: p.quantity for p in broker.positions()}
    return [
        Reconciliation(symbol, expected.get(symbol, 0.0), held.get(symbol, 0.0), tolerance)
        for symbol in sorted(set(expected) | set(held))
    ]
