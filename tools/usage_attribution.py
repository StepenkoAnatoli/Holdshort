#!/usr/bin/env python3
"""Run-level usage and latency attribution (issue #61).

The native Codex comparison exposed requested settings and final answers but not
reliable per-agent tokens, immutable revisions or completion times, and a
parent-session aggregate cannot be allocated to individual models. This module
records one observation per dispatched task instead: what was requested, what
the host reported observing, which policy digest was in force, which clock and
which scheduling/transport boundary the times refer to, and the counters the
host actually exposed.

Rules this enforces:

  * counters are `null` when the host does not expose them, never `0`;
  * `cached_input_tokens <= input_tokens` and
    `reasoning_output_tokens <= output_tokens`: the subsets are recorded, never
    added a second time;
  * an interrupted run keeps its start and records no completion, instead of
    inventing a duration;
  * `export()` refuses any record carrying a field outside the whitelist, so a
    prompt, tool output or credential cannot ride along into tracked evidence;
  * a dollar figure always carries its price revision and its billing
    assumptions, and is `null` when the counters it needs are unknown. An
    account-wide usage percentage is not a per-run measurement and is not
    accepted as one.

Clock: `started_at`/`completed_at` are UTC ISO-8601 instants (a trailing `Z` is
accepted); `clock` names what produced them (`utc`, meaning host wall clock, or
`utc+monotonic`, meaning the duration came from a monotonic reading). `boundary`
names what the interval covers (`transport`, `provider-request` or
`harness-cell`), so two hosts cannot silently compare different spans.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
COUNTER_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
SUBSET_PAIRS = (("cached_input_tokens", "input_tokens"), ("reasoning_output_tokens", "output_tokens"))
SETTING_KEYS = frozenset({"effort", "reasoning", "max_output_tokens"})
CLOCKS = ("utc", "utc+monotonic")
BOUNDARIES = ("transport", "provider-request", "harness-cell")
RECORD_FIELDS = frozenset({
    "schema_version", "run_id", "task_id", "policy_sha256", "requested_model",
    "observed_model", "model_match", "settings", "started_at", "completed_at",
    "latency_ms", "clock", "boundary", "interrupted", "counters",
})


class AttributionError(ValueError):
    """A malformed or over-sharing record; never repaired by guessing."""


def _text(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AttributionError(f"{what} must be a non-empty string")
    return value


def _instant(value, what: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise AttributionError(f"{what} must be an ISO-8601 instant")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise AttributionError(f"{what} must be an ISO-8601 instant") from None
    if parsed.tzinfo is None:
        raise AttributionError(f"{what} must carry a timezone; a naive local time is not comparable")
    return parsed.astimezone(timezone.utc)


def _counters(value) -> dict:
    """The four counters, null-allowed, subset-checked, never zero-filled."""
    if value is None:
        return {field: None for field in COUNTER_FIELDS}
    if not isinstance(value, dict) or set(value) != set(COUNTER_FIELDS):
        raise AttributionError(f"counters must hold exactly {list(COUNTER_FIELDS)}")
    result = {}
    for field in COUNTER_FIELDS:
        number = value[field]
        if number is not None and (type(number) is not int or number < 0):
            raise AttributionError(f"{field} must be a nonnegative integer or null")
        result[field] = number
    for part, whole in SUBSET_PAIRS:
        if result[part] is not None and result[whole] is not None and result[part] > result[whole]:
            raise AttributionError(f"{part} exceeds {whole}; subsets cannot be larger than their total")
    return result


def _settings(value) -> dict:
    """The configuration a comparison record must carry; no free-form payload."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AttributionError("settings must be an object or null")
    unknown = sorted(set(value) - SETTING_KEYS)
    if unknown:
        raise AttributionError(f"unmodeled settings {unknown}; only {sorted(SETTING_KEYS)} are recorded")
    for key, item in value.items():
        if item is not None and not isinstance(item, (str, int, float, bool)):
            raise AttributionError(f"settings.{key} must be a scalar or null")
    if value.get("max_output_tokens") is not None:
        ceiling = value["max_output_tokens"]
        if type(ceiling) is not int or ceiling <= 0:
            raise AttributionError("settings.max_output_tokens must be a positive integer")
    return dict(value)


def observation(*, run_id: str, task_id: str, policy_sha256: str, requested_model: str,
                observed_model: str, started_at: str, completed_at: str | None,
                counters: dict | None, clock: str = "utc", boundary: str = "transport",
                settings: dict | None = None, interrupted: bool = False) -> dict:
    """One attributed task observation; refused rather than repaired."""
    _text(run_id, "run_id")
    _text(task_id, "task_id")
    if (not isinstance(policy_sha256, str) or len(policy_sha256) != 64
            or any(c not in "0123456789abcdef" for c in policy_sha256)):
        raise AttributionError("policy_sha256 must be a lowercase sha256 hex digest")
    _text(requested_model, "requested_model")
    _text(observed_model, "observed_model")
    if clock not in CLOCKS:
        raise AttributionError(f"clock must be one of {list(CLOCKS)}")
    if boundary not in BOUNDARIES:
        raise AttributionError(f"boundary must be one of {list(BOUNDARIES)}")
    if type(interrupted) is not bool:
        raise AttributionError("interrupted must be a boolean")
    start = _instant(started_at, "started_at")
    if interrupted:
        if completed_at is not None:
            raise AttributionError("an interrupted run records no completion time")
        latency = None
    else:
        if completed_at is None:
            raise AttributionError("a completed run needs completed_at")
        finish = _instant(completed_at, "completed_at")
        if finish < start:
            raise AttributionError("completed_at precedes started_at")
        latency = int(round((finish - start).total_seconds() * 1000))
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "task_id": task_id,
        "policy_sha256": policy_sha256,
        "requested_model": requested_model,
        "observed_model": observed_model,
        "model_match": requested_model == observed_model,
        "settings": _settings(settings),
        "started_at": start.isoformat(),
        "completed_at": None if interrupted else _instant(completed_at, "completed_at").isoformat(),
        "latency_ms": latency,
        "clock": clock,
        "boundary": boundary,
        "interrupted": interrupted,
        "counters": _counters(counters),
    }


