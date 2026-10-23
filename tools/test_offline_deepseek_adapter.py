#!/usr/bin/env python3
"""Tests for tools/offline_deepseek_adapter.py — scripted mock transport, zero network calls.

Every response here is synthetic. None of it is a provider observation, a measured cost, a
qualification result, or evidence that the OpenCode gateway accepts the modeled wire shape.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("oda", TOOLS / "offline_deepseek_adapter.py")
oda = importlib.util.module_from_spec(spec)
sys.modules["oda"] = oda
spec.loader.exec_module(oda)

PROFILE = TOOLS / "profiles" / "deepseek-v4.1-flash-free-max.json"
PRICES = TOOLS / "prices-deepseek-v4.1-flash-free-max.json"


def response(*, content="ok", finish="stop", tool_calls=None,
             prompt=12, completion=7, cached=0, reasoning=0,
             model=oda.MODEL_ID, usage=...):
    message = {"role": "assistant", "content": content}
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
        usage = {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        }
        if cached is not None:
            usage["prompt_tokens_details"] = {"cached_tokens": cached}
            usage["prompt_cache_hit_tokens"] = cached
            usage["prompt_cache_miss_tokens"] = prompt - cached
        if reasoning is not None:
            usage["completion_tokens_details"] = {"reasoning_tokens": reasoning}
    doc["usage"] = usage
    return doc


def tool(name="read_file", arguments='{"path": "SPEC.md"}', call_id="call_1"):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    }


class OfflineAdapterTests(unittest.TestCase):

    def setUp(self):
        self.transport = oda.MockTransport()
        self.fn = oda.build_offline_dispatch_fn(transport=self.transport)

    def test_profile_identity_is_the_documented_target_and_unqualified(self):
        profile, prices = oda.load_profile()
        self.assertEqual(profile["display_name"], "DeepSeek V4.1 Flash Free")
        self.assertEqual(profile["model_id"], "deepseek-v4.1-flash-free")
        self.assertEqual(profile["host_model_id"], "opencode/deepseek-v4.1-flash-free")
        self.assertEqual(profile["provider"]["endpoint"], oda.ENDPOINT)
        self.assertEqual(profile["effort"]["selected"], "max")
        self.assertEqual(profile["limits"]["context_tokens"], 200_000)
        self.assertEqual(profile["limits"]["max_output_tokens"], 32_000)
        self.assertEqual(profile["limits"]["input_token_reservation_ceiling"], 168_000)
        self.assertIs(profile["qualification"]["live_qualified"], False)
        self.assertEqual(profile["qualification"]["status"], "unqualified")
        self.assertIs(profile["spend_authorization"]["authorized"], False)
        self.assertEqual(prices["vendor_list_price"]["input_rate_per_mtok"], 0.0)
        self.assertEqual(prices["vendor_list_price"]["output_rate_per_mtok"], 0.0)

    def test_plain_request_pins_model_effort_limits_and_no_key(self):
        self.transport.queue(response())
        self.assertEqual(self.fn(oda.PROFILE_ID, "hello"), (12, 7))
        payload = self.transport.calls[0]["payload"]
        self.assertEqual(payload["model"], "deepseek-v4.1-flash-free")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "hello"}])
        self.assertEqual(payload["max_tokens"], 32_000)
        self.assertEqual(payload["reasoning_effort"], "max")
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertIs(payload["stream"], False)
        self.assertIs(self.transport.calls[0]["key_present"], False)
        self.assertIsNone(self.transport.calls[0]["payload"].get("api_key"))

    def test_dispatch_fn_carries_the_live_dispatcher_contract_without_qualification(self):
        self.assertEqual(self.fn.max_tokens, 32_000)
        self.assertEqual(self.fn.count_tokens(oda.PROFILE_ID, "hello"), 168_000)
        self.assertEqual(self.fn.input_token_ceiling(oda.PROFILE_ID), 168_000)
        self.assertEqual(self.fn.transport_kind, "offline-mock")
        self.assertIs(self.fn.live_dispatch_allowed, False)
        self.assertIs(self.fn.qualified, False)
        self.assertIs(self.fn.final_bill_guaranteed, False)
        self.assertEqual(self.fn.price_revision, "deepseek-v4.1-flash-free-max-prices-3")
        self.assertEqual(self.fn.price_sha256, json.loads(PROFILE.read_text(encoding="utf-8"))["price_sha256"])
        self.assertEqual(self.fn.price_configuration["profiles"][oda.PROFILE_ID]["input_rate_per_mtok"], 0.3)
        self.assertEqual(self.fn.price_configuration["profiles"][oda.PROFILE_ID]["output_rate_per_mtok"], 1.2)

    def test_reservation_is_a_bound_not_a_provider_tokenizer(self):
        self.assertIn("reservation", self.fn.count_tokens.__doc__ or "")
        self.assertEqual(self.fn.count_tokens(oda.PROFILE_ID, "x" * 10), 168_000)
        self.assertEqual(self.transport.calls_made, 0)

    def test_effort_and_thinking_cannot_be_overridden(self):
        for request in (
            {"messages": [{"role": "user", "content": "x"}], "reasoning_effort": "low"},
            {"messages": [{"role": "user", "content": "x"}], "thinking": {"type": "disabled"}},
            {"messages": [{"role": "user", "content": "x"}], "temperature": 0.7},
            {"messages": [{"role": "user", "content": "x"}], "top_p": 1.0},
        ):
            with self.subTest(request=request):
                with self.assertRaises(oda.DispatchRefused):
                    self.fn(oda.PROFILE_ID, request)
        self.assertEqual(self.transport.calls_made, 0)

    def test_model_and_max_tokens_cannot_be_overridden(self):
        for request in (
            {"messages": [{"role": "user", "content": "x"}], "model": "other"},
            {"messages": [{"role": "user", "content": "x"}], "max_tokens": 100},
        ):
            with self.subTest(request=request):
                with self.assertRaises(oda.DispatchRefused):
                    self.fn(oda.PROFILE_ID, request)
        self.assertEqual(self.transport.calls_made, 0)

    def test_unknown_setting_is_refused(self):
        with self.assertRaises(oda.DispatchRefused):
            self.fn(oda.PROFILE_ID, {"messages": [{"role": "user", "content": "x"}], "seed": 1})
        self.assertEqual(self.transport.calls_made, 0)

    def test_tool_call_response_parses_and_defaults_tool_choice_to_auto(self):
        call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"path": "SPEC.md"}'},
        }
        self.transport.queue(response(content=None, finish="tool_calls", tool_calls=[call]))
        result = self.fn.complete(oda.PROFILE_ID, {
            "messages": [{"role": "user", "content": "read the spec"}],
            "tools": [tool()],
        })
        self.assertEqual(result.finish_reason, "tool_calls")
        self.assertEqual(result.tool_calls[0]["function"]["name"], "read_file")
        self.assertEqual(self.transport.calls[0]["payload"]["tool_choice"], "auto")
        self.assertIn("tools", self.transport.calls[0]["payload"])

    def test_required_and_named_tool_choice_are_refused_before_transport(self):
        base = {"messages": [{"role": "user", "content": "x"}], "tools": [tool()]}
        for choice in ("required", {"type": "function", "function": {"name": "read_file"}}):
            with self.subTest(choice=choice):
                with self.assertRaises(oda.DispatchRefused):
                    self.fn(oda.PROFILE_ID, {**base, "tool_choice": choice})
        self.assertEqual(self.transport.calls_made, 0)

    def test_tool_choice_none_is_allowed(self):
        self.transport.queue(response())
        self.fn(oda.PROFILE_ID, {
            "messages": [{"role": "user", "content": "x"}],
            "tools": [tool()],
            "tool_choice": "none",
        })
        self.assertEqual(self.transport.calls[0]["payload"]["tool_choice"], "none")

    def test_tool_history_requires_reasoning_content(self):
        history = [
            {"role": "user", "content": "read"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "read_file", "arguments": '{"path": "SPEC.md"}'}}
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": "text"},
        ]
        with self.assertRaises(oda.DispatchRefused):
            self.fn(oda.PROFILE_ID, {"messages": history, "tools": [tool()]})
        self.assertEqual(self.transport.calls_made, 0)

    def test_tool_history_with_reasoning_content_is_accepted(self):
        self.transport.queue(response())
        history = [
            {"role": "user", "content": "read"},
            {"role": "assistant", "content": None, "reasoning_content": "I will read.",
             "tool_calls": [{"id": "call_1", "type": "function",
                             "function": {"name": "read_file", "arguments": '{"path": "SPEC.md"}'}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "text"},
        ]
        self.fn(oda.PROFILE_ID, {"messages": history, "tools": [tool()]})
        self.assertEqual(self.transport.calls_made, 1)

    def test_json_object_requires_json_instruction_before_transport(self):
        with self.assertRaises(oda.DispatchRefused):
            self.fn(oda.PROFILE_ID, {
                "messages": [{"role": "user", "content": "return an object"}],
                "response_format": {"type": "json_object"},
            })
        self.assertEqual(self.transport.calls_made, 0)

    def test_json_object_valid_content_passes(self):
        self.transport.queue(response(content='{"ok": true}'))
        result = self.fn.complete(oda.PROFILE_ID, {
            "messages": [{"role": "user", "content": "return JSON: {\"ok\": true}"}],
            "response_format": {"type": "json_object"},
        })
        self.assertEqual(result.content, '{"ok": true}')

    def test_json_schema_is_refused(self):
        with self.assertRaises(oda.DispatchRefused):
            self.fn(oda.PROFILE_ID, {
                "messages": [{"role": "user", "content": "return JSON"}],
                "response_format": {"type": "json_schema", "json_schema": {}},
            })
        self.assertEqual(self.transport.calls_made, 0)

    def test_json_empty_content_is_refused_and_keeps_usage(self):
        self.transport.queue(response(content="", prompt=20, completion=5))
        with self.assertRaises(oda.DispatchRefused) as caught:
            self.fn(oda.PROFILE_ID, {
                "messages": [{"role": "user", "content": "return JSON"}],
                "response_format": {"type": "json_object"},
            })
        self.assertIsNotNone(caught.exception.usage)
        self.assertEqual(caught.exception.usage.prompt_tokens, 20)
        self.assertGreater(caught.exception.cost_usd_bound, 0)
        self.assertEqual(self.transport.calls_made, 1)

    def test_json_truncation_is_refused_and_keeps_usage(self):
        self.transport.queue(response(content='{"ok": tr', finish="length"))
        with self.assertRaises(oda.DispatchRefused) as caught:
            self.fn(oda.PROFILE_ID, {
                "messages": [{"role": "user", "content": "return JSON"}],
                "response_format": {"type": "json_object"},
            })
        self.assertEqual(caught.exception.finish_reason, "length")
        self.assertIsNotNone(caught.exception.usage)
        self.assertEqual(self.transport.calls_made, 1)

    def test_missing_usage_is_refused(self):
        self.transport.queue(response(usage=None))
        with self.assertRaises(oda.DispatchRefused) as caught:
            self.fn(oda.PROFILE_ID, "hello")
        self.assertIsNone(caught.exception.usage)
        self.assertEqual(self.transport.calls_made, 1)

    def test_usage_must_be_self_consistent(self):
        bad = []
        bad.append({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 16})
        bad.append({"prompt_tokens": -1, "completion_tokens": 5, "total_tokens": 4})
        bad.append({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "mystery": 1})
        bad.append({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                    "prompt_tokens_details": {"cached_tokens": 11}})
        bad.append({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                    "completion_tokens_details": {"reasoning_tokens": 6}})
        bad.append({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                    "prompt_cache_hit_tokens": 3})
        bad.append({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                    "prompt_cache_hit_tokens": 3, "prompt_cache_miss_tokens": 9})
        for usage in bad:
            with self.subTest(usage=usage):
                transport = oda.MockTransport([response(usage=usage)])
                fn = oda.build_offline_dispatch_fn(transport=transport)
                with self.assertRaises(oda.DispatchRefused):
                    fn(oda.PROFILE_ID, "hello")
                self.assertEqual(transport.calls_made, 1)

    def test_over_ceiling_usage_is_refused(self):
        cases = [
            dict(prompt=168_001, completion=1, cached=None),
            dict(prompt=100, completion=32_001, cached=None),
        ]
        for case in cases:
            with self.subTest(case=case):
                transport = oda.MockTransport([response(**case)])
                fn = oda.build_offline_dispatch_fn(transport=transport)
                with self.assertRaises(oda.DispatchRefused) as caught:
                    fn(oda.PROFILE_ID, "hello")
                self.assertIsNotNone(caught.exception.usage)

    def test_partial_failure_keeps_usage_and_cost_bound(self):
        self.transport.queue(response(finish="aborted", prompt=12, completion=7, cached=0, reasoning=2))
        with self.assertRaises(oda.DispatchRefused) as caught:
            self.fn(oda.PROFILE_ID, "hello")
        self.assertEqual(caught.exception.finish_reason, "aborted")
        self.assertIsNotNone(caught.exception.usage)
        self.assertEqual(caught.exception.usage.reasoning_tokens, 2)
        self.assertGreater(caught.exception.cost_usd_bound, 0)
        self.assertEqual(self.transport.calls_made, 1)

    def test_transport_failure_is_not_retried(self):
        self.transport.queue(RuntimeError("synthetic transport failure"))
        with self.assertRaises(RuntimeError):
            self.fn(oda.PROFILE_ID, "hello")
        self.assertEqual(self.transport.calls_made, 1)

    def test_no_scripted_response_is_refused(self):
        with self.assertRaises(oda.DispatchRefused):
            self.fn(oda.PROFILE_ID, "hello")
        self.assertEqual(self.transport.calls_made, 1)

    def test_non_mock_transport_is_refused_before_it_runs(self):
        called = []
        def possible_network_transport(payload, model, key):
            called.append(payload)
            return response()
        with self.assertRaises(oda.DispatchRefused):
            oda.build_offline_dispatch_fn(transport=possible_network_transport)
        self.assertEqual(called, [])

    def test_response_model_identity_must_match(self):
        self.transport.queue(response(model="some-other-model"))
        with self.assertRaises(oda.DispatchRefused):
            self.fn(oda.PROFILE_ID, "hello")

    def test_wrong_choice_shape_is_refused(self):
        for mutate in (
            lambda doc: doc.update(choices=[]),
            lambda doc: doc["choices"][0].update(index=1),
            lambda doc: doc["choices"][0].update(finish_reason="mystery"),
            lambda doc: doc["choices"][0].update(message={"role": "user", "content": "x"}),
        ):
            with self.subTest(mutate=mutate):
                doc = response()
                mutate(doc)
                transport = oda.MockTransport([doc])
                fn = oda.build_offline_dispatch_fn(transport=transport)
                with self.assertRaises(oda.DispatchRefused):
                    fn(oda.PROFILE_ID, "hello")

    def test_tool_call_arguments_must_be_valid_json(self):
        call = {"id": "call_1", "type": "function",
                "function": {"name": "read_file", "arguments": "{not json"}}
        self.transport.queue(response(content=None, finish="tool_calls", tool_calls=[call]))
        with self.assertRaises(oda.DispatchRefused) as caught:
            self.fn(oda.PROFILE_ID, {
                "messages": [{"role": "user", "content": "x"}],
                "tools": [tool()],
            })
        self.assertIsNotNone(caught.exception.usage)

    def test_finish_reason_and_tool_calls_must_agree(self):
        call = {"id": "call_1", "type": "function",
                "function": {"name": "read_file", "arguments": "{}"}}
        cases = [
            response(content="text", finish="stop", tool_calls=[call]),
            response(content="text", finish="tool_calls", tool_calls=[call]),
            response(content=None, finish="stop", tool_calls=None),
        ]
        for doc in cases:
            with self.subTest(doc=doc):
                transport = oda.MockTransport([doc])
                fn = oda.build_offline_dispatch_fn(transport=transport)
                with self.assertRaises(oda.DispatchRefused):
                    fn(oda.PROFILE_ID, "hello")

    def test_reasoning_tokens_do_not_add_a_second_output_charge(self):
        plain = oda.MockTransport([response(prompt=100, completion=20, cached=0, reasoning=None)])
        with_reasoning = oda.MockTransport([response(prompt=100, completion=20, cached=0, reasoning=10)])
        a = oda.build_offline_dispatch_fn(transport=plain).complete(oda.PROFILE_ID, "hello")
        b = oda.build_offline_dispatch_fn(transport=with_reasoning).complete(oda.PROFILE_ID, "hello")
        self.assertEqual(a.output_tokens, b.output_tokens)
        self.assertEqual(a.cost_usd_bound, b.cost_usd_bound)

    def test_cached_input_tokens_never_lower_the_conservative_bound(self):
        # The price file's cached rate is lower than input; the bound uses the
        # higher rate for every prompt token, so cache detail cannot lower it.
        plain = oda.MockTransport([response(prompt=100, completion=10, cached=None, reasoning=None)])
        cached = oda.MockTransport([response(prompt=100, completion=10, cached=100, reasoning=None)])
        a = oda.build_offline_dispatch_fn(transport=plain).complete(oda.PROFILE_ID, "x")
        b = oda.build_offline_dispatch_fn(transport=cached).complete(oda.PROFILE_ID, "x")
        self.assertEqual(a.cost_usd_bound, b.cost_usd_bound)
        self.assertEqual(a.cached_input_tokens, None)
        self.assertEqual(b.cached_input_tokens, 100)

    def test_missing_profile_or_price_file_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(oda.DispatchRefused):
                oda.load_profile(Path(tmp) / "missing-profile.json", PRICES)
            with self.assertRaises(oda.DispatchRefused):
                oda.load_profile(PROFILE, Path(tmp) / "missing-prices.json")

    def test_price_tamper_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            tampered = Path(tmp) / PRICES.name
            prices = json.loads(PRICES.read_text(encoding="utf-8"))
            prices["conservative_bound"]["output_rate_per_mtok"] = 0.01
            tampered.write_text(json.dumps(prices), encoding="utf-8")
            with self.assertRaises(oda.DispatchRefused) as caught:
                oda.load_profile(PROFILE, tampered)
            self.assertIn("price", str(caught.exception).lower())

    def test_price_hash_ignores_line_endings(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = PRICES.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            price_path = Path(tmp) / PRICES.name
            price_path.write_bytes(data.replace(b"\n", b"\r\n"))
            profile = json.loads(PROFILE.read_text(encoding="utf-8"))
            profile["price_sha256"] = hashlib.sha256(data).hexdigest()
            profile_path = Path(tmp) / PROFILE.name
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            loaded, prices = oda.load_profile(profile_path, price_path)
            self.assertEqual(loaded["profile_id"], oda.PROFILE_ID)
            self.assertEqual(prices["revision"], "deepseek-v4.1-flash-free-max-prices-3")

    def test_qualified_profile_refuses(self):
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        profile["qualification"]["live_qualified"] = True
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / PROFILE.name
            path.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaises(oda.DispatchRefused):
                oda.load_profile(path, PRICES)

    def test_spend_authorization_refuses(self):
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        profile["spend_authorization"]["authorized"] = True
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / PROFILE.name
            path.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaises(oda.DispatchRefused):
                oda.load_profile(path, PRICES)

    def test_zero_conservative_bound_refuses(self):
        for field in ("input_rate_per_mtok", "output_rate_per_mtok"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                prices = json.loads(PRICES.read_text(encoding="utf-8"))
                prices["conservative_bound"][field] = 0.0
                price_path = Path(tmp) / PRICES.name
                price_path.write_text(json.dumps(prices), encoding="utf-8")
                profile = json.loads(PROFILE.read_text(encoding="utf-8"))
                profile["price_sha256"] = hashlib.sha256(
                    price_path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
                ).hexdigest()
                profile_path = Path(tmp) / PROFILE.name
                profile_path.write_text(json.dumps(profile), encoding="utf-8")
                with self.assertRaises(oda.DispatchRefused):
                    oda.load_profile(profile_path, price_path)

    def test_live_check_refuses(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = oda.main(["--check", "live"])
        self.assertEqual(code, 2)
        self.assertIn("REFUSED", output.getvalue())

    def test_self_check_passes(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = oda._self_check()
        self.assertEqual(code, 0, output.getvalue())
        self.assertIn("no network", output.getvalue())
        self.assertIn("no live model qualification", output.getvalue())

    def test_module_contains_no_network_client(self):
        source = Path(oda.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "import urllib", "from urllib", "import http", "from http",
            "import socket", "from socket", "import requests", "from requests",
            "import aiohttp", "from aiohttp", "urlopen(", "httpx",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
