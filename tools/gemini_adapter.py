#!/usr/bin/env python3
"""Gemini-family comparison adapter — offline preparation only (issue #59).

`tools/dispatch_adapter.py` is the only adapter with an authorized destination:
its row-4 contract permits api.anthropic.com and nothing else. This module exists
so a future Gemini comparison can be prepared, tested and reviewed *without* any
egress. It does three things and nothing else:

  1. maps a provider-neutral request to Gemini's `generateContent` body, refusing
     every setting the mapping does not model instead of silently dropping it;
  2. maps the response back to billable usage, keeping usage null when the
     provider exposes no counter and never double-counting the cached-prompt and
     thinking subsets (issue #59 acceptance);
  3. freezes the trial plan over the *same* subject pack and oracle as the
     comparison cohort, so a later run is comparable rather than a new task set.

No network transport is implemented here: `MockTransport` is the offline stand-in.
`build_dispatch_fn` needs a caller-supplied transport *and* a host authorization
record; the checked-in record is deliberately `unqualified`, so an ordinary run
refuses before any request could be made (issue #59: real egress is off by
default and outside ordinary CI). The bindings a future live comparison must satisfy are in
docs/GEMINI_COMPARISON_ADAPTER.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Callable, Dict, NamedTuple, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
AUTHORIZATION_PATH = REPO_ROOT / "tools" / "gemini_comparison_authorization.json"
SHARED_PACK = REPO_ROOT / "tools" / "calibration" / "subject-pack" / "shared"

# The pack version 1 manifest, byte for byte: a different pack is a different
# comparison and must not be silently substituted under the same plan name.
EXPECTED_PACK_MANIFEST_SHA256 = "0840bd6eac9baa6bf9e6b552949ddd7c5e3758a8102a28d5b5890f5a8573c565"
COHORT = "shared-bounded-reader"

# The only endpoint this adapter knows how to shape a request for. Knowing an
# address is not authorization: the record decides, and it names no destination.
KNOWN_ENDPOINTS = ("https://generativelanguage.googleapis.com",)

SUPPORTED_SETTINGS = frozenset({"response_schema", "system_instruction", "temperature"})
USAGE_FIELDS = frozenset({"promptTokenCount", "candidatesTokenCount", "totalTokenCount",
                          "cachedContentTokenCount", "thoughtsTokenCount"})
MAX_OUTPUT_TOKENS_DEFAULT = 4096

HARNESS = {
    "cells": "one run per profile and case; retry limit 0, a harness retry recorded as such",
    "grading": "grade.sh grades pin and fix; the review cell is graded by the kit's grader, "
               "clustering and lens prompts under the classification's three prongs",
    "packet": "tools/calibration/subject-pack/shared, the same pack and oracle as the cohort",
    "difference": "Gemini is a direct API call, not a cell inside the Claude Code workflow harness: "
                  "no tool access, no repository checkout step and no harness-specific preamble is assumed",
    "readings": "the protocol's before/after usage-window readings are the host's duty",
}


class GeminiRefused(RuntimeError):
    """Fail-closed refusal: the caller must not substitute a model or a route."""

    #: token counts parsed for a refused-but-billed response; never a zero fill
    usage = (None, None)


class GeminiResult(NamedTuple):
    text: str
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    finish_reason: str


class MockTransport:
    """A canned transport: records requests and replays queued responses, no socket.

    The issue asks for a mock transport, not only a transport hook: this is the
    object a host dry run or a test hands to `build_dispatch_fn`. An exhausted
    queue is a refusal, so a test can never accidentally compare one response
    twice or fall through to a real request.
    """

    def __init__(self, *documents):
        self.calls = []
        self._queue = list(documents)

    def __call__(self, mapped, model):
        self.calls.append((mapped, model))
        if not self._queue:
            raise GeminiRefused("mock transport has no queued response")
        return self._queue.pop(0)


def _canonical(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _positive_int(value, what: str) -> int:
    if type(value) is not int or value <= 0:
        raise GeminiRefused(f"{what} must be a positive integer")
    return value


def _sha256_name(value, what: str) -> str:
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise GeminiRefused(f"{what} must be a lowercase sha256 hex digest")
    return value


def load_authorization(path: Path = AUTHORIZATION_PATH) -> Dict[str, object]:
    """Load and validate the host record; the checked-in one is unqualified.

    Every field is exact: an unmodeled key is a refusal, not something to
    ignore, because a field this adapter does not understand may be the one
    that authorizes spend.
    """
    try:
        raw = Path(path).read_bytes()
    except OSError:
        raise GeminiRefused(f"authorization record is unreadable: {path}") from None
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeError):
        raise GeminiRefused("authorization record is not valid JSON") from None
    expected = {"schema_version", "issue", "status", "destination", "profiles",
                "accounting", "count_endpoint", "notes"}
    if not isinstance(doc, dict) or set(doc) != expected:
        raise GeminiRefused(f"authorization record must hold exactly {sorted(expected)}")
    if doc["schema_version"] != 1 or type(doc["schema_version"]) is not int:
        raise GeminiRefused("authorization schema_version must be 1")
    if doc["issue"] != 59 or type(doc["issue"]) is not int:
        raise GeminiRefused("authorization record must name issue 59")
    if doc["status"] != "qualified":
        raise GeminiRefused(
            f"authorization record is {doc['status']!r}: issue #59 is offline preparation only, "
            "no Gemini egress is authorized")
    if doc["destination"] not in KNOWN_ENDPOINTS:
        raise GeminiRefused("authorization destination is not an endpoint this adapter can shape")
    profiles = doc["profiles"]
    if not isinstance(profiles, dict) or not profiles:
        raise GeminiRefused("authorization record must qualify at least one profile")
    for profile_id, entry in profiles.items():
        if not isinstance(profile_id, str) or not profile_id:
            raise GeminiRefused("profile ids must be non-empty strings")
        if not isinstance(entry, dict) or set(entry) != {"model", "max_output_tokens", "input_token_ceiling"}:
            raise GeminiRefused(f"profile {profile_id!r} must hold exactly model, max_output_tokens "
                                "and input_token_ceiling")
        if not isinstance(entry["model"], str) or not entry["model"]:
            raise GeminiRefused(f"profile {profile_id!r} has no qualified model id")
        _positive_int(entry["max_output_tokens"], f"profile {profile_id!r} max_output_tokens")
        if type(entry["input_token_ceiling"]) is not int or entry["input_token_ceiling"] < 0:
            raise GeminiRefused(f"profile {profile_id!r} input_token_ceiling must be a "
                                "nonnegative integer")
    accounting = doc["accounting"]
    if not isinstance(accounting, dict) or set(accounting) != {"scope", "currency",
                                                               "price_revision", "price_sha256"}:
        raise GeminiRefused("accounting must hold exactly scope, currency, price_revision "
                            "and price_sha256")
    if accounting["scope"] != "provider-reported-tokens" or accounting["currency"] != "USD":
        raise GeminiRefused("accounting scope must be provider-reported-tokens in USD")
    if not isinstance(accounting["price_revision"], str) or not accounting["price_revision"]:
        raise GeminiRefused("accounting price_revision must be a non-empty string")
    _sha256_name(accounting["price_sha256"], "accounting price_sha256")
    if doc["count_endpoint"] is not None and doc["count_endpoint"] not in KNOWN_ENDPOINTS:
        raise GeminiRefused("count_endpoint is not an endpoint this adapter can shape")
    notes = doc["notes"]
    if not isinstance(notes, list) or any(not isinstance(note, str) for note in notes):
        raise GeminiRefused("authorization notes must be a list of strings")
    return doc


def _authorization_digest(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        raise GeminiRefused("authorization record became unreadable; refusing to continue") from None


def to_request(model: str, request: str, *, max_output_tokens: int,
               settings: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Map a provider-neutral request to the Gemini generateContent body.

    Unsupported settings refuse by name: dropping a tool declaration or a
    safety override would silently compare a different configuration.
    """
    if not isinstance(model, str) or not model:
        raise GeminiRefused("model id must be a non-empty string")
    if not isinstance(request, str) or not request.strip():
        raise GeminiRefused("request must be a non-empty string")
    _positive_int(max_output_tokens, "max_output_tokens")
    settings = {} if settings is None else settings
    if not isinstance(settings, dict):
        raise GeminiRefused("settings must be a mapping")
    unsupported = sorted(set(settings) - SUPPORTED_SETTINGS)
    if unsupported:
        raise GeminiRefused(f"unsupported Gemini settings: {unsupported}; the mapping will not "
                            "drop them")

    generation: Dict[str, object] = {"maxOutputTokens": max_output_tokens}
    if "response_schema" in settings:
        schema = settings["response_schema"]
        if not isinstance(schema, dict) or not isinstance(schema.get("type"), str):
            raise GeminiRefused("response_schema must be a JSON Schema object with a type")
        generation["responseMimeType"] = "application/json"
        generation["responseSchema"] = schema
    if "temperature" in settings:
        temperature = settings["temperature"]
        if (type(temperature) not in (int, float) or isinstance(temperature, bool)
                or not math.isfinite(temperature) or not 0 <= temperature <= 2):
            raise GeminiRefused("temperature must be a finite number between 0 and 2")
        generation["temperature"] = temperature

    body: Dict[str, object] = {
        "contents": [{"role": "user", "parts": [{"text": request}]}],
        "generationConfig": generation,
    }
    if "system_instruction" in settings:
        instruction = settings["system_instruction"]
        if not isinstance(instruction, str) or not instruction.strip():
            raise GeminiRefused("system_instruction must be a non-empty string")
        body["systemInstruction"] = {"parts": [{"text": instruction}]}
    return {"model": model, "body": body}


