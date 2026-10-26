#!/usr/bin/env python3
"""Synthetic tests for tools/usage_attribution.py (issue #61).

Pins the acceptance list: attribution to run and model, documented clock and
boundary, null for counters the host does not expose, subset validation without
double counting, an export whitelist that cannot carry content, and dollar
figures that always state their price revision and assumptions.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ua", TOOLS / "usage_attribution.py")
ua = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ua)

POLICY = "a" * 64
FULL = {"input_tokens": 1000, "cached_input_tokens": 200,
        "output_tokens": 300, "reasoning_output_tokens": 100}


def obs(**overrides) -> dict:
    fields = dict(run_id="run-1", task_id="task-1", policy_sha256=POLICY,
                  requested_model="model-x", observed_model="model-x",
                  started_at="2026-10-21T10:00:00Z",
                  completed_at="2026-10-21T10:00:02.500Z", counters=FULL)
    fields.update(overrides)
    return ua.observation(**fields)


def cli(text: str):
    """(exit code, stdout, stderr) of the CLI run on a JSONL file holding `text`."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "records.jsonl"
        # bytes, so the line endings the test chose reach the CLI unchanged
        path.write_bytes(text.encode("utf-8"))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ua.main([str(path)])
    return code, out.getvalue(), err.getvalue()


