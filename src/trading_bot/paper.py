"""Forward testing: run a frozen rule against bars as they arrive.

The point of this module is not to discover an edge. A backtest can be tuned
until it looks good; a forward test cannot, because the rule is fixed before
the data exists. What it is actually good for:

- catching implementation bugs that a backtest hides,
- noticing when a rule stops behaving the way it did historically,
- and keeping an honest, tamper-evident record of what was decided when.

What it is *not* good for is proving profitability. See `Report.honesty` — for
a rule whose edge over buy-and-hold is as thin as the ones measured here, the
forward test would need to run for longer than recorded history before the
result could be told apart from luck.

State is the whole bar history, replayed on load. Strategies are stateful and
serializing their internals would be fragile; replaying is deterministic, and
it means a tampered rule no longer reproduces its own journal.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Candle, Fill, Signal
from .portfolio import Portfolio
from .sizing import FullInvestment, PositionSizer, VolatilityTarget
from .strategy import (
    BuyAndHold,
    PriceVsSma,
    SmaCrossover,
    Strategy,
    TimeSeriesMomentum,
)

# Only rules that can be named here may be frozen, so a run cannot smuggle in
# an anonymous lambda that nobody can reconstruct later.
STRATEGIES: dict[str, type[Strategy]] = {
    "BuyAndHold": BuyAndHold,
    "SmaCrossover": SmaCrossover,
    "PriceVsSma": PriceVsSma,
    "TimeSeriesMomentum": TimeSeriesMomentum,
}

SIZERS: dict[str, type[PositionSizer]] = {
    "FullInvestment": FullInvestment,
    "VolatilityTarget": VolatilityTarget,
}


@dataclass(frozen=True)
class FrozenRule:
    """A rule pinned down before any forward data exists.

    The `fingerprint` is what makes the freeze meaningful: commit it, and any
    later change to the strategy, its parameters, the costs or the instrument
    produces a different one.
    """

    strategy: str
    params: dict[str, Any]
    symbol: str
    initial_cash: float = 10_000.0
    fee_rate: float = 0.0005
    note: str = ""
    warmup_until: str | None = None
    sizer: str | None = None
    sizer_params: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.strategy not in STRATEGIES:
            raise ValueError(
                f"unknown strategy {self.strategy!r}; "
                f"known: {sorted(STRATEGIES)}"
            )
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if self.fee_rate < 0:
            raise ValueError("fee_rate must not be negative")
        if self.warmup_until is not None:
            try:
                datetime.fromisoformat(self.warmup_until)
            except ValueError as exc:
                raise ValueError(
                    f"warmup_until must be an ISO date, got {self.warmup_until!r}"
                ) from exc
        if self.sizer is not None and self.sizer not in SIZERS:
            raise ValueError(
                f"unknown sizer {self.sizer!r}; known: {sorted(SIZERS)}"
            )
        if self.sizer is None and self.sizer_params:
            raise ValueError("sizer_params given without a sizer")
        # Fail here rather than at the first bar, months later.
        STRATEGIES[self.strategy](**self.params)
        self.build_sizer()

    @property
    def warmup_boundary(self) -> datetime | None:
        """First instant that counts as live, or None if everything counts."""
        if self.warmup_until is None:
            return None
        return datetime.fromisoformat(self.warmup_until)

    def build(self) -> Strategy:
        return STRATEGIES[self.strategy](**self.params)

    def build_sizer(self) -> PositionSizer:
        """The sizer this rule was frozen with, or full investment.

        A rule frozen without one is fully invested whenever it is long, which
        is what every run recorded before sizers existed did.
        """
        if self.sizer is None:
            return FullInvestment()
        return SIZERS[self.sizer](**(self.sizer_params or {}))

    def as_dict(self) -> dict[str, Any]:
        fields = {
            "strategy": self.strategy,
            "params": self.params,
            "symbol": self.symbol,
            "initial_cash": self.initial_cash,
            "fee_rate": self.fee_rate,
            "note": self.note,
        }
        # Absent and None are the same rule, and omitting the key keeps the
        # fingerprints of runs frozen before warmup existed unchanged. The same
        # applies to sizing: a rule with no sizer hashes exactly as it did
        # before sizers existed, so already-frozen runs still load.
        if self.warmup_until is not None:
            fields["warmup_until"] = self.warmup_until
        if self.sizer is not None:
            fields["sizer"] = self.sizer
            fields["sizer_params"] = self.sizer_params or {}
        return fields

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


@dataclass
class JournalEntry:
    timestamp: datetime
    close: float
    signal: str
    quantity: float
    equity: float
    benchmark_equity: float


@dataclass
class Report:
    rule: FrozenRule
    bars: int
    started: datetime | None
    latest: datetime | None
    equity: float
    benchmark_equity: float
    trades: int
    warmup_bars: int = 0

    @property
    def total_return(self) -> float:
        return self.equity / self.rule.initial_cash - 1.0

    @property
    def benchmark_return(self) -> float:
        return self.benchmark_equity / self.rule.initial_cash - 1.0

    @property
    def excess(self) -> float:
        return self.total_return - self.benchmark_return

    @property
    def elapsed_years(self) -> float:
        if not self.started or not self.latest:
            return 0.0
        return (self.latest - self.started).days / 365.25


class PaperRun:
    """A frozen rule, the bars it has seen, and what it did with them."""

    def __init__(self, rule: FrozenRule) -> None:
        self.rule = rule
        self.bars: list[Candle] = []
        self.journal: list[JournalEntry] = []
        self._reset_engines()

    def _reset_engines(self) -> None:
        self._strategy = self.rule.build()
        self._sizer = self.rule.build_sizer()
        self._benchmark_strategy = BuyAndHold()
        self._portfolio = Portfolio(self.rule.initial_cash, self.rule.fee_rate)
        self._benchmark = Portfolio(self.rule.initial_cash, self.rule.fee_rate)
        self._long = False
        self._last_weight = 0.0

    def step(self, candle: Candle) -> JournalEntry | None:
        """Feed one new bar. Bars must arrive in order and only once.

        Returns None for a warmup bar: it advances the strategy's averages but
        does not trade and does not enter the record.
        """
        if self.bars and candle.timestamp <= self.bars[-1].timestamp:
            raise ValueError(
                f"bar for {candle.timestamp} is not newer than the last seen "
                f"{self.bars[-1].timestamp}; forward tests never rewrite history"
            )
        self.bars.append(candle)
        return self._apply(candle)

    def is_live(self, stamp: datetime) -> bool:
        boundary = self.rule.warmup_boundary
        return boundary is None or stamp >= boundary

    def _apply(self, candle: Candle) -> JournalEntry | None:
        signal = self._strategy.on_candle(candle)
        if signal is Signal.BUY:
            self._long = True
        elif signal is Signal.SELL:
            self._long = False

        # Fed on every bar including warmup. A sizer that only saw live bars
        # would hold nothing for its first `lookback` days of real trading,
        # which is the same in-sample trap warmup exists to avoid — except it
        # would cost real position rather than just accuracy.
        # Fed on EVERY bar, whatever the position: volatility is a property of
        # the market, not of what we happen to be holding. Feeding it only
        # while long would estimate from a discontinuous subsample and leave
        # the window empty through any flat stretch, so the rule would come
        # back from being flat holding nothing.
        sized = self._sizer.weight(candle)
        weight = sized if self._long else 0.0
        self._last_weight = weight

        # Warmup bars exist only to fill the strategy's windows. They must not
        # trade and must not reach the equity curve: they are history the rule
        # was chosen against, so counting them would dress up in-sample data as
        # forward evidence. The long/flat state they leave behind is kept, so a
        # rule already long on the freeze date enters on its first live bar.
        if not self.is_live(candle.timestamp):
            return None

        self._trade(self._portfolio, candle, weight)
        # The benchmark is only fed live bars, so buy-and-hold starts on the
        # same bar the rule does rather than at the top of the warmup.
        if self._benchmark_strategy.on_candle(candle) is Signal.BUY:
            self._trade(self._benchmark, candle, 1.0)

        entry = JournalEntry(
            timestamp=candle.timestamp,
            close=candle.close,
            signal=signal.value,
            quantity=self._portfolio.quantity(self.rule.symbol),
            equity=self._portfolio.equity({self.rule.symbol: candle.close}),
            benchmark_equity=self._benchmark.equity({self.rule.symbol: candle.close}),
        )
        self.journal.append(entry)
        return entry

    def _trade(self, portfolio: Portfolio, candle: Candle, weight: float) -> None:
        from .backtest import _rebalance

        _rebalance(
            portfolio,
            self.rule.symbol,
            candle.close,
            candle.timestamp,
            weight,
            threshold=0.2,
            equity=portfolio.equity({self.rule.symbol: candle.close}),
        )

    @property
    def target_weight(self) -> float:
        """The fraction of equity the rule wants held right now.

        This is what the live path must act on. A rule with no sizer answers
        1.0 or 0.0; one frozen with a volatility target answers a different
        number every day, and acting on `journal[-1].quantity > 0` instead
        would silently discard the sizing.
        """
        return self._last_weight

    @property
    def fills(self) -> list[Fill]:
        """Everything the rule traded. Empty while still in warmup."""
        return self._portfolio.fills

    @property
    def benchmark_fills(self) -> list[Fill]:
        return self._benchmark.fills

    @property
    def report(self) -> Report:
        # Counted from the journal, not the bar list, so warmup never inflates
        # the elapsed window a result is judged over.
        return Report(
            rule=self.rule,
            bars=len(self.journal),
            warmup_bars=len(self.bars) - len(self.journal),
            started=self.journal[0].timestamp if self.journal else None,
            latest=self.journal[-1].timestamp if self.journal else None,
            equity=self.journal[-1].equity if self.journal else self.rule.initial_cash,
            benchmark_equity=(
                self.journal[-1].benchmark_equity
                if self.journal
                else self.rule.initial_cash
            ),
            trades=len(self._portfolio.fills),
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "rule": self.rule.as_dict(),
                "fingerprint": self.rule.fingerprint,
                "bars": [
                    {
                        "timestamp": c.timestamp.isoformat(),
                        "open": c.open,
                        "high": c.high,
                        "low": c.low,
                        "close": c.close,
                        "volume": c.volume,
                    }
                    for c in self.bars
                ],
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> PaperRun:
        """Rebuild by replaying the stored bars through the stored rule.

        If the rule was edited after the fact, the fingerprint recorded in the
        file will not match the one the rule now produces, and this refuses to
        load rather than quietly reporting results the rule never generated.
        """
        payload = json.loads(text)
        rule = FrozenRule(**payload["rule"])
        recorded = payload.get("fingerprint")
        if recorded and recorded != rule.fingerprint:
            raise ValueError(
                f"rule fingerprint changed since this run started "
                f"({recorded} -> {rule.fingerprint}); the frozen rule was edited"
            )

        run = cls(rule)
        for bar in payload["bars"]:
            run.step(
                Candle(
                    datetime.fromisoformat(bar["timestamp"]),
                    bar["open"],
                    bar["high"],
                    bar["low"],
                    bar["close"],
                    bar.get("volume", 0.0),
                )
            )
        return run

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json())

    @classmethod
    def load(cls, path: str | Path) -> PaperRun:
        return cls.from_json(Path(path).read_text())


def years_to_detect(information_ratio: float, t_stat: float = 2.0) -> float:
    """Years of forward data needed before an edge clears ``t_stat``.

    The t-statistic of a mean return grows as ``IR * sqrt(years)``, so the
    required span is ``(t / IR) ** 2``. This is the number that decides whether
    a forward test can answer the question at all — for a thin edge it comes
    back in centuries, and no amount of patience fixes that.
    """
    if information_ratio <= 0:
        return math.inf
    return (t_stat / information_ratio) ** 2
