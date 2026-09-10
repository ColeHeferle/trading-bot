"""Read a planned order back to Claude, and print what it says about it.

This is a **proofreader, not a gate**. It can raise an objection; it can never
clear one. Nothing here returns a value the caller branches on, no exit code
comes from it, and a failure to reach the API prints a line and gets out of the
way. Every deterministic refusal in `trading_bot.live` still decides whether an
order is built, before this ever runs.

That asymmetry is the whole design. A language model in the *approving*
position would be a way to talk yourself into a trade the rule did not ask for,
which is the failure this repository spends most of its README guarding
against. In the objecting position the worst it can do is make you look twice.

It is also not a market analyst, and the system prompt says so at length. The
edge this bot trades is undetectable on any horizon a human will live to see —
`SmaCrossover(50, 200)` scored an information ratio of 0.046, so telling it
from luck takes roughly 1,900 years. A model asked whether a trade "looks good"
will produce a fluent opinion about noise every single time. So it is asked
something answerable instead: does this order match the rule that was frozen,
and is anything about it operationally strange?

Runs on every invocation of `research/trade.py`, dry run included, because
exercising the whole path daily is what catches bugs — the same reason the
trade loop itself runs daily in dry-run mode.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

MODEL = "claude-opus-5"

# Asked for a judgement it can actually make. The framing matters more than the
# schema: an open-ended "review this trade" invites a market opinion, which is
# the one thing this must never produce.
SYSTEM = """\
You are proofreading a single order that an automated trading bot has planned \
but not yet placed. The human operator reads your output and decides. You have \
no ability to approve, block, or place anything.

WHAT YOU ARE CHECKING FOR — operational wrongness only:

- The order contradicts the frozen rule it claims to come from: wrong side, a \
size that does not follow from the target weight, an instrument that is not \
the one the rule names.
- The arithmetic does not tie out. Recompute it: quantity x price against \
notional, notional against equity, resulting weight against target weight. \
Say so if a number is off, and show the number you got.
- The traded instrument differs from the instrument the rule was frozen on, in \
a way that makes the sizing wrong rather than merely noted.
- The target weight moved in a way the named sizer cannot explain.
- The trade frequency is out of character for the rule's measured turnover.
- Data that looks wrong: a stale bar, a price implausible for the instrument, \
a position or equity that does not fit the account.
- Anything else an operator would want to see twice before this is sent.

WHAT YOU MUST NOT DO:

- Do not offer a market view. Not on direction, not on timing, not on \
valuation, not on the news. You have no information about the market and are \
not being asked.
- Do not say whether the trade is likely to make money. That question is not \
answerable here: this rule's edge is statistically undetectable — an \
information ratio of 0.046 needs about 1,900 years of data to separate from \
luck. The rule is frozen for its drawdown behaviour, not its return.
- Do not suggest changing, retuning, skipping, or overriding the rule. The \
rule is deliberately frozen and re-freezing it on a whim is the exact failure \
mode its author is guarding against. If the rule itself seems wrong to you, \
that is out of scope.
- Do not pad the output. If the order is a plain execution of the rule and \
every number ties, say that in one line and raise nothing.

