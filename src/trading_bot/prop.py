"""Surviving a funded prop account, where the drawdown is the whole game.

A retail brokerage account dies when it runs out of money. A funded prop
account dies when it touches a line that moves *up* behind you and never
comes back down. That single difference invalidates most position sizing
advice, because the usual advice assumes your loss budget is a fraction of
your capital. Here it is a fixed dollar amount, it is small relative to the
notional you are handed, and winning trades can consume it.

The rule that surprises people is the intraday trail. On an account whose
peak is marked on *unrealized* equity, a trade that goes 20 points your way
and then comes back to breakeven has cost you nothing in balance and a full
20 points of drawdown room. You paid for a winner you never banked. Every
function here exists because that mechanic is invisible in a normal backtest.

Nothing in this module predicts a price. It answers three arithmetic
questions: how much room is left, how large a position that room permits,
and what fraction of traders with a given edge reach a payout before the
floor reaches them. The last one is usually the unwelcome number.

Firm rules change often and differ per account. Every figure here is a
parameter, and `PRESETS` is a convenience that must be checked against your
own account page before it is trusted — see `PRESETS`' docstring.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

__all__ = [
    "Instrument",
    "INSTRUMENTS",
    "PropAccount",
    "PRESETS",
    "DrawdownFloor",
    "RuinEstimate",
    "contracts_for_risk",
    "expectancy",
    "breakeven_win_rate",
    "ruin_probability",
    "max_risk_per_trade",
]


@dataclass(frozen=True)
class Instrument:
    """A futures contract's tick arithmetic.

    `round_turn_cost` is commission plus exchange and clearing fees for a
    complete in-and-out trade. It is a default, not a quote: prop platforms
    bill differently and the number belongs in your own account statement.
    """

    symbol: str
    tick_size: float
    tick_value: float
    round_turn_cost: float
    is_micro: bool

    def ticks_to_dollars(self, ticks: float) -> float:
        return ticks * self.tick_value

    def points_to_dollars(self, points: float) -> float:
        return points / self.tick_size * self.tick_value


# Tick specifications are exchange-defined and stable. Costs are estimates.
INSTRUMENTS: dict[str, Instrument] = {
    "ES": Instrument("ES", 0.25, 12.50, 4.00, is_micro=False),
    "MES": Instrument("MES", 0.25, 1.25, 1.00, is_micro=True),
    "NQ": Instrument("NQ", 0.25, 5.00, 4.00, is_micro=False),
    "MNQ": Instrument("MNQ", 0.25, 0.50, 1.00, is_micro=True),
    "CL": Instrument("CL", 0.01, 10.00, 4.00, is_micro=False),
    "MCL": Instrument("MCL", 0.01, 1.00, 1.00, is_micro=True),
    "GC": Instrument("GC", 0.10, 10.00, 4.00, is_micro=False),
    "MGC": Instrument("MGC", 0.10, 1.00, 1.00, is_micro=True),
}


@dataclass(frozen=True)
class PropAccount:
    """The ruleset a funded account is judged against.

    `max_loss_limit` is the trailing drawdown in dollars — the distance the
    floor sits below the peak. `trail` picks what marks that peak:

    - ``"intraday"``: unrealized equity counts. The floor ratchets while a
      trade is open, so giving back an open profit costs real room.
    - ``"end_of_day"``: only the closing balance counts. Intraday round trips
      are free, which makes this materially more forgiving.

    `trail_stops_at_start` encodes the usual concession that the floor stops
    rising once it reaches the starting balance, so a sufficiently profitable
    account can no longer be failed — only drawn down to breakeven.
    """

    name: str
    starting_balance: float
    max_loss_limit: float
    profit_target: float | None = None
    max_minis: int = 0
    max_micros: int = 0
    trail: str = "intraday"
    trail_stops_at_start: bool = True

    def __post_init__(self) -> None:
        if self.trail not in ("intraday", "end_of_day"):
            raise ValueError(f"unknown trail mode: {self.trail!r}")
        if self.max_loss_limit <= 0:
            raise ValueError("max_loss_limit must be positive")


# Published figures change without notice and differ by account generation.
# These are a starting point to be overwritten with your own account's page,
# not a source of truth. `research/prop_risk.py --help` says how to override.
#
# TPT100's drawdown and target were confirmed against a live account on
# 2026-09-15. The rest remain inferred from published tables and the 6%
# target, and the contract caps are inferred for every size including TPT100.
PRESETS: dict[str, PropAccount] = {
    "TPT25": PropAccount("TPT25", 25_000, 1_500, 1_500, 3, 30),
    "TPT50": PropAccount("TPT50", 50_000, 2_000, 3_000, 6, 60),
    "TPT75": PropAccount("TPT75", 75_000, 2_500, 4_500, 9, 90),
    "TPT100": PropAccount("TPT100", 100_000, 3_000, 6_000, 12, 120),  # confirmed
    "TPT150": PropAccount("TPT150", 150_000, 4_500, 9_000, 18, 180),
}


class DrawdownFloor:
    """The moving line the account dies on.

    Feed it every equity mark you care about. In ``intraday`` mode that means
    open-trade equity, not just closed balance — marking only on closes models
    a gentler account than the one you are trading.
    """

    def __init__(self, account: PropAccount) -> None:
        self.account = account
        self.balance = account.starting_balance
        self.peak = account.starting_balance
        self._breached = False

    @property
    def floor(self) -> float:
        floor = self.peak - self.account.max_loss_limit
        if self.account.trail_stops_at_start:
            floor = min(floor, self.account.starting_balance)
        return floor

    @property
    def room(self) -> float:
        """Dollars of loss available before the account is failed."""
        return self.balance - self.floor

    @property
    def breached(self) -> bool:
        return self._breached

    def mark(self, equity: float) -> None:
        """Observe open-trade equity. Raises the peak in intraday mode only."""
        if equity <= self.floor:
            self._breached = True
        if self.account.trail == "intraday":
            self.peak = max(self.peak, equity)

    def close_trade(self, pnl: float) -> None:
        """Settle a realized result into the balance."""
        self.balance += pnl
        if self.balance <= self.floor:
            self._breached = True
        self.peak = max(self.peak, self.balance)

    def close_day(self) -> None:
        """End of session. In end-of-day mode this is what marks the peak."""
        if self.account.trail == "end_of_day":
            self.peak = max(self.peak, self.balance)


def contracts_for_risk(
    risk_dollars: float,
    stop_ticks: float,
    instrument: Instrument,
    account: PropAccount,
) -> int:
    """Largest position whose stop loss costs no more than `risk_dollars`.

    Rounds *down*, so a sizing error undershoots, and includes the round-turn
    cost in the loss — a stop that is exactly your risk budget breaches it
    once commission is paid. Returns 0 when even one contract is too large,
    which is a refusal to trade rather than a suggestion to widen the stop.
    """
    if stop_ticks <= 0:
        raise ValueError("stop_ticks must be positive")
    per_contract = instrument.ticks_to_dollars(stop_ticks) + instrument.round_turn_cost
    if per_contract <= 0:
        raise ValueError("instrument has non-positive loss per contract")
    cap = account.max_micros if instrument.is_micro else account.max_minis
    return max(0, min(int(risk_dollars // per_contract), cap))


def expectancy(win_rate: float, reward_risk: float, cost_ratio: float = 0.0) -> float:
    """Expected profit per trade in units of risk (R).

    `cost_ratio` is the round-turn cost expressed in R, and it is subtracted
    from every trade, winner or loser. A rule showing positive expectancy
    gross and negative net is the normal case at small stop distances.
    """
    return win_rate * reward_risk - (1.0 - win_rate) * 1.0 - cost_ratio


def breakeven_win_rate(reward_risk: float, cost_ratio: float = 0.0) -> float:
    """Win rate at which `expectancy` is exactly zero."""
    return (1.0 + cost_ratio) / (1.0 + reward_risk)


@dataclass(frozen=True)
class RuinEstimate:
    """Outcome frequencies from a Monte Carlo over trade sequences."""

    ruin: float
    target: float
    undecided: float
    median_trades_to_target: int | None
    mean_peak_room_used: float
    trials: int = field(default=0, compare=False)

    def __str__(self) -> str:
        median = "n/a" if self.median_trades_to_target is None else str(self.median_trades_to_target)
        return (
            f"ruin {self.ruin:6.1%}   target {self.target:6.1%}   "
            f"undecided {self.undecided:6.1%}   median trades to target {median}"
        )


def ruin_probability(
    account: PropAccount,
    risk_dollars: float,
    win_rate: float,
    reward_risk: float,
    *,
    target_dollars: float | None = None,
    give_back: float = 0.0,
    cost_dollars: float = 0.0,
    max_trades: int = 500,
    trials: int = 20_000,
    seed: int = 0,
) -> RuinEstimate:
    """How often a given edge reaches its target before the floor reaches it.

    Each trade wins `reward_risk * risk_dollars` with probability `win_rate`
    and loses `risk_dollars` otherwise, less `cost_dollars` either way.

    `give_back` is the mechanic that makes an intraday-trailed account harder
    than it looks. It is maximum favourable excursion in units of R: how far
    beyond its realized result every trade first ran in your favour. A loser
    goes `give_back` R your way before reversing; a winner exits `give_back`
    R below its own best price. Either way that high-water mark is what the
    floor trails, so you are charged for profit you never banked.

    Set it to 0 only to model an account trailing on closed balance. On an
    intraday-trailed account 0 is not conservative, it is wrong: no trade
    exits at its exact high.

    `undecided` counts paths that did neither within `max_trades` — a large
    value means the horizon, not the edge, decided the answer.
    """
    if not 0.0 <= win_rate <= 1.0:
        raise ValueError("win_rate must be a probability")
    if risk_dollars <= 0:
        raise ValueError("risk_dollars must be positive")
    target = target_dollars if target_dollars is not None else account.profit_target
    if target is None:
        raise ValueError("no target: pass target_dollars or give the account a profit_target")

    rng = random.Random(seed)
    win = reward_risk * risk_dollars - cost_dollars
    loss = -risk_dollars - cost_dollars
    excursion = give_back * risk_dollars
    goal = account.starting_balance + target

    ruined = hit = 0
    trade_counts: list[int] = []
    room_used = 0.0

    for _ in range(trials):
        book = DrawdownFloor(account)
        worst_room = book.room
        for n in range(1, max_trades + 1):
            outcome = win if rng.random() < win_rate else loss
            # The trade's best price, which is what an intraday floor trails.
            book.mark(book.balance + max(outcome, 0.0) + excursion)
            book.close_trade(outcome)
            worst_room = min(worst_room, book.room)
            if book.breached:
                ruined += 1
                break
            if book.balance >= goal:
                hit += 1
                trade_counts.append(n)
                break
        room_used += account.max_loss_limit - max(worst_room, 0.0)

    decided = ruined + hit
    trade_counts.sort()
    median = trade_counts[len(trade_counts) // 2] if trade_counts else None
    return RuinEstimate(
        ruin=ruined / trials,
        target=hit / trials,
        undecided=(trials - decided) / trials,
        median_trades_to_target=median,
        mean_peak_room_used=room_used / trials,
        trials=trials,
    )


def max_risk_per_trade(
    account: PropAccount,
    win_rate: float,
    reward_risk: float,
    *,
    tolerance: float = 0.10,
    target_dollars: float | None = None,
    give_back: float = 0.0,
    cost_dollars: float = 0.0,
    trials: int = 4_000,
    seed: int = 0,
    steps: int = 18,
) -> float:
    """Largest per-trade risk whose ruin probability stays under `tolerance`.

    Bisects on risk. Ruin falls monotonically as risk shrinks for any edge
    worth trading, so the search is well behaved; a negative-expectancy edge
    has no safe size and this returns 0.0 rather than an encouraging number.
    """
    lo, hi = 0.0, account.max_loss_limit
    if ruin_probability(
        account, hi, win_rate, reward_risk,
        target_dollars=target_dollars, give_back=give_back,
        cost_dollars=cost_dollars, trials=trials, seed=seed,
    ).ruin <= tolerance:
        return hi
    for _ in range(steps):
        mid = (lo + hi) / 2
        if mid <= 0:
            break
        estimate = ruin_probability(
            account, mid, win_rate, reward_risk,
            target_dollars=target_dollars, give_back=give_back,
            cost_dollars=cost_dollars, trials=trials, seed=seed,
        )
        if estimate.ruin <= tolerance:
            lo = mid
        else:
            hi = mid
    return lo