class Record(unittest.TestCase):
    def test_record_carries_identity_timing_and_subsets(self):
        record = obs()
        self.assertEqual(record["latency_ms"], 2500)
        self.assertIs(record["model_match"], True)
        self.assertEqual(record["counters"], FULL)
        self.assertEqual((record["clock"], record["boundary"]), ("utc", "transport"))
        self.assertEqual(record["completed_at"], "2026-10-21T10:00:02.500000+00:00")

    def test_missing_counters_stay_null(self):
        record = obs(counters=None)
        self.assertEqual(record["counters"], {field: None for field in ua.COUNTER_FIELDS})
        totals = ua.by_model([record])["model-x"]
        self.assertIsNone(totals["input_tokens"])
        self.assertEqual(totals["input_tokens_unknown"], 1)
        self.assertNotEqual(totals["input_tokens"], 0)

    def test_malformed_counters_refuse(self):
        for bad in ({"input_tokens": -1, "cached_input_tokens": None,
                     "output_tokens": 1, "reasoning_output_tokens": None},
                    {"input_tokens": True, "cached_input_tokens": None,
                     "output_tokens": 1, "reasoning_output_tokens": None},
                    {"input_tokens": 1.5, "cached_input_tokens": None,
                     "output_tokens": 1, "reasoning_output_tokens": None},
                    {"input_tokens": 1, "output_tokens": 1},
                    {"input_tokens": 1, "cached_input_tokens": None,
                     "output_tokens": 1, "reasoning_output_tokens": None, "total_tokens": 2}):
            with self.subTest(counters=bad):
                with self.assertRaises(ua.AttributionError):
                    obs(counters=bad)

    def test_subsets_cannot_exceed_their_totals(self):
        with self.assertRaises(ua.AttributionError):
            obs(counters={**FULL, "cached_input_tokens": 1001})
        with self.assertRaises(ua.AttributionError):
            obs(counters={**FULL, "reasoning_output_tokens": 301})

    def test_requested_and_observed_model_are_both_recorded(self):
        record = obs(observed_model="model-x-20261001")
        self.assertEqual((record["requested_model"], record["observed_model"]),
                         ("model-x", "model-x-20261001"))
        self.assertIs(record["model_match"], False)

    def test_settings_are_bounded(self):
        self.assertEqual(obs(settings={"effort": "high", "max_output_tokens": 4096})["settings"],
                         {"effort": "high", "max_output_tokens": 4096})
        self.assertEqual(obs(settings={"reasoning": True})["settings"], {"reasoning": True})
        for bad in ({"prompt": "secret text"}, {"max_output_tokens": 0},
                    {"effort": {"nested": True}}, {"effort": "x" * 33},
                    {"effort": "Here is the whole prompt: ..."}, {"reasoning": float("nan")},
                    {"max_output_tokens": True}):
            with self.subTest(settings=bad):
                with self.assertRaises(ua.AttributionError):
                    obs(settings=bad)

    def test_timing_rejects_naive_and_reversed_instants(self):
        with self.assertRaises(ua.AttributionError):
            obs(started_at="2026-10-21T10:00:00")
        with self.assertRaises(ua.AttributionError):
            obs(started_at="2026-10-21T10:00:05Z", completed_at="2026-10-21T10:00:00Z")
        with self.assertRaises(ua.AttributionError):
            obs(completed_at=None)
        with self.assertRaises(ua.AttributionError):
            obs(interrupted=True, completed_at="2026-10-21T10:00:02Z")

    def test_instants_without_a_utc_form_refuse(self):
        # converting these to UTC overflowed the date range and crashed the CLI
        for start in ("0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59"):
            with self.subTest(start=start):
                with self.assertRaises(ua.AttributionError):
                    obs(started_at=start, interrupted=True, completed_at=None)
                code, out, err = cli(json.dumps({**obs(), "started_at": start}, sort_keys=True)
                                     + "\n")
                self.assertEqual((code, out), (2, ""))
                self.assertIn("REFUSED", err)

    def test_interrupted_run_keeps_its_start_and_no_duration(self):
        record = obs(interrupted=True, completed_at=None)
        self.assertIs(record["interrupted"], True)
        self.assertIsNone(record["completed_at"])
        self.assertIsNone(record["latency_ms"])

    def test_offsets_are_normalised_before_comparison(self):
        record = obs(started_at="2026-10-21T12:00:00+02:00",
                     completed_at="2026-10-21T10:00:01Z")
        self.assertEqual(record["started_at"], "2026-10-21T10:00:00+00:00")
        self.assertEqual(record["latency_ms"], 1000)

    def test_identity_fields_are_validated(self):
        for overrides in ({"policy_sha256": "zz"}, {"policy_sha256": "a" * 63},
                          {"run_id": ""}, {"observed_model": None},
                          {"clock": "local"}, {"boundary": "whatever"}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ua.AttributionError):
                    obs(**overrides)

    def test_identifiers_refuse_invisible_and_control_characters(self):
        # "no whitespace" alone let zero-width and word joiners, a byte-order mark, a soft
        # hyphen, a bidi override, C1 controls and tag characters (an invisible copy of
        # ASCII text) through, so a sentence could ride along looking like one token
        for code in (0x200B, 0x2060, 0xFEFF, 0x00AD, 0x202E, 0x0080, 0x009F, 0xE0041,
                     0x00A0, 0x2028):
            for field in ("run_id", "task_id", "requested_model", "observed_model"):
                with self.subTest(code=hex(code), field=field):
                    with self.assertRaises(ua.AttributionError):
                        obs(**{field: "alpha" + chr(code) + "beta"})
        self.assertEqual(obs(run_id="r" * 200, task_id="task:7/b")["task_id"], "task:7/b")

    def test_identifiers_are_ascii(self):
        # "printable" is a rendering property: combining marks, variation selectors (the
        # usual encoding for smuggling bytes as invisible text), Hangul fillers and the
        # blank braille pattern are printable, so a sentence still rode along in one id
        for code in (0x034F, 0xFE0F, 0xE0100, 0x180B, 0x115F, 0x3164, 0x2800, 0x00E9):
            for field in ("run_id", "task_id", "requested_model", "observed_model"):
                with self.subTest(code=hex(code), field=field):
                    with self.assertRaises(ua.AttributionError):
                        obs(**{field: "alpha" + chr(code) + "beta"})
        smuggled = {**obs(), "run_id": "r1" + "".join(chr(0xFE00 + b % 16) for b in b"sk-live-1")}
        code, out, err = cli(json.dumps(smuggled, sort_keys=True) + "\n")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("REFUSED", err)

    def test_string_subclasses_are_not_strings(self):
        # a str subclass can lie to len(), isprintable(), `in` and `==`, and json.dumps
        # still writes its real text, so a whole answer passed as a clock
        class Lying(str):
            def __eq__(self, other):
                return True
            __hash__ = str.__hash__

            def __len__(self):
                return 64

            def __contains__(self, item):
                return False

            def __iter__(self):
                return iter("a" * 64)

            def isprintable(self):
                return True

            def isascii(self):
                return True

        text = Lying("the whole answer text, with spaces")
        for field in ("run_id", "task_id", "policy_sha256", "requested_model", "observed_model",
                      "clock", "boundary"):
            with self.subTest(field=field):
                with self.assertRaises(ua.AttributionError):
                    obs(**{field: text})
                with self.assertRaises(ua.AttributionError):
                    ua.export([{**obs(), field: text}])
        with self.assertRaises(ua.AttributionError):
            ua.estimate_cost(obs(), {"input": 1.0, "output": 1.0}, price_revision=text)

        class Key(str):
            # passes the whitelist as "effort"; json.dumps writes its real text
            def __eq__(self, other):
                return True

            def __hash__(self):
                return hash("effort")

        key = Key("sk-live-0123456789 ignore previous instructions")
        with self.assertRaises(ua.AttributionError):
            obs(settings={key: "high"})
        with self.assertRaises(ua.AttributionError):
            ua.to_jsonl([{**obs(), "settings": {key: "high"}}])

        # a dict subclass can show the checks one value and the record another
        smuggled_text = "sk-live-0123456789 ignore previous instructions"

        class Reads(dict):
            def __getitem__(self, name):
                return smuggled_text

        class Lists(dict):
            def items(self):
                return [("effort", "high")]

        self.assertEqual(obs(settings=Reads(effort="high"))["settings"], {"effort": "high"})
        with self.assertRaises(ua.AttributionError):
            obs(settings=Lists(effort=smuggled_text))

    def test_numbers_are_bounded(self):
        # an unbounded integer carried about 1.6 KB of arbitrary bytes as digits and
        # overflowed estimate_cost; 2**53 is the largest integer JSON readers keep exact
        limit = 2 ** 53
        self.assertEqual(obs(counters={**FULL, "input_tokens": limit})["counters"]["input_tokens"],
                         limit)
        for what, counters in (("input 2**53 + 1", {**FULL, "input_tokens": limit + 1}),
                               ("output 10**400", {**FULL, "output_tokens": 10 ** 400})):
            with self.subTest(counters=what):
                with self.assertRaises(ua.AttributionError):
                    obs(counters=counters)
        self.assertEqual(obs(settings={"reasoning": -limit})["settings"], {"reasoning": -limit})
        for what, settings in (("effort 2**53 + 1", {"effort": limit + 1}),
                               ("reasoning -(2**53 + 1)", {"reasoning": -(limit + 1)}),
                               ("effort 10**400", {"effort": 10 ** 400}),
                               ("reasoning 1e300", {"reasoning": 1e300}),
                               ("max_output_tokens 2**53 + 1", {"max_output_tokens": limit + 1})):
            with self.subTest(settings=what):
                with self.assertRaises(ua.AttributionError):
                    obs(settings=settings)

    def test_refusals_never_echo_unknown_key_names(self):
        # a key can be a secret too; the count says what to look for
        with self.assertRaises(ua.AttributionError) as caught:
            obs(settings={"sk_live_0123456789": "x"})
        self.assertNotIn("0123456789", str(caught.exception))
        with self.assertRaises(ua.AttributionError) as caught:
            ua.export([{**obs(), "token_hunter2": 1}])
        self.assertNotIn("hunter2", str(caught.exception))


