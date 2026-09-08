"""A small, dependency-free toolkit for building and backtesting trading bots."""

from .backtest import (
    BacktestResult,
    EquityMetrics,
    MultiBacktestResult,
    run_backtest,
    run_multi_backtest,
)
from .bonds import modified_duration, par_bond_returns, total_return_index
from .broker import (
    Account,
    AlpacaBroker,
    Broker,
    BrokerError,
    BrokerOrder,
    BrokerPosition,
    Reconciliation,
    RiskLimitExceeded,
    RiskLimits,
    client_order_id,
    reconcile,
)
from .feed import BadBar, MergeResult, format_csv, merge, parse_csv, parse_stooq
from .indicators import ema, rsi, sma
from .live import Intent, NotSafeToTrade, check_freshness, check_reconciled, plan, plan_order
from .models import Candle, Fill, Order, Position, Side, Signal
from .paper import FrozenRule, JournalEntry, PaperRun, Report, years_to_detect
from .portfolio import InsufficientFunds, InsufficientPosition, Portfolio
from .sizing import FullInvestment, PositionSizer, VolatilityTarget
from .strategy import (
    BuyAndHold,
    PriceVsSma,
    SmaCrossover,
    Strategy,
    TimeSeriesMomentum,
)

__version__ = "0.1.0"

__all__ = [
    "Account",
    "AlpacaBroker",
    "BacktestResult",
    "BadBar",
    "Broker",
    "BrokerError",
    "BrokerOrder",
    "BrokerPosition",
    "BuyAndHold",
    "Candle",
    "EquityMetrics",
    "Fill",
    "FrozenRule",
    "FullInvestment",
    "InsufficientFunds",
    "InsufficientPosition",
    "Intent",
    "JournalEntry",
    "MergeResult",
    "MultiBacktestResult",
    "NotSafeToTrade",
    "Order",
    "PaperRun",
    "Portfolio",
    "Position",
    "PositionSizer",
    "PriceVsSma",
    "Reconciliation",
    "Report",
    "RiskLimitExceeded",
    "RiskLimits",
    "Side",
    "Signal",
    "SmaCrossover",
    "Strategy",
    "TimeSeriesMomentum",
    "VolatilityTarget",
    "check_freshness",
    "check_reconciled",
    "client_order_id",
    "ema",
    "format_csv",
    "merge",
    "modified_duration",
    "par_bond_returns",
    "parse_csv",
    "parse_stooq",
    "plan",
    "plan_order",
    "reconcile",
    "rsi",
    "run_backtest",
    "run_multi_backtest",
    "sma",
    "total_return_index",
    "years_to_detect",
]
