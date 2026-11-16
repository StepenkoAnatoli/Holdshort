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
  * `export()` refuses any record carrying a field outside the whitelist and
    re-derives every record it is given through `observation()`, refusing any
    value that differs from what `observation()` would have recorded. A record
    read from JSONL is held to the same rules as one built in memory, so free
    text cannot ride along inside a whitelisted field: identifiers are single
    bounded tokens of visible ASCII, `settings` values are short tokens or
    numbers, and every number is bounded. The CLI reads only the canonical
    lines `to_jsonl()` writes, so the file holds nothing the checks do not see;
  * a dollar figure always carries its price revision and its billing
    assumptions, and is `null` when the counters it needs are unknown. An
    account-wide usage percentage is not a per-run measurement and is not
    accepted as one.

Clock: `started_at`/`completed_at` are UTC ISO-8601 instants (`observation()`
accepts a trailing `Z`; records store and export the `+00:00` form); `clock` names what produced them (`utc`, meaning host wall clock, or
`utc+monotonic`, meaning the duration came from a monotonic reading). `boundary`
names what the interval covers (`transport`, `provider-request` or
`harness-cell`), so two hosts cannot silently compare different spans.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
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
# Identifiers name a run, a task or a model; a prompt or an answer is not one.
IDENTIFIER_LENGTH = 200
# The largest integer every JSON reader keeps exact (RFC 8259, section 6). A larger
# number is not a count, a rate or a setting, and its digits could carry arbitrary bytes.
LARGEST_NUMBER = 2 ** 53
# `effort` / `reasoning` are levels such as `high` or `xhigh`, never sentences.
SETTING_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}")
RECORD_FIELDS = frozenset({
    "schema_version", "run_id", "task_id", "policy_sha256", "requested_model",
    "observed_model", "model_match", "settings", "started_at", "completed_at",
    "latency_ms", "clock", "boundary", "interrupted", "counters",
})


class AttributionError(ValueError):
    """A malformed or over-sharing record; never repaired by guessing."""


# Strings are checked with `type(value) is str`: a str subclass can answer len(),
# isprintable(), `in` and `==` however it likes while json.dumps writes its real text.


def _text(value, what: str) -> str:
    if type(value) is not str or not value.strip():
        raise AttributionError(f"{what} must be a non-empty string")
    return value


def _identifier(value, what: str) -> str:
    # Visible ASCII only: "printable" is a rendering property, and combining marks,
    # variation selectors (the usual encoding for smuggling bytes as invisible text),
    # Hangul fillers and the blank braille pattern are all printable, so a sentence
    # could ride along looking like one token. Every real run, task or model id is ASCII.
    if (type(value) is not str or not 1 <= len(value) <= IDENTIFIER_LENGTH
            or not value.isascii() or not value.isprintable() or " " in value):
        raise AttributionError(f"{what} must be 1-{IDENTIFIER_LENGTH} visible ASCII characters "
                               "with no spaces")
    return value


def _instant(value, what: str) -> datetime:
    if type(value) is not str or not value:
        raise AttributionError(f"{what} must be an ISO-8601 instant")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise AttributionError(f"{what} must be an ISO-8601 instant") from None
    if parsed.tzinfo is None:
        raise AttributionError(f"{what} must carry a timezone; a naive local time is not comparable")
    try:
        return parsed.astimezone(timezone.utc)
    except OverflowError:
        # e.g. 0001-01-01T00:00:00+23:59 has no UTC form
        raise AttributionError(f"{what} falls outside the range of UTC instants") from None


def _counters(value) -> dict:
    """The four counters, null-allowed, subset-checked, never zero-filled."""
    if value is None:
        return {field: None for field in COUNTER_FIELDS}
    if not isinstance(value, dict) or set(value) != set(COUNTER_FIELDS):
        raise AttributionError(f"counters must hold exactly {list(COUNTER_FIELDS)}")
    result = {}
    for field in COUNTER_FIELDS:
        number = value[field]
        if number is not None and (type(number) is not int or not 0 <= number <= LARGEST_NUMBER):
            raise AttributionError(f"{field} must be an integer from 0 to 2**53 or null")
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
    # One plain copy of the stored pairs is checked and returned: a dict subclass can
    # show items(), [] and iteration different values, so none of them is consulted.
    value = dict(dict.items(value))
    if any(type(key) is not str for key in value):
        # a str subclass can pass the whitelist as a known name and still be written
        # with its own text, like the string values above
        raise AttributionError("settings keys must be strings")
    unknown = set(value) - SETTING_KEYS
    if unknown:
        # the names are not echoed: a key can be a secret too
        raise AttributionError(f"{len(unknown)} unmodeled settings key(s); only "
                               f"{sorted(SETTING_KEYS)} are recorded")
    for key, item in value.items():
        if item is None or type(item) is bool:
            continue
        if type(item) in (int, float):
            # also False for NaN and infinities
            if not abs(item) <= LARGEST_NUMBER:
                raise AttributionError(f"settings.{key} must be a finite number within 2**53")
        elif type(item) is str:
            if not SETTING_TOKEN.fullmatch(item):
                raise AttributionError(f"settings.{key} must be a short lowercase token such as "
                                       "'high'; free text is not a setting")
        else:
            raise AttributionError(f"settings.{key} must be a scalar or null")
    if value.get("max_output_tokens") is not None:
        ceiling = value["max_output_tokens"]
        if type(ceiling) is not int or ceiling <= 0:
            raise AttributionError("settings.max_output_tokens must be a positive integer")
    return value


