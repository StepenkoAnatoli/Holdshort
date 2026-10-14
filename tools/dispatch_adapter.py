#!/usr/bin/env python3
"""Anthropic dispatch adapter — the real `dispatch_fn` for tools/live_dispatcher.py.

Row-4 contract (docs/PHASE4_LIVE_START_PACKET.md §3, SIGNED 2026-10-10):
  * egress to **api.anthropic.com ONLY** — any other endpoint refuses hard
  * key lives in the **gitignored local .env** (ANTHROPIC_API_KEY=sk-ant-…);
    never read from or written to any tracked file
  * returns the model's ACTUAL (input_tokens, output_tokens) from the
    response usage block — the dispatcher prices spend from these figures
  * the returned dispatch_fn carries `max_tokens`, the request's output
    ceiling, so the dispatcher can reserve worst-case cost before sending
  * no third-party dependencies: stdlib urllib only

Profile → model mapping is pinned to the plan §10 catalog (prices-2.json).
cloud-C-alt maps to a different provider entirely and is refused here — it
belongs on api.openai.com and is NOT approved for this pilot.
"""
from __future__ import annotations

import json
import sys
import urllib.request
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
    timeout_s: int = REQUEST_TIMEOUT_S,
    transport: Optional[Callable[[dict, str, str], Tuple[int, int]]] = None,
):
    """Return a dispatch_fn(profile_id, request) -> (in_tokens, out_tokens).

    All refusals raise DispatchRefused (the dispatcher turns that into a
    fail-closed ledger entry via its gate pipeline — the exception is never
    swallowed into a zero-fill).
    """
    if transport is None:
        transport = _http_transport
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

    def dispatch_fn(profile_id: str, request: str) -> Tuple[int, int]:
        model = MODEL_FOR_PROFILE.get(profile_id)
        if model is None:
            raise DispatchRefused(
                f"profile {profile_id!r} has no approved Anthropic model mapping — refusing"
            )
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": request}],
        }
        return transport(payload, model, key)

    # the output ceiling the dispatcher prices into its pre-send reservation
    dispatch_fn.max_tokens = max_tokens
    return dispatch_fn


def _http_transport(payload: dict, model: str, key: str) -> Tuple[int, int]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        method="POST",
        url=f"{APPROVED_ENDPOINT}/v1/messages",
        data=body,
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
        doc = json.loads(resp.read().decode("utf-8"))
    usage = doc.get("usage") or {}
    in_toks = int(usage.get("input_tokens") or 0)
    out_toks = int(usage.get("output_tokens") or 0)
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
