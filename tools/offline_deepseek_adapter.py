#!/usr/bin/env python3
"""Offline DeepSeek V4.1 Flash Free (max effort) adapter and scripted mock transport.

This module exists to prepare and exercise the host adapter contract without egress:

  * `build_offline_dispatch_fn()` returns a `dispatch_fn(profile_id, request)`
    callable with the attributes tools/live_dispatcher.py reads from a real
    adapter (`max_tokens`, `count_tokens`, `input_token_ceiling`,
    `price_configuration`, `price_revision`, `price_sha256`,
    `qualification_scope`, `final_bill_guaranteed`).
  * The only accepted transport is a `MockTransport` marked
    `is_offline_mock = True`. All other callables are refused before they run,
    so an accidental network transport cannot be wired here.
  * There is no HTTP client, no socket, no credential read, and no fallback to
    a real provider. `--check live` always refuses.
  * The profile and price file are deliberately unqualified. Loading a profile
    that claims live qualification or target spend authorization refuses.

The request and response shapes are modeled from DeepSeek's official API
documentation; the OpenCode gateway's exact acceptance of those fields remains
an explicitly recorded ambiguity. The mock is evidence of local behavior only,
never of provider behavior.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = REPO_ROOT / "tools" / "profiles" / "deepseek-v4.1-flash-free-max.json"
PRICES_PATH = REPO_ROOT / "tools" / "prices-deepseek-v4.1-flash-free-max.json"
UNIFIED_CONFIG_PATH = REPO_ROOT / "tools" / "profiles" / "deepseek-v4.1-flash-free-max.unified.json"

try:
    import adapter_config as _ac
except ImportError:
    from tools import adapter_config as _ac
_UNIFIED = _ac.load(UNIFIED_CONFIG_PATH)

PROFILE_ID = "deepseek-v4.1-flash-free-max"
MODEL_ID = _UNIFIED["model_for_profile"][PROFILE_ID]
HOST_MODEL_ID = _UNIFIED["host_model_id"]
ENDPOINT = _UNIFIED["approved_endpoint"]
CONTEXT_TOKENS = 200_000
MAX_OUTPUT_TOKENS = 32_000
INPUT_RESERVATION_CEILING = CONTEXT_TOKENS - MAX_OUTPUT_TOKENS
QUALIFICATION_SCOPE = "offline-vendor-limits-and-list-price-bounds"

FINISH_REASONS_USABLE = {"stop", "tool_calls"}
FINISH_REASONS_ALL = {
    "stop", "length", "content_filter", "tool_calls",
    "insufficient_system_resource", "aborted",
}
USAGE_KEYS = {
    "prompt_tokens", "completion_tokens", "total_tokens",
    "prompt_tokens_details", "prompt_cache_hit_tokens",
    "prompt_cache_miss_tokens", "completion_tokens_details",
}


try:
    import dispatch_core as _dc
except ImportError:
    from tools import dispatch_core as _dc

class DispatchRefused(_dc.DispatchRefused):
    """Fail-closed refusal; no guessed usage, no alternate route, no retry."""

    def __init__(self, message: str, *, usage: "Usage | None" = None,
                 cost_usd_bound: Optional[float] = None,
                 finish_reason: Optional[str] = None):
        super().__init__(message)
        self.usage = usage
        self.cost_usd_bound = cost_usd_bound
        self.finish_reason = finish_reason


class UnsupportedRequest(DispatchRefused):
    """The request uses a setting this profile does not model."""


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_input_tokens: Optional[int]
    reasoning_tokens: Optional[int]


@dataclass(frozen=True)
class CompletionResult:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: Optional[int]
    reasoning_tokens: Optional[int]
    cost_usd_bound: float
    finish_reason: str
    content: Optional[str]
    reasoning_content: Optional[str]
    tool_calls: tuple[dict, ...]
    response_model: str
    raw: dict = field(repr=False, compare=False)


def _refuse(message: str, *, usage: Usage | None = None,
            cost: Optional[float] = None,
            finish: Optional[str] = None) -> None:
    raise DispatchRefused(message, usage=usage, cost_usd_bound=cost,
                          finish_reason=finish)


def _read_json(path: Path) -> tuple[bytes, dict]:
    try:
        raw = path.read_bytes()
    except OSError:
        _refuse(f"offline profile input is unavailable: {path.name}")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        _refuse(f"offline profile input is not valid UTF-8 JSON: {path.name}")
    if not isinstance(document, dict):
        _refuse(f"offline profile input is not a JSON object: {path.name}")
    return raw, document


def _is_int(value: Any) -> bool:
    return type(value) is int


def _require_int(value: Any, name: str, *, minimum: int = 0,
                 maximum: Optional[int] = None) -> int:
    if not _is_int(value) or value < minimum or (maximum is not None and value > maximum):
        _refuse(f"{name} is not an integer in the allowed range")
    return value


def _require_str(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        _refuse(f"{name} is not a non-empty string")
    return value


def _require_rate(value: Any, name: str) -> float:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or value < 0 or value != value or value in (float("inf"), float("-inf"))):
        _refuse(f"{name} is not a finite non-negative rate")
    return float(value)


def load_profile(profile_path: Path = PROFILE_PATH,
                 prices_path: Path = PRICES_PATH) -> tuple[dict, dict]:
    """Load the unqualified profile and its hash-bound price bounds, or refuse."""
    profile_bytes, profile = _read_json(profile_path)
    price_bytes, prices = _read_json(prices_path)
    del profile_bytes  # only the price bytes are hash-bound by the profile

    if profile.get("schema_version") != 1:
        _refuse("offline profile schema_version is not 1")
    if profile.get("profile_id") != PROFILE_ID:
        _refuse("offline profile id does not match this adapter")
    if profile.get("model_id") != MODEL_ID:
        _refuse("offline profile model_id does not match this adapter")
    if profile.get("host_model_id") != HOST_MODEL_ID:
        _refuse("offline profile host_model_id does not match this adapter")

    provider = profile.get("provider")
    if (not isinstance(provider, dict) or provider.get("id") != "opencode"
            or provider.get("request_style") != "openai-chat-completions"
            or provider.get("endpoint") != ENDPOINT):
        _refuse("offline profile provider or endpoint is not the documented OpenCode target")

    if profile.get("price_file") != prices_path.name:
        _refuse("offline profile does not bind this price file")
    # Normalise line endings so a CRLF checkout cannot invalidate the bound.
    digest = hashlib.sha256(
        price_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    ).hexdigest()
    if profile.get("price_sha256") != digest:
        _refuse("offline price file changed; the profile's price hash does not match")

    _validate_prices(prices)
    _validate_profile_limits(profile)
    _validate_effort(profile)
    _validate_unqualified(profile, prices)
    return copy.deepcopy(profile), copy.deepcopy(prices)


def _validate_prices(prices: dict) -> None:
    if prices.get("profile_id") != PROFILE_ID or prices.get("model_id") != MODEL_ID:
        _refuse("price file identity does not match the offline profile")
    if prices.get("provider") != "opencode":
        _refuse("price file provider is not opencode")
    if prices.get("currency") != "USD" or prices.get("unit") != "USD per million tokens":
        _refuse("price file currency or unit is not the documented USD-per-MTok form")

    vendor = prices.get("vendor_list_price")
    if not isinstance(vendor, dict) or vendor.get("label") != "vendor list price, not measured cost":
        _refuse("price file does not carry the target's labeled vendor list price")
    for key in ("input_rate_per_mtok", "cached_input_rate_per_mtok", "output_rate_per_mtok"):
        if _require_rate(vendor.get(key), f"vendor_list_price.{key}") != 0.0:
            _refuse(f"vendor_list_price.{key} is not the documented free list price of zero")

    bound = prices.get("conservative_bound")
    if not isinstance(bound, dict):
        _refuse("price file has no conservative bound")
    _require_rate(bound.get("input_rate_per_mtok"), "conservative_bound.input_rate_per_mtok")
    _require_rate(bound.get("cached_input_rate_per_mtok"), "conservative_bound.cached_input_rate_per_mtok")
    _require_rate(bound.get("output_rate_per_mtok"), "conservative_bound.output_rate_per_mtok")
    if (bound.get("input_rate_per_mtok") <= 0
            or bound.get("output_rate_per_mtok") <= 0):
        _refuse("conservative input and output rates must be positive; a zero bound would understate cost")

    spend = prices.get("spend_authorization")
    if not isinstance(spend, dict) or spend.get("authorized") is not False:
        _refuse("price file carries a target spend authorization; this offline adapter refuses it")


def _validate_profile_limits(profile: dict) -> None:
    limits = profile.get("limits")
    if not isinstance(limits, dict):
        _refuse("offline profile has no limits object")
    context = _require_int(limits.get("context_tokens"), "limits.context_tokens")
    output = _require_int(limits.get("max_output_tokens"), "limits.max_output_tokens")
    reservation = _require_int(limits.get("input_token_reservation_ceiling"),
                               "limits.input_token_reservation_ceiling")
    requested = _require_int(limits.get("max_tokens_requested"), "limits.max_tokens_requested")
    if (context, output) != (CONTEXT_TOKENS, MAX_OUTPUT_TOKENS):
        _refuse("offline profile limits are not the documented 200,000 context / 32,000 output")
    if reservation != INPUT_RESERVATION_CEILING or requested != MAX_OUTPUT_TOKENS:
        _refuse("offline profile reservation ceiling or requested max_tokens is inconsistent")
    if reservation + output != context:
        _refuse("offline profile reservation ceiling is not context minus max output")


def _validate_effort(profile: dict) -> None:
    effort = profile.get("effort")
    if not isinstance(effort, dict):
        _refuse("offline profile has no effort object")
    if effort.get("selected") != "max":
        _refuse("offline profile effort is not max")
    if effort.get("request_reasoning_effort") != "max":
        _refuse("offline profile does not pin reasoning_effort to max")
    if effort.get("request_thinking") != {"type": "enabled"}:
        _refuse("offline profile does not pin thinking mode to enabled")
    variants = effort.get("host_variants")
    if not (isinstance(variants, list) and "max" in variants):
        _refuse("offline profile host variants do not include max")
    if not isinstance(effort.get("wire_ambiguity"), str) or len(effort["wire_ambiguity"]) < 20:
        _refuse("offline profile does not record the gateway wire ambiguity")


def _validate_unqualified(profile: dict, prices: dict) -> None:
    qualification = profile.get("qualification")
    if (not isinstance(qualification, dict)
            or qualification.get("status") != "unqualified"
            or qualification.get("live_qualified") is not False):
        _refuse("offline profile claims live qualification; refusing to load it")
    spend = profile.get("spend_authorization")
    if (not isinstance(spend, dict) or spend.get("authorized") is not False
            or prices.get("spend_authorization", {}).get("authorized") is not False):
        _refuse("offline profile or price file claims spend authorization; refusing to load it")


class MockTransport:
    """A scripted, no-network transport. It never creates a socket or URL."""

    is_offline_mock = True

    def __init__(self, responses: Optional[list[Any]] = None):
        self._responses = deque(copy.deepcopy(responses or []))
        self.calls: list[dict] = []
        self.calls_made = 0
        self.key_seen = False

    def queue(self, response: Any) -> None:
        self._responses.append(copy.deepcopy(response))

    @property
    def remaining(self) -> int:
        return len(self._responses)

    def __call__(self, payload: dict, model: str, key: Any) -> dict:
        self.calls_made += 1
        self.key_seen = self.key_seen or bool(key)
        self.calls.append({
            "payload": copy.deepcopy(payload),
            "model": model,
            "key_present": bool(key),
        })
        if not self._responses:
            _refuse("offline mock transport has no scripted response; usage is unknown")
        response = self._responses.popleft()
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return response(copy.deepcopy(payload), model, key)
        return copy.deepcopy(response)


def _offline_transport(transport: Optional[Callable]) -> Callable:
    if transport is None:
        return MockTransport()
    if getattr(transport, "is_offline_mock", False) is not True:
        _refuse("offline adapter accepts only a transport marked is_offline_mock; refusing a possible network transport")
    return transport


def _request_payload(profile: dict, request: Any, *, max_tokens: int) -> dict:
    if isinstance(request, str):
        request_doc: dict = {}
        messages = [{"role": "user", "content": request}]
    elif isinstance(request, dict):
        request_doc = copy.deepcopy(request)
        messages = request_doc.pop("messages", None)
    else:
        _refuse("request must be a string or an object carrying messages")

    if not isinstance(messages, list) or not messages:
        _refuse("request messages must be a non-empty list")
    for i, message in enumerate(messages):
        if not isinstance(message, dict):
            _refuse(f"request messages[{i}] is not an object")
        if message.get("role") not in {"system", "user", "assistant", "tool"}:
            _refuse(f"request messages[{i}].role is not a chat role")
        if message.get("role") in {"system", "user"}:
            if not isinstance(message.get("content"), str):
                _refuse(f"request messages[{i}].content must be text")
        elif message.get("role") == "assistant":
            if message.get("content") is not None and not isinstance(message.get("content"), str):
                _refuse(f"request messages[{i}].content must be text or null")
            if message.get("reasoning_content") is not None and not isinstance(message["reasoning_content"], str):
                _refuse(f"request messages[{i}].reasoning_content must be text or null")
            if message.get("tool_calls") is not None:
                _validate_tool_calls(message["tool_calls"], where=f"request messages[{i}].tool_calls")
        elif message.get("role") == "tool":
            _require_str(message.get("tool_call_id"), f"request messages[{i}].tool_call_id")
            if not isinstance(message.get("content"), str):
                _refuse(f"request messages[{i}].content must be text")

    if "model" in request_doc or "max_tokens" in request_doc:
        _refuse("request must not override the profile's model or max_tokens")
    allowed = {"tools", "tool_choice", "response_format", "thinking",
               "reasoning_effort", "stream", "temperature", "top_p"}
    unknown = set(request_doc) - allowed
    if unknown:
        _refuse(f"request uses unmodeled settings: {', '.join(sorted(unknown))}")
    if request_doc.get("stream") not in (None, False):
        _refuse("offline adapter models non-streaming responses only")
    if request_doc.get("temperature") is not None:
        _refuse("thinking mode ignores temperature; the profile does not model an ignored sampling setting")
    if request_doc.get("top_p") is not None:
        _refuse("top_p is outside the offline profile's modeled request shape")

    effort = request_doc.get("reasoning_effort")
    if effort is not None and effort != "max":
        _refuse("profile pins reasoning_effort to max")
    thinking = request_doc.get("thinking")
    if thinking is not None and thinking != {"type": "enabled"}:
        _refuse("profile pins thinking mode to enabled")

    tools = request_doc.get("tools")
    if tools is not None:
        if not isinstance(tools, list):
            _refuse("request tools must be a list")
        for i, tool in enumerate(tools):
            _validate_tool_definition(tool, where=f"request tools[{i}]")
        if tools:
            _validate_assistant_history(messages)

    tool_choice = request_doc.get("tool_choice")
    if tools and tool_choice is None:
        tool_choice = "auto"
    if tool_choice is not None:
        if tool_choice == "required" or isinstance(tool_choice, dict):
            _refuse("thinking mode does not support required or named tool_choice")
        if tool_choice not in {"auto", "none"}:
            _refuse("tool_choice must be auto or none in thinking mode")
        if not tools and tool_choice != "none":
            _refuse("tool_choice is set but the request carries no tools")

    response_format = request_doc.get("response_format")
    if response_format is not None:
        if not isinstance(response_format, dict) or response_format.get("type") not in {"text", "json_object"}:
            _refuse("response_format must be text or json_object; json_schema is not documented for this profile")
        if response_format.get("type") == "json_object":
            if not any(message.get("role") in {"system", "user"}
                       and isinstance(message.get("content"), str)
                       and "json" in message["content"].lower() for message in messages):
                _refuse("json_object requires the word JSON in a system or user message")

    payload = {
        "model": profile["model_id"],
        "messages": copy.deepcopy(messages),
        "max_tokens": max_tokens,
        "reasoning_effort": "max",
        "thinking": {"type": "enabled"},
        "stream": False,
    }
    if tools:
        payload["tools"] = copy.deepcopy(tools)
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    if response_format is not None:
        payload["response_format"] = copy.deepcopy(response_format)
    return payload


def _validate_tool_definition(tool: Any, *, where: str) -> None:
    if not isinstance(tool, dict) or set(tool) != {"type", "function"} or tool.get("type") != "function":
        _refuse(f"{where} is not a function tool")
    function = tool.get("function")
    if not isinstance(function, dict):
        _refuse(f"{where}.function is not an object")
    name = _require_str(function.get("name"), f"{where}.function.name")
    if len(name) > 128 or any(not (c.isalnum() or c in "_-") for c in name):
        _refuse(f"{where}.function.name is outside the documented character set")
    if not isinstance(function.get("description", ""), str):
        _refuse(f"{where}.function.description is not text")
    if not isinstance(function.get("parameters", {}), dict):
        _refuse(f"{where}.function.parameters is not a JSON Schema object")


def _validate_tool_calls(tool_calls: Any, *, where: str) -> None:
    if not isinstance(tool_calls, list) or not tool_calls:
        _refuse(f"{where} must be a non-empty list")
    seen = set()
    for i, call in enumerate(tool_calls):
        if not isinstance(call, dict) or set(call) != {"id", "type", "function"}:
            _refuse(f"{where}[{i}] is not a function tool call")
        if call.get("type") != "function":
            _refuse(f"{where}[{i}].type is not function")
        call_id = _require_str(call.get("id"), f"{where}[{i}].id")
        if call_id in seen:
            _refuse(f"{where}[{i}].id is duplicated")
        seen.add(call_id)
        function = call.get("function")
        if not isinstance(function, dict) or set(function) != {"name", "arguments"}:
            _refuse(f"{where}[{i}].function is not a name/arguments object")
        _require_str(function.get("name"), f"{where}[{i}].function.name")
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            _refuse(f"{where}[{i}].function.arguments is not a JSON string")
        try:
            parsed = json.loads(arguments)
        except ValueError:
            _refuse(f"{where}[{i}].function.arguments is not valid JSON")
        if not isinstance(parsed, dict):
            _refuse(f"{where}[{i}].function.arguments is not a JSON object")


def _validate_assistant_history(messages: list[dict]) -> None:
    known_calls = set()
    for i, message in enumerate(messages):
        if message.get("role") == "assistant":
            if not isinstance(message.get("reasoning_content"), str):
                _refuse(f"request messages[{i}] omits reasoning_content while tools are present (DeepSeek thinking-mode tool history rule)")
            for call in message.get("tool_calls") or []:
                known_calls.add(call["id"])
        elif message.get("role") == "tool" and message.get("tool_call_id") not in known_calls:
            _refuse(f"request messages[{i}].tool_call_id does not match an earlier assistant tool call")


def _parse_usage(usage: Any) -> Usage:
    if not isinstance(usage, dict):
        _refuse("provider response has missing usage; usage is unknown")
    unknown = set(usage) - USAGE_KEYS
    if unknown:
        _refuse(f"provider usage contains unmodeled fields ({', '.join(sorted(unknown))}); total charge is unknown")
    prompt = _require_int(usage.get("prompt_tokens"), "usage.prompt_tokens")
    completion = _require_int(usage.get("completion_tokens"), "usage.completion_tokens")
    total = _require_int(usage.get("total_tokens"), "usage.total_tokens")
    if total != prompt + completion:
        _refuse("provider usage total_tokens is not prompt_tokens + completion_tokens; usage is unknown")

    cached = None
    details = usage.get("prompt_tokens_details")
    if details is not None:
        if not isinstance(details, dict) or set(details) - {"cached_tokens"}:
            _refuse("provider prompt_tokens_details is not the documented cached_tokens object")
        cached = _require_int(details.get("cached_tokens", 0), "prompt_tokens_details.cached_tokens",
                              maximum=prompt)
    hit = usage.get("prompt_cache_hit_tokens")
    miss = usage.get("prompt_cache_miss_tokens")
    if hit is not None or miss is not None:
        if hit is None or miss is None:
            _refuse("provider usage carries only one of prompt_cache_hit_tokens and prompt_cache_miss_tokens")
        hit = _require_int(hit, "usage.prompt_cache_hit_tokens", maximum=prompt)
        miss = _require_int(miss, "usage.prompt_cache_miss_tokens", maximum=prompt)
        if hit + miss != prompt:
            _refuse("provider cache hit + miss tokens do not equal prompt_tokens; usage is unknown")
        if cached is not None and cached != hit:
            _refuse("provider cached_tokens and prompt_cache_hit_tokens disagree; usage is unknown")
        cached = hit

    reasoning = None
    reasoning_details = usage.get("completion_tokens_details")
    if reasoning_details is not None:
        if not isinstance(reasoning_details, dict) or set(reasoning_details) - {"reasoning_tokens"}:
            _refuse("provider completion_tokens_details is not the documented reasoning_tokens object")
        reasoning = _require_int(reasoning_details.get("reasoning_tokens", 0),
                                  "completion_tokens_details.reasoning_tokens",
                                  maximum=completion)
    return Usage(prompt, completion, total, cached, reasoning)


def _conservative_cost(usage: Usage, prices: dict) -> float:
    bound = prices["conservative_bound"]
    input_rate = float(bound["input_rate_per_mtok"])
    cached_rate = float(bound["cached_input_rate_per_mtok"])
    output_rate = float(bound["output_rate_per_mtok"])
    # Use the higher input/cache rate for every prompt token: a true upper bound
    # whether the cache detail is present, absent, or priced above the base rate.
    prompt_rate = max(input_rate, cached_rate)
    return (usage.prompt_tokens * prompt_rate
            + usage.completion_tokens * output_rate) / 1_000_000.0


def _parse_response(document: Any, payload: dict, profile: dict,
                    prices: dict) -> CompletionResult:
    if not isinstance(document, dict):
        _refuse("provider response is not a JSON object; usage is unknown")
    model = document.get("model")
    if model not in {profile["model_id"], profile["host_model_id"]}:
        _refuse("provider model identity does not match the profile; usage is unknown")

    choices = document.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        _refuse("provider response must carry exactly one choice; usage is unknown")
    choice = choices[0]
    if not isinstance(choice, dict) or choice.get("index") != 0:
        _refuse("provider choice index is not 0; usage is unknown")

    usage = _parse_usage(document.get("usage"))
    cost = _conservative_cost(usage, prices)
    if usage.prompt_tokens > INPUT_RESERVATION_CEILING:
        _refuse("provider prompt_tokens exceeds the offline input reservation ceiling",
                usage=usage, cost=cost)
    if usage.completion_tokens > payload["max_tokens"]:
        _refuse("provider completion_tokens exceeds the requested output ceiling",
                usage=usage, cost=cost)
    if usage.total_tokens > CONTEXT_TOKENS:
        _refuse("provider total_tokens exceeds the documented context limit",
                usage=usage, cost=cost)

    finish = choice.get("finish_reason")
    if finish not in FINISH_REASONS_ALL:
        _refuse(f"provider finish_reason {finish!r} is not a documented value",
                usage=usage, cost=cost)
    if finish not in FINISH_REASONS_USABLE:
        _refuse(f"provider finish_reason {finish!r} is not a usable completion",
                usage=usage, cost=cost, finish=finish)

    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        _refuse("provider choice has no assistant message; usage is unknown",
                usage=usage, cost=cost)
    content = message.get("content")
    reasoning = message.get("reasoning_content")
    tool_calls = message.get("tool_calls")
    if content is not None and not isinstance(content, str):
        _refuse("provider message content is not text or null", usage=usage, cost=cost)
    if reasoning is not None and not isinstance(reasoning, str):
        _refuse("provider message reasoning_content is not text or null", usage=usage, cost=cost)

    if finish == "tool_calls":
        if content not in (None, ""):
            _refuse("provider finish_reason is tool_calls but the message carries content",
                    usage=usage, cost=cost)
        try:
            _validate_tool_calls(tool_calls, where="response message.tool_calls")
        except DispatchRefused as error:
            if error.usage is None:
                raise DispatchRefused(str(error), usage=usage, cost_usd_bound=cost,
                                      finish_reason=finish) from error
            raise
    else:
        if tool_calls is not None:
            _refuse("provider finish_reason is not tool_calls but the message carries tool_calls",
                    usage=usage, cost=cost)
        if content is None:
            _refuse("provider completion has no content", usage=usage, cost=cost)

    response_format = payload.get("response_format")
    if response_format is not None and response_format.get("type") == "json_object":
        if finish != "stop" or not content:
            _refuse("JSON Output returned empty or non-stop content; structured output is unusable",
                    usage=usage, cost=cost, finish=finish)
        try:
            parsed = json.loads(content)
        except ValueError:
            _refuse("JSON Output content is not valid JSON", usage=usage, cost=cost)
        if not isinstance(parsed, (dict, list)):
            _refuse("JSON Output content is not a JSON object or array", usage=usage, cost=cost)

    return CompletionResult(
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        cost_usd_bound=cost,
        finish_reason=finish,
        content=content,
        reasoning_content=reasoning,
        tool_calls=tuple(copy.deepcopy(tool_calls or [])),
        response_model=model,
        raw=copy.deepcopy(document),
    )


def _price_configuration(profile: dict, prices: dict) -> dict:
    bound = prices["conservative_bound"]
    row = {
        "role": "offline DeepSeek V4.1 Flash Free max prep",
        "model": profile["display_name"],
        "input_rate_per_mtok": float(bound["input_rate_per_mtok"]),
        "output_rate_per_mtok": float(bound["output_rate_per_mtok"]),
        "uncertainty_class": "vendor-list-bound-not-measured",
        "bounds_source": bound["source_url"],
        "target_vendor_list_price": copy.deepcopy(prices["vendor_list_price"]),
    }
    return {
        "revision": prices["revision"],
        "currency": prices["currency"],
        "profiles": {PROFILE_ID: row},
        "statement": "conservative vendor list price bound; not a bill and not a target-price claim",
    }


def build_offline_dispatch_fn(*, profile_path: Path = PROFILE_PATH,
                              prices_path: Path = PRICES_PATH,
                              transport: Optional[Callable] = None,
                              max_tokens: Optional[int] = None):
    """Return the offline dispatch callable, or refuse before any transport runs.

    The returned callable follows the real adapter's profile-id request shape
    and carries the same reservation/price attributes the live dispatcher reads.
    It is marked `live_dispatch_allowed = False` and `qualified = False`.
    """
    profile, prices = load_profile(profile_path, prices_path)
    wire = _offline_transport(transport)
    if max_tokens is None:
        max_tokens = profile["limits"]["max_tokens_requested"]
    if not _is_int(max_tokens) or max_tokens <= 0 or max_tokens > MAX_OUTPUT_TOKENS:
        _refuse("max_tokens must be a positive integer no greater than the documented 32,000 output limit")

    def complete(profile_id: str, request: Any) -> CompletionResult:
        if profile_id != PROFILE_ID:
            _refuse(f"profile {profile_id!r} has no offline mapping in this adapter")
        payload = _request_payload(profile, request, max_tokens=max_tokens)
        document = wire(payload, profile["model_id"], None)
        return _parse_response(document, payload, profile, prices)

    def dispatch_fn(profile_id: str, request: Any) -> tuple[int, int]:
        result = complete(profile_id, request)
        dispatch_fn.last_result = result
        return result.input_tokens, result.output_tokens

    def count_tokens(profile_id: str, request: Any) -> int:
        """Return the local reservation ceiling, not a measured or provider tokenizer count."""
        if profile_id != PROFILE_ID:
            _refuse(f"profile {profile_id!r} has no offline mapping in this adapter")
        _request_payload(profile, request, max_tokens=max_tokens)
        # A local reservation bound, not a measured prompt size and not a provider tokenizer.
        return INPUT_RESERVATION_CEILING

    dispatch_fn.complete = complete
    dispatch_fn.max_tokens = max_tokens
    dispatch_fn.count_tokens = count_tokens
    dispatch_fn.input_token_ceiling = lambda profile_id: (
        INPUT_RESERVATION_CEILING if profile_id == PROFILE_ID
        else _refuse(f"profile {profile_id!r} has no offline mapping in this adapter")
    )
    dispatch_fn.price_configuration = _price_configuration(profile, prices)
    dispatch_fn.price_revision = prices["revision"]
    dispatch_fn.price_sha256 = profile["price_sha256"]
    dispatch_fn.qualification_scope = QUALIFICATION_SCOPE
    dispatch_fn.final_bill_guaranteed = False
    dispatch_fn.live_dispatch_allowed = False
    dispatch_fn.qualified = False
    dispatch_fn.transport_kind = "offline-mock"
    dispatch_fn.profile = copy.deepcopy(profile)
    dispatch_fn.last_result = None
    return dispatch_fn


# ---- self-check: local behavior evidence only -------------------------------------------------


def _response(*, content: Optional[str] = "ok", finish: str = "stop",
              tool_calls: Optional[list] = None,
              prompt: int = 12, completion: int = 7,
              cached: Optional[int] = 0, reasoning: Optional[int] = 0,
              model: str = MODEL_ID, usage: Any = ...) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = "synthetic reasoning"
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    doc = {
        "id": "synthetic-offline-response",
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "finish_reason": finish, "message": message}],
    }
    if usage is ...:
        u = {"prompt_tokens": prompt, "completion_tokens": completion,
             "total_tokens": prompt + completion}
        if cached is not None:
            u["prompt_tokens_details"] = {"cached_tokens": cached}
            u["prompt_cache_hit_tokens"] = cached
            u["prompt_cache_miss_tokens"] = prompt - cached
        if reasoning is not None:
            u["completion_tokens_details"] = {"reasoning_tokens": reasoning}
        doc["usage"] = u
    else:
        doc["usage"] = usage
    return doc


def _self_check() -> int:
    checks: list[tuple[str, bool]] = []

    def check(name: str, fn) -> None:
        try:
            fn()
            checks.append((name, True))
        except Exception as error:  # noqa: BLE001 - self-check reports, never hides
            checks.append((name, False))
            print(f"FAIL {name}: {error.__class__.__name__}: {error}")

    def plain() -> None:
        transport = MockTransport([_response()])
        fn = build_offline_dispatch_fn(transport=transport)
        assert fn(PROFILE_ID, "hello") == (12, 7)
        payload = transport.calls[0]["payload"]
        assert payload["model"] == MODEL_ID
        assert payload["reasoning_effort"] == "max"
        assert payload["thinking"] == {"type": "enabled"}
        assert payload["max_tokens"] == MAX_OUTPUT_TOKENS
        assert transport.key_seen is False

    def tools() -> None:
        call = {"id": "call_1", "type": "function",
                "function": {"name": "read_file", "arguments": "{\"path\": \"SPEC.md\"}"}}
        transport = MockTransport([_response(content=None, finish="tool_calls", tool_calls=[call])])
        fn = build_offline_dispatch_fn(transport=transport)
        result = fn.complete(PROFILE_ID, {
            "messages": [{"role": "user", "content": "read the spec"}],
            "tools": [{"type": "function", "function": {"name": "read_file",
                       "description": "read a file", "parameters": {"type": "object"}}}],
        })
        assert result.finish_reason == "tool_calls"
        assert result.tool_calls[0]["function"]["name"] == "read_file"
        assert transport.calls[0]["payload"]["tool_choice"] == "auto"

    def json_output() -> None:
        transport = MockTransport([_response(content="{\"ok\": true}")])
        fn = build_offline_dispatch_fn(transport=transport)
        result = fn.complete(PROFILE_ID, {
            "messages": [{"role": "user", "content": "return JSON: {\"ok\": true}"}],
            "response_format": {"type": "json_object"},
        })
        assert result.content == "{\"ok\": true}"

    def missing_usage() -> None:
        transport = MockTransport([_response(usage=None)])
        fn = build_offline_dispatch_fn(transport=transport)
        try:
            fn(PROFILE_ID, "hello")
        except DispatchRefused as error:
            assert error.usage is None
            assert transport.calls_made == 1
            return
        raise AssertionError("missing usage was not refused")

    def failure_path() -> None:
        transport = MockTransport([_response(finish="aborted")])
        fn = build_offline_dispatch_fn(transport=transport)
        try:
            fn(PROFILE_ID, "hello")
        except DispatchRefused as error:
            assert error.finish_reason == "aborted"
            assert error.usage is not None
            assert error.cost_usd_bound and error.cost_usd_bound > 0
            return
        raise AssertionError("aborted completion was not refused")

    def unsupported() -> None:
        transport = MockTransport([_response()])
        fn = build_offline_dispatch_fn(transport=transport)
        for request in (
            {"messages": [{"role": "user", "content": "x"}], "response_format": {"type": "json_schema"}},
            {"messages": [{"role": "user", "content": "x"}], "tools": [], "tool_choice": "required"},
            {"messages": [{"role": "user", "content": "x"}], "temperature": 0.7},
        ):
            try:
                fn(PROFILE_ID, request)
            except DispatchRefused:
                pass
            else:
                raise AssertionError(f"unsupported request was not refused: {request!r}")
        assert transport.calls_made == 0

    def reservation() -> None:
        fn = build_offline_dispatch_fn(transport=MockTransport())
        assert fn.count_tokens(PROFILE_ID, "hello") == INPUT_RESERVATION_CEILING
        assert fn.input_token_ceiling(PROFILE_ID) == INPUT_RESERVATION_CEILING
        assert fn.max_tokens == MAX_OUTPUT_TOKENS
        assert fn.live_dispatch_allowed is False
        assert fn.qualified is False
        assert fn.transport_kind == "offline-mock"
        assert fn.final_bill_guaranteed is False

    def price_bound() -> None:
        fn = build_offline_dispatch_fn(transport=MockTransport())
        row = fn.price_configuration["profiles"][PROFILE_ID]
        assert row["input_rate_per_mtok"] == 0.3
        assert row["output_rate_per_mtok"] == 1.2
        assert row["target_vendor_list_price"]["input_rate_per_mtok"] == 0.0

    for name, fn in (("plain request and effort", plain),
                     ("tool call", tools),
                     ("structured JSON output", json_output),
                     ("missing usage refused", missing_usage),
                     ("finish_reason failure keeps usage", failure_path),
                     ("unsupported settings refused before transport", unsupported),
                     ("reservation and offline marks", reservation),
                     ("conservative price bound", price_bound)):
        check(name, fn)

    passed = sum(1 for _, ok in checks if ok)
    print(f"offline self-check: {passed}/{len(checks)} passed; no network; no live model qualification")
    return 0 if passed == len(checks) else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline DeepSeek V4.1 Flash Free (max) adapter")
    parser.add_argument("--check", choices=["profile", "live", "self-check"], required=True)
    args = parser.parse_args(argv)
    if args.check == "live":
        print("live: REFUSED - offline adapter only; no target credential, no OpenCode endpoint approval, "
              "no target spend authorization, and no qualified judging profile")
        return 2
    if args.check == "profile":
        profile, prices = load_profile()
        print(json.dumps({
            "profile_id": profile["profile_id"],
            "display_name": profile["display_name"],
            "model_id": profile["model_id"],
            "endpoint": profile["provider"]["endpoint"],
            "effort": profile["effort"]["selected"],
            "context_tokens": profile["limits"]["context_tokens"],
            "max_output_tokens": profile["limits"]["max_output_tokens"],
            "input_reservation_ceiling": profile["limits"]["input_token_reservation_ceiling"],
            "qualified": profile["qualification"]["live_qualified"],
            "price_revision": prices["revision"],
            "price_sha256": profile["price_sha256"],
        }, indent=2))
        return 0
    return _self_check()


if __name__ == "__main__":
    sys.exit(main())
