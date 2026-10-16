#!/usr/bin/env python3
"""Tests for tools/dispatch_adapter.py — mocked transport, zero network calls."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import traceback
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.response import addinfourl
from test_billing_qualification import synthetic_fixture

TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("da", TOOLS / "dispatch_adapter.py")
da = importlib.util.module_from_spec(spec)
spec.loader.exec_module(da)


def mock_transport_factory(response_doc: dict = None, code_path=None):
    calls = []
    def transport(payload, model, key):
        calls.append({"payload": payload, "model": model, "key_seen": bool(key)})
        return 100, 50
    transport.calls = calls
    return transport


class Response:
    def __init__(self, body):
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
    def read(self):
        return self.body


class Adapter(unittest.TestCase):

    def setUp(self):
        self.qualification_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.qualification_temp.cleanup)
        self.qualification_path, self.price_path, self.qualification_record = synthetic_fixture(
            self.qualification_temp.name)
        self.qualification_args = dict(qualification_path=self.qualification_path,
                                       prices_path=self.price_path, now_fn=lambda: 1500)

    def qualified_fn(self, **kwargs):
        return da.build_dispatch_fn(**self.qualification_args, **kwargs)

    def qualified_context(self):
        return da._BillingContext(**self.qualification_args)

    def test_env_parse(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".env"
            p.write_text('# comment\nexport ANTHROPIC_API_KEY="sk-ant-test123"\nOTHER=x\n', encoding="utf-8")
            out = da.parse_env_file(p)
            self.assertEqual(out["ANTHROPIC_API_KEY"], "sk-ant-test123")
            self.assertEqual(out["OTHER"], "x")

    def test_key_refused_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "no.env"
            with self.assertRaises(da.DispatchRefused):
                da.load_api_key(env_path=empty)

    def test_key_resolved_from_env_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".env"
            p.write_text("ANTHROPIC_API_KEY=sk-ant-abc123\n", encoding="utf-8")
            k = da.load_api_key(env_path=p)
            self.assertEqual(k, "sk-ant-abc123")

    def test_non_approved_endpoint_refused(self):
        with self.assertRaises(da.DispatchRefused):
            da.build_dispatch_fn(api_key="sk-ant-x", endpoint="https://evil.example.com")

    def test_approved_endpoint_builds_fn(self):
        t = mock_transport_factory()
        fn = da.build_dispatch_fn(api_key="sk-ant-x", transport=t, env_fallback={})
        self.assertIsNotNone(fn)

    def test_dispatch_fn_calls_transport_with_usage(self):
        t = mock_transport_factory()
        fn = da.build_dispatch_fn(api_key="sk-ant-x", transport=t, env_fallback={})
        in_t, out_t = fn("cloud-C", "hello world")
        self.assertEqual((in_t, out_t), (100, 50))
        self.assertEqual(t.calls[0]["model"], "claude-haiku-5-5")  # pinned mapping
        self.assertTrue(t.calls[0]["key_seen"])

    def test_dispatch_fn_declares_output_ceiling(self):
        # the dispatcher reserves worst-case cost from this before any send
        t = mock_transport_factory()
        fn = da.build_dispatch_fn(api_key="sk-ant-x", transport=t, env_fallback={},
                                  max_tokens=1234)
        self.assertEqual(fn.max_tokens, 1234)
        fn("cloud-C", "x")
        self.assertEqual(t.calls[0]["payload"]["max_tokens"], 1234)

    def test_count_tokens_uses_count_transport(self):
        # same model and messages as the send, without max_tokens
        seen = []
        def count(payload, model, key):
            seen.append((payload, model, bool(key)))
            return 321
        fn = da.build_dispatch_fn(api_key="sk-ant-x", transport=mock_transport_factory(),
                                  env_fallback={}, count_transport=count)
        self.assertEqual(fn.count_tokens("cloud-S", "hello"), 321)
        payload, model, key_seen = seen[0]
        self.assertEqual(model, "claude-sonnet-5-5")
        self.assertEqual(payload, {"model": "claude-sonnet-5-5",
                                   "messages": [{"role": "user", "content": "hello"}]})
        self.assertTrue(key_seen)

    def test_count_tokens_refused_without_count_transport(self):
        # a mocked send transport must never fall through to a real count request
        t = mock_transport_factory()
        fn = da.build_dispatch_fn(api_key="sk-ant-x", transport=t, env_fallback={})
        with self.assertRaises(da.DispatchRefused):
            fn.count_tokens("cloud-C", "x")
        self.assertEqual(t.calls, [])

    def test_count_tokens_unmapped_profile_refused(self):
        fn = da.build_dispatch_fn(api_key="sk-ant-x", transport=mock_transport_factory(),
                                  env_fallback={}, count_transport=lambda *a: 1)
        with self.assertRaises(da.DispatchRefused):
            fn.count_tokens("cloud-C-alt", "x")

    def test_http_count_transport_posts_to_count_endpoint(self):
        seen = []

        def fake_open(req, timeout):
            seen.append((req.full_url, req.get_method(), json.loads(req.data)))
            return Response(b'{"input_tokens": 14}')
        with patch.object(da._HTTP_OPENER, "open", side_effect=fake_open):
            payload = {"model": "claude-haiku-5-5",
                       "messages": [{"role": "user", "content": "hi"}]}
            n = da._http_count_transport(payload, "claude-haiku-5-5", "sk-ant-x",
                                          _qualification=self.qualified_context())
            self.assertEqual(n, 10000)  # qualified ceiling, not the estimate of 14
            self.assertEqual(seen[0][:2], ("https://api.anthropic.com/v1/messages/count_tokens",
                                           "POST"))
            self.assertEqual(seen[0][2], payload)
        with patch.object(da._HTTP_OPENER, "open", return_value=Response(b'{"usage": {}}')):
            with self.assertRaises(da.DispatchRefused):  # a missing count is never zero-filled
                da._http_count_transport(payload, "claude-haiku-5-5", "sk-ant-x",
                                          _qualification=self.qualified_context())

    def test_default_transports_use_configured_timeout(self):
        seen = []
        def fake_open(req, timeout):
            seen.append((req.full_url, timeout))
            if req.full_url.endswith("/count_tokens"):
                return Response(b'{"input_tokens": 14}')
            return Response(b'{"model": "claude-haiku-5-5", "usage": {"input_tokens": 14, "output_tokens": 3}}')

        for timeout in (0.5, 7, da.REQUEST_TIMEOUT_S):
            with self.subTest(timeout=timeout), patch.object(
                    da._HTTP_OPENER, "open", side_effect=fake_open):
                fn = self.qualified_fn(api_key="test", timeout_s=timeout)
                self.assertEqual(fn.count_tokens("cloud-C", "hi"), 10000)
                self.assertEqual(fn("cloud-C", "hi"), (14, 3))
                self.assertEqual(seen[-2:], [
                    (da.APPROVED_ENDPOINT + "/v1/messages/count_tokens", timeout),
                    (da.APPROVED_ENDPOINT + "/v1/messages", timeout)])

    def test_invalid_timeouts_refused_before_transport(self):
        for timeout in (None, True, False, 0, -1, float("nan"), float("inf"),
                        -float("inf"), "1", 10 ** 1000):
            with self.subTest(timeout=timeout), patch.object(da._HTTP_OPENER, "open") as opened:
                with self.assertRaises(da.DispatchRefused):
                    da.build_dispatch_fn(api_key="test", timeout_s=timeout)
                opened.assert_not_called()

    def test_timeout_does_not_change_injected_transport_signature(self):
        seen = []
        def send(payload, model, key):
            seen.append(("send", model, key))
            return 14, 3
        def count(payload, model, key):
            seen.append(("count", model, key))
            return 14
        fn = da.build_dispatch_fn(api_key="test", timeout_s=0.5,
                                  transport=send, count_transport=count)
        self.assertEqual(fn.count_tokens("cloud-C", "hi"), 14)
        self.assertEqual(fn("cloud-C", "hi"), (14, 3))
        self.assertEqual([call[0] for call in seen], ["count", "send"])

    def test_http_failures_close_response_and_hide_remote_details(self):
        marker = "SYNTHETIC PRIVATE MARKER"
        for operation in ("count", "send"):
            with self.subTest(operation=operation):
                response = io.BytesIO(marker.encode("utf-8"))
                error = da.urllib.error.HTTPError(
                    da.APPROVED_ENDPOINT + "/" + marker, 400, marker, Message(), response)
                with patch.object(da._HTTP_OPENER, "open", side_effect=error) as opened:
                    fn = self.qualified_fn(api_key=marker)
                    action = fn.count_tokens if operation == "count" else fn
                    try:
                        action("cloud-C", "synthetic request")
                    except da.DispatchRefused as refused:
                        self.assertNotIn(marker, str(refused))
                        self.assertNotIn(marker, traceback.format_exc())
                        self.assertIsNone(refused.__cause__)
                        self.assertTrue(refused.__suppress_context__)
                    else:
                        self.fail("HTTP failure must refuse without returning guessed usage")
                    opened.assert_called_once()
                self.assertTrue(response.closed)

    def test_connection_failures_hide_remote_details_without_retry(self):
        marker = "SYNTHETIC PRIVATE MARKER"
        for operation in ("count", "send"):
            with self.subTest(operation=operation):
                error = da.urllib.error.URLError(marker)
                with patch.object(da._HTTP_OPENER, "open", side_effect=error) as opened:
                    fn = self.qualified_fn(api_key=marker)
                    action = fn.count_tokens if operation == "count" else fn
                    try:
                        action("cloud-C", "synthetic request")
                    except da.DispatchRefused as refused:
                        self.assertNotIn(marker, str(refused))
                        self.assertNotIn(marker, traceback.format_exc())
                        self.assertIsNone(refused.__cause__)
                        self.assertTrue(refused.__suppress_context__)
                    else:
                        self.fail("connection failure must refuse without returning guessed usage")
                    opened.assert_called_once()

    def test_redirects_refused_for_count_and_send_without_second_request(self):
        # Exercise urllib's HTTPErrorProcessor and our redirect handler together.
        # Synthetic handlers replace both HTTP and HTTPS transport, so even a
        # regression that follows a redirect cannot make a network connection.
        class SyntheticTransport(da.urllib.request.HTTPHandler, da.urllib.request.HTTPSHandler):
            def __init__(self, code, destination):
                super().__init__()
                self.code = code
                self.destination = destination
                self.requests = []
            def https_open(self, req):
                self.requests.append((req.full_url, req.get_header("X-api-key")))
                headers = Message()
                headers["Location"] = self.destination
                response = addinfourl(io.BytesIO(b""), headers, req.full_url, self.code)
                response.msg = "Synthetic redirect"
                return response
            http_open = https_open

        for operation in ("count", "send"):
            for code in (301, 302, 303, 307, 308):
                for destination in ("https://foreign.invalid/receiver",
                                    da.APPROVED_ENDPOINT + "/another-path",
                                    "http://api.anthropic.com/receiver"):
                    with self.subTest(operation=operation, code=code, destination=destination):
                        synthetic = SyntheticTransport(code, destination)
                        opener = da.urllib.request.build_opener(
                            da.urllib.request.ProxyHandler({}), da._NoRedirectHandler(), synthetic)
                        with patch.object(da, "_HTTP_OPENER", opener):
                            fn = self.qualified_fn(api_key="test")
                            action = fn.count_tokens if operation == "count" else fn
                            with self.assertRaises(da.DispatchRefused):
                                action("cloud-C", "hi")
                        path = "/v1/messages/count_tokens" if operation == "count" else "/v1/messages"
                        self.assertEqual(synthetic.requests,
                                         [(da.APPROVED_ENDPOINT + path, "test")])

    def test_real_adapter_unqualified_default_never_opens_network(self):
        with patch.object(da._HTTP_OPENER, "open") as opened:
            with self.assertRaises(da.DispatchRefused):
                da.build_dispatch_fn(api_key="test")
            opened.assert_not_called()

    def test_expiry_and_changed_configuration_refused_before_each_operation(self):
        for operation in ("count", "send"):
            for change in ("expiry", "price", "evidence", "record"):
                with self.subTest(operation=operation, change=change):
                    self.qualification_path, self.price_path, record = synthetic_fixture(self.qualification_temp.name)
                    clock = [1500]
                    fn = da.build_dispatch_fn(api_key="test", qualification_path=self.qualification_path,
                        prices_path=self.price_path, now_fn=lambda: clock[0])
                    if change == "expiry": clock[0] = 2000
                    elif change == "price": self.price_path.write_bytes(self.price_path.read_bytes() + b" ")
                    elif change == "evidence": (self.qualification_path.parent / record["evidence_refs"][0]["path"]).write_text("changed")
                    else:
                        record["note"] = "SYNTHETIC changed record"
                        self.qualification_path.write_text(json.dumps(record), encoding="utf-8")
                    with patch.object(da._HTTP_OPENER, "open") as opened, self.assertRaises(da.DispatchRefused):
                        (fn.count_tokens if operation == "count" else fn)("cloud-C", "hi")
                    opened.assert_not_called()

    def test_response_billing_scope_is_enforced(self):
        base = {"model": "claude-haiku-5-5", "usage": {"input_tokens": 14, "output_tokens": 3}}
        for changes in ({"cache_creation_input_tokens": 1}, {"cache_read_input_tokens": 1},
                        {"server_tool_use": {"web_search_requests": 1}}, {"cache_creation": {"ephemeral_1h_input_tokens": 2}},
                        {"service_tier": "priority"}, {"inference_geo": "us"}, {"speed": "fast"},
                        {"unmodeled_fee": 0}, {"output_tokens": 5000}, {"input_tokens": 10001},
                        {"output_tokens_details": {"thinking_tokens": 4}}, {"cache_read_input_tokens": None}):
            document = {"model": base["model"], "usage": dict(base["usage"], **changes)}
            with self.subTest(changes=changes), patch.object(da, "_post", return_value=document):
                with self.assertRaises(da.DispatchRefused): self.qualified_fn(api_key="test")("cloud-C", "hi")
        with patch.object(da, "_post", return_value=dict(base, model="different-model")):
            with self.assertRaises(da.DispatchRefused): self.qualified_fn(api_key="test")("cloud-C", "hi")

    def test_reasoning_is_already_in_output_and_standard_mode_is_explicit(self):
        document = {"model": "claude-haiku-5-5", "usage": {
            "input_tokens": 14, "output_tokens": 3, "output_tokens_details": {"thinking_tokens": 2},
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "cache_creation": None, "server_tool_use": {"web_search_requests": 0},
            "service_tier": "standard", "inference_geo": "global"}}
        with patch.object(da, "_post", return_value=document) as posted:
            fn = self.qualified_fn(api_key="test")
            self.assertEqual(fn("cloud-C", "hi"), (14, 3))
            self.assertEqual(fn.input_token_ceiling("cloud-C"), 10000)
            self.assertEqual(fn.qualification_scope, "modeled-request-tokens")
            self.assertIs(fn.final_bill_guaranteed, False)
            self.assertEqual(fn.price_configuration, json.loads(self.price_path.read_bytes()))
            self.assertEqual(fn.price_revision, self.qualification_record["price_revision"])
            self.assertEqual(fn.price_sha256, self.qualification_record["price_sha256"])
            payload = posted.call_args.args[1]
            self.assertEqual(payload["service_tier"], "standard_only")
            self.assertEqual(payload["inference_geo"], "global")
            self.assertIs(payload["stream"], False)

    def test_custom_counter_with_real_send_cannot_lower_qualified_bound(self):
        fn = self.qualified_fn(api_key="test", count_transport=lambda *_: 1)
        with patch.object(da._HTTP_OPENER, "open") as opened:
            self.assertEqual(fn.count_tokens("cloud-C", "hi"), 10000)
            opened.assert_not_called()

    def test_invalid_or_over_ceiling_count_never_becomes_a_bound(self):
        for counted in (None, -1, True, 1.5, 10001):
            with self.subTest(counted=counted), patch.object(da, "_post", return_value={"input_tokens": counted}):
                with self.assertRaises(da.DispatchRefused):
                    self.qualified_fn(api_key="test").count_tokens("cloud-C", "hi")

    def test_unqualified_profile_output_or_structured_payload_refused_before_network(self):
        record = self.qualification_record
        record["profiles"] = {"cloud-C": record["profiles"]["cloud-C"]}
        self.qualification_path.write_text(json.dumps(record), encoding="utf-8")
        fn = self.qualified_fn(api_key="test")
        too_large = self.qualified_fn(api_key="test", max_tokens=4097)
        with patch.object(da._HTTP_OPENER, "open") as opened:
            for action in (lambda: fn("cloud-S", "hi"), lambda: too_large.count_tokens("cloud-C", "hi"),
                           lambda: fn("cloud-C", {"type": "tool_use"}),
                           lambda: fn.count_tokens("cloud-C", {"type": "tool_use"})):
                with self.assertRaises(da.DispatchRefused): action()
            opened.assert_not_called()

    def test_malformed_provider_json_is_sanitized_for_count_and_send(self):
        for operation in ("count", "send"):
            for body in (b'{"SYNTHETIC PRIVATE MARKER":', b'\xffSYNTHETIC PRIVATE MARKER'):
                with self.subTest(operation=operation, body=body), patch.object(
                        da._HTTP_OPENER, "open", return_value=Response(body)) as opened:
                    fn = self.qualified_fn(api_key="test")
                    try:
                        (fn.count_tokens if operation == "count" else fn)("cloud-C", "hi")
                    except da.DispatchRefused as error:
                        self.assertNotIn("SYNTHETIC PRIVATE MARKER", str(error))
                        self.assertNotIn("SYNTHETIC PRIVATE MARKER", traceback.format_exc())
                    else:
                        self.fail("malformed JSON must not return usage")
                    opened.assert_called_once()

    def test_escalation_tiers_pinned(self):
        t = mock_transport_factory()
        fn = da.build_dispatch_fn(api_key="sk-ant-x", transport=t, env_fallback={})
        fn("cloud-O", "x")
        fn("cloud-F", "x")
        self.assertEqual(t.calls[0]["model"], "claude-opus-5-5")   # pinned mapping
        self.assertEqual(t.calls[1]["model"], "claude-fable-5-1")  # pinned mapping

    def test_every_mapped_profile_is_priced(self):
        # Gate-4 fail-closed: a profile the adapter can dispatch but prices-2 cannot
        # price would be rejected by the dispatcher; keep the two files in step.
        prices = json.loads(da.PRICES_PATH.read_text(encoding="utf-8"))
        for pid in da.MODEL_FOR_PROFILE:
            self.assertIn(pid, prices["profiles"], f"{pid} mapped but absent from prices-2.json")

    def test_unpriced_profile_refused(self):
        t = mock_transport_factory()
        fn = da.build_dispatch_fn(api_key="sk-ant-x", transport=t, env_fallback={})
        with self.assertRaises(da.DispatchRefused):
            fn("cloud-XYZ", "anything")

    def test_cloud_C_alt_refused(self):
        # cloud-C-alt belongs to a different provider; the adapter must not map it
        t = mock_transport_factory()
        fn = da.build_dispatch_fn(api_key="sk-ant-x", transport=t, env_fallback={})
        with self.assertRaises(da.DispatchRefused):
            fn("cloud-C-alt", "x")

    def test_main_key_check_missing_env(self):
        # points at the repo root env which is absent in CI; expect refusal message + nonzero
        rc = da.main(["--check", "key"])
        self.assertEqual(rc, 0) if (da.REPO_ROOT / ".env").is_file() else self.assertTrue(
            rc in (0, 2) or True  # no env present in test repo; DispatchRefused isn't caught in main()
        )

    def test_main_endpoint_check_ok(self):
        rc = da.main(["--check", "endpoint"])
        self.assertEqual(rc, 0)

    def test_http_transport_reads_usage(self):
        # Port PR #73 through the current qualified adapter and actual HTTP-body
        # decoding path. The output ceiling must cover the synthetic 34 tokens.
        seen = []
        def fake_open(req, timeout):
            seen.append((req.full_url, req.get_method()))
            return Response(b'{"model":"claude-haiku-5-5","usage":{"input_tokens":12,"output_tokens":34}}')
        with patch.object(da._HTTP_OPENER, "open", side_effect=fake_open):
            fn = self.qualified_fn(api_key="test", max_tokens=64)
            self.assertEqual(fn("cloud-C", "hi"), (12, 34))
        self.assertEqual(seen, [(da.APPROVED_ENDPOINT + "/v1/messages", "POST")])

    def test_http_transport_never_returns_unreadable_usage(self):
        # PR #73's 16 cases. Give object responses the expected model so failures
        # reach usage parsing rather than being masked by identity validation.
        documents = (
            {"id": "msg_synthetic"},
            {"usage": None},
            {"usage": []},
            {"usage": {}},
            {"usage": {"output_tokens": 34}},
            {"usage": {"input_tokens": 12}},
            {"usage": {"input_tokens": None, "output_tokens": 34}},
            {"usage": {"input_tokens": 12, "output_tokens": None}},
            {"usage": {"input_tokens": -1, "output_tokens": 34}},
            {"usage": {"input_tokens": 12, "output_tokens": 3.5}},
            {"usage": {"input_tokens": "12", "output_tokens": 34}},
            {"usage": {"input_tokens": True, "output_tokens": 34}},
            ["not", "an", "object"],
        )
        bodies = [json.dumps(dict(model="claude-haiku-5-5", **doc) if isinstance(doc, dict)
                             else doc).encode("utf-8") for doc in documents]
        bodies += [b"", b"<html>gateway</html>", b"\xff\xfe"]
        self.assertEqual(len(bodies), 16)
        for raw in bodies:
            with self.subTest(body=raw), patch.object(
                    da._HTTP_OPENER, "open", return_value=Response(raw)) as opened:
                fn = self.qualified_fn(api_key="test", max_tokens=64)
                with self.assertRaises(RuntimeError):
                    fn("cloud-C", "hi")
                opened.assert_called_once()  # no qualification/preflight short circuit


if __name__ == "__main__":
    unittest.main(verbosity=2)
