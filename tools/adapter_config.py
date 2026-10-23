"""Unified adapter profile configuration loader.

All provider adapters should describe their facts in this common schema so the
security-critical transport in dispatch_core can stay provider-agnostic.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


REQUIRED_TOP = {"schema_version", "provider", "approved_endpoint", "auth_env_var",
                "model_for_profile", "price_model_for_profile"}


class AdapterConfigError(ValueError):
    pass


def load(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise AdapterConfigError(f"cannot read adapter config: {exc}") from None
    if not isinstance(data, dict):
        raise AdapterConfigError("adapter config must be an object")
    missing = REQUIRED_TOP - set(data)
    if missing:
        raise AdapterConfigError(f"missing required fields: {sorted(missing)}")
    if data.get("schema_version") != 1:
        raise AdapterConfigError("schema_version must be 1")
    if not isinstance(data["model_for_profile"], dict) or not data["model_for_profile"]:
        raise AdapterConfigError("model_for_profile must be a nonempty object")
    if not isinstance(data["price_model_for_profile"], dict):
        raise AdapterConfigError("price_model_for_profile must be an object")
    # every mapped profile must have a price model
    for pid in data["model_for_profile"]:
        if pid not in data["price_model_for_profile"]:
            raise AdapterConfigError(f"profile {pid!r} lacks a price_model_for_profile entry")
    return data


def model_map(cfg: Dict[str, Any]) -> Dict[str, str]:
    return dict(cfg["model_for_profile"])


def price_model_map(cfg: Dict[str, Any]) -> Dict[str, str]:
    return dict(cfg["price_model_for_profile"])
