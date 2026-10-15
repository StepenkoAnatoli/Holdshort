#!/usr/bin/env python3
"""Anthropic dispatch adapter — the real `dispatch_fn` for tools/live_dispatcher.py.

Row-4 contract (docs/PHASE4_LIVE_START_PACKET.md §3, SIGNED 2026-10-10):
  * egress to **api.anthropic.com ONLY** — any other endpoint refuses hard
  * key lives in the **gitignored local .env** (ANTHROPIC_API_KEY=sk-ant-…);
    never read from or written to any tracked file
  * returns the model's ACTUAL (input_tokens, output_tokens) from the
    response usage block — the dispatcher prices spend from these figures
  * the returned dispatch_fn carries `max_tokens`, the request's output
    ceiling, and `count_tokens(profile_id, request)`, which asks the free
    /v1/messages/count_tokens endpoint (same approved host) for the prompt's
    input tokens, so the dispatcher can reserve worst-case cost before sending
  * no third-party dependencies: stdlib urllib only

Profile → model mapping is pinned to the plan §10 catalog (prices-2.json).
cloud-C-alt maps to a different provider entirely and is refused here — it
belongs on api.openai.com and is NOT approved for this pilot.
"""
from __future__ import annotations

import json
import math
import sys
import urllib.error
import urllib.request
from functools import partial
from pathlib import Path
from typing import Dict, Optional, Tuple, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICES_PATH = REPO_ROOT / "tools" / "prices-2.json"
ENV_PATH = Path.home() / ".env"  # only used if no local .env next to repo — .env in repo root is the documented location

APPROVED_ENDPOINT = "https://api.anthropic.com"
MODEL_FOR_PROFILE: Dict[str, str] = {
    "cloud-S": "claude-sonnet-5-5",
    "cloud-C": "claude-haiku-5-5",
    "cloud-O": "claude-opus-5-5",
    "cloud-F": "claude-fable-5-1",
}
MAX_TOKENS_DEFAULT = 4096
REQUEST_TIMEOUT_S = 120


class DispatchRefused(RuntimeError):
    """Fail-closed refusal: caller must not attempt any other route."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects before urllib can forward a credential-bearing request."""

    def http_error_302(self, req, fp, code, msg, headers):
        fp.close()
        raise DispatchRefused("HTTP redirect refused: only the approved endpoint is allowed")

    http_error_301 = http_error_302
    http_error_303 = http_error_302
    http_error_307 = http_error_302
    http_error_308 = http_error_302


# Do not use urlopen's global opener: its default redirect handler can copy
# x-api-key to another origin. Both token counting and dispatch use this opener.
_HTTP_OPENER = urllib.request.build_opener(_NoRedirectHandler())


def parse_env_file(path: Path) -> Dict[str, str]:
    """Tiny .env parser: KEY=VALUE lines; export- and quote-tolerant; no eval."""
    out: Dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            out[k] = v
    return out


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
):
    """Return a dispatch_fn(profile_id, request) -> (in_tokens, out_tokens).

    All refusals raise DispatchRefused (the dispatcher turns that into a
    fail-closed ledger entry via its gate pipeline — the exception is never
    swallowed into a zero-fill).
    """
    if type(timeout_s) not in (int, float):
        raise DispatchRefused("timeout_s must be a finite positive number")
    try:
        timeout_s = float(timeout_s)
    except OverflowError:
        raise DispatchRefused("timeout_s must be a finite positive number") from None
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise DispatchRefused("timeout_s must be a finite positive number")

    if transport is None:
        transport = partial(_http_transport, timeout_s=timeout_s)
        if count_transport is None:
            count_transport = partial(_http_count_transport, timeout_s=timeout_s)
    else:
        # test/mocked transport still goes through consent checks below
        pass

    key = api_key if api_key is not None else load_api_key(env_fallback=env_fallback)

    # endpoint allow-list — the row-4 ONLY-provider rule
    approved = endpoint == APPROVED_ENDPOINT
    if not approved:
        raise DispatchRefused(
            f"endpoint {endpoint!r} is not the approved api.anthropic.com — row-4 egress refus"
        )

    def model_for(profile_id: str) -> str:
        model = MODEL_FOR_PROFILE.get(profile_id)
        if model is None:
            raise DispatchRefused(
                f"profile {profile_id!r} has no approved Anthropic model mapping — refusing"
            )
        return model

    def dispatch_fn(profile_id: str, request: str) -> Tuple[int, int]:
        model = model_for(profile_id)
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": request}],
        }
        return transport(payload, model, key)

    def count_tokens(profile_id: str, request: str) -> int:
        model = model_for(profile_id)
        if count_transport is None:
            # a mocked send transport must never fall through to a real count request
            raise DispatchRefused("no token-count transport wired — refusing to guess the prompt size")
        payload = {"model": model, "messages": [{"role": "user", "content": request}]}
        return count_transport(payload, model, key)

    # the output ceiling and input count the dispatcher prices into its pre-send reservation
    dispatch_fn.max_tokens = max_tokens
    dispatch_fn.count_tokens = count_tokens
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


def _http_count_transport(payload: dict, model: str, key: str,
                          *, timeout_s: float = REQUEST_TIMEOUT_S) -> int:
    # no zero-fill: a missing count must fail the reservation, not price the prompt at $0
    return _post("/v1/messages/count_tokens", payload, key,
                 timeout_s=timeout_s)["input_tokens"]


def _http_transport(payload: dict, model: str, key: str,
                    *, timeout_s: float = REQUEST_TIMEOUT_S) -> Tuple[int, int]:
    doc = _post("/v1/messages", payload, key, timeout_s=timeout_s)
    usage = doc.get("usage")
    if (not isinstance(usage, dict) or any(type(usage.get(field)) is not int
            or usage[field] < 0 for field in ("input_tokens", "output_tokens"))):
        raise RuntimeError("provider response has missing or invalid usage; usage is unknown")
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
            build_dispatch_fn(endpoint=args.endpoint, env_fallback={"ANTHROPIC_API_KEY": "placeholder-check"})
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