def observation(*, run_id: str, task_id: str, policy_sha256: str, requested_model: str,
                observed_model: str, started_at: str, completed_at: str | None,
                counters: dict | None, clock: str = "utc", boundary: str = "transport",
                settings: dict | None = None, interrupted: bool = False) -> dict:
    """One attributed task observation; refused rather than repaired."""
    _identifier(run_id, "run_id")
    _identifier(task_id, "task_id")
    if (type(policy_sha256) is not str or len(policy_sha256) != 64
            or any(c not in "0123456789abcdef" for c in policy_sha256)):
        raise AttributionError("policy_sha256 must be a lowercase sha256 hex digest")
    _identifier(requested_model, "requested_model")
    _identifier(observed_model, "observed_model")
    if type(clock) is not str or clock not in CLOCKS:
        raise AttributionError(f"clock must be one of {list(CLOCKS)}")
    if type(boundary) is not str or boundary not in BOUNDARIES:
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


def _canonical(value) -> str:
    # JSON text, so `1`, `1.0` and `true` stay different values (Python's `==` merges them)
    return json.dumps(value, sort_keys=True, allow_nan=False)


def export(records) -> list[dict]:
    """The tracked-evidence projection: a whitelist, not a redaction pass.

    Key names are not enough: a record read back from JSONL was never built by
    `observation()`, so each one is rebuilt through it from its own fields and must
    come out identical. A derived value (`model_match`, `latency_ms`) that disagrees
    with its inputs, a value `observation()` would refuse, or a non-canonical form
    refuses the whole export instead of being repaired.
    """
    out = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise AttributionError(f"record {index} is not an object")
        unknown = set(record) - RECORD_FIELDS
        if unknown:
            # the names are not echoed: a key can be a secret too
            raise AttributionError(f"record {index} carries {len(unknown)} field(s) outside the "
                                   "export whitelist")
        missing = sorted(RECORD_FIELDS - set(record))
        if missing:
            raise AttributionError(f"record {index} is missing {missing}")
        try:
            rebuilt = observation(
                run_id=record["run_id"], task_id=record["task_id"],
                policy_sha256=record["policy_sha256"], requested_model=record["requested_model"],
                observed_model=record["observed_model"], started_at=record["started_at"],
                completed_at=record["completed_at"], counters=record["counters"],
                clock=record["clock"], boundary=record["boundary"], settings=record["settings"],
                interrupted=record["interrupted"])
        except AttributionError as error:
            raise AttributionError(f"record {index}: {error}") from None
        try:
            differs = sorted(field for field in RECORD_FIELDS
                             if _canonical(record[field]) != _canonical(rebuilt[field]))
        except (TypeError, ValueError, RecursionError):
            # fields observation() does not take (schema_version, model_match, latency_ms)
            # reach this comparison unchecked
            raise AttributionError(f"record {index} holds a value that is not finite JSON") from None
        if differs:
            raise AttributionError(f"record {index} disagrees with the observation its own fields "
                                   f"give in {differs}; derived and canonical values are not "
                                   "taken on trust")
        out.append({field: rebuilt[field] for field in sorted(RECORD_FIELDS)})
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
        # bounded like the counters, so the cost is always a finite float (the
        # comparison is also False for NaN and infinities)
        if type(rate) not in (int, float) or not 0 <= rate <= LARGEST_NUMBER:
            raise AttributionError(f"rates.{key} must be a finite number from 0 to 2**53")
    if not isinstance(record, dict) or not isinstance(record.get("counters"), dict):
        raise AttributionError("record must carry a counters object")
    usage = _counters(record["counters"])
    common = {"price_revision": price_revision, "currency": "USD",
              "unit": "per million tokens", "billing_assumptions": []}
    if usage["input_tokens"] is None or usage["output_tokens"] is None:
        return {**common, "cost_usd": None,
                "billing_assumptions": ["input or output counter is unknown: no cost is claimed"]}
    cached = usage["cached_input_tokens"]
    if cached is None and "cached_input" in rates:
        # A discounted cache rate makes the unknown split unpricable: guessing
        # either half would turn an unknown into a number.
        return {**common, "cost_usd": None, "billing_assumptions": [
            "cached-input count is unknown, so the cached/uncached split cannot be priced"]}
    if cached:
        if "cached_input" not in rates:
            raise AttributionError("cached input tokens are present but no cached-input rate is "
                                   "given; assuming they are free would understate the cost")
        common["billing_assumptions"].append("cached input is billed at the cached-input rate and "
                                             "is not billed again as uncached input")
        prompt_cost = ((usage["input_tokens"] - cached) * rates["input"]
                       + cached * rates["cached_input"])
    else:
        if cached is None:
            common["billing_assumptions"].append(
                "cached-input count is unknown and the sheet has no cached-input rate: all input "
                "is billed at the input rate")
        prompt_cost = usage["input_tokens"] * rates["input"]
    reasoning = usage["reasoning_output_tokens"]
    if reasoning is None and "reasoning" in rates:
        return {**common, "cost_usd": None, "billing_assumptions": [
            "reasoning count is unknown, so output cannot be split between output and "
            "reasoning prices"]}
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
        if reasoning is None:
            common["billing_assumptions"].append(
                "reasoning count is unknown and the sheet has no reasoning rate: any reasoning "
                "tokens are billed as output")
        output_cost = usage["output_tokens"] * rates["output"]
    return {**common, "cost_usd": round((prompt_cost + output_cost) / 1_000_000, 6)}


