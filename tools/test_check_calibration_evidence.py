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