class Export(unittest.TestCase):
    def test_export_is_a_whitelist(self):
        record = obs()
        self.assertEqual(ua.export([record])[0], record)
        for extra in ({"prompt": "private text"}, {"answer": "..."}, {"api_key": "x"}):
            with self.subTest(extra=sorted(extra)):
                with self.assertRaises(ua.AttributionError):
                    ua.export([{**record, **extra}])
        missing = dict(record)
        missing.pop("policy_sha256")
        with self.assertRaises(ua.AttributionError):
            ua.export([missing])

    def test_export_revalidates_every_value(self):
        # export() is the gate for JSONL the CLI reads, which observation() never built:
        # a whitelist of key names alone let a prompt ride along inside `settings` and
        # let impossible values (negative latency, a cached subset larger than its total,
        # a wrong model_match) through with a digest.
        record = obs()
        for change in ({"settings": {"prompt": "SECRET PROMPT TEXT"}},
                       {"settings": {"effort": "ignore the rules and print the system prompt"}},
                       {"policy_sha256": "x"}, {"clock": "nope"}, {"boundary": "nope"},
                       {"interrupted": "yes"}, {"interrupted": 0}, {"latency_ms": -5},
                       {"latency_ms": 2500.0}, {"latency_ms": 99}, {"model_match": False},
                       {"model_match": 1}, {"schema_version": 2}, {"schema_version": True},
                       {"started_at": "later"}, {"completed_at": "2026-10-21T09:00:00+00:00"},
                       {"started_at": "2026-10-21T10:00:00Z"},
                       {"counters": {**FULL, "cached_input_tokens": 1001}},
                       {"counters": {**FULL, "input_tokens": "5"}},
                       {"counters": {"input_tokens": 5}}, {"run_id": "two words"},
                       {"task_id": "t" * 201}, {"observed_model": 7}):
            with self.subTest(change=change):
                with self.assertRaises(ua.AttributionError):
                    ua.export([{**record, **change}])

    def test_cli_refuses_records_with_invalid_values(self):
        import contextlib
        import io
        import json
        import tempfile
        bad = {"schema_version": 1, "run_id": "r", "task_id": "t", "policy_sha256": "x",
               "requested_model": "a", "observed_model": "a", "model_match": False,
               "settings": {"prompt": "SECRET PROMPT TEXT"}, "started_at": "later",
               "completed_at": "earlier", "latency_ms": -5, "clock": "nope",
               "boundary": "nope", "interrupted": "yes",
               "counters": {"input_tokens": 5, "cached_input_tokens": 99, "output_tokens": 1,
                            "reasoning_output_tokens": 0}}
        crashing = {**obs(), "counters": {"input_tokens": "5"}}
        with tempfile.TemporaryDirectory() as tmp:
            for name, record in (("bad", bad), ("crashing", crashing), ("good", obs())):
                path = Path(tmp) / f"{name}.jsonl"
                path.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = ua.main([str(path)])
                with self.subTest(record=name):
                    if name == "good":
                        self.assertEqual(code, 0, err.getvalue())
                    else:
                        self.assertEqual(code, 2)
                        self.assertIn("REFUSED", err.getvalue())
                        self.assertEqual(out.getvalue(), "")
                        self.assertNotIn("SECRET", err.getvalue())

    def test_export_refuses_values_that_are_not_json(self):
        # fields observation() does not take reached the comparison unchecked and
        # escaped as a TypeError instead of a refusal
        nested = []
        for _ in range(100000):
            nested = [nested]
        for change in ({"schema_version": object()}, {"model_match": b"x"},
                       {"latency_ms": {1, 2}}, {"schema_version": nested}):
            with self.subTest(change=sorted(change)):
                with self.assertRaises(ua.AttributionError):
                    ua.export([{**obs(), **change}])

    def test_cli_refuses_a_repeated_key(self):
        # json.loads keeps the last copy of a repeated key: the first one stayed in the
        # file, unchecked, behind a clean digest
        record = {key: value for key, value in obs().items() if key != "settings"}
        line = (json.dumps(record)[:-1] + ', "settings": {"effort": "FREE TEXT NOT A SETTING"}'
                ', "settings": {"effort": "high"}}')
        code, out, err = cli(line + "\n")
        self.assertEqual(code, 2)
        self.assertIn("REFUSED", err)
        self.assertEqual(out, "")
        self.assertNotIn("FREE TEXT", err)

    def test_cli_refuses_a_deeply_nested_line(self):
        for line in ("[" * 200000 + "]" * 200000, '{"a": ' * 200000 + "1" + "}" * 200000):
            with self.subTest(shape=line[0]):
                code, out, err = cli(line + "\n")
                self.assertEqual(code, 2)
                self.assertIn("REFUSED", err)
                self.assertEqual(out, "")

    def test_cli_reads_only_canonical_lines(self):
        # The verdict and the digest cover the parsed records, so text the parse
        # discarded stayed in the file unchecked behind a clean digest: a float keeps 17
        # digits of any number of them, and padding, escapes and key order vanish too.
        line = json.dumps(obs(settings={"effort": 1.5}), sort_keys=True)
        self.assertEqual(line.count('"effort": 1.5'), 1)
        code, out, err = cli(line + "\n")
        self.assertEqual(code, 0, err)
        record = json.loads(line)
        for name, text in (
            ("float digits", line.replace('"effort": 1.5', '"effort": 1.5' + "0" * 4000)),
            ("exponent digits", line.replace('"effort": 1.5', '"effort": 15e-' + "0" * 400 + "1")),
            ("padding", line.replace(", ", ",  \t ")),
            ("an escaped letter", line.replace('"run-1"', '"\\u0072un-1"')),
            ("key order", json.dumps(dict(reversed(list(record.items()))))),
            ("compact separators", json.dumps(record, sort_keys=True, separators=(",", ":"))),
            ("a blank line", line + "\n"),
            ("a whitespace line", line + "\n \t"),
        ):
            with self.subTest(name):
                code, out, err = cli(text + "\n")
                self.assertEqual((code, out), (2, ""))
                self.assertIn("REFUSED", err)
        code, out, err = cli(line)
        self.assertEqual((code, out), (2, ""), "a last line with no newline")

    def test_cli_reads_one_line_ending(self):
        # A checkout may turn every LF into CRLF, so an all-CRLF file reads as its LF
        # form. Universal newlines also read a lone CR and a per-line mix, so a file
        # could carry a choice of ending per line behind the same digest.
        text = ua.to_jsonl([obs(), obs(task_id="task-2")])
        code, out, err = cli(text)
        self.assertEqual(code, 0, err)
        digest = json.loads(out)["digest"]
        code, out, err = cli(text.replace("\n", "\r\n"))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["digest"], digest)
        first, second = text.split("\n")[:2]
        for name, mixed in (("CRLF then LF", f"{first}\r\n{second}\n"),
                            ("LF then CRLF", f"{first}\n{second}\r\n"),
                            ("lone CR", text.replace("\n", "\r")),
                            ("lone CR between records", f"{first}\r{second}\n"),
                            ("CR before CRLF", f"{first}\r\r\n{second}\r\n")):
            with self.subTest(name):
                code, out, err = cli(mixed)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("REFUSED", err)

    def test_to_jsonl_writes_what_the_cli_reads(self):
        records = [obs(), obs(task_id="task-2", settings={"effort": "high", "reasoning": 0.25})]
        text = ua.to_jsonl(records)
        self.assertEqual(text, "".join(json.dumps(record, sort_keys=True) + "\n"
                                       for record in ua.export(records)))
        code, out, err = cli(text)
        self.assertEqual(code, 0, err)
        summary = json.loads(out)
        self.assertEqual(summary["records"], 2)
        digest = ua.hashlib.sha256(json.dumps(ua.export(records), sort_keys=True)
                                   .encode("utf-8")).hexdigest()
        self.assertEqual(summary["digest"], digest)
        with self.assertRaises(ua.AttributionError):
            ua.to_jsonl([{**obs(), "prompt": "SECRET"}])

    def test_export_has_no_free_form_text_field(self):
        exported = ua.export([obs()])[0]
        self.assertEqual(set(exported), ua.RECORD_FIELDS)
        self.assertNotIn("prompt", exported)
        self.assertNotIn("output_text", exported)


