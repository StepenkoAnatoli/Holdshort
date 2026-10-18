#!/usr/bin/env python3
"""tools/check_calibration_evidence.py: the calibration evidence check (docs/proposals/calibration-first-onboarding.md,
Item 4.3).

Hermetic: the kit-run folders are built from the kit's own synthetic fixture (tests/fixtures/calibration/: its journal,
run file, manifest and grades) through the kit's observations.py, and each failing folder under
tests/fixtures/calibration-evidence/ is one edit of the passing one; the committed fixtures are regenerated here and must
match byte for byte. Nothing here calls a provider, reads a credential or needs the network.

usage: test_check_calibration_evidence.py            run the tests
       test_check_calibration_evidence.py --write-fixtures   rewrite tests/fixtures/calibration-evidence/ from the kit
"""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "tools" / "check_calibration_evidence.py"
KIT = ROOT / "tools" / "calibration"
KIT_FIX = ROOT / "tests" / "fixtures" / "calibration"
FIXTURES = ROOT / "tests" / "fixtures" / "calibration-evidence"
FOLDER = "fixture-host-calibration-1"

RULES = ("protocol-frozen", "prongs-declared", "scores-derivable", "fewer-prong-pass-flagged", "pin-category-mapping",
         "judging-profile-named", "relayed-chat-statement", "no-secrets-or-bodies")
# one failing fixture per rule: its directory name and the rule it must fail, and nothing else
FAILING = {
    "a-protocol-frozen": "protocol-frozen",
    "b-prongs-declared": "prongs-declared",
    "c-scores-derivable": "scores-derivable",
    "d-fewer-prong-pass-flagged": "fewer-prong-pass-flagged",
    "e-pin-category-mapping": "pin-category-mapping",
    "f-judging-profile-named": "judging-profile-named",
    "g-relayed-chat-statement": "relayed-chat-statement",
    "h-no-secrets-or-bodies": "no-secrets-or-bodies",
}


def load_check():
    spec = importlib.util.spec_from_file_location("check_calibration_evidence", CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, doc) -> None:
    # the kit's own form (observations.py): indent 1, UTF-8, one trailing newline
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def two_prong_run(tmp: Path) -> tuple[Path, Path]:
    """The kit fixture's protocol and run file under a two-prong classification: the protocol declares holds and
    reachable, and the lens records carry no forbidden field (the run-3 shape, G-2)."""
    protocol = read(KIT_FIX / "protocol.json")
    protocol["classification"]["prongs"] = ["holds", "reachable"]
    run = read(KIT_FIX / "run.json")
    for adj in run["result"]["adjudications"]:
        for lens in adj["lenses"]:
            lens.pop("forbidden", None)
    write(tmp / "protocol-2.json", protocol)
    write(tmp / "run-2.json", run)
    return tmp / "protocol-2.json", tmp / "run-2.json"


