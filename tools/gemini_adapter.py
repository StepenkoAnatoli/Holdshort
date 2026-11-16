#!/usr/bin/env python3
"""Gemini-family comparison adapter — offline preparation only (issue #59).

`tools/dispatch_adapter.py` is the only adapter with an authorized destination:
its row-4 contract permits api.anthropic.com and nothing else. This module exists
so a future Gemini comparison can be prepared, tested and reviewed *without* any
egress. It does three things and nothing else:

  1. maps a provider-neutral request to Gemini's `generateContent` body, refusing
     every setting the mapping does not model instead of silently dropping it;
  2. maps the response back to billable usage, keeping usage null when the
     provider exposes no counter, never double-counting the cached-prompt subset
     (already inside promptTokenCount) and never dropping the thinking tokens
     (separate from candidatesTokenCount, billed as output) (issue #59 acceptance);
     a refusal raised after a billed response carries its counts;
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
USAGE_COUNTERS = ("promptTokenCount", "candidatesTokenCount", "totalTokenCount",
                  "cachedContentTokenCount", "thoughtsTokenCount")
# Per-modality breakdowns (ModalityTokenCount lists) of the counter each one names.
USAGE_DETAILS = {"promptTokensDetails": "promptTokenCount",
                 "cacheTokensDetails": "cachedContentTokenCount",
                 "candidatesTokensDetails": "candidatesTokenCount"}
USAGE_FIELDS = frozenset(USAGE_COUNTERS) | frozenset(USAGE_DETAILS)
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
    """Fail-closed refusal: the caller must not substitute a model or a route.

    A refusal raised after a billed response carries that response's counts as
    `input_tokens` / `output_tokens`: the attributes `live_dispatcher` reads from any
    failed send (its `DispatchFailure` contract). They stay None, never 0, when the
    charge is unknown; only the output is None when the prompt count is still known.
    A refusal before anything is sent carries a known zero for both.
    """

    def __init__(self, message, *, input_tokens=None, output_tokens=None):
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


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
            # nothing is sent, so the charge is a known zero
            raise GeminiRefused("mock transport has no queued response", input_tokens=0,
                                output_tokens=0)
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
    identified = document.get("modelVersion") == model
    feedback = document.get("promptFeedback")
    if isinstance(feedback, dict) and feedback.get("blockReason") is not None:
        # A blocked prompt returns no candidates, and whether it names its model is
        # undocumented, so the block is reported first. Its counts are carried only
        # when they are this model's and known.
        counts = (None, None)
        if identified:
            try:
                counts = _billable_usage(document.get("usageMetadata"))
            except GeminiRefused:
                pass  # the block is the reason; an unknown charge carries no counts
            else:
                if _unreported_output(document):
                    counts = (counts[0], None)
        raise GeminiRefused("provider blocked the prompt; nothing was answered",
                            input_tokens=counts[0], output_tokens=counts[1])
    if not identified:
        # a different model is a different comparison, never a fallback; its counts
        # are not this profile's spend, so they are not carried either
        raise GeminiRefused("provider model identity does not match the qualified model")
    usage = document.get("usageMetadata")
    input_tokens, output_tokens = _billable_usage(usage)
    if _unreported_output(document):
        # The output charge is unknown (None, never 0); the prompt count stays known,
        # and the dispatcher keeps it as a cost floor. This holds before every other
        # refusal, which would carry the reported zero.
        raise GeminiRefused("provider reports no candidate tokens for generated text; output "
                            "usage is unknown", input_tokens=input_tokens, output_tokens=None)

    def refuse(reason: str) -> GeminiRefused:
        # every refusal from here on follows a billed response with known counts
        return GeminiRefused(reason, input_tokens=input_tokens, output_tokens=output_tokens)

    if output_tokens is not None and output_tokens > max_output_tokens:
        raise refuse("provider output exceeds the declared ceiling; usage is outside the "
                     "qualified configuration")
    candidates = document.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise refuse("exactly one candidate is part of the qualified configuration")
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise refuse("provider candidate is not an object")
    finish_reason = candidate.get("finishReason")
    if not isinstance(finish_reason, str) or not finish_reason:
        raise refuse("provider candidate has no finishReason")
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    texts = [_part_text(part) for part in parts] if isinstance(parts, list) else []
    if not texts or any(not isinstance(text, str) for text in texts):
        if finish_reason == "STOP":
            raise refuse("provider candidate has no text parts")
        # A void finish (MAX_TOKENS after thinking spent the budget, SAFETY) can carry
        # no text at all. The cell is void either way; its billed usage must survive.
        return GeminiResult("", input_tokens, output_tokens, finish_reason)
    text = "".join(texts)
    if finish_reason == "STOP" and not text.strip():
        # a STOP candidate can hold a single empty part: nothing was answered
        raise refuse("provider candidate has only empty text")
    return GeminiResult(text, input_tokens, output_tokens, finish_reason)


def _part_text(part):
    """The text a response part adds, or None when it holds another payload.

    A part holding only a thoughtSignature carries no answer, so it adds no text.
    Whether the API sends one outside streaming is unverified. A part with any other
    payload (functionCall, inlineData, ...), even beside text, or with a signature that
    is not a string, still refuses.
    """
    if not isinstance(part, dict) or not set(part) <= {"text", "thoughtSignature"}:
        return None
    if "thoughtSignature" in part and not isinstance(part["thoughtSignature"], str):
        return None
    if "text" in part:
        return part["text"]
    return "" if part else None


def _unreported_output(document) -> bool:
    """Whether the usage block reports no candidate tokens beside generated text.

    Text is not generated in zero tokens, so such a block under-reports the answer.
    Call it only once _billable_usage has accepted the block: an omitted candidate
    count is then a proven zero.
    """
    usage = document.get("usageMetadata")
    return (usage is not None and usage.get("candidatesTokenCount", 0) == 0
            and _generated_text(document.get("candidates")))


def _generated_text(candidates) -> bool:
    """Whether any candidate holds non-empty text, however malformed the rest is."""
    if not isinstance(candidates, list):
        return False
    for candidate in candidates:
        content = candidate.get("content") if isinstance(candidate, dict) else None
        parts = content.get("parts") if isinstance(content, dict) else None
        if isinstance(parts, list) and any(
                isinstance(part, dict) and isinstance(part.get("text"), str) and part["text"]
                for part in parts):
            return True
    return False


def _billable_usage(usage):
    """(input, output) as the dispatcher prices them, or (None, None) when absent.

    Refuses, carrying no counts, whenever the charge is unknown.
    """
    if usage is None:
        return None, None
    if not isinstance(usage, dict):
        raise GeminiRefused("provider usageMetadata is not an object")
    unmodeled = sorted(set(usage) - USAGE_FIELDS)
    if unmodeled:
        raise GeminiRefused(f"unmodeled provider usage fields {unmodeled}; total charge is unknown")
    # The API omits a zero counter ("an implicit presence integer with a 0 value",
    # protobuf.dev/programming-guides/json/), so an absent counter reads as 0. That zero
    # is never trusted for the prompt, and for the candidates only when the reported
    # total proves it (googleapis/python-genai#782: a MAX_TOKENS answer whose thinking
    # spent the budget has no candidatesTokenCount). Without a total, the omission
    # could be a zero or a cut-short usage block, so the charge is unknown.
    counts = {}
    for name in USAGE_COUNTERS:
        value = usage.get(name, 0)
        if type(value) is not int or value < 0:
            raise GeminiRefused(f"provider {name} is invalid; usage is unknown")
        counts[name] = value
    if "promptTokenCount" not in usage:
        raise GeminiRefused("provider promptTokenCount is missing; usage is unknown")
    if "candidatesTokenCount" not in usage and "totalTokenCount" not in usage:
        raise GeminiRefused("provider candidatesTokenCount is missing and no total proves it "
                            "zero; usage is unknown")
    prompt, candidates_tokens = counts["promptTokenCount"], counts["candidatesTokenCount"]
    cached, thoughts = counts["cachedContentTokenCount"], counts["thoughtsTokenCount"]
    if cached > prompt:
        raise GeminiRefused("cached prompt tokens exceed the prompt total; usage is unknown")
    for field, counter in USAGE_DETAILS.items():
        if field in usage and _text_tokens(usage[field], field) != counts[counter]:
            raise GeminiRefused(f"provider {field} disagrees with {counter}; usage is unknown")
    # ai.google.dev/api/generate-content (UsageMetadata): promptTokenCount already
    # includes the cached content, while thoughtsTokenCount is separate from
    # candidatesTokenCount (totalTokenCount = prompt + tool-use prompt + thoughts +
    # candidates; the tool-use prompt count is refused above as unmodeled). Output is
    # billed "including thinking tokens" (ai.google.dev/gemini-api/docs/pricing), so
    # thoughts are added. Cached tokens stay in the input and are priced at the full
    # input rate: a conservative upper bound, never a zero, because the dispatcher
    # has no separate cached rate.
    if "totalTokenCount" in usage and counts["totalTokenCount"] != prompt + candidates_tokens + thoughts:
        raise GeminiRefused("provider totalTokenCount disagrees with its parts; usage is unknown")
    return prompt, candidates_tokens + thoughts


def _text_tokens(details, field: str) -> int:
    """The token sum of a ModalityTokenCount list, refusing any modality but text.

    The request sends only text and the dispatcher prices one input and one output
    rate, while another modality has its own price (Gemini 2.5 Flash input: $0.30 for
    text, image or video, $1.00 for audio; ai.google.dev/gemini-api/docs/pricing).
    """
    if not isinstance(details, list):
        raise GeminiRefused(f"provider {field} is not a list; usage is unknown")
    total = 0
    for entry in details:
        if (not isinstance(entry, dict) or not set(entry) <= {"modality", "tokenCount"}
                or entry.get("modality") != "TEXT"):
            raise GeminiRefused(f"provider {field} holds more than text tokens; the charge is "
                                "unknown")
        count = entry.get("tokenCount", 0)  # a zero count is omitted like a zero counter
        if type(count) is not int or count < 0:
            raise GeminiRefused(f"provider {field} holds an invalid token count; usage is unknown")
        total += count
    return total


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

    def prepare(profile_id: str, request: str):
        if _authorization_digest(authorization_path) != snapshot:
            raise GeminiRefused("authorization record changed; rebuild the adapter")
        profile = profiles.get(profile_id) if isinstance(profile_id, str) else None
        if profile is None:
            raise GeminiRefused(f"profile {profile_id!r} is not in the authorization record; "
                                "refusing instead of substituting a model")
        if max_output_tokens > profile["max_output_tokens"]:
            raise GeminiRefused("output ceiling exceeds the profile's qualified maximum")
        return profile, to_request(profile["model"], request, max_output_tokens=max_output_tokens)

    def dispatch_fn(profile_id: str, request: str):
        try:
            profile, mapped = prepare(profile_id, request)
        except GeminiRefused as err:
            # Nothing was sent, so the charge is a known zero. None would make the
            # dispatcher halt the pilot on an unknown with nothing to reconcile.
            raise GeminiRefused(str(err), input_tokens=0, output_tokens=0) from err
        # a transport refusal keeps its own counts: a real request may already be out
        document = transport(mapped, profile["model"])
        result = parse_response(document, model=profile["model"],
                                max_output_tokens=max_output_tokens)
        if result.finish_reason != "STOP":
            raise GeminiRefused(f"provider stopped with finishReason {result.finish_reason!r}; "
                                "the cell is void, not a graded answer",
                                input_tokens=result.input_tokens,
                                output_tokens=result.output_tokens)
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
