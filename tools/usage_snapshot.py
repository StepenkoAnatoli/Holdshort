#!/usr/bin/env python3
"""Extract usage metadata from one explicitly supplied Codex rollout.

No prompts, tool arguments, credentials, account IDs, or conversation text are
copied. Cumulative tokens are session observations, not a bill or savings claim.
Missing counters remain null; cached input is a subset of input, not extra input.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
          "output_tokens", "reasoning_output_tokens", "total_tokens")


def counters(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("usage must be an object or null")
    result = {key: value.get(key) for key in FIELDS}
    for number in result.values():
        if number is not None and (type(number) is not int or number < 0):
            raise ValueError("usage counters must be nonnegative integers or null")
    for part, whole in (("cached_input_tokens", "input_tokens"),
                        ("reasoning_output_tokens", "output_tokens")):
        if result[part] is not None and result[whole] is not None and result[part] > result[whole]:
            raise ValueError("usage subset exceeds its total")
    return result


def snapshot(path: Path) -> dict:
    latest = None
    models = set()
    model = effort = None
    observations = 0
    with path.open(encoding="utf-8") as source:
        for line in source:
            event = json.loads(line)
            payload = event.get("payload") or {}
            if event.get("type") == "turn_context":
                model = payload.get("model")
                effort = payload.get("effort")
                if isinstance(model, str):
                    models.add(model)
            if event.get("type") == "event_msg" and payload.get("type") == "token_count":
                latest = {"timestamp": event.get("timestamp"), "info": payload.get("info")}
                observations += 1
    info = (latest or {}).get("info") or {}
    cumulative = counters(info.get("total_token_usage"))
    recent = counters(info.get("last_token_usage"))
    return {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_id": hashlib.sha256(path.name.encode()).hexdigest()[:16],
        "usage_observed_at": (latest or {}).get("timestamp"),
        "token_events_observed": observations,
        "latest_model": model,
        "reasoning_effort": effort,
        "models_observed": sorted(models),
        "model_attribution": "session aggregate; not allocated per model or task",
        "context_window_tokens": info.get("model_context_window"),
        "cumulative_usage": cumulative,
        "last_observed_response_usage": recent,
        "usage_status": "observed" if cumulative is not None else "unknown",
        "is_final_bill": False,
        "provider_cost_usd": None,
        "accounting_note": "Cached input overlaps input; reasoning overlaps output. Unknown is not zero. No savings derived.",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        result = snapshot(args.session)
        text = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0
    except (OSError, ValueError, TypeError, AttributeError):
        print("usage_snapshot: malformed or unreadable source; no usage inferred", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