def parse_response(document, *, model: str, max_output_tokens: int) -> GeminiResult:
    """Map a Gemini response to text and billable usage; usage stays null when absent."""
    if not isinstance(model, str) or not model:
        raise GeminiRefused("model id must be a non-empty string")
    _positive_int(max_output_tokens, "max_output_tokens")
    if not isinstance(document, dict):
        raise GeminiRefused("provider response is not an object")
    feedback = document.get("promptFeedback")
    if isinstance(feedback, dict) and feedback.get("blockReason") is not None:
        raise GeminiRefused("provider blocked the prompt; nothing was answered")
    if document.get("modelVersion") != model:
        # a different model is a different comparison, never a fallback
        raise GeminiRefused("provider model identity does not match the qualified model")

    candidates = document.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise GeminiRefused("exactly one candidate is part of the qualified configuration")
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise GeminiRefused("provider candidate is not an object")
    finish_reason = candidate.get("finishReason")
    if not isinstance(finish_reason, str) or not finish_reason:
        raise GeminiRefused("provider candidate has no finishReason")
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if (not isinstance(parts, list) or not parts
            or any(not isinstance(part, dict) or not isinstance(part.get("text"), str)
                   for part in parts)):
        raise GeminiRefused("provider candidate has no text parts")
    text = "".join(part["text"] for part in parts)

    usage = document.get("usageMetadata")
    if usage is None:
        return GeminiResult(text, None, None, finish_reason)
    if not isinstance(usage, dict):
        raise GeminiRefused("provider usageMetadata is not an object")
    unmodeled = sorted(set(usage) - USAGE_FIELDS)
    if unmodeled:
        raise GeminiRefused(f"unmodeled provider usage fields {unmodeled}; total charge is unknown")
    prompt, candidates_tokens = usage.get("promptTokenCount"), usage.get("candidatesTokenCount")
    for value, what in ((prompt, "promptTokenCount"), (candidates_tokens, "candidatesTokenCount")):
        if type(value) is not int or value < 0:
            raise GeminiRefused(f"provider {what} is missing or invalid; usage is unknown")
    cached = usage.get("cachedContentTokenCount", 0)
    thoughts = usage.get("thoughtsTokenCount", 0)
    for value, what in ((cached, "cachedContentTokenCount"), (thoughts, "thoughtsTokenCount")):
        if type(value) is not int or value < 0:
            raise GeminiRefused(f"provider {what} is invalid; usage is unknown")
    if cached > prompt:
        raise GeminiRefused("cached prompt tokens exceed the prompt total; usage is unknown")
    if thoughts > candidates_tokens:
        raise GeminiRefused("thinking tokens exceed the candidate total; usage is unknown")
    if "totalTokenCount" in usage:
        total = usage["totalTokenCount"]
        if type(total) is not int or total != prompt + candidates_tokens:
            raise GeminiRefused("provider totalTokenCount disagrees with its parts; usage is unknown")
    # The cached subset is already billed through promptTokenCount and the thinking
    # subset through candidatesTokenCount: subtract, never add, or they double-count.
    input_tokens, output_tokens = prompt - cached, candidates_tokens - thoughts
    if output_tokens > max_output_tokens:
        raise GeminiRefused("provider output exceeds the declared ceiling; usage is outside the "
                            "qualified configuration")
    return GeminiResult(text, input_tokens, output_tokens, finish_reason)


