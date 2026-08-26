"""A small, dependency-free toolkit for building and backtesting trading bots."""

from .backtest import BacktestResult, run_backtest
from .indicators import ema, rsi, sma
from .models import Candle, Fill, Order, Position, Side, Signal
from .portfolio import InsufficientFunds, InsufficientPosition, Portfolio
from .strategy import SmaCrossover, Strategy

__version__ = "0.1.0"

__all__ = [
    "BacktestResult",
    "Candle",
    "Fill",
    "InsufficientFunds",
    "InsufficientPosition",
    "Order",
    "Portfolio",
    "Position",
    "Side",
    "Signal",
    "SmaCrossover",
    "Strategy",
    "ema",
    "rsi",
    "run_backtest",
    "sma",
]
