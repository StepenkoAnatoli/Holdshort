#!/usr/bin/env python3
"""Anthropic dispatch adapter — the real `dispatch_fn` for tools/live_dispatcher.py.

Row-4 contract (docs/PHASE4_LIVE_START_PACKET.md §3, SIGNED 2026-10-10):
  * egress to **api.anthropic.com ONLY** — any other endpoint refuses hard
  * key lives in the **gitignored local .env** (ANTHROPIC_API_KEY=sk-ant-…);
    never read from or written to any tracked file
  * returns observed (input_tokens, output_tokens) only for its qualified
    plain-text standard/global scope; final billing is not guaranteed
  * the returned dispatch_fn carries `max_tokens`, the request's output
    ceiling, and `count_tokens(profile_id, request)`, which asks the free
    /v1/messages/count_tokens endpoint (same approved host) to check the prompt,
    then returns the qualified provider input ceiling for reservation
  * real transports require fresh host-reviewed, hash-bound local qualification;
    the checked-in record is unqualified and refuses before any request
  * no third-party dependencies: stdlib urllib only

Profile → model mapping is pinned to the plan §10 catalog (prices-2.json).
cloud-C-alt maps to a different provider entirely and is refused here — it
belongs on api.openai.com and is NOT approved for this pilot.
"""
from __future__ import annotations

try:
    import dispatch_core as _dc
except ImportError:
    from tools import dispatch_core as _dc

import json
import hashlib
import math
import sys
import time
import urllib.error
import urllib.request
from functools import partial
from copy import deepcopy
from pathlib import Path
from typing import Dict, Optional, Tuple, Callable

try:
    import billing_qualification as bq
except ImportError:
    from tools import billing_qualification as bq

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICES_PATH = REPO_ROOT / "tools" / "prices-2.json"
QUALIFICATION_PATH = REPO_ROOT / "tools" / "live_billing_qualification.json"

try:
    import adapter_config as _ac
except ImportError:
    from tools import adapter_config as _ac

_PROFILE_PATH = REPO_ROOT / "tools" / "profiles" / "anthropic.json"
_PROFILE = _ac.load(_PROFILE_PATH)
APPROVED_ENDPOINT = _PROFILE["approved_endpoint"]
MODEL_FOR_PROFILE: Dict[str, str] = _ac.model_map(_PROFILE)
PRICE_MODEL_FOR_PROFILE = _ac.price_model_map(_PROFILE)
MAX_TOKENS_DEFAULT = 4096
REQUEST_TIMEOUT_S = 120


DispatchRefused = _dc.DispatchRefused


class _BillingContext:
    """A fixed host-qualified scope, revalidated before each real operation."""

    def __init__(self, qualification_path=QUALIFICATION_PATH, prices_path=PRICES_PATH,
                 now_fn=time.time):
        self.path, self.prices_path, self.now_fn = qualification_path, prices_path, now_fn
        self.snapshot = self._load()
        try:
            price_bytes = Path(self.prices_path).read_bytes()
            if hashlib.sha256(price_bytes).hexdigest() != self.snapshot["price_sha256"]:
                raise DispatchRefused("qualified price configuration changed during adapter setup")
            self.price_configuration = json.loads(price_bytes)
        except (OSError, ValueError, UnicodeError):
            raise DispatchRefused("qualified price configuration is unavailable") from None

    def _load(self):
        try:
            return bq.load_qualification(self.path, self.prices_path,
                endpoint=APPROVED_ENDPOINT, models=MODEL_FOR_PROFILE,
                price_models=PRICE_MODEL_FOR_PROFILE, now=self.now_fn())
        except bq.BillingQualificationError as error:
            raise DispatchRefused(str(error)) from None

    def profile(self, profile_id, max_tokens):
        current = self._load()
        if current != self.snapshot:
            raise DispatchRefused("billing qualification changed; rebuild the dispatch adapter")
        limit = current["profiles"].get(profile_id)
        if (limit is None or type(max_tokens) is not int or max_tokens <= 0
                or max_tokens > limit["max_output_tokens"]):
            raise DispatchRefused("profile or output ceiling lacks matching billing qualification")
        return limit

    def payload(self, payload, model, *, count=False):
        if not isinstance(payload, dict):
            raise DispatchRefused("request is outside the qualified plain-text billing scope")
        profile_id = next((pid for pid, mid in MODEL_FOR_PROFILE.items() if mid == model), None)
        limit = self.profile(profile_id, 1 if count else payload.get("max_tokens"))
        expected = {"model", "messages"} if count else {
            "model", "messages", "max_tokens", "service_tier", "inference_geo", "stream"}
        messages = payload.get("messages")
        if (set(payload) != expected or payload.get("model") != model
                or not isinstance(messages, list) or len(messages) != 1
                or not isinstance(messages[0], dict) or set(messages[0]) != {"role", "content"}
                or messages[0].get("role") != "user" or not isinstance(messages[0].get("content"), str)
                or (not count and (payload.get("service_tier") != "standard_only"
                    or payload.get("inference_geo") != "global" or payload.get("stream") is not False))):
            raise DispatchRefused("request is outside the qualified plain-text billing scope")
        return limit


