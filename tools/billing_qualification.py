"""Validate host-owned evidence for the plain-text modeled-token billing scope.

Artifact hashes establish integrity, not the truth of captured provider claims.
The host must review the evidence before marking a record qualified. Validation
is local only and never fetches a URL or sends a prompt.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time

try:
    import pricing
except ImportError:
    from tools import pricing

REQUEST_MODE = "anthropic-messages-plaintext-standard-global-v1"
QUALIFICATION_SCOPE = "modeled-request-tokens"
EVIDENCE_KINDS = {"provider-limit", "rate", "request-scope"}


class BillingQualificationError(ValueError):
    """The exact supported configuration lacks usable local qualification."""


def _refuse(message):
    raise BillingQualificationError(message)


def _timestamp(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _positive_integer(value):
    return type(value) is int and value > 0


def _evidence(refs, directory, required):
    if not isinstance(refs, list) or not refs:
        _refuse("qualification requires captured local evidence")
    kinds = set()
    for ref in refs:
        if (not isinstance(ref, dict) or not isinstance(ref.get("kind"), str)
                or ref["kind"] not in EVIDENCE_KINDS
                or not isinstance(ref.get("path"), str) or not ref["path"].strip()
                or not isinstance(ref.get("sha256"), str) or len(ref["sha256"]) != 64):
            _refuse("qualification evidence reference is invalid")
        candidate = Path(ref["path"])
        if candidate.is_absolute() or ":" in ref["path"]:
            _refuse("qualification evidence must be a relative local artifact")
        try:
            artifact = (directory / candidate).resolve()
            artifact.relative_to(directory)
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        except (OSError, ValueError, RuntimeError, UnicodeError):
            _refuse("qualification evidence artifact is unavailable")
        if digest != ref["sha256"]:
            _refuse("qualification evidence artifact changed")
        kinds.add(ref["kind"])
    if not required <= kinds:
        _refuse("qualification evidence does not cover its required scope")


def load_qualification(path, prices_path, *, endpoint, models, price_models,
                       now=None):
    """Return a validated snapshot, or refuse without exposing artifact contents.

    Profiles may be qualified individually. Evidence paths are relative to the
    record and must remain inside that directory. Each call checks timestamps,
    exact price-file bytes, model identities, and captured evidence hashes.
    """
    path, prices_path = Path(path), Path(prices_path)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        price_bytes = prices_path.read_bytes()
        prices = json.loads(price_bytes)
    except (OSError, ValueError, UnicodeError):
        _refuse("billing qualification or price configuration is unavailable")
    if not isinstance(record, dict) or record.get("qualified") is not True:
        _refuse("live modeled-token billing qualification is not established")
    if (type(record.get("schema_version")) is not int or record["schema_version"] != 1
            or record.get("endpoint") != endpoint or record.get("request_mode") != REQUEST_MODE
            or record.get("qualification_scope") != QUALIFICATION_SCOPE
            or record.get("final_bill_guaranteed") is not False):
        _refuse("billing qualification does not match the supported request scope")
    observed = time.time() if now is None else now
    verified, expires = record.get("verified_at"), record.get("expires_at")
    if (not all(_timestamp(v) for v in (observed, verified, expires))
            or not verified <= observed < expires):
        _refuse("billing qualification is expired or has invalid timestamps")
    if (not isinstance(prices, dict) or not isinstance(prices.get("profiles"), dict)
            or prices.get("currency") != "USD"
            or not isinstance(record.get("price_revision"), str)
            or record["price_revision"] != prices.get("revision")
            or record.get("price_sha256") != hashlib.sha256(price_bytes).hexdigest()):
        _refuse("billing qualification does not match the current price configuration")
    directory = path.resolve().parent
    _evidence(record.get("evidence_refs"), directory, EVIDENCE_KINDS)
    profiles = record.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        _refuse("billing qualification has no supported profiles")
    for profile_id, limit in profiles.items():
        row = prices["profiles"].get(profile_id)
        if (not isinstance(limit, dict) or profile_id not in models
                or not isinstance(row, dict)
                or limit.get("model_id") != models[profile_id]
                or limit.get("price_model") != price_models.get(profile_id)
                or row.get("model") != limit["price_model"]
                or limit.get("bound_kind") != "provider-enforced-token-ceiling"
                or not _positive_integer(limit.get("input_token_ceiling"))
                or not _positive_integer(limit.get("max_output_tokens"))):
            _refuse("billing qualification profile identity or token ceiling is invalid")
        try:
            pricing.validate_profile(row)
        except (pricing.UnpriceableProfile, ArithmeticError, TypeError):
            _refuse("billing qualification contains unpriceable profile rates")
        tier = row.get("long_context")
        if tier is not None and any(tier[field] < row[field] for field in
                                    ("input_rate_per_mtok", "output_rate_per_mtok")):
            _refuse("billing qualification does not support declining context-tier rates")
        _evidence(limit.get("evidence_refs"), directory, {"provider-limit", "rate"})
    return deepcopy(record)