Raising nothing is the correct and expected answer most days. A flag you \
cannot justify with a specific number or a specific contradiction is noise, \
and noise here trains the operator to stop reading you.\
"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        # Deliberately not "approved" / "rejected". The reviewer has no such
        # power, and a word implying it would misdescribe the output.
        "verdict": {"type": "string", "enum": ["no-objection", "flag"]},
        "summary": {
            "type": "string",
            "description": "One sentence. What this order is, in the operator's terms.",
        },
        "concerns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "issue": {"type": "string", "description": "The problem, in one line."},
                    "evidence": {
                        "type": "string",
                        "description": "The specific numbers or contradiction behind it.",
                    },
                },
                "required": ["severity", "issue", "evidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["verdict", "summary", "concerns"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Review:
    verdict: str
    summary: str
    concerns: list[dict[str, str]]

    @property
    def flagged(self) -> bool:
        return self.verdict == "flag" or bool(self.concerns)


def dossier(
    run: Any,
    intent: Any,
    traded_symbol: str,
    equity: float,
    current_quantity: float,
    expected_quantity: float | None,
    now: Any,
) -> dict[str, Any]:
    """Everything the reviewer gets, as plain JSON-able data.

    Built here rather than inline so the exact payload sent to a third party is
    readable in one place. No credentials, no account identifiers — the rule,
    the arithmetic, and the position.
    """
    latest = run.journal[-1]
    rule = run.rule
    notional = intent.quantity * intent.price
    return {
        "frozen_rule": {
            "strategy": rule.strategy,
            "params": rule.params,
            "instrument_rule_watches": rule.symbol,
            "sizer": rule.sizer,
            "sizer_params": rule.sizer_params,
            "fingerprint": rule.fingerprint,
            "fee_rate": rule.fee_rate,
            # The freeze note says why this rule exists and what it is not.
            # It is the reviewer's only source for "is this in character".
            "freeze_note": rule.note,
        },
        "decision": {
            "target_weight": run.target_weight,
            "as_of_bar": latest.timestamp.isoformat(),
            "close_of_that_bar": latest.close,
            "bars_recorded_live": len(run.journal),
            "reviewed_at": now.isoformat(timespec="seconds"),
        },
        "account": {
            "instrument_being_traded": traded_symbol,
            "traded_instrument_is_the_one_the_rule_watches": (
                traded_symbol == rule.symbol
            ),
            "live_price_of_traded_instrument": intent.price,
            "broker_equity": equity,
            "currently_held_quantity": current_quantity,
            "quantity_the_run_expected_to_hold": expected_quantity,
            "current_weight": (
                current_quantity * intent.price / equity if equity else None
            ),
        },
        "planned_order": {
            "side": intent.side.value if intent.side else None,
            "quantity": intent.quantity,
            "is_an_action": intent.is_action,
            "engine_reason": intent.reason,
            "notional": notional,
            "notional_as_fraction_of_equity": notional / equity if equity else None,
        },
    }


def request(payload: dict[str, Any], model: str = MODEL) -> Review:
    """Ask Claude. Raises on any failure — the caller decides what that means."""
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": (
                    "Proofread this planned order.\n\n"
                    + json.dumps(payload, indent=2, default=str)
                ),
            }
        ],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("the model declined to answer")
    text = next(block.text for block in response.content if block.type == "text")
    parsed = json.loads(text)
    return Review(
        verdict=parsed["verdict"],
        summary=parsed["summary"],
        concerns=parsed.get("concerns", []),
    )


def render(review: Review) -> str:
    """The review as printable text. Loud when it has something to say."""
    rule = "─" * 72
    lines = [rule]
    if review.flagged:
        lines.append("!!  PROOFREADER RAISED SOMETHING — read before you execute  !!")
    else:
        lines.append("proofreader: no objection")
        # Said every time, because a green light nobody questions becomes an
        # approval in the operator's head within about a week.
        lines.append("(this is not an approval, and it is not a market opinion)")
    lines.append(rule)
    lines.append(review.summary)
    for concern in review.concerns:
        lines.append("")
        lines.append(f"  [{concern['severity'].upper()}] {concern['issue']}")
        lines.append(f"      {concern['evidence']}")
    lines.append(rule)
    return "\n".join(lines)


def _explain(exc: BaseException) -> str:
    """Why the review did not happen, in the operator's terms.

    The chain is for the message only — every branch has the same consequence,
    so nothing here decides anything.
    """
    name = type(exc).__name__
    if name == "AuthenticationError":
        return "no credentials (set ANTHROPIC_API_KEY, or run `ant auth login`)"
    if name == "RateLimitError":
        return "rate limited"
    if name == "APIConnectionError":
        return "could not reach the API"
    status = getattr(exc, "status_code", None)
    if status is not None:
        return f"API error {status}"
    return f"{name}: {exc}"


def proofread(
    run: Any,
    intent: Any,
    traded_symbol: str,
    equity: float,
    current_quantity: float,
    expected_quantity: float | None,
    now: Any,
    model: str = MODEL,
    out: Any = None,
    request_fn: Any = None,
) -> None:
    """Print a review of `intent`. Never raises, never returns a verdict.

    Every failure ends in a printed line and a return, including failures
    nobody anticipated — hence the bare `except Exception`, which is load
    bearing rather than lazy. A proofreader that can take the trading loop down
    with it is worse than no proofreader, and one whose silence could be read
    as approval is worse still, so when it cannot run it says which.

    `request_fn` exists so the printing can be tested without a network or an
    API key. It is not a seam for swapping in a different reviewer.
    """
    import sys

    out = out or sys.stdout

    if request_fn is None:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            print(
                '\nproofreader: not run — pip install ".[review]" to enable it',
                file=out,
            )
            return
        request_fn = request

    try:
        payload = dossier(
            run, intent, traded_symbol, equity, current_quantity,
            expected_quantity, now,
        )
        review = request_fn(payload, model=model)
    except Exception as exc:  # noqa: BLE001 — see the docstring
        print(f"\nproofreader: not run — {_explain(exc)}", file=out)
        return

    print("\n" + render(review), file=out)