def _refuse_count(profile_id: str, request: str) -> int:
    # Even a record that names a count endpoint does not enable one: this module
    # implements no counting transport, so the dispatcher must block instead of
    # pricing the prompt at zero.
    raise GeminiRefused(
        "no Gemini token-count transport is implemented: the dispatcher's pre-send reservation "
        "must block rather than price the prompt at zero")


def build_dispatch_fn(*, authorization_path: Path = AUTHORIZATION_PATH,
                      transport: Optional[Callable] = None,
                      max_output_tokens: int = MAX_OUTPUT_TOKENS_DEFAULT) -> Callable:
    """Return a dispatcher-compatible `dispatch_fn`, or refuse.

    `transport` is mandatory: this module ships no egress path at all, so a real
    comparison stays a separate, explicitly authorized change.
    """
    _positive_int(max_output_tokens, "max_output_tokens")
    if transport is not None and not callable(transport):
        raise GeminiRefused("transport must be callable")
    if transport is None:
        raise GeminiRefused("real Gemini egress is not implemented or authorized; a mock "
                            "transport is required (issue #59 keeps egress off by default)")
    record = load_authorization(authorization_path)
    snapshot = _authorization_digest(authorization_path)
    profiles = record["profiles"]

    def dispatch_fn(profile_id: str, request: str):
        if _authorization_digest(authorization_path) != snapshot:
            raise GeminiRefused("authorization record changed; rebuild the adapter")
        profile = profiles.get(profile_id) if isinstance(profile_id, str) else None
        if profile is None:
            raise GeminiRefused(f"profile {profile_id!r} is not in the authorization record; "
                                "refusing instead of substituting a model")
        if max_output_tokens > profile["max_output_tokens"]:
            raise GeminiRefused("output ceiling exceeds the profile's qualified maximum")
        mapped = to_request(profile["model"], request, max_output_tokens=max_output_tokens)
        document = transport(mapped, profile["model"])
        result = parse_response(document, model=profile["model"],
                                max_output_tokens=max_output_tokens)
        if result.finish_reason != "STOP":
            refusal = GeminiRefused(f"provider stopped with finishReason {result.finish_reason!r}; "
                                    "the cell is void, not a graded answer")
            refusal.usage = (result.input_tokens, result.output_tokens)
            raise refusal
        return result.input_tokens, result.output_tokens

    dispatch_fn.max_tokens = max_output_tokens
    dispatch_fn.endpoint = record["destination"]
    dispatch_fn.count_tokens = _refuse_count
    dispatch_fn.usage_may_be_missing = True
    dispatch_fn.authorization_sha256 = snapshot
    return dispatch_fn


