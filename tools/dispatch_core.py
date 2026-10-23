"""Shared, provider-agnostic dispatch core for Holdshort adapters.

This module owns the security-critical, fail-closed pieces that every provider
adapter needs: redirect refusal, finite timeouts, env parsing, key loading, and
the generic HTTP POST helper. Provider-specific facts (endpoint, model map,
payload schema, qualification record) live in adapter modules or profile configs.

Nothing here may be disabled by configuration.
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


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


def load_api_key(env_var: str = "ANTHROPIC_API_KEY", env_path: Optional[Path] = None,
                 env_fallback: Optional[Dict[str, str]] = None) -> str:
    """Resolve an API key from env_fallback or a .env file. Never echoes the value."""
    if env_fallback:
        v = env_fallback.get(env_var, "")
        if v:
            return v
    path = env_path  # caller supplies default
    if path is None:
        raise DispatchRefused("no env path supplied for key resolution")
    parsed = parse_env_file(path)
    key = parsed.get(env_var, "")
    if not key:
        raise DispatchRefused(f"no {env_var} found in {path} - refusing live dispatch")
    return key


def validate_timeout(timeout_s: Any) -> float:
    import math as _math
    if type(timeout_s) not in (int, float):
        raise DispatchRefused("timeout_s must be a finite positive number")
    try:
        timeout_s = float(timeout_s)
    except (OverflowError, ValueError):
        raise DispatchRefused("timeout_s must be a finite positive number") from None
    if not _math.isfinite(timeout_s) or timeout_s <= 0:
        raise DispatchRefused("timeout_s must be a finite positive number")
    return timeout_s


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects before urllib can forward a credential-bearing request."""

    def http_error_302(self, req, fp, code, msg, headers):
        fp.close()
        raise DispatchRefused("HTTP redirect refused: only the approved endpoint is allowed")

    http_error_301 = http_error_302
    http_error_303 = http_error_302
    http_error_307 = http_error_302
    http_error_308 = http_error_302


def build_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_NoRedirectHandler())


_HTTP_OPENER = build_opener()


def http_post(endpoint: str, path: str, payload: dict, key: str, *,
              headers: Optional[Dict[str, str]] = None, timeout_s: float = 120.0) -> dict:
    """Generic, redirect-refusing POST. Returns parsed JSON or raises DispatchRefused."""
    body = json.dumps(payload).encode("utf-8")
    hdrs = {"content-type": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(
        method="POST",
        url=f"{endpoint.rstrip('/')}{path}",
        data=body,
        headers=hdrs,
    )
    try:
        with _HTTP_OPENER.open(req, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        raise DispatchRefused("approved provider HTTP request failed; usage is unknown") from None
    except urllib.error.URLError:
        raise DispatchRefused("approved provider connection failed; usage is unknown") from None
    except (json.JSONDecodeError, UnicodeError):
        raise DispatchRefused("provider response is not valid JSON; usage is unknown") from None
