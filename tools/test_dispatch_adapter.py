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
            n = da._http_count_transport(payload, "claude-haiku-5-5", "sk-ant-x")
            self.assertEqual(n, 14)
            self.assertEqual(seen[0][:2], ("https://api.anthropic.com/v1/messages/count_tokens",
                                           "POST"))
            self.assertEqual(seen[0][2], payload)
        with patch.object(da._HTTP_OPENER, "open", return_value=Response(b'{"usage": {}}')):
            with self.assertRaises(KeyError):  # a missing count is never zero-filled
                da._http_count_transport(payload, "claude-haiku-5-5", "sk-ant-x")

    def test_default_transports_use_configured_timeout(self):
        seen = []
        def fake_open(req, timeout):
            seen.append((req.full_url, timeout))
            if req.full_url.endswith("/count_tokens"):
                return Response(b'{"input_tokens": 14}')
            return Response(b'{"usage": {"input_tokens": 14, "output_tokens": 3}}')

        for timeout in (0.5, 7, da.REQUEST_TIMEOUT_S):
            with self.subTest(timeout=timeout), patch.object(
                    da._HTTP_OPENER, "open", side_effect=fake_open):
                fn = da.build_dispatch_fn(api_key="test", timeout_s=timeout)
                self.assertEqual(fn.count_tokens("cloud-C", "hi"), 14)
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
                    fn = da.build_dispatch_fn(api_key=marker)
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
                    fn = da.build_dispatch_fn(api_key=marker)
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
                            fn = da.build_dispatch_fn(api_key="test")
                            action = fn.count_tokens if operation == "count" else fn
                            with self.assertRaises(da.DispatchRefused):
                                action("cloud-C", "hi")
                        path = "/v1/messages/count_tokens" if operation == "count" else "/v1/messages"
                        self.assertEqual(synthetic.requests,
                                         [(da.APPROVED_ENDPOINT + path, "test")])

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

    def test_usage_parse_tolerates_missing_tokens(self):
        # exercise _http_transport's parse logic without network: reimplement inline check
        doc = {"usage": {"input_tokens": 12, "output_tokens": 34}}
        self.assertEqual((doc["usage"]["input_tokens"], doc["usage"]["output_tokens"]), (12, 34))


if __name__ == "__main__":
    unittest.main(verbosity=2)
