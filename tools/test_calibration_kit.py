#!/usr/bin/env python3
"""tools/calibration: the calibration kit (docs/proposals/calibration-first-onboarding.md, Items 2-4.2).

Hermetic: every test runs on the synthetic fixtures under tests/fixtures/calibration/ or on temporary git
repositories it builds itself; nothing here calls a provider, reads a credential or needs the network.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "tools" / "calibration"
FIX = ROOT / "tests" / "fixtures" / "calibration"

# The keys of one observation in observations.json (the flat profile map hosts/claude-code/route.mjs `rate` reads:
# calibrationEvidence takes the model from usage[<task>].model, the effort from the profile key's suffix, and the grades
# from pin.score, fix.score and review-grade.result). tools/calibration/README.md documents each of them.
OBSERVATION_KEYS = {"profile", "review-only", "pin", "fix", "review", "review-grade", "self-reported-mistakes", "harness-retries", "usage"}
USAGE_KEYS = {"label", "model", "effort", "state", "tokens", "ms", "run"}
SCORES_KEYS = {"schema_version", "run_id", "supplementary_run_id", "pack", "pass_rules", "accounting_note", "profiles", "void_cells",
               "totals", "category_mapping", "adjudication_schema"}


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build(out: Path, *extra: str, run: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(KIT / "observations.py"), str(FIX / "journal.jsonl"), str(run or FIX / "run.json"), str(FIX / "manifest.json"),
           str(FIX / "grades"), str(out), "--protocol", str(FIX / "protocol.json"), *extra]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def git_env(home: Path) -> dict:
    """Hermetic git: no global or system config (signing, machine-wide hooks), a fixed identity."""
    import os
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    cfg = home / "gitconfig"
    if not cfg.exists():
        cfg.write_text("[user]\n\tname = t\n\temail = t@localhost\n[init]\n\tdefaultBranch = main\n")
    env.update(GIT_CONFIG_GLOBAL=str(cfg), GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1")
    return env


def sh(args, cwd: Path, env: dict, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
    if check and p.returncode != 0:
        raise AssertionError(f"{args} exit {p.returncode}: {p.stdout}{p.stderr}")
    return p


def commit_all(repo: Path, env: dict, msg: str) -> str:
    sh(["git", "add", "-A"], repo, env)
    sh(["git", "commit", "-q", "-m", msg], repo, env)
    return sh(["git", "rev-parse", "HEAD"], repo, env).stdout.strip()


def make_pack(root: Path, env: dict, report: str = "exit-code") -> tuple[Path, dict]:
    """A temporary subject pack: a two-line module (add answers a - b at the base), a one-row test, the accepted fix."""
    pack, repo = root / "pack", root / "pack" / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "docs").mkdir()
    (repo / ".gitignore").write_text("__pycache__/\n")
    (repo / "src" / "mod.py").write_text("def add(a, b):\n    return a - b\n")
    (repo / "src" / "other.py").write_text("X = 1\n")
    (repo / "docs" / "MAP.md").write_text("map\n")
    (repo / "README.md").write_text("readme\n")
    (repo / "tests" / "test_mod.py").write_text(
        "import unittest\nfrom src.mod import add\n\n\nclass T(unittest.TestCase):\n    def test_zero(self):\n        self.assertEqual(add(0, 0), 0)\n")
    sh(["git", "init", "-q"], repo, env)
    base = commit_all(repo, env, "base")
    (repo / "src" / "mod.py").write_text("def add(a, b):\n    return a + b\n")
    with (repo / "tests" / "test_mod.py").open("a") as f:
        f.write("\n    def test_sum(self):\n        self.assertEqual(add(2, 3), 5)\n")
    accepted = commit_all(repo, env, "accepted fix")
    test_cmd = "python3 -m unittest {files}"
    if report == "vitest-json":
        test_cmd = ("if python3 -m unittest {files}; then echo '{\"numPassedTests\": 1, \"numFailedTests\": 0, \"numTotalTests\": 1}' > {report}; "
                    "else echo '{\"numPassedTests\": 0, \"numFailedTests\": 1, \"numTotalTests\": 1}' > {report}; fi")
    manifest = json.loads((FIX / "manifest.json").read_text())
    manifest.update(accepted_fix=accepted, commands={"test": test_cmd, "test_report": report, "lint": "python3 -m py_compile {files}", "timeout_seconds": 120})
    for case in ("pin", "fix"):
        manifest["cases"][case]["base"] = base
    manifest["cases"]["review"]["base"] = base
    (pack / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return pack, {"base": base, "accepted": accepted, "repo": repo}


def checkout(src: Path, commit: str, target: Path, env: dict, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(KIT / "historyless-checkout.sh"), *flags, str(src), commit, str(target), "cal/test"],
                          env=env, capture_output=True, text=True, timeout=120)


def grade(manifest: Path, task: str, cand: Path, env: dict) -> tuple[int, dict, str]:
    p = subprocess.run(["bash", str(KIT / "grade.sh"), str(manifest), task, str(cand)], env=env, capture_output=True, text=True, timeout=600)
    try:
        doc = json.loads(p.stdout)
    except ValueError:
        doc = {}
    return p.returncode, doc, p.stdout + p.stderr


def md_section(text: str, heading: str) -> str:
    """The body of a '## <heading>' section of a kit markdown file (run.template.js reads the prompts the same way)."""
    m = re.search(r"^## " + re.escape(heading) + r"[ \t]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        raise AssertionError(f"no '## {heading}' section")
    return m.group(1).strip()


def md_schema(text: str) -> dict:
    body = md_section(text, "Output schema")
    m = re.search(r"```json\n(.*?)\n```", body, re.S)
    if not m:
        raise AssertionError("no fenced json block under '## Output schema'")
    return json.loads(m.group(1))


PROTOCOL_KEYS = {"_lineage", "schema_version", "kit_version", "status", "run_id", "frozen_at", "revision", "host", "subject_pack", "profiles",
                 "review_only_profiles", "runs_per_profile_per_task", "retry_limit", "cases", "sources", "source_hash_convention", "metrics",
                 "accounting", "timing", "privacy", "limits", "classification", "judging_profile", "relayed_operator_text",
                 "usage_window_readings", "amendments"}


class Observations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def built(self, *extra, run=None):
        p = build(self.out, *extra, run=run)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads((self.out / "observations.json").read_text()), json.loads((self.out / "scores.json").read_text())

    def test_flat_profile_map_the_adapter_reads(self):
        obs, _ = self.built()
        self.assertEqual(sorted(obs), ["alpha-low", "beta-max"])
        for key, o in obs.items():
            self.assertEqual(set(o), OBSERVATION_KEYS, key)
            self.assertEqual(o["profile"], key)
            for task, u in o["usage"].items():
                if u is not None:
                    self.assertEqual(set(u), USAGE_KEYS, f"{key} usage {task}")
        a, b = obs["alpha-low"], obs["beta-max"]
        self.assertIs(a["pin"]["score"], True)
        self.assertEqual(a["pin"]["tier"], "T1")
        self.assertIs(a["fix"]["score"], True)
        self.assertIsNone(a["review-grade"])  # not run for this profile: nothing to count
        self.assertEqual(a["usage"]["pin"]["model"], "model-alpha-1")
        self.assertEqual(a["harness-retries"]["pin"], 1)  # attempt 2 in the run file: a harness retry, not a model retry
        self.assertIs(b["review-only"], True)
        self.assertIsNone(b["pin"])
        self.assertIsNone(b["fix"])
        self.assertEqual(b["review-grade"]["result"], "PASS")
        self.assertEqual(b["review-grade"]["tier"], "T1")
        self.assertEqual(b["review-grade"]["rawFalseBlocking"], 1)
        self.assertEqual(b["review-grade"]["adjudicatedFalseBlocking"], 0)
        self.assertEqual(b["usage"]["review"]["model"], "model-beta-1")  # the candidate's model, never the grader's
        self.assertEqual(b["usage"]["grade"]["model"], "model-gamma-1")
        other = b["review-grade"]["others"][0]
        self.assertEqual((other["cluster"], other["clusterReal"], other["adjudicated"]), ("C-1", True, True))

    def test_scores_totals_sum_and_carry_the_schema(self):
        _, s = self.built()
        self.assertTrue(SCORES_KEYS <= set(s), SCORES_KEYS - set(s))
        run = json.loads((FIX / "run.json").read_text())
        agent_tokens = sum(e["tokens"] for e in run["workflowProgress"] if e["type"] == "workflow_agent")
        m = s["totals"]["tokens"]["main_run"]
        self.assertEqual((m["items"], m["graders"], m["clustering"], m["lenses"], m["other"]), (6000, 500, 200, 500, 0))
        self.assertEqual(m["total"], m["items"] + m["graders"] + m["clustering"] + m["lenses"] + m["other"])
        self.assertEqual(m["total"], agent_tokens)
        self.assertEqual(s["totals"]["tokens"]["both_runs_total"], agent_tokens)
        self.assertEqual(s["totals"]["tokens"]["judging_both_runs"], 1200)
        self.assertEqual(s["category_mapping"]["pin"], "pin-tests")
        self.assertEqual(s["adjudication_schema"]["prongs_in_classification"], ["holds", "reachable", "forbidden"])
        self.assertEqual(s["adjudication_schema"]["prongs_in_lens_schema"], ["holds", "reachable", "forbidden"])
        self.assertEqual(s["adjudication_schema"]["missing_prong"], [])
        review = s["profiles"]["beta-max"]["review"]
        self.assertIs(review["would_fail_under_three_prong"], False)
        self.assertEqual(review["result"], "PASS")
        pin = s["profiles"]["alpha-low"]["pin"]
        self.assertEqual(pin["estimate"], {"tokens": 1000, "usd_all_input": 0.001, "usd_all_output": 0.005})
        self.assertEqual(s["totals"]["cells"]["pin"], "1 of 1 PASS")

    def test_writes_the_results_layout(self):
        self.built()
        for name in ("observations.json", "scores.json", "results-table.md", "clusters.md", "tokens-and-estimates.md", "adjudication.json", "void-cells.json"):
            self.assertTrue((self.out / name).is_file(), name)
        table = (self.out / "results-table.md").read_text()
        self.assertIn("| alpha-low | PASS | PASS | yes | - |", table)
        self.assertIn("| C-1 |", (self.out / "clusters.md").read_text())
        self.assertIn("7,200", (self.out / "tokens-and-estimates.md").read_text())

    def test_a_lens_record_without_forbidden_cannot_carry_a_three_prong_pass(self):
        run = json.loads((FIX / "run.json").read_text())
        for lens in run["result"]["adjudications"][0]["lenses"]:
            del lens["forbidden"]  # run 3's lens schema (G-2): two prongs only
        path = Path(self.tmp.name) / "run-two-prong.json"
        path.write_text(json.dumps(run))
        _, s = self.built(run=path)
        review = s["profiles"]["beta-max"]["review"]
        self.assertEqual(review["result"], "PASS")  # the run's preregistered verdict stands for the score
        self.assertIs(review["would_fail_under_three_prong"], True)
        self.assertEqual(review["three_prong_false_blocking"], 1)
        self.assertEqual(s["adjudication_schema"]["missing_prong"], ["forbidden"])
        self.assertEqual(s["totals"]["cells"]["review"], "1 of 1 PASS (0 of 1 under the three-prong definition)")

    def test_three_prong_vote_needs_forbidden_on_a_majority(self):
        run = json.loads((FIX / "run.json").read_text())
        run["result"]["adjudications"][0]["lenses"][1]["forbidden"] = False  # now one lens of three says forbidden
        path = Path(self.tmp.name) / "run-one-forbidden.json"
        path.write_text(json.dumps(run))
        _, s = self.built(run=path)
        self.assertIs(s["profiles"]["beta-max"]["review"]["would_fail_under_three_prong"], True)

    def test_void_cell_replaced_by_the_supplementary_run(self):
        tmp = Path(self.tmp.name)
        fix_result = json.loads((FIX / "journal.jsonl").read_text().splitlines()[-7])["result"]
        (tmp / "j2.jsonl").write_text("\n".join(json.dumps(e) for e in [
            {"type": "launched"}, {"type": "started", "agentId": "b01", "key": "b01", "label": "fix:alpha-low", "phase": "Fix"},
            {"type": "result", "agentId": "b01", "key": "b01", "result": fix_result}]) + "\n")
        (tmp / "r2.json").write_text(json.dumps({"runId": "run-supp-1", "workflowProgress": [
            {"type": "workflow_agent", "label": "fix:alpha-low", "agentId": "b01", "model": "model-alpha-1", "state": "done", "tokens": 1800, "durationMs": 1, "attempt": 1}],
            "result": {"results": [], "clusters": {"clusters": []}, "adjudications": []}}))
        obs, s = self.built("--void", "fix:alpha-low", "--supplementary", str(tmp / "j2.jsonl"), str(tmp / "r2.json"))
        self.assertEqual(obs["alpha-low"]["usage"]["fix"]["run"], "run-supp-1")
        self.assertEqual(obs["alpha-low"]["usage"]["fix"]["tokens"], 1800)
        void = json.loads((self.out / "void-cells.json").read_text())
        self.assertEqual(void["void-cells"]["fix:alpha-low"]["main-run"]["usage"]["tokens"], 2000)
        t = s["totals"]["tokens"]
        self.assertEqual(t["main_run"]["of_which_void_cells"], 2000)
        self.assertEqual(t["supplementary_run"]["items"], 1800)
        self.assertEqual(t["scored_cells_items"], 6000 - 2000 + 1800)
        self.assertEqual(s["profiles"]["alpha-low"]["fix"]["supplementary_run"], "run-supp-1")
        self.assertEqual(s["supplementary_run_id"], "run-supp-1")

    def test_a_void_cell_without_a_supplementary_run_is_refused(self):
        p = build(self.out, "--void", "fix:alpha-low")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("void", p.stderr)

    def test_missing_input_is_refused_with_a_reason(self):
        p = subprocess.run([sys.executable, str(KIT / "observations.py"), str(FIX / "nope.jsonl"), str(FIX / "run.json"), str(FIX / "manifest.json"),
                            str(FIX / "grades"), str(self.out)], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 2)
        self.assertIn("nope.jsonl", p.stderr)

    @unittest.skipUnless(shutil.which("node"), "node is not installed: the adapter cannot run here")
    def test_the_adapter_counts_the_built_observations(self):
        self.built()
        trace = Path(self.tmp.name) / "trace"
        (trace / "calibration-1").mkdir(parents=True)
        shutil.copy(self.out / "observations.json", trace / "calibration-1" / "observations.json")
        p = subprocess.run(["node", str(ROOT / "hosts" / "claude-code" / "route.mjs"), "rate", "--trace", str(trace), "--policy",
                            str(ROOT / "hosts" / "claude-code" / "host-policy.json"), "--now", "2026-10-18T00:00:00Z"],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        for line in ("alpha-low (no policy profile) pin-tests: 1 pass, 0 partial, 0 fail (calibration-1)",
                     "alpha-low (no policy profile) fix: 1 pass, 0 partial, 0 fail (calibration-1)",
                     "beta-max (no policy profile) review: 1 pass, 0 partial, 0 fail (calibration-1)"):
            self.assertIn(f"CALIBRATION {line}", p.stdout)

    def test_review_rule_pass_partial_fail(self):
        mod = load_module("observations")
        truth = lambda *found: [{"id": f"D-{n}", "found": f, "causeNamed": f, "severity": "S3"} for n, f in enumerate(found, 1)]
        g = {"truth": truth(True, True), "copiedFromHistory": False}
        self.assertEqual(mod.review_result(g, 0, ["D-1", "D-2"]), "PASS")
        self.assertEqual(mod.review_result(g, 1, ["D-1", "D-2"]), "FAIL")
        self.assertEqual(mod.review_result({**g, "truth": truth(True, False)}, 0, ["D-1", "D-2"]), "PARTIAL")
        self.assertEqual(mod.review_result({**g, "truth": truth(False, False)}, 0, ["D-1", "D-2"]), "FAIL")
        self.assertEqual(mod.review_result({**g, "copiedFromHistory": True}, 0, ["D-1", "D-2"]), "FAIL")
        # a ground-truth id the grader left out is not found
        self.assertEqual(mod.review_result({**g, "truth": truth(True)}, 0, ["D-1", "D-2"]), "PARTIAL")


class Scripts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = git_env(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_both_scripts_pass_bash_n(self):
        for name in ("grade.sh", "historyless-checkout.sh"):
            p = subprocess.run(["bash", "-n", str(KIT / name)], capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, 0, f"{name}: {p.stderr}")

    def test_historyless_checkout_is_one_root_commit_with_the_source_tree(self):
        pack, c = make_pack(self.root, self.env)
        (c["repo"] / ".gitattributes").write_text("README.md export-ignore\n")  # git archive would drop it; the tree must not
        base2 = commit_all(c["repo"], self.env, "attributes")
        target = self.root / "cand"
        p = checkout(c["repo"], base2, target, self.env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        g = lambda *a: sh(["git", *a], target, self.env).stdout.strip()
        self.assertEqual(g("rev-list", "--all", "--count"), "1")
        self.assertEqual(g("rev-list", "--max-parents=0", "HEAD"), g("rev-parse", "HEAD"))
        self.assertEqual(g("rev-parse", "HEAD^{tree}"), sh(["git", "rev-parse", f"{base2}^{{tree}}"], c["repo"], self.env).stdout.strip())
        self.assertEqual(g("branch", "--show-current"), "cal/test")
        self.assertEqual(g("status", "--porcelain"), "")
        self.assertTrue((target / "README.md").is_file())
        for sha in (c["accepted"], c["base"], base2):  # no commit of the source is an object here
            self.assertNotEqual(sh(["git", "cat-file", "-e", sha], target, self.env, check=False).returncode, 0, sha)

    def test_historyless_checkout_links_only_on_request_and_hides_the_links(self):
        pack, c = make_pack(self.root, self.env)
        (c["repo"] / "deps").mkdir()
        p = checkout(c["repo"], c["base"], self.root / "plain", self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse((self.root / "plain" / "deps").exists())
        p = checkout(c["repo"], c["base"], self.root / "linked", self.env, "--link", "deps")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((self.root / "linked" / "deps").is_symlink())
        self.assertEqual(sh(["git", "status", "--porcelain"], self.root / "linked", self.env).stdout.strip(), "")

    def test_historyless_checkout_refuses_an_existing_target_and_one_inside_the_pack(self):
        pack, c = make_pack(self.root, self.env)
        (self.root / "taken").mkdir()
        p = checkout(c["repo"], c["base"], self.root / "taken", self.env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        p = checkout(c["repo"], c["base"], pack / "cand", self.env, "--pack", str(pack))
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("pack", p.stderr)
        self.assertFalse((pack / "cand").exists())
        p = checkout(c["repo"], c["base"], self.root / "ok", self.env, "--pack", str(pack))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def candidate(self, c, name):
        target = self.root / name
        p = checkout(c["repo"], c["base"], target, self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        return target

    def fix_like_the_accepted_one(self, cand):
        (cand / "src" / "mod.py").write_text("def add(a, b):\n    return a + b\n")
        with (cand / "tests" / "test_mod.py").open("a") as f:
            f.write("\n    def test_sum(self):\n        self.assertEqual(add(2, 3), 5)\n")
        (cand / "docs" / "MAP.md").write_text("map: add answers the sum\n")

    def test_grade_fix_green_candidate_passes(self):
        pack, c = make_pack(self.root, self.env)
        cand = self.candidate(c, "fix-good")
        self.fix_like_the_accepted_one(cand)
        commit_all(cand, self.env, "fix")
        before = (cand / "src" / "mod.py").read_bytes()
        code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual((d["candidateGreen"], d["guardRed"], d["acceptedPinGreen"], d["scopeOk"], d["lint"]), (True, True, True, True, "ok"), out)
        self.assertIs(d["committedWithMap"], True)
        self.assertIs(d["PASS"], True)
        self.assertEqual((cand / "src" / "mod.py").read_bytes(), before)  # the grade restores what it swapped
        self.assertFalse((cand / "tests" / "test_zz_accepted.py").exists())

    def test_grade_fix_source_touching_candidate_fails_on_scope(self):
        pack, c = make_pack(self.root, self.env)
        cand = self.candidate(c, "fix-scope")
        self.fix_like_the_accepted_one(cand)
        (cand / "src" / "other.py").write_text("X = 2\n")
        commit_all(cand, self.env, "fix and more")
        code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertIs(d["candidateGreen"], True, out)
        self.assertIs(d["scopeOk"], False, out)
        self.assertIn("src/other.py", d["changed"])
        self.assertIs(d["PASS"], False)

    def test_grade_pin_red_then_green_with_the_accepted_fix_passes(self):
        pack, c = make_pack(self.root, self.env)
        cand = self.candidate(c, "pin-good")
        (cand / "tests" / "test_pin.py").write_text(
            "import unittest\nfrom src.mod import add\n\n\nclass P(unittest.TestCase):\n    def test_sum(self):\n        self.assertEqual(add(2, 3), 5)\n")
        commit_all(cand, self.env, "pin")
        code, d, out = grade(pack / "manifest.json", "pin", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual(d["testFiles"], ["tests/test_pin.py"])
        self.assertEqual((d["redAtHead"], d["greenWithFix"], d["srcClean"], d["lint"], d["committed"]), (True, True, True, "ok", True), out)
        self.assertIs(d["PASS"], True)
        self.assertEqual((cand / "src" / "mod.py").read_text(), "def add(a, b):\n    return a - b\n")

    def test_grade_pin_source_touching_candidate_fails(self):
        pack, c = make_pack(self.root, self.env)
        cand = self.candidate(c, "pin-src")
        (cand / "tests" / "test_pin.py").write_text(
            "import unittest\nfrom src.mod import add\n\n\nclass P(unittest.TestCase):\n    def test_sum(self):\n        self.assertEqual(add(2, 3), 5)\n")
        (cand / "src" / "other.py").write_text("X = 3\n")
        commit_all(cand, self.env, "pin and a source edit")
        code, d, out = grade(pack / "manifest.json", "pin", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertIs(d["srcClean"], False, out)
        self.assertEqual(d["srcTouched"], ["src/other.py"])
        self.assertIs(d["PASS"], False)

    def test_grade_pin_green_at_the_base_fails(self):
        pack, c = make_pack(self.root, self.env)
        cand = self.candidate(c, "pin-weak")
        (cand / "tests" / "test_pin.py").write_text(  # passes at the base: it does not express the rule
            "import unittest\nfrom src.mod import add\n\n\nclass P(unittest.TestCase):\n    def test_zero(self):\n        self.assertEqual(add(0, 0), 0)\n")
        commit_all(cand, self.env, "pin")
        code, d, out = grade(pack / "manifest.json", "pin", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual((d["redAtHead"], d["greenWithFix"]), (False, True), out)
        self.assertIs(d["PASS"], False)

    def test_grade_reads_a_counting_report(self):
        pack, c = make_pack(self.root, self.env, report="vitest-json")
        cand = self.candidate(c, "pin-json")
        (cand / "tests" / "test_pin.py").write_text(
            "import unittest\nfrom src.mod import add\n\n\nclass P(unittest.TestCase):\n    def test_sum(self):\n        self.assertEqual(add(2, 3), 5)\n")
        commit_all(cand, self.env, "pin")
        code, d, out = grade(pack / "manifest.json", "pin", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual((d["atHead"]["failed"], d["withAcceptedFix"]["passed"]), (1, 1), out)
        self.assertIs(d["PASS"], True)

    def test_grade_refuses_a_checkout_inside_the_pack_and_a_bad_task(self):
        pack, c = make_pack(self.root, self.env)
        inside = pack / "cand"
        self.assertEqual(checkout(c["repo"], c["base"], inside, self.env).returncode, 0)
        code, d, out = grade(pack / "manifest.json", "pin", inside, self.env)
        self.assertEqual(code, 2, out)
        self.assertIn("pack", out)
        code, d, out = grade(pack / "manifest.json", "review", self.candidate(c, "x"), self.env)
        self.assertEqual(code, 2, out)
        code, d, out = grade(pack / "manifest.json", "fix", self.root / "missing", self.env)
        self.assertEqual(code, 3, out)
        self.assertIn("error", d)


class TemplateAndPrompts(unittest.TestCase):
    def test_protocol_template_parses_and_carries_every_key(self):
        doc = json.loads((KIT / "protocol.template.json").read_text())
        self.assertEqual(set(doc), PROTOCOL_KEYS)
        self.assertIn("run 3", doc["_lineage"])
        self.assertIsNone(doc["run_id"], "the run id is recorded at the launch, never before")
        self.assertEqual(doc["amendments"], [])
        self.assertEqual((doc["runs_per_profile_per_task"], doc["retry_limit"]), (1, 0))
        self.assertEqual([c["id"] for c in doc["cases"]], ["pin", "fix", "review"])
        for c in doc["cases"]:
            self.assertTrue({"id", "category", "tier", "base", "grading", "pass_rule"} <= set(c), c["id"])
        self.assertEqual(doc["cases"][0]["category"], "pin-tests")  # the host category, not a protocol label (run 3 A-2)
        self.assertIn("CRLF", doc["source_hash_convention"])
        self.assertEqual(doc["classification"]["prongs"], ["holds", "reachable", "forbidden"])
        jp = doc["judging_profile"]
        self.assertTrue({"key", "model", "effort", "qualification", "limitation"} <= set(jp))
        self.assertIn("judging profile not independently qualified", jp["limitation"])
        rot = doc["relayed_operator_text"]
        self.assertIsNone(rot["text"])
        self.assertIn("relays no operator text", rot["statement"])
        self.assertTrue({"mode", "prices_source", "rates_per_mtok", "statement"} <= set(doc["accounting"]))
        self.assertTrue({"pack", "pack_version", "kind", "manifest_sha256"} <= set(doc["subject_pack"]))
        self.assertTrue({"before", "after"} <= set(doc["usage_window_readings"]))

    def test_the_fixture_protocol_is_a_filled_template(self):
        tpl = json.loads((KIT / "protocol.template.json").read_text())
        filled = json.loads((FIX / "protocol.json").read_text())
        self.assertEqual(set(filled) - {"_comment"}, set(tpl) - {"_lineage"})
        for key in ("subject_pack", "accounting", "classification", "judging_profile", "usage_window_readings"):
            self.assertEqual(set(filled[key]), set(tpl[key]), key)
        self.assertNotIn("{{", json.dumps(filled), "a placeholder left in a filled protocol")

    def test_classification_names_three_prongs_the_s4_rule_and_the_rules_runs_produced(self):
        text = (KIT / "classification.md").read_text()
        definition = md_section(text, "Definition")
        for word in ("holds at HEAD", "reachable", "admissible", "forbids"):
            self.assertIn(word, definition)
        self.assertIn("at most S4", definition)
        rules = md_section(text, "Rules the runs produced")
        self.assertIn("G-1", rules)
        self.assertIn("G-2", rules)

    def test_prompts_carry_their_output_schema_and_placeholders(self):
        for name, required in (("grader", {"truth", "others", "falseBlocking", "copiedFromHistory", "notes"}),
                               ("lens", {"claim", "lens", "holds", "reachable", "forbidden", "severity", "scratchTest", "why"}),
                               ("cluster", {"clusters"})):
            text = (KIT / f"{name}.prompt.md").read_text()
            self.assertTrue(text.startswith("<!-- Lineage:"), name)
            schema = md_schema(text)
            self.assertEqual(schema["type"], "object", name)
            self.assertEqual(set(schema["required"]), required, name)
            used = set(re.findall(r"\{\{([a-z_]+)\}\}", md_section(text, "Prompt")))
            self.assertTrue(used, f"{name}: no {{{{placeholder}}}} in the prompt")
            documented = set(re.findall(r"^- `\{\{([a-z_]+)\}\}`", md_section(text, "Placeholders"), re.M))
            self.assertEqual(used - documented, set(), f"{name}: placeholders used but not documented")

    def test_lens_votes_real_only_on_all_three_prongs(self):
        text = (KIT / "lens.prompt.md").read_text()
        schema = md_schema(text)
        self.assertEqual(schema["properties"]["forbidden"]["type"], "boolean")
        self.assertIn("forbidden", schema["required"])
        self.assertIn("a lens votes real only when holds is true, reachable is not no, and forbidden is true", md_section(text, "Vote rule"))
        for lens in ("reproduce", "reachability", "refute"):
            self.assertTrue(md_section(text, f"Lens: {lens}"), lens)
        self.assertIn("{{classification}}", md_section(text, "Prompt"))
        self.assertIn("{{classification}}", md_section((KIT / "grader.prompt.md").read_text(), "Prompt"))

    def test_cluster_prompt_has_the_assignment_variant(self):
        text = (KIT / "cluster.prompt.md").read_text()
        self.assertIn("{{existing_clusters}}", md_section(text, "Assignment prompt"))


# K3: no provider call, no credential, no host path, no session or run id anywhere in the kit.
HYGIENE = [
    ("an absolute host path", re.compile(r"(?<![\w.~$}{-])/(?:home|tmp|root|Users|var|opt|mnt|srv|versions|private)/")),
    ("a Windows drive path", re.compile(r"\b[A-Za-z]:\\\\")),
    ("a session id", re.compile(r"session_")),
    ("a 32-hex id", re.compile(r"\b[0-9a-f]{32}\b")),
    ("a workflow run id", re.compile(r"\bwf_[0-9a-f]{6,}")),
    ("a MoonAliza name", re.compile(r"(?i)moonaliza|github-oauth")),
    ("an environment read", re.compile(r"os\.environ|getenv|process\.env|\$\{?[A-Z_]*(?:KEY|TOKEN|SECRET)")),
    ("a provider call", re.compile(r"(?i)urllib|http\.client|import requests|api\.anthropic|api\.openai|fetch\(")),
]


class Hygiene(unittest.TestCase):
    def scan(self, root: Path):
        hits = []
        for f in sorted(root.rglob("*")):
            if not f.is_file() or "__pycache__" in f.parts:
                continue  # a bytecode cache is not kit content (and is git-ignored)
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if n == 1 and line.startswith("#!"):
                    continue  # the interpreter line
                if "EXAMPLE:" in line:
                    continue  # an example clearly marked as one
                bare = re.sub(r"\{\{[^}]*\}\}", "", line)  # a {{placeholder}} may name anything
                for what, rx in HYGIENE:
                    if rx.search(bare):
                        hits.append(f"{f.relative_to(root)}:{n}: {what}: {line.strip()[:120]}")
        return hits

    def test_the_kit_has_no_host_path_session_id_key_or_provider_call(self):
        self.assertTrue(KIT.is_dir())
        self.assertEqual(self.scan(KIT), [])

    def test_the_scan_catches_each_kind(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.md"
            samples = ["see /" + "home/user/x", "id session" + "_01ABC", "run " + "a" * 32, "run " + "wf_" + "4e9ef48d-066",
                       "Moon" + "Aliza", "os." + "environ['X']", "fetch" + "(url)", "C:" + "\\\\Users"]
            bad.write_text("\n".join(["# x"] + samples + ["{{/" + "tmp/ok}}", "EXAMPLE: /" + "tmp/ok"]) + "\n")
            self.assertEqual(len(self.scan(Path(d))), len(samples))


if __name__ == "__main__":
    unittest.main(verbosity=2)