def build_kit_folder(out: Path, protocol: Path | None = None, run: Path | None = None) -> Path:
    """One kit-run evidence folder: observations.py over the kit fixture, plus the frozen protocol it was built under."""
    protocol = protocol or KIT_FIX / "protocol.json"
    cmd = [sys.executable, str(KIT / "observations.py"), str(KIT_FIX / "journal.jsonl"), str(run or KIT_FIX / "run.json"),
           str(KIT_FIX / "manifest.json"), str(KIT_FIX / "grades"), str(out), "--protocol", str(protocol)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise AssertionError(f"observations.py exit {p.returncode}: {p.stderr}")
    shutil.copy(protocol, out / "protocol.json")
    return out


def edit_json(folder: Path, name: str, fn) -> None:
    doc = read(folder / name)
    fn(doc)
    write(folder / name, doc)


def build_fixtures(dest: Path) -> None:
    """Every fixture folder: pass/, and one per rule a-h, each the passing folder with one edit (d: the passing folder
    built under two prongs, with the kit's would-fail flag taken away)."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        (dest / "pass" / FOLDER).mkdir(parents=True)
        build_kit_folder(dest / "pass" / FOLDER)
        for name in FAILING:
            shutil.copytree(dest / "pass" / FOLDER, dest / name / FOLDER)
        f = lambda name: dest / name / FOLDER  # noqa: E731
        edit_json(f("a-protocol-frozen"), "protocol.json", lambda p: p.update(run_id=None))
        edit_json(f("b-prongs-declared"), "protocol.json", lambda p: p["classification"].update(prongs=["holds", "reachable"]))
        edit_json(f("c-scores-derivable"), "scores.json", lambda s: s["profiles"]["alpha-low"]["pin"].update({"pass": False}))
        # d: built under two prongs, where the kit flags the PASS; the flag and the three-prong count are then removed
        shutil.rmtree(f("d-fewer-prong-pass-flagged"))
        protocol2, run2 = two_prong_run(tmp)
        f("d-fewer-prong-pass-flagged").mkdir(parents=True)
        build_kit_folder(f("d-fewer-prong-pass-flagged"), protocol2, run2)

        def unflag(s):
            review = s["profiles"]["beta-max"]["review"]
            review["would_fail_under_three_prong"] = False
            for k in ("three_prong_false_blocking", "three_prong_note"):
                review.pop(k, None)
            s["totals"]["cells"]["review"] = "1 of 1 PASS"
        edit_json(f("d-fewer-prong-pass-flagged"), "scores.json", unflag)
        edit_json(f("e-pin-category-mapping"), "scores.json", lambda s: s["category_mapping"].update(pin="build-tests"))
        edit_json(f("f-judging-profile-named"), "protocol.json", lambda p: p["judging_profile"].update(qualification=None, limitation=None))
        edit_json(f("g-relayed-chat-statement"), "protocol.json", lambda p: p["relayed_operator_text"].update(statement=""))
        (f("h-no-secrets-or-bodies") / "journal.jsonl").write_text('{"type": "launched"}\n', encoding="utf-8")


def tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def run_check(*folders: Path, cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CHECK), *map(str, folders)], capture_output=True, text=True, timeout=120, cwd=cwd)


def lines(out: str, kind: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln.startswith(kind + " ")]


def rule_of(line: str) -> str:
    # "FAIL <folder> <rule>: <text>"
    return line.split(" ", 2)[2].split(":", 1)[0]


class Fixtures(unittest.TestCase):
    def test_the_committed_fixtures_are_the_kit_built_ones(self):
        with tempfile.TemporaryDirectory() as d:
            build_fixtures(Path(d))
            self.assertEqual(sorted(tree(FIXTURES)), sorted(tree(Path(d))), "rerun with --write-fixtures")
            self.assertEqual(tree(FIXTURES), tree(Path(d)), "rerun with --write-fixtures")

    def test_one_failing_fixture_per_rule(self):
        self.assertEqual(sorted(FAILING.values()), sorted(RULES))
        self.assertEqual(sorted(p.name for p in FIXTURES.iterdir() if p.is_dir()), sorted(["pass", *FAILING]))


class KitRuns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def copy_pass(self, name: str = "x") -> Path:
        out = self.root / name / FOLDER
        shutil.copytree(FIXTURES / "pass" / FOLDER, out)
        return out

    def assert_fails_only(self, folder: Path, rule: str) -> list[str]:
        p = run_check(folder)
        fails = lines(p.stdout, "FAIL")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertTrue(fails, p.stdout)
        self.assertEqual({rule_of(ln) for ln in fails}, {rule}, p.stdout)
        self.assertEqual(lines(p.stdout, "LIMIT"), [], p.stdout)
        return fails

    def test_the_passing_folder_passes_with_no_limitation(self):
        p = run_check(FIXTURES / "pass" / FOLDER)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(lines(p.stdout, "FAIL") + lines(p.stdout, "LIMIT"), [], p.stdout)

    def test_each_failing_fixture_fails_its_rule_and_nothing_else(self):
        for name, rule in FAILING.items():
            with self.subTest(name):
                fails = self.assert_fails_only(FIXTURES / name / FOLDER, rule)
                folder = (FIXTURES / name / FOLDER).relative_to(ROOT).as_posix()
                for ln in fails:
                    self.assertTrue(ln.startswith(f"FAIL {folder} {rule}: "), ln)

    def test_a_key_shaped_string_fails_the_secrets_rule(self):
        folder = self.copy_pass()
        key = "sk-" + "ant-" + "a1B2c3D4" * 4  # written by concatenation: no literal for check_secrets to find here
        (folder / "notes.md").write_text(f"left behind: {key}\n", encoding="utf-8")
        fails = self.assert_fails_only(folder, "no-secrets-or-bodies")
        self.assertIn("notes.md", fails[0])
        self.assertNotIn(key, "\n".join(fails))  # the hit names the file and the pattern, never the value

    def test_prompt_bodies_and_transcripts_fail_the_secrets_rule(self):
        for name in ("grader.prompt.md", "transcript-1.txt", "journal.jsonl"):
            with self.subTest(name):
                folder = self.copy_pass(name)
                (folder / name).write_text("text\n", encoding="utf-8")
                fails = self.assert_fails_only(folder, "no-secrets-or-bodies")
                self.assertIn(name, fails[0])

    def test_a_two_prong_run_that_flags_but_counts_the_pass_fails_the_flag_rule(self):
        protocol2, run2 = two_prong_run(self.root)
        folder = self.root / "two" / FOLDER
        folder.mkdir(parents=True)
        build_kit_folder(folder, protocol2, run2)
        self.assertEqual(run_check(folder).returncode, 0)  # as the kit builds it: flagged, and the count excludes it
        edit_json(folder, "scores.json", lambda s: s["totals"]["cells"].update(review="1 of 1 PASS"))
        fails = self.assert_fails_only(folder, "fewer-prong-pass-flagged")
        self.assertIn("1 of 1 PASS", fails[0])

    def test_declared_prongs_must_equal_the_lens_schema_even_when_the_folder_agrees_with_itself(self):
        folder = self.copy_pass()
        two = ["holds", "reachable"]
        edit_json(folder, "protocol.json", lambda p: p["classification"].update(prongs=two))
        edit_json(folder, "adjudication.json", lambda a: a.update({"declared-prongs": two}))
        edit_json(folder, "scores.json", lambda s: s["adjudication_schema"].update(prongs_in_classification=two))
        fails = self.assert_fails_only(folder, "prongs-declared")
        self.assertEqual(len(fails), 1, fails)
        self.assertIn("lens schema carries holds, reachable, forbidden", fails[0])

    def test_a_flag_on_a_review_that_passes_on_every_prong_fails_the_flag_rule(self):
        folder = self.copy_pass()
        edit_json(folder, "scores.json", lambda s: s["profiles"]["beta-max"]["review"].update(would_fail_under_three_prong=True))
        self.assert_fails_only(folder, "fewer-prong-pass-flagged")

    def test_a_review_result_the_declared_prongs_do_not_give_fails_derivable(self):
        folder = self.copy_pass()
        # one lens fewer voting on all three prongs: C-1 is not real, so R-3 blocks and the review is not a PASS
        edit_json(folder, "adjudication.json", lambda a: a["clusters"][0]["lenses"][1].update(forbidden=False))
        fails = self.assert_fails_only(folder, "scores-derivable")
        self.assertIn("review:beta-max", "\n".join(fails))

    def test_the_bootstrap_judge_passes_with_its_limitation(self):
        folder = self.copy_pass()
        line = "judging profile not independently qualified, host-declared by the lead"
        edit_json(folder, "protocol.json", lambda p: p["judging_profile"].update(qualification=None, limitation=line))
        p = run_check(folder)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual([rule_of(ln) for ln in lines(p.stdout, "LIMIT")], ["judging-profile-named"])
        self.assertIn(line, p.stdout)
        edit_json(folder, "protocol.json", lambda p: p["judging_profile"].update(limitation="judged by the lead"))
        self.assert_fails_only(folder, "judging-profile-named")

    def test_relayed_text_is_verbatim_text_or_null_with_the_statement(self):
        folder = self.copy_pass()
        edit_json(folder, "protocol.json", lambda p: p["relayed_operator_text"].update(
            text="focus on the router for now", statement="the harness relays this operator text into every worker; the candidate preamble reconciles it"))
        self.assertEqual(run_check(folder).returncode, 0)
        for bad in ({"text": ""}, {"text": 7}, {"statement": None}, {"statement": "  "}):  # a {{placeholder}} is rule a's
            with self.subTest(bad):
                edit_json(folder, "protocol.json", lambda p, bad=bad: p["relayed_operator_text"].update(bad))
                self.assert_fails_only(folder, "relayed-chat-statement")
                edit_json(folder, "protocol.json", lambda p: p.update(relayed_operator_text=read(FIXTURES / "pass" / FOLDER / "protocol.json")["relayed_operator_text"]))
        edit_json(folder, "protocol.json", lambda p: p.pop("relayed_operator_text"))
        self.assert_fails_only(folder, "relayed-chat-statement")  # still a kit run: the other kit keys are there

    def test_a_missing_judging_profile_in_a_kit_run_fails_its_rule(self):
        folder = self.copy_pass()
        edit_json(folder, "protocol.json", lambda p: p.pop("judging_profile"))
        self.assert_fails_only(folder, "judging-profile-named")

    def test_protocol_freeze_failures(self):
        cases = [
            (lambda p: p.update(status="draft"), "status"),
            (lambda p: p.update(schema_version=0), "schema_version"),
            (lambda p: p.update(frozen_at="{{ISO-8601 UTC time of the freeze commit}}"), "placeholder"),
            (lambda p: p["accounting"]["rates_per_mtok"].update({"{{model alias}}": {}}), "placeholder"),
            (lambda p: p.update(run_id="run-other"), "run-other"),
        ]
        for fn, needle in cases:
            with self.subTest(needle):
                folder = self.copy_pass(needle + str(cases.index((fn, needle))))
                edit_json(folder, "protocol.json", fn)
                fails = self.assert_fails_only(folder, "protocol-frozen")
                self.assertIn(needle, "\n".join(fails))
        folder = self.copy_pass("complete")
        edit_json(folder, "protocol.json", lambda p: p.update(status="run complete; results in observations.json, scores.json, results-table.md and clusters.md; see amendments"))
        self.assertEqual(run_check(folder).returncode, 0)

    def test_scores_that_disagree_with_the_records_fail(self):
        cases = [
            ("scores.json", lambda s: s["profiles"]["beta-max"]["review"].update(result="PARTIAL", **{"pass": False}), "scores-derivable"),
            ("scores.json", lambda s: s["profiles"].pop("alpha-low"), "scores-derivable"),
            ("observations.json", lambda o: o["alpha-low"]["fix"].update(score=False), "scores-derivable"),
            ("scores.json", lambda s: s["adjudication_schema"].update(prongs_in_lens_schema=["holds"]), "prongs-declared"),
            ("adjudication.json", lambda a: a.update({"declared-prongs": ["holds", "reachable"]}), "prongs-declared"),
            ("scores.json", lambda s: s.pop("category_mapping"), "pin-category-mapping"),
        ]
        for i, (name, fn, rule) in enumerate(cases):
            with self.subTest(i=i, rule=rule):
                folder = self.copy_pass(f"s{i}")
                edit_json(folder, name, fn)
                self.assert_fails_only(folder, rule)

    def test_a_missing_or_unreadable_file_fails_by_name(self):
        for name, rule in (("protocol.json", "protocol-frozen"), ("scores.json", "scores-derivable"),
                           ("observations.json", "scores-derivable"), ("adjudication.json", "prongs-declared")):
            with self.subTest(name):
                folder = self.copy_pass("m-" + name)
                (folder / name).unlink()
                p = run_check(folder)
                self.assertEqual(p.returncode, 1, p.stdout)
                self.assertIn(f"{rule}: {name}", p.stdout)
                folder = self.copy_pass("u-" + name)
                (folder / name).write_text("{not json", encoding="utf-8")
                p = run_check(folder)
                self.assertEqual(p.returncode, 1, p.stdout)
                self.assertIn(f"{rule}: {name}", p.stdout)
        p = run_check(self.root / "nowhere")
        self.assertEqual(p.returncode, 1)
        self.assertIn("not a directory", p.stdout)

    def test_output_is_one_line_per_failure_and_a_summary(self):
        p = run_check(FIXTURES / "pass" / FOLDER, FIXTURES / "a-protocol-frozen" / FOLDER)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(len(lines(p.stdout, "FAIL")), 1, p.stdout)
        self.assertRegex(p.stdout.splitlines()[-1], r"^check_calibration_evidence: 2 folder\(s\), 1 failure\(s\), 0 limitation\(s\)$")


RUN1 = "docs/evidence/2026-10-17/claude-code-calibration"
RUN2 = "docs/evidence/2026-10-17/claude-code-calibration-2"
RUN3 = "docs/evidence/2026-10-18/claude-code-calibration-3"
PIN_LIMIT = ("pin-category-mapping: legacy run: scores.json records no category_mapping; the protocol labels the pin case build-tests; "
             "the table reads it as pin-tests under the host's rule 4 (run 3 amendment A-2)")
JUDGE_LIMIT = ("judging-profile-named: legacy run: no judging_profile; the grader opus-high is named in protocol.json cases[review].grading; "
               "its qualification is not recorded")
# the brief's C1: what each legacy folder cannot answer, recorded as a named limitation and never as a pass
LEGACY_LIMITS = [
    f"LIMIT {RUN1} prongs-declared: legacy run: no adjudication record (scores.json has no adjudication_schema, the folder no adjudication.json); no prongs declared",
    f"LIMIT {RUN1} fewer-prong-pass-flagged: legacy run: no adjudication record; its 8 review PASSes are unadjudicated and excluded from the table's pass count",
    f"LIMIT {RUN1} {PIN_LIMIT}",
    f"LIMIT {RUN1} {JUDGE_LIMIT}",
    f"LIMIT {RUN1} relayed-chat-statement: legacy run: no relayed_operator_text; whether the harness relayed operator text into workers is not recorded",
    f"LIMIT {RUN2} prongs-declared: legacy run: no adjudication record (scores.json has no adjudication_schema, the folder no adjudication.json); no prongs declared",
    f"LIMIT {RUN2} fewer-prong-pass-flagged: legacy run: no adjudication record; its 9 review PASSes are unadjudicated and excluded from the table's pass count",
    f"LIMIT {RUN2} {PIN_LIMIT}",
    f"LIMIT {RUN2} {JUDGE_LIMIT}",
    f"LIMIT {RUN2} relayed-chat-statement: legacy run: no relayed_operator_text; whether the harness relayed operator text into workers is not recorded",
    f"LIMIT {RUN3} prongs-declared: legacy run: the lens schema carried holds, reachable; the classification declares holds, reachable, forbidden; "
    "missing forbidden (scores.json adjudication_schema)",
    f"LIMIT {RUN3} fewer-prong-pass-flagged: legacy run: the lens records carry no forbidden field, so which review PASSes hold only by the missing prong "
    "is the run's own reading (flagged: haiku-medium, haiku-high), not a recorded vote; the flags and the stated count are checked, the reading is not",
    f"LIMIT {RUN3} {JUDGE_LIMIT}",
    f"LIMIT {RUN3} relayed-chat-statement: legacy run: no relayed_operator_text before the launch; the relayed text is recorded after the run in amendment A-1",
]


class LegacyRuns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def copy_run(self, rel: str) -> Path:
        self.n = getattr(self, "n", 0) + 1  # one fresh copy per call, so a failed subtest leaves no folder in the way
        out = self.root / str(self.n) / Path(rel).name
        shutil.copytree(ROOT / rel, out)  # a copy: the evidence folders themselves are never edited
        return out

    def fails(self, folder: Path) -> list[str]:
        p = run_check(folder)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        return lines(p.stdout, "FAIL")

    def test_the_three_real_folders_pass_with_exactly_these_limitations(self):
        p = run_check()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(lines(p.stdout, "FAIL"), [])
        self.assertEqual(lines(p.stdout, "LIMIT"), LEGACY_LIMITS)
        self.assertEqual(p.stdout.splitlines()[-1], f"check_calibration_evidence: 3 folder(s), 0 failure(s), {len(LEGACY_LIMITS)} limitation(s)")

    def test_the_report_classifies_each_real_folder(self):
        check = load_check()
        r1, r2, r3 = (check.check_folder(ROOT / rel) for rel in (RUN1, RUN2, RUN3))
        self.assertEqual((r1.kind, r2.kind, r3.kind), ("legacy", "legacy", "legacy"))
        self.assertEqual(r1.unadjudicated, ["sonnet-low", "sonnet-medium", "opus-medium", "opus-high", "opus-xhigh", "fable-medium", "fable-high", "fable-xhigh"])
        self.assertEqual(len(r2.unadjudicated), 9)
        self.assertEqual((r3.unadjudicated, r3.flagged, r3.review_prongs), ([], ["haiku-medium", "haiku-high"], ["holds", "reachable"]))
        self.assertEqual((r1.review_prongs, r2.review_prongs), (None, None))

    def test_a_score_the_observations_do_not_support_fails(self):
        cases = [
            (RUN1, "scores.json", lambda s: s["profiles"]["haiku-medium"]["review"].update({"pass": True}), "review:haiku-medium"),
            (RUN1, "scores.json", lambda s: s["profiles"]["sonnet-low"]["pin"].update({"pass": False}), "pin:sonnet-low"),
            (RUN2, "scores.json", lambda s: s["profiles"]["sonnet-low"]["review"].update(result="PASS", **{"pass": True}), "review:sonnet-low"),
            (RUN2, "observations.json", lambda o: o["profiles"]["opus-high"]["fix"]["grade"].update(guardRed=False), "fix:opus-high"),
            (RUN3, "scores.json", lambda s: s["profiles"]["fable-medium"]["pin"].update({"pass": True}), "pin:fable-medium"),
            # one lens of C-4 no longer holds: C-4 is not real, so haiku-high's R-2 blocks and its review is no PASS
            (RUN3, "adjudication.json", lambda a: next(x for x in a["adjudications"] if x["cluster"]["id"] == "C-4")["lenses"][1].update(holds=False), "review:haiku-high"),
        ]
        for rel, name, fn, cell in cases:
            with self.subTest(cell):
                folder = self.copy_run(rel)
                edit_json(folder, name, fn)
                fails = self.fails(folder)
                self.assertIn("scores-derivable", {rule_of(ln) for ln in fails}, fails)
                self.assertTrue(any(cell in ln for ln in fails), fails)
                shutil.rmtree(folder)

    def test_a_pass_rule_the_check_does_not_encode_fails(self):
        folder = self.copy_run(RUN2)
        edit_json(folder, "protocol.json", lambda p: p["cases"][0].update(pass_rule=p["cases"][0]["pass_rule"] + " AND the tests are fast"))
        fails = self.fails(folder)
        self.assertEqual({rule_of(ln) for ln in fails}, {"scores-derivable"})
        self.assertIn("pin pass rule", fails[0])

    def test_a_scored_case_with_no_encoded_pass_rule_fails(self):
        # F1: a folder that drops the kit keys is a legacy run; a case it scores under no encoded rule is refused, never
        # skipped, so a folder cannot pass by dropping its own pass rules
        kit = self.root / "kit" / FOLDER
        shutil.copytree(FIXTURES / "pass" / FOLDER, kit)

        def strip(p):
            for k in ("judging_profile", "relayed_operator_text", "classification", "cases"):
                p.pop(k, None)
        edit_json(kit, "protocol.json", strip)
        # C-1 no longer real: under any rule beta-max's review would not be a PASS, while scores.json still says PASS
        edit_json(kit, "adjudication.json", lambda a: [ln.update(holds=False) for c in a["clusters"] for ln in c["lenses"]])
        fails = [ln for ln in self.fails(kit) if rule_of(ln) == "scores-derivable"]
        for case in ("pin", "fix", "review"):
            self.assertTrue(any(f"no encoded pass rule for the {case} case" in ln for ln in fails), fails)
        cases = [
            (RUN1, lambda p: p.pop("cases"), ("pin", "fix", "review")),
            (RUN2, lambda p: next(c for c in p["cases"] if c["id"] == "fix").update(id="fix-renamed"), ("fix",)),
        ]
        for rel, fn, want in cases:
            with self.subTest(rel=rel, want=want):
                folder = self.copy_run(rel)
                edit_json(folder, "protocol.json", fn)
                fails = self.fails(folder)
                self.assertEqual({rule_of(ln) for ln in fails}, {"scores-derivable"}, fails)
                self.assertEqual(sorted(ln.split("no encoded pass rule for the ", 1)[1].split(" ", 1)[0] for ln in fails), sorted(want), fails)

    def test_a_case_stated_twice_fails(self):
        # two encoded rules for one case: neither is chosen silently
        folder = self.copy_run(RUN2)
        run1_pin = next(c for c in read(ROOT / RUN1 / "protocol.json")["cases"] if c["id"] == "pin")
        edit_json(folder, "protocol.json", lambda p: p["cases"].append(run1_pin))
        fails = self.fails(folder)
        self.assertEqual({rule_of(ln) for ln in fails}, {"scores-derivable"}, fails)
        self.assertIn("states the pin case 2 times", "\n".join(fails))

    def test_run3_flags_and_count_must_agree(self):
        cases = [
            (lambda s: s["profiles"]["haiku-medium"]["review"].update(would_fail_under_three_prong=False), "15 of 15 PASS"),  # the count still says 13
            (lambda s: s["profiles"]["sonnet-high"]["review"].update(would_fail_under_three_prong=True),
             "review:sonnet-high is flagged would-fail, yet none of its S1-S3 other findings"),  # it has no blocking other to fall
            (lambda s: s["totals"]["cells"].update(review="15 of 15 PASS"), "15 of 15 PASS"),
            (lambda s: s["profiles"]["fable-medium"]["pin"].update(would_fail_under_three_prong=True) or
             s["profiles"]["haiku-low"]["review"].update(result="FAIL", would_fail_under_three_prong=True),
             "review:haiku-low carries would_fail_under_three_prong: true on a 'FAIL', not a PASS"),
        ]
        for i, (fn, needle) in enumerate(cases):
            with self.subTest(i):
                folder = self.copy_run(RUN3)
                edit_json(folder, "scores.json", fn)
                fails = [ln for ln in self.fails(folder) if rule_of(ln) == "fewer-prong-pass-flagged"]
                self.assertTrue(fails)
                self.assertIn(needle, "\n".join(fails))
                shutil.rmtree(folder)

    def test_run3_schema_contradictions_fail_prongs_declared(self):
        cases = [
            ("scores.json", lambda s: s["adjudication_schema"].update(missing_prong="reachable")),
            ("scores.json", lambda s: s["adjudication_schema"].update(prongs_in_lens_schema=["holds", "reachable", "forbidden"])),
            ("adjudication.json", lambda a: a.update(lens_schema_prongs=["holds"])),
            ("adjudication.json", lambda a: a["adjudications"][0]["lenses"][0].update(forbidden=True)),
        ]
        for i, (name, fn) in enumerate(cases):
            with self.subTest(i):
                folder = self.copy_run(RUN3)
                edit_json(folder, name, fn)
                self.assertIn("prongs-declared", {rule_of(ln) for ln in self.fails(folder)})
                shutil.rmtree(folder)
        folder = self.copy_run(RUN3)
        (folder / "adjudication.json").unlink()
        self.assertIn("prongs-declared", {rule_of(ln) for ln in self.fails(folder)})

    def test_a_legacy_run_id_must_agree_and_exist(self):
        folder = self.copy_run(RUN1)
        edit_json(folder, "scores.json", lambda s: s.update(run_id="wf_other"))
        self.assertEqual({rule_of(ln) for ln in self.fails(folder)}, {"protocol-frozen"})
        edit_json(folder, "protocol.json", lambda p: p.pop("run_id"))
        self.assertIn("run_id", "\n".join(self.fails(folder)))

    def test_a_legacy_run_carries_no_kit_rule_it_cannot_answer_as_a_failure(self):
        # a legacy run is never refused for lacking kit keys: it has no judging_profile, relayed text or prongs
        p = run_check(ROOT / RUN1)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual({rule_of(ln) for ln in lines(p.stdout, "LIMIT")},
                         {"prongs-declared", "fewer-prong-pass-flagged", "pin-category-mapping", "judging-profile-named", "relayed-chat-statement"})


class Gate(unittest.TestCase):
    def test_registered_in_the_regression_gate_after_the_kit(self):
        spec = importlib.util.spec_from_file_location("run_regression", ROOT / "tools" / "run_regression.py")
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        names = [name for name, _ in gate.CHECKS]
        i = names.index("test_calibration_kit")
        want = [("test_check_calibration_evidence", ["tools/test_check_calibration_evidence.py"]),
                ("check_calibration_evidence", ["tools/check_calibration_evidence.py"]),
                ("test_qualification_table", ["tools/test_qualification_table.py"]),
                ("qualification_table", ["tools/qualification_table.py", "--check"])]
        self.assertEqual([(n, cmd[1:]) for n, cmd in gate.CHECKS[i + 1:i + 5]], want)
        for _, cmd in gate.CHECKS[i + 1:i + 5]:
            self.assertEqual(cmd[0], sys.executable)


class Docs(unittest.TestCase):
    def test_the_evidence_readme_documents_every_rule_and_both_kinds_of_run(self):
        text = (ROOT / "docs" / "evidence" / "README.md").read_text(encoding="utf-8")
        section = text.split("## Calibration evidence check", 1)[1].split("\n## ", 1)[0]
        for rule in RULES:
            self.assertIn(f"`{rule}`", section, rule)
        for words in ("kit run", "legacy run", "LIMIT", "FAIL", "python3 tools/check_calibration_evidence.py", "never edit"):
            self.assertIn(words, text, words)

    def test_the_kit_readme_names_the_check_a_results_pull_request_must_pass(self):
        text = (KIT / "README.md").read_text(encoding="utf-8")
        paragraphs = [p for p in text.split("\n\n") if "check_calibration_evidence.py" in p]
        self.assertEqual(len(paragraphs), 1, paragraphs)
        for rule in RULES:
            self.assertIn(rule, paragraphs[0])
        self.assertIn("qualification_table.py", paragraphs[0])

    def test_one_changelog_line_names_the_check_and_the_table(self):
        unreleased = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split("## Unreleased", 1)[1].split("\n## ", 1)[0]
        hits = [ln for ln in unreleased.splitlines() if "check_calibration_evidence.py" in ln]
        self.assertEqual(len(hits), 1, hits)
        self.assertIn("qualification_table.py", hits[0])
        self.assertIn("calibration-first-onboarding", hits[0])
        self.assertNotIn("tools/calibration/", hits[0])  # the kit's own test allows one Unreleased line naming that path


class Discovery(unittest.TestCase):
    def test_default_folders_are_the_calibration_runs_under_docs_evidence(self):
        check = load_check()
        found = [p.relative_to(ROOT).as_posix() for p in check.discover(ROOT)]
        self.assertEqual(found, ["docs/evidence/2026-10-17/claude-code-calibration",
                                 "docs/evidence/2026-10-17/claude-code-calibration-2",
                                 "docs/evidence/2026-10-18/claude-code-calibration-3"])

    def test_discovery_matches_both_patterns_once_each(self):
        check = load_check()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel in ("docs/evidence/2026-01-02/claude-code-calibration-4", "docs/evidence/2026-01-01/other-host-calibration-1",
                        "docs/evidence/2026-01-01/model-policy-pilot", "docs/evidence/2026-01-01/claude-code-calibration"):
                (root / rel).mkdir(parents=True)
            (root / "docs/evidence/2026-01-01/x-calibration-2.json").write_text("{}")
            found = [p.relative_to(root).as_posix() for p in check.discover(root)]
            self.assertEqual(found, ["docs/evidence/2026-01-01/claude-code-calibration", "docs/evidence/2026-01-01/other-host-calibration-1",
                                     "docs/evidence/2026-01-02/claude-code-calibration-4"])


def main() -> int:
    if sys.argv[1:] == ["--write-fixtures"]:
        if FIXTURES.exists():
            shutil.rmtree(FIXTURES)
        FIXTURES.mkdir(parents=True)
        build_fixtures(FIXTURES)
        print(f"written: {FIXTURES.relative_to(ROOT)}")
        return 0
    return 0 if unittest.main(verbosity=2, exit=False).result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
