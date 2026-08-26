"""A small, dependency-free toolkit for building and backtesting trading bots."""

from .backtest import BacktestResult, run_backtest
from .indicators import ema, rsi, sma
from .models import Candle, Fill, Order, Position, Side, Signal
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
    "BuyAndHold",
    "Candle",
    "Fill",
    "FullInvestment",
    "InsufficientFunds",
    "InsufficientPosition",
    "Order",
    "Portfolio",
    "Position",
    "PositionSizer",
    "PriceVsSma",
    "Side",
    "Signal",
    "SmaCrossover",
    "Strategy",
    "TimeSeriesMomentum",
    "VolatilityTarget",
    "ema",
    "rsi",
    "run_backtest",
    "sma",
]
