"""How much history a fetch asks for, which is not a detail.

A live run recorded 20 bars for a rule that needs 50 before it can signal at
all, and reported itself healthy: the fetch succeeded, the merge succeeded, the
run advanced. Nothing failed. The window was simply too short to mean anything,
because `yfinance.download` without a start date returns about a month rather
than everything it has.

These tests stub the vendor rather than calling it. The point is not what the
vendor returns — it is what this repo *asks for*, which is the part that was
wrong and the part a network test would not have pinned.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load_script():
    spec = importlib.util.spec_from_file_location(
        "fetch_bars", ROOT / "research" / "fetch_bars.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch_bars = load_script()


class FakeFrame:
    """The little of a DataFrame that `from_yfinance` actually touches."""

    def __init__(self, rows):
        self._rows = rows
        self.columns = types.SimpleNamespace(nlevels=1)

    @property
    def empty(self):
        return not self._rows

    def iterrows(self):
        for stamp, row in self._rows:
            yield _Stamp(stamp), row


class _Stamp:
    def __init__(self, when):
        self._when = when

    def to_pydatetime(self):
        return self._when


@pytest.fixture
def vendor(monkeypatch):
    """Install a stub `yfinance`, recording the arguments it was called with.

    CI installs only `.[dev]`, so the real package is absent — which is the
    right shape for this anyway: the assertion is about the request, and a stub
    makes that visible where a live call would hide it behind whatever the
    vendor felt like returning.
    """
    calls = []

    def download(symbol, **kwargs):
        calls.append({"symbol": symbol, **kwargs})
        day = datetime(2026, 9, 14)
        rows = [
            (day - timedelta(days=i), {
                "Open": 700.0, "High": 705.0, "Low": 695.0,
                "Close": 701.0, "Volume": 1000,
            })
            for i in range(3)
        ]
        return FakeFrame(rows)

    module = types.ModuleType("yfinance")
    module.download = download
    monkeypatch.setitem(sys.modules, "yfinance", module)
    return calls


class TestHowMuchHistoryItAsksFor:
    def test_no_start_date_asks_for_everything(self, vendor):
        """The bug: this used to inherit yfinance's ~1 month default."""
        fetch_bars.from_yfinance("QQQ", None)
        assert vendor[0].get("period") == "max"
        assert "start" not in vendor[0], (
            "passing start=None is what selected the one-month default"
        )

    def test_an_explicit_start_is_honoured(self, vendor):
        fetch_bars.from_yfinance("QQQ", "2015-01-01")
        assert vendor[0].get("start") == "2015-01-01"
        assert "period" not in vendor[0], (
            "period and start together would make the window ambiguous"
        )

    def test_adjustment_stays_off_either_way(self, vendor):
        """Auto-adjusted closes would restate history under a running record."""
        fetch_bars.from_yfinance("QQQ", None)
        fetch_bars.from_yfinance("QQQ", "2015-01-01")
        assert all(call["auto_adjust"] is False for call in vendor)

    def test_an_empty_response_is_refused_rather_than_written(self, monkeypatch):
        module = types.ModuleType("yfinance")
        module.download = lambda symbol, **kw: FakeFrame([])
        monkeypatch.setitem(sys.modules, "yfinance", module)
        with pytest.raises(SystemExit, match="no rows"):
            fetch_bars.from_yfinance("QQQ", None)