_NoRedirectHandler = _dc._NoRedirectHandler


# Do not use urlopen's global opener: its default redirect handler can copy
# x-api-key to another origin. Both token counting and dispatch use this opener.
_HTTP_OPENER = _dc.build_opener()


parse_env_file = _dc.parse_env_file


def load_api_key(env_path: Optional[Path] = None, env_fallback: Optional[Dict[str, str]] = None) -> str:
    """Key resolution order: env_fallback dict → ANTHROPIC_API_KEY from .env file.

    The value is never echoed; callers handle it exclusively.
    """
    if env_fallback:
        v = env_fallback.get("ANTHROPIC_API_KEY", "")
        if v:
            return v
    path = env_path or (REPO_ROOT / ".env")
    parsed = parse_env_file(path)
    key = parsed.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise DispatchRefused(
            f"no ANTHROPIC_API_KEY found in {path} — refusing live dispatch (row-4 key placement)"
        )
    return key


def build_dispatch_fn(
    *,
    api_key: Optional[str] = None,
    env_fallback: Optional[Dict[str, str]] = None,
    endpoint: str = APPROVED_ENDPOINT,
    max_tokens: int = MAX_TOKENS_DEFAULT,
    timeout_s: float = REQUEST_TIMEOUT_S,
    transport: Optional[Callable[[dict, str, str], Tuple[int, int]]] = None,
    count_transport: Optional[Callable[[dict, str, str], int]] = None,
    qualification_path: Path = QUALIFICATION_PATH,
    prices_path: Path = PRICES_PATH,
    now_fn: Callable[[], float] = time.time,
):
    """Return a dispatch_fn(profile_id, request) -> (in_tokens, out_tokens).

    All refusals raise DispatchRefused (the dispatcher turns that into a
    fail-closed ledger entry via its gate pipeline — the exception is never
    swallowed into a zero-fill).

    Custom send transports own their qualification and accounting contract.
    They retain the three-argument interface and never get a real count fallback.
    """
    if type(timeout_s) not in (int, float):
        raise DispatchRefused("timeout_s must be a finite positive number")
    try:
        timeout_s = float(timeout_s)
    except OverflowError:
        raise DispatchRefused("timeout_s must be a finite positive number") from None
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise DispatchRefused("timeout_s must be a finite positive number")

    if endpoint != APPROVED_ENDPOINT:
        raise DispatchRefused("endpoint is not the approved api.anthropic.com")
    billing = None
    if transport is None:
        if type(max_tokens) is not int or max_tokens <= 0:
            raise DispatchRefused("real dispatch requires a positive integer output ceiling")
        billing = _BillingContext(qualification_path, prices_path, now_fn)
        transport = partial(_http_transport, timeout_s=timeout_s, _qualification=billing)
        if count_transport is None:
            count_transport = partial(_http_count_transport, timeout_s=timeout_s, _qualification=billing)
    else:
        # test/mocked transport still goes through consent checks below
        pass

    key = api_key if api_key is not None else load_api_key(env_fallback=env_fallback)

    def model_for(profile_id: str) -> str:
        model = MODEL_FOR_PROFILE.get(profile_id)
        if model is None:
            raise DispatchRefused(
                f"profile {profile_id!r} has no approved Anthropic model mapping — refusing"
            )
        if billing is not None:
            billing.profile(profile_id, max_tokens)
        return model

    def dispatch_fn(profile_id: str, request: str) -> Tuple[int, int]:
        model = model_for(profile_id)
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": request}],
        }
        if billing is not None:
            payload.update(service_tier="standard_only", inference_geo="global", stream=False)
        return transport(payload, model, key)

    def count_tokens(profile_id: str, request: str) -> int:
        model = model_for(profile_id)
        if count_transport is None:
            # a mocked send transport must never fall through to a real count request
            raise DispatchRefused("no token-count transport wired — refusing to guess the prompt size")
        payload = {"model": model, "messages": [{"role": "user", "content": request}]}
        counted = count_transport(payload, model, key)
        if billing is not None:
            ceiling = billing.profile(profile_id, max_tokens)["input_token_ceiling"]
            if type(counted) is not int or not 0 <= counted <= ceiling:
                raise DispatchRefused("input token count is outside the qualified provider ceiling")
            return ceiling
        return counted

    # the output ceiling and input count the dispatcher prices into its pre-send reservation
    dispatch_fn.max_tokens = max_tokens
    dispatch_fn.count_tokens = count_tokens
    if billing is not None:
        dispatch_fn.input_token_ceiling = lambda profile_id: billing.profile(profile_id, max_tokens)["input_token_ceiling"]
        dispatch_fn.qualification_scope = bq.QUALIFICATION_SCOPE
        dispatch_fn.final_bill_guaranteed = False
        dispatch_fn.price_revision = billing.snapshot["price_revision"]
        dispatch_fn.price_sha256 = billing.snapshot["price_sha256"]
        dispatch_fn.price_configuration = deepcopy(billing.price_configuration)
    return dispatch_fn


