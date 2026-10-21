#!/usr/bin/env python3
"""Offline tests for tools/gemini_adapter.py (issue #59).

Every test here is mock-only: no socket is opened, no key is read and no
provider is contacted. The acceptance list this pins:

  * request mapping, structured output, missing usage, partial failure and
    unsupported settings (issue #59 acceptance 1);
  * unknown capability, price, accounting or destination blocks execution
    instead of substituting a model (acceptance 2);
  * usage stays null when the provider exposes no counter, and the cached-prompt
    and thinking subsets are never double-counted (acceptance 4);
  * real egress stays disabled: the checked-in record is unqualified and the
    adapter has no transport of its own (acceptance 5);
  * the frozen trial plan uses the cohort's packet and oracle (acceptance 3).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
spec = importlib.util.spec_from_file_location("ga", TOOLS / "gemini_adapter.py")
ga = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ga)

MODEL = "gemini-3.0-pro-001"


def qualified_record(**overrides) -> dict:
    """A synthetic qualification: the shape a host record must have, never a host approval."""
    doc = {
        "schema_version": 1,
        "issue": 59,
        "status": "qualified",
        "destination": "https://generativelanguage.googleapis.com",
        "profiles": {"cloud-G": {"model": MODEL, "max_output_tokens": 4096,
                                 "input_token_ceiling": 200000}},
        "accounting": {"scope": "provider-reported-tokens", "currency": "USD",
                       "price_revision": "gemini-prices-1", "price_sha256": "a" * 64},
        "count_endpoint": None,
        "notes": ["synthetic test record, not a host authorization"],
    }
    doc.update(overrides)
    return doc


def response(*, usage=None, finish="STOP", version=MODEL, text="answer") -> dict:
    doc = {"modelVersion": version,
           "candidates": [{"finishReason": finish, "content": {"parts": [{"text": text}]}}]}
    if usage is not None:
        doc["usageMetadata"] = usage
    return doc


class RecordCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "authorization.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, doc) -> Path:
        self.path.write_text(json.dumps(doc), encoding="utf-8")
        return self.path

    def adapter(self, record=None, calls=None, document=None, **kwargs):
        transport = None
        if calls is not None:
            def transport(mapped, model):
                calls.append((mapped, model))
                return document
        return ga.build_dispatch_fn(authorization_path=self.write(record or qualified_record()),
                                    transport=transport, **kwargs)


class RequestMapping(unittest.TestCase):
    def test_maps_to_a_generate_content_body(self):
        mapped = ga.to_request(MODEL, "do the task", max_output_tokens=512)
        self.assertEqual(mapped["model"], MODEL)
        self.assertEqual(mapped["body"], {
            "contents": [{"role": "user", "parts": [{"text": "do the task"}]}],
            "generationConfig": {"maxOutputTokens": 512},
        })

    def test_structured_output_carries_the_schema_and_mime_type(self):
        schema = {"type": "object", "properties": {"verdict": {"type": "string"}},
                  "required": ["verdict"]}
        body = ga.to_request(MODEL, "review", max_output_tokens=64,
                             settings={"response_schema": schema})["body"]
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(body["generationConfig"]["responseSchema"], schema)

    def test_system_instruction_and_temperature_are_mapped(self):
        body = ga.to_request(MODEL, "review", max_output_tokens=64,
                             settings={"system_instruction": "You are a grader.",
                                       "temperature": 0})["body"]
        self.assertEqual(body["systemInstruction"], {"parts": [{"text": "You are a grader."}]})
        self.assertEqual(body["generationConfig"]["temperature"], 0)

    def test_unsupported_settings_refuse_by_name(self):
        for settings in ({"tools": [{"functionDeclarations": []}]},
                         {"safetySettings": [{"category": "HARM_CATEGORY_HATE_SPEECH"}]},
                         {"cachedContent": "cachedContents/abc"},
                         {"thinkingConfig": {"thinkingBudget": 1024}},
                         {"stream": True}):
            with self.subTest(settings=sorted(settings)):
                with self.assertRaises(ga.GeminiRefused) as caught:
                    ga.to_request(MODEL, "x", max_output_tokens=64, settings=settings)
                self.assertIn(sorted(settings)[0], str(caught.exception))

    def test_invalid_values_refuse_instead_of_being_clamped(self):
        for settings in ({"temperature": 2.5}, {"temperature": float("nan")},
                         {"temperature": True}, {"response_schema": {"properties": {}}},
                         {"system_instruction": "  "}):
            with self.subTest(settings=settings):
                with self.assertRaises(ga.GeminiRefused):
                    ga.to_request(MODEL, "x", max_output_tokens=64, settings=settings)
        for bad in (0, -1, True, 1.5, "64"):
            with self.subTest(max_output_tokens=bad):
                with self.assertRaises(ga.GeminiRefused):
                    ga.to_request(MODEL, "x", max_output_tokens=bad)
        with self.assertRaises(ga.GeminiRefused):
            ga.to_request(MODEL, "", max_output_tokens=64)


class ResponseMapping(unittest.TestCase):
    def test_reads_text_and_usage(self):
        result = ga.parse_response(
            response(usage={"promptTokenCount": 30, "candidatesTokenCount": 12,
                            "totalTokenCount": 42}),
            model=MODEL, max_output_tokens=64)
        self.assertEqual(result.text, "answer")
        self.assertEqual((result.input_tokens, result.output_tokens), (30, 12))
        self.assertEqual(result.finish_reason, "STOP")

    def test_missing_usage_is_null_never_zero(self):
        result = ga.parse_response(response(), model=MODEL, max_output_tokens=64)
        self.assertIsNone(result.input_tokens)
        self.assertIsNone(result.output_tokens)
        self.assertNotEqual((result.input_tokens, result.output_tokens), (0, 0))

    def test_cached_and_thinking_subsets_are_subtracted_not_added(self):
        result = ga.parse_response(
            response(usage={"promptTokenCount": 100, "candidatesTokenCount": 40,
                            "cachedContentTokenCount": 60, "thoughtsTokenCount": 15,
                            "totalTokenCount": 140}),
            model=MODEL, max_output_tokens=64)
        # billed prompt = 100 - 60, billed output = 40 - 15: the subsets are inside the totals
        self.assertEqual((result.input_tokens, result.output_tokens), (40, 25))

    def test_identity_mismatch_and_blocked_prompt_refuse(self):
        with self.assertRaises(ga.GeminiRefused):
            ga.parse_response(response(version="gemini-other"), model=MODEL, max_output_tokens=64)
        with self.assertRaises(ga.GeminiRefused):
            ga.parse_response({"promptFeedback": {"blockReason": "SAFETY"},
                               "candidates": []}, model=MODEL, max_output_tokens=64)
        with self.assertRaises(ga.GeminiRefused):
            ga.parse_response(response(version=None), model=MODEL, max_output_tokens=64)

    def test_partial_finish_reasons_are_void_not_answers(self):
        for finish in ("MAX_TOKENS", "SAFETY", "RECITATION", "OTHER"):
            with self.subTest(finish=finish):
                result = ga.parse_response(response(finish=finish), model=MODEL, max_output_tokens=64)
                self.assertEqual(result.finish_reason, finish)

    def test_usage_subsets_cannot_exceed_their_totals(self):
        for usage in ({"promptTokenCount": 10, "candidatesTokenCount": 5,
                       "cachedContentTokenCount": 11},
                      {"promptTokenCount": 10, "candidatesTokenCount": 5,
                       "thoughtsTokenCount": 6},
                      {"promptTokenCount": 10, "candidatesTokenCount": 5,
                       "totalTokenCount": 99},
                      {"promptTokenCount": 10, "candidatesTokenCount": 5,
                       "cachedContentTokenCount": -1},
                      {"promptTokenCount": 10}):
            with self.subTest(usage=usage):
                with self.assertRaises(ga.GeminiRefused):
                    ga.parse_response(response(usage=usage), model=MODEL, max_output_tokens=64)

    def test_unmodeled_usage_fields_refuse(self):
        with self.assertRaises(ga.GeminiRefused):
            ga.parse_response(response(usage={"promptTokenCount": 1, "candidatesTokenCount": 1,
                                              "audioTokenCount": 7}),
                              model=MODEL, max_output_tokens=64)

    def test_output_over_the_declared_ceiling_refuses(self):
        with self.assertRaises(ga.GeminiRefused):
            ga.parse_response(response(usage={"promptTokenCount": 1,
                                              "candidatesTokenCount": 65}),
                              model=MODEL, max_output_tokens=64)


class EgressAndAuthorization(RecordCase):
    def test_checked_in_record_is_unqualified_and_names_no_destination(self):
        with self.assertRaises(ga.GeminiRefused) as caught:
            ga.load_authorization(ga.AUTHORIZATION_PATH)
        self.assertIn("offline preparation", str(caught.exception))
        raw = json.loads(ga.AUTHORIZATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(raw["status"], "unqualified")
        self.assertIsNone(raw["destination"])
        self.assertEqual(raw["profiles"], {})

    def test_no_transport_refuses_even_when_qualified(self):
        with self.assertRaises(ga.GeminiRefused) as caught:
            ga.build_dispatch_fn(authorization_path=self.write(qualified_record()), transport=None)
        self.assertIn("mock transport", str(caught.exception))

    def test_unknown_destination_or_missing_accounting_blocks(self):
        for overrides in ({"destination": "https://generativelanguage.googleapis.com.evil.test"},
                          {"destination": None},
                          {"accounting": None},
                          {"accounting": {"scope": "guessed", "currency": "USD",
                                          "price_revision": "r", "price_sha256": "a" * 64}},
                          {"accounting": {"scope": "provider-reported-tokens", "currency": "USD",
                                          "price_revision": "r", "price_sha256": "zz"}},
                          {"profiles": {}},
                          {"profiles": {"cloud-G": {"model": MODEL}}},
                          {"count_endpoint": "https://example.test/count"},
                          {"issue": 58},
                          {"unexpected": True}):
            with self.subTest(overrides=sorted(overrides)):
                with self.assertRaises(ga.GeminiRefused):
                    ga.build_dispatch_fn(authorization_path=self.write(qualified_record(**overrides)),
                                         transport=lambda mapped, model: response())

    def test_unreadable_and_malformed_records_refuse(self):
        with self.assertRaises(ga.GeminiRefused):
            ga.load_authorization(Path(self.tmp.name) / "absent.json")
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ga.GeminiRefused):
            ga.load_authorization(self.path)

    def test_dispatch_maps_and_returns_provider_counts(self):
        calls = []
        document = response(usage={"promptTokenCount": 20, "candidatesTokenCount": 5})
        adapter = self.adapter(calls=calls, document=document)
        self.assertEqual(adapter("cloud-G", "question"), (20, 5))
        self.assertEqual(calls[0][1], MODEL)
        self.assertEqual(calls[0][0]["model"], MODEL)
        self.assertEqual(calls[0][0]["body"]["contents"][0]["parts"][0]["text"], "question")

    def test_unknown_profile_refuses_before_the_transport_runs(self):
        calls = []
        adapter = self.adapter(calls=calls, document=response())
        with self.assertRaises(ga.GeminiRefused) as caught:
            adapter("cloud-X", "question")
        self.assertIn("substituting", str(caught.exception))
        self.assertEqual(calls, [])

    def test_partial_response_refuses_and_carries_its_usage(self):
        calls = []
        adapter = self.adapter(calls=calls, document=response(
            finish="MAX_TOKENS", usage={"promptTokenCount": 20, "candidatesTokenCount": 4096}))
        with self.assertRaises(ga.GeminiRefused) as caught:
            adapter("cloud-G", "question")
        self.assertIn("MAX_TOKENS", str(caught.exception))
        self.assertEqual(caught.exception.usage, (20, 4096))

    def test_no_count_transport_is_invented(self):
        calls = []
        adapter = self.adapter(calls=calls, document=response())
        with self.assertRaises(ga.GeminiRefused) as caught:
            adapter.count_tokens("cloud-G", "question")
        self.assertIn("count endpoint", str(caught.exception))
        self.assertEqual(calls, [])

    def test_authorization_change_stops_a_built_adapter(self):
        calls = []
        adapter = self.adapter(calls=calls, document=response())
        self.write(qualified_record(status="unqualified", destination=None, profiles={}))
        with self.assertRaises(ga.GeminiRefused):
            adapter("cloud-G", "question")
        self.assertEqual(calls, [])


class FrozenPlan(unittest.TestCase):
    def test_plan_uses_the_cohort_packet_and_oracle(self):
        plan = ga.frozen_trial_plan()
        self.assertEqual(plan["cohort"], "shared-bounded-reader")
        self.assertEqual(plan["manifest_sha256"], ga.EXPECTED_PACK_MANIFEST_SHA256)
        self.assertEqual([trial["case"] for trial in plan["trials"]], ["fix", "pin", "review"])
        self.assertEqual(len({trial["base"] for trial in plan["trials"]}), 2)
        self.assertEqual(plan, ga.frozen_trial_plan())          # deterministic across calls
        self.assertEqual(len(plan["plan_sha256"]), 64)

    def test_plan_refuses_a_changed_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "pack"
            shutil.copytree(ga.SHARED_PACK, pack)
            (pack / "README.md").write_text("edited\n", encoding="utf-8")
            with self.assertRaises(ga.GeminiRefused) as caught:
                ga.frozen_trial_plan(pack)
            self.assertIn("file changed", str(caught.exception))
            (pack / "README.md").write_text(
                (ga.SHARED_PACK / "README.md").read_text(encoding="utf-8"), encoding="utf-8")
            manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
            manifest["pack_version"] = "2"
            (pack / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ga.GeminiRefused) as caught:
                ga.frozen_trial_plan(pack)
            self.assertIn("subject pack changed", str(caught.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