def export(records) -> list[dict]:
    """The tracked-evidence projection: a whitelist, not a redaction pass."""
    out = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise AttributionError(f"record {index} is not an object")
        unknown = sorted(set(record) - RECORD_FIELDS)
        if unknown:
            raise AttributionError(f"record {index} carries fields outside the export whitelist: "
                                   f"{unknown}")
        missing = sorted(RECORD_FIELDS - set(record))
        if missing:
            raise AttributionError(f"record {index} is missing {missing}")
        out.append({field: record[field] for field in sorted(RECORD_FIELDS)})
    return out


def by_model(records) -> dict:
    """Per-model totals; a model with any unknown counter reports null, never 0."""
    groups: dict[str, list[dict]] = {}
    for record in records:
        groups.setdefault(record["observed_model"], []).append(record)
    summary = {}
    for model, group in sorted(groups.items()):
        totals = {}
        for field in COUNTER_FIELDS:
            values = [record["counters"][field] for record in group]
            totals[field] = None if any(v is None for v in values) else sum(values)
            totals[f"{field}_unknown"] = sum(1 for v in values if v is None)
        latencies = [record["latency_ms"] for record in group if record["latency_ms"] is not None]
        totals["latency_ms_median"] = int(statistics.median(latencies)) if latencies else None
        totals["latency_ms_unknown"] = sum(1 for record in group if record["latency_ms"] is None)
        totals["observations"] = len(group)
        totals["interrupted"] = sum(1 for record in group if record["interrupted"])
        summary[model] = totals
    return summary


def estimate_cost(record: dict, rates: dict, *, price_revision: str) -> dict:
    """A dollar figure with its revision and assumptions, or null when unknowable."""
    _text(price_revision, "price_revision")
    if not isinstance(rates, dict) or not set(rates) <= {"input", "cached_input", "output", "reasoning"}:
        raise AttributionError("rates must hold only input, cached_input, output and reasoning")
    if not {"input", "output"} <= set(rates):
        raise AttributionError("rates must state at least the input and output prices")
    for key, rate in rates.items():
        if (type(rate) not in (int, float) or isinstance(rate, bool)
                or not math.isfinite(rate) or rate < 0):
            raise AttributionError(f"rates.{key} must be a finite nonnegative number")
    if not isinstance(record, dict) or not isinstance(record.get("counters"), dict):
        raise AttributionError("record must carry a counters object")
    usage = record["counters"]
    common = {"price_revision": price_revision, "currency": "USD",
              "unit": "per million tokens", "billing_assumptions": []}
    if usage["input_tokens"] is None or usage["output_tokens"] is None:
        return {**common, "cost_usd": None,
                "billing_assumptions": ["input or output counter is unknown: no cost is claimed"]}
    cached = usage["cached_input_tokens"]
    if cached:
        if "cached_input" not in rates:
            raise AttributionError("cached input tokens are present but no cached-input rate is "
                                   "given; assuming they are free would understate the cost")
        common["billing_assumptions"].append("cached input is billed at the cached-input rate and "
                                             "is not billed again as uncached input")
        prompt_cost = ((usage["input_tokens"] - cached) * rates["input"]
                       + cached * rates["cached_input"])
    else:
        prompt_cost = usage["input_tokens"] * rates["input"]
    reasoning = usage["reasoning_output_tokens"]
    if reasoning:
        if "reasoning" in rates:
            common["billing_assumptions"].append("reasoning tokens are billed at the reasoning rate, "
                                                 "not again at the output rate")
            output_cost = ((usage["output_tokens"] - reasoning) * rates["output"]
                           + reasoning * rates["reasoning"])
        else:
            common["billing_assumptions"].append("reasoning tokens are billed as output")
            output_cost = usage["output_tokens"] * rates["output"]
    else:
        output_cost = usage["output_tokens"] * rates["output"]
    return {**common, "cost_usd": round((prompt_cost + output_cost) / 1_000_000, 6)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate attributed usage records (issue #61)")
    parser.add_argument("records", type=Path, help="JSONL of attributed observations")
    args = parser.parse_args(argv)
    try:
        records = [json.loads(line) for line in args.records.read_text(encoding="utf-8").splitlines()
                   if line.strip()]
        exported = export(records)
    except (OSError, ValueError, AttributionError) as error:
        print(f"usage_attribution: REFUSED — {error}", file=sys.stderr)
        return 2
    digest = hashlib.sha256(json.dumps(exported, sort_keys=True).encode("utf-8")).hexdigest()
    print(json.dumps({"schema_version": SCHEMA_VERSION, "records": len(exported),
                      "digest": digest, "by_model": by_model(exported)}, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