def frozen_trial_plan(pack_dir: Path = SHARED_PACK) -> Dict[str, object]:
    """The same packet and oracle as the cohort, frozen to the pack's manifest."""
    manifest_path = Path(pack_dir) / "manifest.json"
    try:
        raw = manifest_path.read_bytes()
    except OSError:
        raise GeminiRefused(f"subject pack manifest is unreadable: {manifest_path}") from None
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_PACK_MANIFEST_SHA256:
        raise GeminiRefused(
            f"subject pack changed (manifest {digest[:12]}…): a new comparison needs a new "
            "pinned plan and a new cohort, not a silent substitution")
    try:
        manifest = json.loads(raw)
    except (ValueError, UnicodeError):
        raise GeminiRefused("subject pack manifest is not valid JSON") from None
    for name, expected in manifest["source_hashes"].items():
        target = Path(pack_dir) / name
        if name == "manifest.json":
            continue
        try:
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError:
            raise GeminiRefused(f"subject pack file is missing: {name}") from None
        if actual != expected:
            raise GeminiRefused(f"subject pack file changed: {name}")

    trials = [{"trial_id": f"gemini-{case}", "case": case, "base": spec["base"],
               "tier": spec["tier"], "repeat": 1}
              for case, spec in sorted(manifest["cases"].items())]
    oracle = {key: manifest[key] for key in ("findings", "commands", "paths", "accepted_fix",
                                             "checkout", "commit_rule", "isolation")}
    plan = {
        "cohort": COHORT,
        "pack_version": manifest["pack_version"],
        "manifest_sha256": digest,
        "oracle_sha256": _canonical(oracle),
        "trials": trials,
        "harness": HARNESS,
    }
    plan["plan_sha256"] = _canonical(plan)
    return plan


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Gemini comparison adapter (offline; issue #59)")
    parser.add_argument("command", choices=["plan", "status"])
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            print(json.dumps(frozen_trial_plan(), indent=1, sort_keys=True))
            return 0
        record = load_authorization()
        print(f"status: {record['status']} (destination {record['destination']})")
        return 0
    except GeminiRefused as error:
        print(f"gemini_adapter: REFUSED — {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
