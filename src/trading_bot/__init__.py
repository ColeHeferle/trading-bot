"""A small, dependency-free toolkit for building and backtesting trading bots."""

from .backtest import (
    BacktestResult,
    EquityMetrics,
    MultiBacktestResult,
    run_backtest,
    run_multi_backtest,
)
from .bonds import modified_duration, par_bond_returns, total_return_index
from .feed import BadBar, MergeResult, format_csv, merge, parse_csv, parse_stooq
from .indicators import ema, rsi, sma
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
    "BacktestResult",
    "BadBar",
    "BuyAndHold",
    "Candle",
    "EquityMetrics",
    "Fill",
    "FrozenRule",
    "FullInvestment",
    "InsufficientFunds",
    "InsufficientPosition",
    "JournalEntry",
    "MergeResult",
    "MultiBacktestResult",
    "Order",
    "PaperRun",
    "Portfolio",
    "Position",
    "PositionSizer",
    "PriceVsSma",
    "Report",
    "Side",
    "Signal",
    "SmaCrossover",
    "Strategy",
    "TimeSeriesMomentum",
    "VolatilityTarget",
    "ema",
    "format_csv",
    "merge",
    "modified_duration",
    "par_bond_returns",
    "parse_csv",
    "parse_stooq",
    "rsi",
    "run_backtest",
    "run_multi_backtest",
    "sma",
    "total_return_index",
    "years_to_detect",
]
