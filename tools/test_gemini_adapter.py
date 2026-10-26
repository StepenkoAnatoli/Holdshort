#!/usr/bin/env python3
"""Offline tests for tools/gemini_adapter.py (issue #59).

Every test here is mock-only: no socket is opened, no key is read and no
provider is contacted. The acceptance list this pins:

  * request mapping, structured output, missing usage, partial failure and
    unsupported settings (issue #59 acceptance 1);
  * unknown capability, price, accounting or destination blocks execution
    instead of substituting a model (acceptance 2);
  * usage stays null when the provider exposes no counter, the cached-prompt
    subset is never double-counted and the thinking tokens are never dropped
    (acceptance 4), and a refusal after a billed response carries its counts on
    the attributes the dispatcher reads;
  * real egress stays disabled: the checked-in record is unqualified and the
    adapter has no transport of its own (acceptance 5);
  * the frozen trial plan uses the cohort's packet and oracle (acceptance 3).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
spec = importlib.util.spec_from_file_location("ga", TOOLS / "gemini_adapter.py")
ga = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ga)
sys.path.insert(0, str(TOOLS))
import live_dispatcher as ld  # noqa: E402  (only for the settlement round trip below)

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

    def test_cached_and_thinking_tokens_are_billed_not_zeroed(self):
        # ai.google.dev/api/generate-content UsageMetadata: promptTokenCount includes
        # the cached content; totalTokenCount = prompt + tool-use prompt + thoughts +
        # candidates, so thoughtsTokenCount is separate from candidatesTokenCount.
        # Pricing bills output "including thinking tokens" and cached tokens at a
        # nonzero rate. The dispatcher prices (input, output) at the input and output
        # rates only, so input keeps the cached tokens (an upper bound) and output
        # adds the thoughts; subtracting either bills real tokens at $0.
        result = ga.parse_response(
            response(usage={"promptTokenCount": 100, "candidatesTokenCount": 40,
                            "cachedContentTokenCount": 60, "thoughtsTokenCount": 300,
                            "totalTokenCount": 440}),
            model=MODEL, max_output_tokens=512)
        self.assertEqual((result.input_tokens, result.output_tokens), (100, 340))
        # without a reported total the same rule holds
        result = ga.parse_response(
            response(usage={"promptTokenCount": 100, "candidatesTokenCount": 40,
                            "cachedContentTokenCount": 60, "thoughtsTokenCount": 15}),
            model=MODEL, max_output_tokens=64)
        self.assertEqual((result.input_tokens, result.output_tokens), (100, 55))
        # the old prompt + candidates total is now a disagreement, not a match
        with self.assertRaises(ga.GeminiRefused):
            ga.parse_response(
                response(usage={"promptTokenCount": 100, "candidatesTokenCount": 40,
                                "thoughtsTokenCount": 300, "totalTokenCount": 140}),
                model=MODEL, max_output_tokens=512)
        # thinking counts against the output ceiling the dispatcher reserved
        with self.assertRaises(ga.GeminiRefused) as caught:
            ga.parse_response(
                response(usage={"promptTokenCount": 1, "candidatesTokenCount": 40,
                                "thoughtsTokenCount": 30}),
                model=MODEL, max_output_tokens=64)
        # ...and that refusal comes after a billed response, so it carries the counts
        self.assertEqual((caught.exception.input_tokens, caught.exception.output_tokens), (1, 70))

    def test_a_refusal_with_unknown_usage_carries_no_counts(self):
        # parts that disagree with their total leave the charge unknown: null, never 0,
        # so the dispatcher keeps the whole reservation instead of settling a guess
        with self.assertRaises(ga.GeminiRefused) as caught:
            ga.parse_response(response(usage={"promptTokenCount": 10, "candidatesTokenCount": 5,
                                              "totalTokenCount": 99}),
                              model=MODEL, max_output_tokens=64)
        self.assertEqual((caught.exception.input_tokens, caught.exception.output_tokens),
                         (None, None))

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
                       "thoughtsTokenCount": 6, "totalTokenCount": 15},
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
        with self.assertRaises(ga.GeminiRefused) as caught:
            ga.parse_response(response(usage={"promptTokenCount": 1,
                                              "candidatesTokenCount": 65}),
                              model=MODEL, max_output_tokens=64)
        self.assertEqual((caught.exception.input_tokens, caught.exception.output_tokens), (1, 65))

    def test_refusals_after_a_billed_response_carry_its_counts(self):
        usage = {"promptTokenCount": 7, "candidatesTokenCount": 3}
        stop_without_text = response(usage=usage)
        stop_without_text["candidates"][0]["content"] = {"role": "model"}
        two_candidates = response(usage=usage)
        two_candidates["candidates"].append(two_candidates["candidates"][0])
        blocked = response(usage=usage)
        blocked["promptFeedback"] = {"blockReason": "SAFETY"}
        for name, document in (("no text", stop_without_text), ("two candidates", two_candidates),
                               ("blocked", blocked)):
            with self.subTest(name):
                with self.assertRaises(ga.GeminiRefused) as caught:
                    ga.parse_response(document, model=MODEL, max_output_tokens=64)
                self.assertEqual((caught.exception.input_tokens, caught.exception.output_tokens),
                                 (7, 3))
        # a different model's counts are not this profile's spend: unknown, not borrowed
        with self.assertRaises(ga.GeminiRefused) as caught:
            ga.parse_response(response(usage=usage, version="gemini-other"), model=MODEL,
                              max_output_tokens=64)
        self.assertEqual((caught.exception.input_tokens, caught.exception.output_tokens),
                         (None, None))

    def test_the_usage_shape_the_api_sends_is_billed(self):
        # The API omits zero counters (proto3 JSON mapping) and adds per-modality
        # details (UsageMetadata, ai.google.dev/api/generate-content). A thinking model
        # stopped at MAX_TOKENS, from googleapis/python-genai#782: no candidate count,
        # prompt_token_count=1674, prompt_tokens_details=[TEXT 1674],
        # thoughts_token_count=2000, total_token_count=3674.
        void = response(finish="MAX_TOKENS", usage={
            "promptTokenCount": 1674,
            "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 1674}],
            "thoughtsTokenCount": 2000, "totalTokenCount": 3674})
        void["candidates"][0]["content"] = {"role": "model"}
        result = ga.parse_response(void, model=MODEL, max_output_tokens=2000)
        self.assertEqual(result, ga.GeminiResult("", 1674, 2000, "MAX_TOKENS"))
        for name, usage, text, expected in (
            ("details on both sides", {
                "promptTokenCount": 30, "candidatesTokenCount": 12, "totalTokenCount": 42,
                "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 30}],
                "candidatesTokensDetails": [{"modality": "TEXT", "tokenCount": 12}]},
             "answer", (30, 12)),
            ("a cached prompt", {
                "promptTokenCount": 100, "cachedContentTokenCount": 60, "candidatesTokenCount": 5,
                "totalTokenCount": 105,
                "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 100}],
                "cacheTokensDetails": [{"modality": "TEXT", "tokenCount": 60}]},
             "answer", (100, 5)),
            # a zero detail count is omitted the same way as a zero counter (no text was
            # generated, so a zero output is consistent)
            ("a zero detail", {
                "promptTokenCount": 9, "totalTokenCount": 9,
                "candidatesTokensDetails": [{"modality": "TEXT"}]}, "", (9, 0)),
        ):
            with self.subTest(name):
                result = ga.parse_response(response(usage=usage, finish="MAX_TOKENS", text=text),
                                           model=MODEL, max_output_tokens=64)
                self.assertEqual((result.input_tokens, result.output_tokens), expected)

    def test_usage_details_and_omitted_counters_stay_fail_closed(self):
        # An omitted counter is a zero only when the reported total proves it. A detail
        # list must hold text tokens (the only modality the request sends and the
        # dispatcher prices) that add up to its counter. Anything else leaves the charge
        # unknown: no counts, so the dispatcher holds the whole reservation.
        def text(count):
            return [{"modality": "TEXT", "tokenCount": count}]

        base = {"promptTokenCount": 20, "candidatesTokenCount": 5, "totalTokenCount": 25}
        for name, usage in (
            ("no candidate count and no total (js-genai#1769)", {"promptTokenCount": 22649}),
            ("no candidate count, total disagrees", {"promptTokenCount": 20, "totalTokenCount": 25}),
            ("prompt details disagree", {**base, "promptTokensDetails": text(19)}),
            ("cache details disagree", {**base, "cachedContentTokenCount": 10,
                                        "cacheTokensDetails": text(11)}),
            ("candidate details disagree", {**base, "candidatesTokensDetails": text(4)}),
            ("an audio prompt", {**base, "promptTokensDetails": [{"modality": "AUDIO",
                                                                  "tokenCount": 20}]}),
            ("an image answer", {**base, "candidatesTokensDetails": [{"modality": "IMAGE",
                                                                      "tokenCount": 5}]}),
            ("no modality", {**base, "promptTokensDetails": [{"tokenCount": 20}]}),
            ("details not a list", {**base, "promptTokensDetails": text(20)[0]}),
            ("a detail with an extra key", {**base, "promptTokensDetails": [
                {"modality": "TEXT", "tokenCount": 20, "audio": 1}]}),
            ("a boolean detail count", {**base, "candidatesTokensDetails": [
                {"modality": "TEXT", "tokenCount": True}]}),
            ("a negative detail count", {**base, "promptTokensDetails": text(21) + text(-1)}),
            ("a tool-use prompt", {**base, "toolUsePromptTokenCount": 3, "totalTokenCount": 28}),
            ("tool-use details", {**base, "toolUsePromptTokensDetails": text(0)}),
            ("a service tier", {**base, "serviceTier": "priority"}),
        ):
            with self.subTest(name):
                with self.assertRaises(ga.GeminiRefused) as caught:
                    ga.parse_response(response(usage=usage, finish="MAX_TOKENS"), model=MODEL,
                                      max_output_tokens=64)
                self.assertEqual((caught.exception.input_tokens, caught.exception.output_tokens),
                                 (None, None))

    def test_a_stop_answer_with_empty_text_is_void(self):
        # js-genai#1769: a STOP candidate can hold a single empty part. Nothing was
        # answered, so it is not graded; its tokens were billed, so the refusal carries them
        for text, usage, counts in (
            ("", {"promptTokenCount": 20, "candidatesTokenCount": 0, "totalTokenCount": 20},
             (20, 0)),
            (" \n\t", {"promptTokenCount": 20, "candidatesTokenCount": 1, "totalTokenCount": 21},
             (20, 1)),
        ):
            with self.subTest(text=text):
                with self.assertRaises(ga.GeminiRefused) as caught:
                    ga.parse_response(response(usage=usage, text=text), model=MODEL,
                                      max_output_tokens=64)
                self.assertEqual((caught.exception.input_tokens, caught.exception.output_tokens),
                                 counts)

    def test_text_with_no_candidate_tokens_leaves_the_output_unknown(self):
        # Text is not generated in zero tokens: a usage block that reports none for an
        # answer under-reports it. The output charge is then unknown (None, never 0) while
        # the prompt count stays known, so the dispatcher keeps it as a cost floor.
        omitted = {"promptTokenCount": 20, "totalTokenCount": 20}
        for name, usage, finish, text in (
            ("omitted candidate count", omitted, "STOP", "answer"),
            ("a zero beside thoughts", {"promptTokenCount": 20, "candidatesTokenCount": 0,
                                        "thoughtsTokenCount": 7, "totalTokenCount": 27},
             "STOP", "answer"),
            ("a whitespace answer", omitted, "STOP", " \n"),
            ("a partial answer", omitted, "MAX_TOKENS", "partial"),
        ):
            with self.subTest(name):
                with self.assertRaises(ga.GeminiRefused) as caught:
                    ga.parse_response(response(usage=usage, finish=finish, text=text), model=MODEL,
                                      max_output_tokens=64)
                self.assertEqual((caught.exception.input_tokens, caught.exception.output_tokens),
                                 (20, None))

    def test_unreported_output_holds_whatever_else_refuses(self):
        # The contradiction is checked before every other refusal: a refusal that came
        # first carried the reported zero, so the text's tokens settled at $0
        omitted = {"promptTokenCount": 20, "totalTokenCount": 20}
        above = response(usage={"promptTokenCount": 20, "candidatesTokenCount": 0,
                                "thoughtsTokenCount": 100, "totalTokenCount": 120})
        unfinished = response(usage=omitted)
        del unfinished["candidates"][0]["finishReason"]
        two = response(usage=omitted)
        two["candidates"].append({"finishReason": "STOP", "content": {"parts": [{"text": "b"}]}})
        mixed = response(usage=omitted)
        mixed["candidates"][0]["content"]["parts"][0]["inlineData"] = {"mimeType": "image/png",
                                                                       "data": "AA=="}
        blocked = response(usage=omitted)
        blocked["promptFeedback"] = {"blockReason": "SAFETY"}
        for name, document in (("above the ceiling", above), ("no finishReason", unfinished),
                               ("two candidates", two), ("text beside a payload", mixed),
                               ("a blocked prompt", blocked)):
            with self.subTest(name):
                with self.assertRaises(ga.GeminiRefused) as caught:
                    ga.parse_response(document, model=MODEL, max_output_tokens=64)
                self.assertEqual((caught.exception.input_tokens, caught.exception.output_tokens),
                                 (20, None))

    def test_a_signature_only_part_adds_no_text(self):
        # A part holding only a thoughtSignature carries no answer (whether the API sends
        # one outside streaming is unverified), so it adds no text instead of voiding the
        # answer. A part with any other payload still refuses.
        usage = {"promptTokenCount": 20, "candidatesTokenCount": 5, "totalTokenCount": 25}
        document = response(usage=usage)
        document["candidates"][0]["content"]["parts"].append({"thoughtSignature": "c2ln"})
        self.assertEqual(ga.parse_response(document, model=MODEL, max_output_tokens=64),
                         ga.GeminiResult("answer", 20, 5, "STOP"))
        for name, parts in (
            ("only a signature", [{"thoughtSignature": "c2ln"}]),
            ("inline data", [{"text": "answer"}, {"inlineData": {"mimeType": "image/png",
                                                                 "data": "AA=="}}]),
            # a payload beside text in the same part was graded with the payload dropped
            ("text with inline data", [{"text": "answer", "inlineData": {"mimeType": "image/png",
                                                                         "data": "AA=="}}]),
            ("text with a function call", [{"text": "answer",
                                            "functionCall": {"name": "f", "args": {}}}]),
            ("a signature that is not a string", [{"text": "answer", "thoughtSignature": 7}]),
        ):
            with self.subTest(name):
                document = response(usage=usage)
                document["candidates"][0]["content"]["parts"] = parts
                with self.assertRaises(ga.GeminiRefused) as caught:
                    ga.parse_response(document, model=MODEL, max_output_tokens=64)
                self.assertEqual((caught.exception.input_tokens, caught.exception.output_tokens),
                                 (20, 5))

    def test_a_blocked_prompt_is_reported_as_blocked(self):
        # A blocked prompt returns no candidates, and whether it carries modelVersion is
        # undocumented, so the block is named before the identity check. Its counts are
        # carried only when they are this model's and known.
        blocked = {"blockReason": "SAFETY"}
        known = {"promptTokenCount": 9, "totalTokenCount": 9}
        for name, document, counts in (
            ("no modelVersion", {"promptFeedback": blocked, "usageMetadata": known}, (None, None)),
            ("another model", {"modelVersion": "gemini-other", "promptFeedback": blocked,
                               "usageMetadata": known}, (None, None)),
            ("unknown usage", {"modelVersion": MODEL, "promptFeedback": blocked,
                               "usageMetadata": {"promptTokenCount": 9, "totalTokenCount": 99}},
             (None, None)),
            ("this model, known usage", {"modelVersion": MODEL, "promptFeedback": blocked,
                                         "usageMetadata": known}, (9, 0)),
        ):
            with self.subTest(name):
                with self.assertRaises(ga.GeminiRefused) as caught:
                    ga.parse_response(document, model=MODEL, max_output_tokens=64)
                self.assertIn("blocked", str(caught.exception))
                self.assertEqual((caught.exception.input_tokens, caught.exception.output_tokens),
                                 counts)


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
                          {"notes": {"a": 1}},
                          {"notes": [1]},
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
        # live_dispatcher reads exc.input_tokens / exc.output_tokens from a failed send
        self.assertEqual((caught.exception.input_tokens, caught.exception.output_tokens),
                         (20, 4096))

    def test_void_finish_without_text_still_carries_its_usage(self):
        # a thinking model that spends the whole budget can stop at MAX_TOKENS with no
        # text part at all; the cell is void, but the tokens were billed. This is the
        # shape the API sends (googleapis/python-genai#782): the zero candidate count
        # is omitted and the prompt carries per-modality details.
        document = response(finish="MAX_TOKENS", usage={
            "promptTokenCount": 20, "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 20}],
            "thoughtsTokenCount": 4096, "totalTokenCount": 4116})
        document["candidates"][0]["content"] = {"role": "model"}
        adapter = self.adapter(calls=[], document=document)
        with self.assertRaises(ga.GeminiRefused) as caught:
            adapter("cloud-G", "question")
        self.assertIn("MAX_TOKENS", str(caught.exception))
        self.assertEqual((caught.exception.input_tokens, caught.exception.output_tokens),
                         (20, 4096))

    def test_dispatcher_settles_the_billed_usage_of_a_void_cell(self):
        # Round trip through the real settlement path: before the fix the counts sat on
        # an attribute the dispatcher never reads, so a billed void cell settled as
        # unknown usage. The profile id is a prices-2 id so the dispatcher can price it.
        # Thinking spent the whole output budget, in the shape the API sends for it
        # (googleapis/python-genai#782): no candidatesTokenCount, prompt details, no text.
        record = qualified_record(profiles={"cloud-C": {"model": MODEL, "max_output_tokens": 4096,
                                                        "input_token_ceiling": 200000}})
        void = response(finish="MAX_TOKENS", usage={
            "promptTokenCount": 20, "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 20}],
            "thoughtsTokenCount": 4096, "totalTokenCount": 4116})
        void["candidates"][0]["content"] = {"role": "model"}
        adapter = self.adapter(record=record, calls=[], document=void)
        # this module implements no count transport; a future host supplies one
        adapter.count_tokens = lambda profile_id, request: 20
        prices = ld.load_prices(TOOLS / "prices-2.json")
        with tempfile.TemporaryDirectory() as td:
            dispatcher = ld.LiveDispatcher(prices, Path(td) / "pilot_ledger.jsonl",
                                           dispatch_fn=adapter, confirm_egress=True)
            entry = dispatcher.attempt("T-void", "cloud-C", "question", work_bound=0.05,
                                       review_bound=0, expected_in=20, expected_out=4096)
            with dispatcher.budget.transaction() as doc:
                halted, pending = doc.get("halted", False), doc["tasks"]["T-void"]["pending"]
        self.assertEqual((entry.input_tokens, entry.output_tokens), (20, 4096), entry.reason)
        self.assertEqual(entry.usage_status, "observed", entry.reason)
        # the spend settled: nothing is left pending and the pilot is not stopped
        self.assertIsNone(pending)
        self.assertFalse(halted)
        # prices-2 cloud-C: $0.10 per million input, $0.50 per million output
        self.assertAlmostEqual(entry.cost_usd, (20 * 0.10 + 4096 * 0.50) / 1e6, delta=1e-15)

    def test_dispatcher_keeps_a_floor_for_an_answer_with_unreported_output(self):
        # An answer whose usage reports no candidate tokens: the dispatcher keeps the
        # known prompt as a cost floor and stops the pilot for review, never settling
        # the output at $0.
        record = qualified_record(profiles={"cloud-C": {"model": MODEL, "max_output_tokens": 4096,
                                                        "input_token_ceiling": 200000}})
        answer = response(usage={"promptTokenCount": 20, "totalTokenCount": 20})
        adapter = self.adapter(record=record, calls=[], document=answer)
        adapter.count_tokens = lambda profile_id, request: 20
        prices = ld.load_prices(TOOLS / "prices-2.json")
        with tempfile.TemporaryDirectory() as td:
            dispatcher = ld.LiveDispatcher(prices, Path(td) / "pilot_ledger.jsonl",
                                           dispatch_fn=adapter, confirm_egress=True)
            entry = dispatcher.attempt("T-answer", "cloud-C", "question", work_bound=0.05,
                                       review_bound=0, expected_in=20, expected_out=4096)
            with dispatcher.budget.transaction() as doc:
                halted, pending = doc.get("halted", False), doc["tasks"]["T-answer"]["pending"]
        self.assertEqual((entry.usage_status, entry.input_tokens, entry.output_tokens),
                         ("unknown", 20, None), entry.reason)
        self.assertEqual(pending["status"], "uncertain")
        self.assertTrue(halted)

    def test_a_refusal_before_anything_is_sent_is_a_known_zero(self):
        # Nothing reached a provider, so the charge is a known zero. None would make the
        # dispatcher halt the pilot on an unknown with nothing to reconcile.
        record = qualified_record(profiles={"cloud-C": {"model": MODEL, "max_output_tokens": 4096,
                                                        "input_token_ceiling": 200000}})
        for name, profile_id, request, kwargs, change_record in (
            ("ceiling above the profile maximum", "cloud-C", "q", {"max_output_tokens": 8192}, False),
            ("unknown profile", "cloud-X", "q", {}, False),
            ("empty request", "cloud-C", " ", {}, False),
            ("authorization changed", "cloud-C", "q", {}, True),
        ):
            with self.subTest(name):
                calls = []
                adapter = self.adapter(record=record, calls=calls, document=response(), **kwargs)
                if change_record:
                    self.write(qualified_record(status="unqualified", destination=None, profiles={}))
                with self.assertRaises(ga.GeminiRefused) as caught:
                    adapter(profile_id, request)
                self.assertEqual((caught.exception.input_tokens, caught.exception.output_tokens),
                                 (0, 0))
                self.assertEqual(calls, [])
        # the mock sends nothing either, and the dispatcher settles that attempt at $0
        adapter = ga.build_dispatch_fn(authorization_path=self.write(record),
                                       transport=ga.MockTransport())
        adapter.count_tokens = lambda profile_id, request: 20
        prices = ld.load_prices(TOOLS / "prices-2.json")
        with tempfile.TemporaryDirectory() as td:
            dispatcher = ld.LiveDispatcher(prices, Path(td) / "pilot_ledger.jsonl",
                                           dispatch_fn=adapter, confirm_egress=True)
            entry = dispatcher.attempt("T-empty", "cloud-C", "question", work_bound=0.05,
                                       review_bound=0, expected_in=20, expected_out=4096)
            with dispatcher.budget.transaction() as doc:
                halted, pending = doc.get("halted", False), doc["tasks"]["T-empty"]["pending"]
        self.assertEqual((entry.usage_status, entry.cost_usd), ("observed", 0.0), entry.reason)
        self.assertIsNone(pending)
        self.assertFalse(halted)

    def test_mock_transport_replays_and_refuses_when_exhausted(self):
        transport = ga.MockTransport(response(usage={"promptTokenCount": 3,
                                              "candidatesTokenCount": 1}))
        adapter = ga.build_dispatch_fn(authorization_path=self.write(qualified_record()),
                                       transport=transport)
        self.assertEqual(adapter("cloud-G", "q"), (3, 1))
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(transport.calls[0][1], MODEL)
        self.assertEqual(transport.calls[0][0]["body"]["contents"][0]["parts"][0]["text"], "q")
        with self.assertRaises(ga.GeminiRefused):
            adapter("cloud-G", "second call with no queued response")

    def test_no_count_transport_is_invented(self):
        calls = []
        adapter = self.adapter(calls=calls, document=response())
        with self.assertRaises(ga.GeminiRefused) as caught:
            adapter.count_tokens("cloud-G", "question")
        self.assertIn("token-count", str(caught.exception))
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
