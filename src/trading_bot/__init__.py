"""A small, dependency-free toolkit for building and backtesting trading bots."""

from .backtest import BacktestResult, run_backtest
from .indicators import ema, rsi, sma
from .models import Candle, Fill, Order, Position, Side, Signal
from .portfolio import InsufficientFunds, InsufficientPosition, Portfolio
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
    "InsufficientFunds",
    "InsufficientPosition",
    "Order",
    "Portfolio",
    "Position",
    "PriceVsSma",
    "Side",
    "Signal",
    "SmaCrossover",
    "Strategy",
    "TimeSeriesMomentum",
    "ema",
    "rsi",
    "run_backtest",
    "sma",
]
