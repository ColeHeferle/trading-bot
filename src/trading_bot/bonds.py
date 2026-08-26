"""Turning bond yields into something a backtest can actually trade.

A yield is not a price. Buying a bond series quoted in yields would get the
sign backwards — yields rise when prices fall — so a yield series has to be
converted into a total-return index before any strategy touches it.

The index here tracks a *constant-maturity par bond*: at the start of every
period you hold a bond priced at par yielding the current rate, you earn a
period of carry, and you mark it at the next period's yield. That is the same
convention constant-maturity index proxies use, and it is a model rather than a
traded price — see `total_return_index` for what it leaves out.

Yields are decimals throughout: 0.0283, not 2.83.
"""

from __future__ import annotations

from collections.abc import Sequence


def modified_duration(yield_: float, maturity_years: float) -> float:
    """Modified duration of a par bond, in years.

    For a bond priced at par the Macaulay duration collapses to a closed form,
    ``(1 + y) / y * (1 - (1 + y) ** -M)``, which this divides by ``(1 + y)``.
    """
    if maturity_years <= 0:
        raise ValueError(f"maturity_years must be positive, got {maturity_years}")
    if yield_ <= 0:
        # At a zero yield every coupon is undiscounted, so duration is just the
        # average cash-flow time; the closed form divides by y and blows up.
        return maturity_years
    macaulay = (1 + yield_) / yield_ * (1 - (1 + yield_) ** -maturity_years)
    return macaulay / (1 + yield_)


def par_bond_returns(
    yields: Sequence[float],
    maturity_years: float = 10.0,
    periods_per_year: int = 12,
) -> list[float]:
    """Period total returns of a constant-maturity par bond.

    Each return is carry minus the price move implied by the change in yield:
    ``y_prev / periods_per_year - duration * (y_now - y_prev)``. One shorter
    than ``yields``, since the first observation only sets the starting yield.
    """
    if periods_per_year <= 0:
        raise ValueError(f"periods_per_year must be positive, got {periods_per_year}")
    if len(yields) < 2:
        return []

    step = 1.0 / periods_per_year
    out = []
    for previous, current in zip(yields, yields[1:]):
        carry = previous * step
        duration = modified_duration(previous, maturity_years)
        out.append(carry - duration * (current - previous))
    return out


def total_return_index(
    yields: Sequence[float],
    maturity_years: float = 10.0,
    periods_per_year: int = 12,
    start: float = 100.0,
) -> list[float]:
    """Compound `par_bond_returns` into a price series starting at ``start``.

    What this leaves out: convexity, so a large yield move is overstated as a
    loss and understated as a gain (second order, and small for the monthly
    steps this was built for); the roll-down pickup from a curve that is not
    flat; bid-offer and financing. It is a defensible proxy for a bond index,
    not a bond you could have bought.
    """
    if start <= 0:
        raise ValueError(f"start must be positive, got {start}")

    level = start
    index = [level]
    for period_return in par_bond_returns(yields, maturity_years, periods_per_year):
        level *= 1.0 + period_return
        index.append(level)
    return index
