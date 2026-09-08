"""Turning a rule's decision into a broker order.

The planning is a pure function so the arithmetic that decides how many shares
to move is testable without a broker, a network or a clock. Everything that can
refuse to trade does so here, before an order exists.

Three refusals are deliberate:

- a stale bar means the feed is behind, and acting on a price that may be days
  old is worse than doing nothing;
- a position that disagrees with what the run expects is not something to trade
  on top of — the divergence compounds;
- an order is planned in whole shares, rounded *down*, so a sizing error
  undershoots rather than overshooting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .broker import Broker, Reconciliation, reconcile
from .models import Side


class NotSafeToTrade(RuntimeError):
    """A precondition failed. No order was built."""


@dataclass(frozen=True)
class Intent:
    """What to do about one symbol, including doing nothing."""

    symbol: str
    side: Side | None
    quantity: float
    reason: str

    @property
    def is_action(self) -> bool:
        return self.side is not None and self.quantity > 0

    def describe(self) -> str:
        if not self.is_action:
            return f"{self.symbol}: no order — {self.reason}"
        return (
            f"{self.symbol}: {self.side.value} {self.quantity:g} — {self.reason}"
        )


def check_freshness(
    latest_bar: datetime, now: datetime, max_age_days: int = 4
) -> None:
    """Refuse to act on a price the feed has not refreshed recently.

    Four days covers a long weekend plus a holiday. A wider gap means the fetch
    has been failing, and the rule's view of the market is not current.
    """
    if max_age_days <= 0:
        raise ValueError("max_age_days must be positive")
    age = now - latest_bar
    if age > timedelta(days=max_age_days):
        raise NotSafeToTrade(
            f"latest bar is {latest_bar.date()}, {age.days} days old "
            f"(limit {max_age_days}); the feed is behind, so no order was built"
        )


def check_reconciled(rows: list[Reconciliation]) -> None:
    """Refuse to trade while the broker and the run disagree about holdings."""
    drifted = [row for row in rows if not row.matches]
    if drifted:
        detail = "; ".join(row.describe() for row in drifted)
        raise NotSafeToTrade(
            f"positions disagree, so no order was built: {detail}. "
            "Reconcile by hand — trading on top of a divergence compounds it."
        )


def plan_order(
    symbol: str,
    want_long: bool,
    price: float,
    equity: float,
    current_quantity: float,
    threshold: float = 0.2,
    whole_shares: bool = True,
) -> Intent:
    """How many shares to move to reach the rule's target.

    Sizing is against *broker* equity, not the simulated portfolio: the account
    that will actually be charged is the one that decides what is affordable.

    Buys round down to whole shares so a sizing error undershoots. Exits sell
    the entire position rather than a rounded target, because leaving a rump
    holding after the rule has gone flat is its own kind of wrong.
    """
    if price <= 0 or equity <= 0:
        return Intent(symbol, None, 0.0, "no price or no equity")

    current_weight = current_quantity * price / equity
    target_weight = 1.0 if want_long else 0.0

    if not want_long:
        if current_quantity <= 0:
            return Intent(symbol, None, 0.0, "already flat")
        # Exits are never banded: flat means flat.
        return Intent(
            symbol, Side.SELL, current_quantity, "rule is flat, closing position"
        )

    if abs(target_weight - current_weight) < threshold:
        return Intent(
            symbol,
            None,
            0.0,
            f"within the {threshold:g} band (weight {current_weight:.2f})",
        )

    target_quantity = equity / price
    delta = target_quantity - current_quantity
    if whole_shares:
        delta = math.floor(delta)
    if delta <= 0:
        return Intent(symbol, None, 0.0, "less than one whole share to buy")
    return Intent(
        symbol, Side.BUY, float(delta), f"rule is long, weight {current_weight:.2f}"
    )


def plan(
    broker: Broker,
    symbol: str,
    want_long: bool,
    latest_bar: datetime,
    now: datetime,
    expected_quantity: float | None = None,
    threshold: float = 0.2,
    max_age_days: int = 4,
    price: float | None = None,
) -> Intent:
    """Run every refusal, then plan. Raises `NotSafeToTrade` rather than trading.

    The price is fetched for `symbol` from the broker, deliberately: the rule
    may have decided on an index it cannot trade, and sizing an order off that
    index's level would buy the wrong amount by whatever ratio separates the
    two — an S&P level near 6,400 against an ETF near 640 is a tenfold error.
    Pass `price` only to override that lookup.

    `expected_quantity` is what the run believes it holds. Passing None skips
    the reconciliation gate, which is only appropriate before the first order
    has ever been placed.
    """
    check_freshness(latest_bar, now, max_age_days)
    held = broker.position(symbol)
    if expected_quantity is not None:
        check_reconciled(reconcile({symbol: expected_quantity}, broker))
    account = broker.account()
    traded_price = price if price is not None else broker.latest_price(symbol)
    return plan_order(
        symbol, want_long, traded_price, account.equity, held.quantity, threshold
    )
