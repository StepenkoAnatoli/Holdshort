"""Shared, provider-agnostic dispatch core for Holdshort adapters.

This module shares redirect refusal, env parsing, and the refusal exception.
Provider adapters retain endpoint authorization, credential handling, finite
timeouts, payload validation, and billing qualification before any HTTP call.

Nothing here may be disabled by configuration.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Dict


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
