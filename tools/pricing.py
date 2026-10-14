#!/usr/bin/env python3
"""Token pricing for prices-2.json profile rows — one formula for every caller.

live_dispatcher (spend enforcement) and pilot_report (ledger audit) must price
identically, or the audit flags correct spend as a mismatch. Both call here.

A row may carry a `long_context` block for models priced by prompt length
(Claude Haiku 5.5: a prompt *over* 100,000 tokens pays higher input AND output
rates for the whole request):

    "long_context": {"threshold_input_tokens": 100000,
                     "input_rate_per_mtok": 0.50, "output_rate_per_mtok": 2.50}

Fail-closed: a row whose `input_rate_condition` names a conditional rate but
has no valid `long_context` block is unpriceable, because a prompt past the
condition would silently be billed at the cheaper rate.
"""
from __future__ import annotations

import math
from typing import Any, Tuple


class UnpriceableProfile(ValueError):
    """The row cannot price this request; the caller must block, not guess."""


def _rate_ok(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def validate_profile(profile: Any) -> None:
    """Raise UnpriceableProfile unless every rate the row can select is valid."""
    if not isinstance(profile, dict):
        raise UnpriceableProfile("profile row is not an object")
    for k in ("input_rate_per_mtok", "output_rate_per_mtok"):
        if not _rate_ok(profile.get(k)):
            raise UnpriceableProfile(f"invalid {k}")
    lc = profile.get("long_context")
    if lc is None:
        if profile.get("input_rate_condition"):
            raise UnpriceableProfile(
                "row has input_rate_condition but no long_context rates")
        return
    if not isinstance(lc, dict):
        raise UnpriceableProfile("long_context is not an object")
    t = lc.get("threshold_input_tokens")
    if type(t) is not int or t <= 0:
        raise UnpriceableProfile("invalid long_context.threshold_input_tokens")
    for k in ("input_rate_per_mtok", "output_rate_per_mtok"):
        if not _rate_ok(lc.get(k)):
            raise UnpriceableProfile(f"invalid long_context.{k}")


def select_rates(profile: dict, in_toks: int) -> Tuple[float, float]:
    """(input_rate, output_rate) per MTok for a request with this prompt size."""
    validate_profile(profile)
    lc = profile.get("long_context")
    if lc is not None and in_toks > lc["threshold_input_tokens"]:
        return lc["input_rate_per_mtok"], lc["output_rate_per_mtok"]
    return profile["input_rate_per_mtok"], profile["output_rate_per_mtok"]


def token_cost(profile: dict, in_toks: int, out_toks: int) -> float:
    in_rate, out_rate = select_rates(profile, in_toks)
    return (in_rate * in_toks + out_rate * out_toks) / 1_000_000.0
