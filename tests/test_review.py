"""The proofreader is advisory, and these tests pin that it stays advisory.

Most of what matters about this component is what it *cannot* do: it cannot
block an order, cannot raise, cannot approve anything, and cannot take the
trading loop down when the API is unreachable. Those are the properties tested
here. What Claude actually says about a given order is not testable and is not
the point — the point is that whatever it says changes nothing on its own.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from datetime import datetime
from pathlib import Path

import pytest

from trading_bot import FrozenRule, PaperRun
from trading_bot.live import Intent
from trading_bot.models import Candle, Side

ROOT = Path(__file__).resolve().parent.parent


def load_script():
    spec = importlib.util.spec_from_file_location(
        "review", ROOT / "research" / "review.py"
    )
    module = importlib.util.module_from_spec(spec)
    # Registered before execution because the module defines a dataclass, and
    # `dataclasses` resolves annotations through sys.modules.
    sys.modules["review"] = module
    spec.loader.exec_module(module)
    return module


review = load_script()


def run_with_a_bar():
    rule = FrozenRule(
        strategy="SmaCrossover",
        params={"fast_period": 2, "slow_period": 4},
        symbol="QQQ",
        sizer="VolatilityTarget",
        sizer_params={"target_volatility": 0.25},
        note="Frozen for the drawdown, not the return.",
    )
    run = PaperRun(rule=rule)
    for i, close in enumerate([10, 11, 12, 13, 14, 15]):
        run.step(Candle(datetime(2026, 9, 1 + i), close, close, close, close))
    return run


BUY = Intent("QQQ", Side.BUY, 12.0, "target 0.75, holding 0.00", price=600.0)


def dossier_for(intent=BUY, **kw):
    kwargs = dict(
        run=run_with_a_bar(),
        intent=intent,
        traded_symbol="QQQ",
        equity=10_000.0,
        current_quantity=0.0,
        expected_quantity=None,
        now=datetime(2026, 9, 10, 22, 0),
    )
    kwargs.update(kw)
    return review.dossier(**kwargs)


class TestDossier:
    def test_carries_the_freeze_so_the_order_can_be_checked_against_it(self):
        payload = dossier_for()
        assert payload["frozen_rule"]["strategy"] == "SmaCrossover"
        assert payload["frozen_rule"]["sizer"] == "VolatilityTarget"
        assert "drawdown" in payload["frozen_rule"]["freeze_note"]

    def test_states_the_arithmetic_so_it_can_be_recomputed(self):
        order = dossier_for()["planned_order"]
        assert order["notional"] == pytest.approx(7_200.0)
        assert order["notional_as_fraction_of_equity"] == pytest.approx(0.72)

    def test_says_plainly_when_the_traded_instrument_is_not_the_frozen_one(self):
        account = dossier_for(traded_symbol="TQQQ")["account"]
        assert account["traded_instrument_is_the_one_the_rule_watches"] is False

    def test_is_json_serialisable_without_reaching_for_repr(self):
        import json

        json.loads(json.dumps(dossier_for(), default=str))

    def test_carries_no_credentials(self):
        import json

        blob = json.dumps(dossier_for(), default=str).lower()
        for secret in ("apca", "api_key", "secret", "token"):
            assert secret not in blob


class TestRender:
    def test_a_clean_review_still_refuses_to_read_as_an_approval(self):
        text = review.render(review.Review("no-objection", "Plain rule entry.", []))
        assert "not an approval" in text

    def test_a_concern_is_loud_and_shows_its_evidence(self):
        text = review.render(
            review.Review(
                "flag",
                "Order is ten times the target weight.",
                [{"severity": "high", "issue": "Sized off the index level",
                  "evidence": "12 x 6400 = 76,800 against 10,000 equity"}],
            )
        )
        assert "!!" in text and "HIGH" in text
        assert "76,800" in text

    def test_concerns_are_loud_even_when_the_verdict_forgot_to_be(self):
        # A model that lists problems and still says "no-objection" is not a
        # reason to print a quiet header.
        flagged = review.Review(
            "no-objection", "Fine.",
            [{"severity": "low", "issue": "x", "evidence": "y"}],
        )
        assert flagged.flagged
        assert "!!" in review.render(flagged)


class TestNeverBlocks:
    def _proofread(self, request_fn):
        out = io.StringIO()
        review.proofread(
            run_with_a_bar(), BUY, "QQQ", 10_000.0, 0.0, None,
            datetime(2026, 9, 10, 22, 0), out=out, request_fn=request_fn,
        )
        return out.getvalue()

    def test_an_api_failure_prints_and_returns_rather_than_raising(self):
        class Boom(Exception):
            status_code = 500

        text = self._proofread(lambda payload, model: (_ for _ in ()).throw(Boom()))
        assert "not run" in text and "500" in text

    def test_an_unreachable_api_does_not_take_the_loop_down(self):
        def unreachable(payload, model):
            raise ConnectionError("no route to host")

        assert "not run" in self._proofread(unreachable)

    def test_an_unanticipated_failure_is_still_caught(self):
        def broken(payload, model):
            return {}["missing"]

        assert "not run" in self._proofread(broken)

    def test_a_review_that_works_is_printed(self):
        def fine(payload, model):
            return review.Review("no-objection", "Plain rule entry.", [])

        assert "Plain rule entry." in self._proofread(fine)

    def test_it_returns_nothing_the_caller_could_branch_on(self):
        def fine(payload, model):
            return review.Review("flag", "Something is off.", [])

        out = io.StringIO()
        result = review.proofread(
            run_with_a_bar(), BUY, "QQQ", 10_000.0, 0.0, None,
            datetime(2026, 9, 10, 22, 0), out=out, request_fn=fine,
        )
        assert result is None


class TestPrompt:
    def test_forbids_a_market_opinion(self):
        assert "Do not offer a market view" in review.SYSTEM

    def test_forbids_talking_the_operator_into_retuning_the_frozen_rule(self):
        assert "retuning" in review.SYSTEM

    def test_the_schema_has_no_word_for_approval(self):
        verdicts = review.SCHEMA["properties"]["verdict"]["enum"]
        assert verdicts == ["no-objection", "flag"]