def _unique_keys(pairs) -> dict:
    # json.loads keeps the last copy of a repeated key, so an earlier copy would stay in
    # the file unchecked behind a clean digest
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise AttributionError("a JSON object repeats a key; only one copy could be checked")
        obj[key] = value
    return obj


def to_jsonl(records) -> str:
    """The JSONL text of the exported records: one canonical line each, as the CLI reads it."""
    return "".join(_canonical(record) + "\n" for record in export(records))


def _parse_jsonl(text: str) -> list:
    # The verdict and the digest cover the parsed records, so any text the parse
    # discards (float digits past the 17 a double keeps, padding, escapes, key order,
    # a blank line) would stay in the file unchecked behind a clean digest. Every line
    # must therefore be the canonical JSON of its record, as to_jsonl() writes it.
    if "\r" in text:
        # A checkout may turn every LF into CRLF, so an all-CRLF file reads as its LF
        # form. A lone CR or a mix of endings is no such conversion: it would carry a
        # choice per line that the digest never sees.
        if not text.count("\r") == text.count("\r\n") == text.count("\n"):
            raise AttributionError("line endings must be all LF or all CRLF; a lone CR or a "
                                   "mix refuses")
        text = text.replace("\r\n", "\n")
    if text and not text.endswith("\n"):
        raise AttributionError("the last line does not end in a newline")
    records = []
    for number, line in enumerate(text.split("\n")[:-1], 1):
        try:
            record = json.loads(line, object_pairs_hook=_unique_keys)
            canonical = _canonical(record)
        except ValueError as error:
            raise AttributionError(f"line {number}: {error}") from None
        if line != canonical:
            raise AttributionError(f"line {number} is not the canonical JSON of its record (sorted "
                                   "keys, default separators, ASCII escapes, as to_jsonl() "
                                   "writes it)")
        records.append(record)
    return records


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate attributed usage records (issue #61)")
    parser.add_argument("records", type=Path, help="JSONL of attributed observations")
    args = parser.parse_args(argv)
    try:
        # bytes, not read_text(): universal newlines would hide the line endings
        records = _parse_jsonl(args.records.read_bytes().decode("utf-8"))
        exported = export(records)
    except (OSError, ValueError, AttributionError, RecursionError) as error:
        # RecursionError: json.loads gives up on a deeply nested line
        print(f"usage_attribution: REFUSED — {error}", file=sys.stderr)
        return 2
    digest = hashlib.sha256(json.dumps(exported, sort_keys=True).encode("utf-8")).hexdigest()
    print(json.dumps({"schema_version": SCHEMA_VERSION, "records": len(exported),
                      "digest": digest, "by_model": by_model(exported)}, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