def _post(path: str, payload: dict, key: str, *, timeout_s: float = REQUEST_TIMEOUT_S) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        method="POST",
        url=f"{APPROVED_ENDPOINT}{path}",
        data=body,
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with _HTTP_OPENER.open(req, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        # HTTPError owns the response even though open() never returned it.
        # Remote error reasons/bodies may contain private request material.
        try:
            error.close()
        finally:
            raise DispatchRefused("approved provider HTTP request failed; usage is unknown") from None
    except urllib.error.URLError:
        raise DispatchRefused("approved provider connection failed; usage is unknown") from None
    except (json.JSONDecodeError, UnicodeError):
        raise DispatchRefused("provider response is not valid JSON; usage is unknown") from None


def _http_count_transport(payload: dict, model: str, key: str,
                          *, timeout_s: float = REQUEST_TIMEOUT_S, _qualification=None) -> int:
    # no zero-fill: a missing count must fail the reservation, not price the prompt at $0
    qualification = _qualification or _BillingContext()
    limit = qualification.payload(payload, model, count=True)
    document = _post("/v1/messages/count_tokens", payload, key, timeout_s=timeout_s)
    counted = document.get("input_tokens") if isinstance(document, dict) else None
    if type(counted) is not int or counted < 0 or counted > limit["input_token_ceiling"]:
        raise DispatchRefused("input token count is outside the qualified provider ceiling")
    # The provider estimate is a check, not the reservation bound. Returning the
    # qualified enforced ceiling makes the dispatcher's legacy margin conservative.
    return limit["input_token_ceiling"]


def _http_transport(payload: dict, model: str, key: str,
                    *, timeout_s: float = REQUEST_TIMEOUT_S, _qualification=None) -> Tuple[int, int]:
    qualification = _qualification or _BillingContext()
    limit = qualification.payload(payload, model)
    doc = _post("/v1/messages", payload, key, timeout_s=timeout_s)
    if not isinstance(doc, dict) or doc.get("model") != model:
        raise DispatchRefused("provider model identity does not match qualification; usage is unknown")
    usage = doc.get("usage")
    if (not isinstance(usage, dict) or any(type(usage.get(field)) is not int
            or usage[field] < 0 for field in ("input_tokens", "output_tokens"))):
        raise RuntimeError("provider response has missing or invalid usage; usage is unknown")
    allowed = {"input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
               "cache_creation", "server_tool_use", "output_tokens_details", "inference_geo", "service_tier", "speed"}
    if (set(usage) - allowed or usage["input_tokens"] > limit["input_token_ceiling"]
            or usage["output_tokens"] > payload["max_tokens"]
            or usage.get("inference_geo", "global") != "global"
            or usage.get("service_tier", "standard") != "standard"
            or usage.get("speed", "standard") != "standard"):
        raise DispatchRefused("provider usage is outside the qualified billing scope; usage is unknown")
    for field in ("cache_creation_input_tokens", "cache_read_input_tokens"):
        if field in usage and (type(usage[field]) is not int or usage[field] != 0):
            raise DispatchRefused("unmodeled cached-token usage; total charge is unknown")
    for field in ("cache_creation", "server_tool_use"):
        value = usage.get(field)
        if value is not None and (not isinstance(value, dict)
                or any(type(n) is not int or n != 0 for n in value.values())):
            raise DispatchRefused("unmodeled provider feature usage; total charge is unknown")
    details = usage.get("output_tokens_details")
    if details is not None and (not isinstance(details, dict) or set(details) - {"thinking_tokens"}
            or ("thinking_tokens" in details and (type(details["thinking_tokens"]) is not int
                or not 0 <= details["thinking_tokens"] <= usage["output_tokens"]))):
        raise DispatchRefused("provider output usage details are invalid; usage is unknown")
    in_toks = usage["input_tokens"]
    out_toks = usage["output_tokens"]
    return in_toks, out_toks


def main(argv=None) -> int:
    """Standalone smoke: refuse-without-key / refuse-unapproved-endpoint / consent-only."""
    import argparse
    ap = argparse.ArgumentParser(description="Anthropic dispatch adapter (fail-closed)")
    ap.add_argument("--check", choices=["key", "endpoint", "mapping"], required=True)
    ap.add_argument("--endpoint", default=APPROVED_ENDPOINT)
    ap.add_argument("--profile", default="cloud-C")
    args = ap.parse_args(argv)

    if args.check == "key":
        try:
            load_api_key(env_path=REPO_ROOT / ".env")
        except DispatchRefused as e:
            print(f"key: REFUSED - {e}")
            return 2
        print("key: present (value not echoed)")
        return 0
    if args.check == "endpoint":
        try:
            # This diagnostic checks endpoint policy without authorizing egress.
            build_dispatch_fn(endpoint=args.endpoint, api_key="check",
                              transport=lambda *_: (0, 0))
        except DispatchRefused as e:
            print(f"endpoint: REFUSED - {e}")
            return 2
        print("endpoint: approved")
        return 0
    if args.check == "mapping":
        print(f"profile→model mapping: {MODEL_FOR_PROFILE}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