class Cost(unittest.TestCase):
    def test_cost_states_revision_and_assumptions(self):
        record = obs(counters={"input_tokens": 1_000_000, "cached_input_tokens": 200_000,
                               "output_tokens": 100_000, "reasoning_output_tokens": 0})
        cost = ua.estimate_cost(record, {"input": 3.0, "cached_input": 0.3, "output": 15.0},
                                price_revision="prices-2")
        self.assertEqual(cost["cost_usd"], 3.96)
        self.assertEqual(cost["price_revision"], "prices-2")
        self.assertEqual(cost["currency"], "USD")
        self.assertTrue(any("cached input" in line for line in cost["billing_assumptions"]))

    def test_reasoning_is_billed_once(self):
        record = obs(counters={"input_tokens": 0, "cached_input_tokens": 0,
                               "output_tokens": 100_000, "reasoning_output_tokens": 40_000})
        split = ua.estimate_cost(record, {"input": 0, "output": 15.0, "reasoning": 20.0},
                                 price_revision="prices-2")
        self.assertEqual(split["cost_usd"], 1.7)             # 60k*15 + 40k*20, not 100k+40k
        merged = ua.estimate_cost(record, {"input": 0, "output": 15.0}, price_revision="prices-2")
        self.assertEqual(merged["cost_usd"], 1.5)            # reasoning billed as output
        self.assertTrue(any("reasoning" in line for line in merged["billing_assumptions"]))

    def test_unknown_counters_never_become_zero_dollars(self):
        record = obs(counters=None)
        cost = ua.estimate_cost(record, {"input": 3.0, "output": 15.0}, price_revision="prices-2")
        self.assertIsNone(cost["cost_usd"])
        self.assertEqual(cost["price_revision"], "prices-2")
        self.assertTrue(cost["billing_assumptions"])

    def test_unknown_subsets_do_not_become_a_guessed_split(self):
        unknown_cached = obs(counters={**FULL, "cached_input_tokens": None})
        priced = ua.estimate_cost(unknown_cached,
                                  {"input": 3.0, "cached_input": 0.3, "output": 15.0},
                                  price_revision="prices-2")
        self.assertIsNone(priced["cost_usd"])
        self.assertTrue(any("cached-input count is unknown" in line
                            for line in priced["billing_assumptions"]))

        flat = ua.estimate_cost(obs(counters={**FULL, "cached_input_tokens": None,
                                              "input_tokens": 1_000_000, "output_tokens": 100_000}),
                                {"input": 3.0, "output": 15.0}, price_revision="prices-2")
        self.assertEqual(flat["cost_usd"], 4.5)                # 1M*3 + 100k*15
        self.assertTrue(any("all input" in line for line in flat["billing_assumptions"]))

        unknown_reasoning = obs(counters={**FULL, "reasoning_output_tokens": None})
        split = ua.estimate_cost(unknown_reasoning,
                                 {"input": 3.0, "cached_input": 0.3, "output": 15.0,
                                  "reasoning": 20.0}, price_revision="prices-2")
        self.assertIsNone(split["cost_usd"])
        self.assertTrue(any("reasoning count is unknown" in line
                            for line in split["billing_assumptions"]))

    def test_cost_refuses_an_unpriced_cached_subset_and_a_missing_revision(self):
        record = obs()
        with self.assertRaises(ua.AttributionError):
            ua.estimate_cost(record, {"input": 3.0, "output": 15.0}, price_revision="prices-2")
        with self.assertRaises(ua.AttributionError):
            ua.estimate_cost(record, {"input": 3.0, "cached_input": 0.3, "output": 15.0},
                             price_revision="")
        with self.assertRaises(ua.AttributionError):
            ua.estimate_cost(record, {"input": 3.0, "cached_input": 0.3, "output": float("nan")},
                             price_revision="prices-2")
        with self.assertRaises(ua.AttributionError):
            ua.estimate_cost(record, {"input": 3.0, "candidates": 1.0}, price_revision="prices-2")


    def test_cost_revalidates_the_counters_it_prices(self):
        # cached 9 > input 5 used to price a negative uncached term and return a number
        record = {**obs(), "counters": {**FULL, "input_tokens": 5, "cached_input_tokens": 9}}
        with self.assertRaises(ua.AttributionError):
            ua.estimate_cost(record, {"input": 3.0, "cached_input": 0.3, "output": 15.0},
                             price_revision="prices-2")
        with self.assertRaises(ua.AttributionError):
            ua.estimate_cost({**obs(), "counters": {**FULL, "output_tokens": "300"}},
                             {"input": 3.0, "cached_input": 0.3, "output": 15.0},
                             price_revision="prices-2")

    def test_cost_is_always_a_finite_number_or_a_refusal(self):
        # 10**400 tokens or a 10**400 rate raised OverflowError instead of refusing
        plain = {**FULL, "cached_input_tokens": 0}
        rates = {"input": 3.0, "output": 15.0}
        for what, counters, sheet in (
                ("10**400 input tokens", {**plain, "input_tokens": 10 ** 400}, rates),
                ("10**400 input rate", plain, {"input": 10 ** 400, "output": 15}),
                ("output rate above 2**53", plain, {"input": 3.0, "output": 1e300})):
            with self.subTest(what):
                with self.assertRaises(ua.AttributionError):
                    ua.estimate_cost({"counters": counters}, sheet, price_revision="prices-2")
        limit = 2 ** 53
        largest = ua.estimate_cost(
            {"counters": {"input_tokens": limit, "cached_input_tokens": 0,
                          "output_tokens": limit, "reasoning_output_tokens": 0}},
            {"input": limit, "output": limit}, price_revision="prices-2")
        self.assertEqual(largest["cost_usd"], 2 * limit * limit / 1_000_000)


class Aggregation(unittest.TestCase):
    def test_by_model_keeps_unknowns_null_and_reports_latency(self):
        first = obs(task_id="t1")
        second = obs(task_id="t2", started_at="2026-10-21T10:00:00Z",
                     completed_at="2026-10-21T10:00:01Z")
        other = obs(task_id="t3", observed_model="model-y", counters=None, interrupted=True,
                    completed_at=None)
        summary = ua.by_model([first, second, other])
        self.assertEqual(summary["model-x"]["input_tokens"], 2000)
        self.assertEqual(summary["model-x"]["cached_input_tokens"], 400)
        self.assertEqual(summary["model-x"]["latency_ms_median"], 1750)
        self.assertEqual(summary["model-x"]["observations"], 2)
        self.assertIsNone(summary["model-y"]["input_tokens"])
        self.assertEqual(summary["model-y"]["input_tokens_unknown"], 1)
        self.assertIsNone(summary["model-y"]["latency_ms_median"])
        self.assertEqual(summary["model-y"]["interrupted"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
