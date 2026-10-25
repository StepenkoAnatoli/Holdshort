#!/usr/bin/env python3
"""tools/calibration: the calibration kit (docs/proposals/calibration-first-onboarding.md, Items 2-4.2).

Hermetic: every test runs on the synthetic fixtures under tests/fixtures/calibration/ or on temporary git
repositories it builds itself; nothing here calls a provider, reads a credential or needs the network.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
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
    env.update(GIT_CONFIG_GLOBAL=str(cfg), GIT_CONFIG_NOSYSTEM="1")
    # the bytecode cache stays ON, as in a host's shell: grade.sh must grade correctly with it (review finding F1)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    env.pop("PYTHONPYCACHEPREFIX", None)
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
    manifest = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
    manifest.update(accepted_fix=accepted, commands={"test": test_cmd, "test_report": report, "lint": "python3 -m py_compile {files}", "timeout_seconds": 120})
    for case in ("pin", "fix"):
        manifest["cases"][case]["base"] = base
    manifest["cases"]["review"]["base"] = base
    (pack / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return pack, {"base": base, "accepted": accepted, "repo": repo}


def show_bytes(c: dict, rev: str, path: str = "src/mod.py") -> bytes:
    return subprocess.run(["git", "-C", str(c["repo"]), "show", f"{rev}:{path}"], capture_output=True, check=True).stdout


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


def fill_template(cfg: dict, template: str | None = None) -> str:
    """The README's fill step: the run config into `null // {{RUN}}`, the prompt files into `null // {{PROMPTS}}`
    (`template`: another template's text, e.g. an earlier commit's, in place of the kit's run.template.js)."""
    text = template if template is not None else (KIT / "run.template.js").read_text(encoding="utf-8")
    prompts = {n: (KIT / f"{n}.prompt.md").read_text(encoding="utf-8") for n in ("grader", "lens", "cluster")}
    prompts["classification"] = (KIT / "classification.md").read_text(encoding="utf-8")
    assert text.count("null // {{RUN}}") == 1 and text.count("null // {{PROMPTS}}") == 1
    return text.replace("null // {{RUN}}", json.dumps(cfg)).replace("null // {{PROMPTS}}", json.dumps(prompts))


def run_config(root: Path, **host) -> dict:
    cfg = {"manifest": json.loads((FIX / "manifest.json").read_text(encoding="utf-8")), "protocol": json.loads((FIX / "protocol.json").read_text(encoding="utf-8")),
           "host": {"checkout_root": str(root / "checkouts"), "pack_dir": str(root / "pack"), "adjudication_checkout": str(root / "checkouts" / "cal-adjudication"),
                    "run_tag": "cal", "commit_command": "git commit", "supplementary": None}}
    cfg["host"].update(host)
    return cfg


def canned_outputs(forbidden=(True, True, False)) -> dict:
    results = {}
    for line in (FIX / "journal.jsonl").read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e["type"] == "result":
            results[e["agentId"]] = e["result"]
    cluster = copy.deepcopy(results["a05"])
    cluster["clusters"][0]["members"] = ["alpha-low R-3", "beta-max R-3"]
    cluster["clusters"][0]["graderClassifications"] = ["false", "false"]
    lens = dict(results["a06"])
    return {"pin": results["a01"], "fix": results["a02"], "review": results["a03"], "grade": results["a04"], "cluster": cluster,
            "lens": lens, "forbidden": dict(zip(("reproduce", "reachability", "refute"), forbidden))}


STUB_HARNESS = """
const CANNED = __CANNED__;
const calls = [];
globalThis.agent = async (prompt, opts) => {
  calls.push({ prompt, ...opts });
  const kind = opts.label.split(':')[0];
  if (kind === 'lens') { const lens = opts.label.split(':')[2]; return { ...CANNED.lens, lens, forbidden: CANNED.forbidden[lens] }; }
  return JSON.parse(JSON.stringify(CANNED[kind]));
};
globalThis.pipeline = async (items, ...stages) => {
  const out = [];
  for (const item of items) { let v = await stages[0](item); for (const s of stages.slice(1)) v = await s(v, item); out.push(v); }
  return out;
};
globalThis.parallel = async (fns) => Promise.all(fns.map((f) => f()));
globalThis.log = () => {};
let result = null, error = null;
try { result = await (async () => {
__BODY__
})(); } catch (e) { error = String((e && e.message) || e); }
console.log(JSON.stringify({ calls, result, error }));
"""


def execute_template(cfg: dict, root: Path, canned: dict | None = None, template: str | None = None) -> dict:
    """Run the filled template under node with stub harness globals (the harness wraps a script body the same way)."""
    body = fill_template(cfg, template).replace("export const meta", "const meta", 1)
    src = STUB_HARNESS.replace("__CANNED__", json.dumps(canned or canned_outputs())).replace("__BODY__", body)
    path = root / "filled-run.mjs"
    path.write_text(src)
    p = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise AssertionError(f"node exit {p.returncode}: {p.stderr[-2000:]}")
    return json.loads(p.stdout.strip().splitlines()[-1])


def results_folder(root: Path, run: Path | None = None) -> Path:
    out = root / "docs" / "evidence" / "2026-01-01" / "fixture-host-calibration-1"
    p = build(out, run=run)
    assert p.returncode == 0, p.stderr
    shutil.copy(FIX / "protocol.json", out / "protocol.json")
    return out


# The shared synthetic subject pack (tools/calibration/subject-pack/shared/): its trees, the script that builds its
# repository, its manifest. The trees are the subject a candidate reads, so they carry no lineage header and are listed
# by the pack's own README rather than the kit's.
PACK = KIT / "subject-pack" / "shared"
TREES = ("review", "base", "accepted")


def pack_files(root: Path) -> list[str]:
    """Every file of a pack directory, relative and with '/', leaving out bytecode caches and a built `repo`."""
    out = []
    for f in sorted(root.rglob("*"), key=lambda f: f.relative_to(root).parts):  # by name, with case, on every host
        rel = f.relative_to(root)
        if f.is_file() and "__pycache__" not in rel.parts and rel.parts[0] != "repo":
            out.append(rel.as_posix())
    return out


def in_shared_trees(f: Path) -> bool:
    return (PACK / "trees") in f.parents


def in_shared_pack(f: Path) -> bool:
    """A pack file other than its README: the pack's README lists it, not the kit's."""
    return PACK in f.parents and f != PACK / "README.md"


def build_shared(dest: Path, env: dict, target: Path | None = None) -> tuple[subprocess.CompletedProcess, dict]:
    """A copy of the shared pack at dest with its repository built by make-repo.sh (default: `repo` beside the manifest)."""
    if not dest.exists():
        shutil.copytree(PACK, dest, ignore=shutil.ignore_patterns("__pycache__", "repo"))
    target = target or dest / "repo"
    p = subprocess.run(["bash", str(dest / "make-repo.sh"), str(target)], env=env, capture_output=True, text=True, timeout=120)
    ids = {}
    for line in p.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in {f"{t}0" for t in TREES}:
            ids[parts[0]] = parts[1]
    return p, ids


def tree_files(commit_dir_or_repo: Path, env: dict, rev: str | None = None) -> dict[str, bytes]:
    """The files of a trees/<name> directory, or of commit rev in a repository, as {path: bytes}."""
    if rev is None:
        return {f: (commit_dir_or_repo / f).read_bytes() for f in pack_files(commit_dir_or_repo)}
    names = sh(["git", "ls-tree", "-r", "-z", "--name-only", rev], commit_dir_or_repo, env).stdout.split("\0")
    return {n: subprocess.run(["git", "-C", str(commit_dir_or_repo), "show", f"{rev}:{n}"], capture_output=True, check=True, env=env).stdout
            for n in names if n}


def run_pack_tests(cand: Path, env: dict, *files: str) -> subprocess.CompletedProcess:
    """The pack's own test command (manifest commands.test: python3 tests/run.py FILE...), run with this interpreter."""
    return subprocess.run([sys.executable, "tests/run.py", *files], cwd=cand, env=env, capture_output=True, text=True, timeout=120)


PROMISE = ("read_bounded accepts any iterable whose items are bytes-like (bytes, bytearray, memoryview) or str (encoded as UTF-8), "
           "never raises on such input, and never returns more than limit bytes")


def text_hash(path: Path) -> str:
    """The protocol's source hash convention (README step 2): SHA-256 of the UTF-8 text with CRLF and CR read as LF."""
    import hashlib
    return hashlib.sha256(path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n").encode()).hexdigest()


def strings(v):
    """Every string in a JSON value, keys included."""
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for k, x in v.items():
            yield k
            yield from strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from strings(x)


class Observations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def built(self, *extra, run=None):
        p = build(self.out, *extra, run=run)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads((self.out / "observations.json").read_text(encoding="utf-8")), json.loads((self.out / "scores.json").read_text(encoding="utf-8"))

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
        run = json.loads((FIX / "run.json").read_text(encoding="utf-8"))
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
        table = (self.out / "results-table.md").read_text(encoding="utf-8")
        self.assertIn("| alpha-low | PASS | PASS | yes | - |", table)
        self.assertIn("| C-1 |", (self.out / "clusters.md").read_text(encoding="utf-8"))
        self.assertIn("7,200", (self.out / "tokens-and-estimates.md").read_text(encoding="utf-8"))

    def test_a_lens_record_without_forbidden_cannot_carry_a_three_prong_pass(self):
        run = json.loads((FIX / "run.json").read_text(encoding="utf-8"))
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
        run = json.loads((FIX / "run.json").read_text(encoding="utf-8"))
        run["result"]["adjudications"][0]["lenses"][1]["forbidden"] = False  # now one lens of three says forbidden
        path = Path(self.tmp.name) / "run-one-forbidden.json"
        path.write_text(json.dumps(run))
        _, s = self.built(run=path)
        self.assertIs(s["profiles"]["beta-max"]["review"]["would_fail_under_three_prong"], True)

    def test_void_cell_replaced_by_the_supplementary_run(self):
        tmp = Path(self.tmp.name)
        fix_result = json.loads((FIX / "journal.jsonl").read_text(encoding="utf-8").splitlines()[-7])["result"]
        (tmp / "j2.jsonl").write_text("\n".join(json.dumps(e) for e in [
            {"type": "launched"}, {"type": "started", "agentId": "b01", "key": "b01", "label": "fix:alpha-low", "phase": "Fix"},
            {"type": "result", "agentId": "b01", "key": "b01", "result": fix_result}]) + "\n")
        (tmp / "r2.json").write_text(json.dumps({"runId": "run-supp-1", "workflowProgress": [
            {"type": "workflow_agent", "label": "fix:alpha-low", "agentId": "b01", "model": "model-alpha-1", "state": "done", "tokens": 1800, "durationMs": 1, "attempt": 1}],
            "result": {"results": [], "clusters": {"clusters": []}, "adjudications": []}}))
        obs, s = self.built("--void", "fix:alpha-low", "--supplementary", str(tmp / "j2.jsonl"), str(tmp / "r2.json"))
        self.assertEqual(obs["alpha-low"]["usage"]["fix"]["run"], "run-supp-1")
        self.assertEqual(obs["alpha-low"]["usage"]["fix"]["tokens"], 1800)
        void = json.loads((self.out / "void-cells.json").read_text(encoding="utf-8"))
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


def makes_links(make) -> bool:
    """Whether make(link, target) leaves a symlink on this host: Windows needs a privilege (or Developer Mode) for one,
    and without it Git Bash's `ln -s` copies the target instead."""
    with tempfile.TemporaryDirectory() as d:
        link, target = Path(d) / "link", Path(d) / "target"
        target.mkdir()
        try:
            make(link, target)
        except OSError:
            return False
        return link.is_symlink()


NEEDS_PY_LINKS = unittest.skipUnless(makes_links(lambda link, target: link.symlink_to(target)),
                                     "this host cannot make a symlink (Windows without the privilege or Developer Mode)")
NEEDS_SH_LINKS = unittest.skipUnless(
    makes_links(lambda link, target: subprocess.run(["bash", "-c", 'ln -s "$1" "$2"', "ln", str(target), str(link)], capture_output=True, timeout=60)),
    "bash's ln -s makes no symlink on this host (Git Bash without the privilege copies the directory)")


def repo_holding(path: Path) -> Path | None:
    """The nearest of path's real path and its ancestors that holds a .git entry (a directory, or the file a linked
    worktree has) or is a git directory (HEAD, objects/ and refs/: a bare repository), as historyless-checkout.sh --link
    looks; None when there is none."""
    p = Path(path).resolve()
    for d in (p, *p.parents):
        if (d / ".git").exists() or (d / ".git").is_symlink() or ((d / "HEAD").is_file() and (d / "objects").is_dir() and (d / "refs").is_dir()):
            return d
    return None


# A test that needs --link to accept a directory it made under the temporary directory refuses to run when that
# directory is inside a repository: the script would refuse the link for that reason, not the test's (IC4-1).
TEMP_IN_REPO = "the temporary directory {} is inside the git repository {}: set TEMP outside any repository to run this test"


def native_links(env: dict) -> dict:
    """env with Git Bash's `ln -s` making a native symlink (by default it copies the target). Only MSYS programs read
    MSYS, so other hosts are unaffected."""
    msys = env.get("MSYS", "")
    return env if "winsymlinks" in msys else {**env, "MSYS": f"{msys} winsymlinks:nativestrict".strip()}


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

    @NEEDS_SH_LINKS
    def test_historyless_checkout_links_only_on_request_and_hides_the_links(self):
        pack, c = make_pack(self.root, self.env)
        deps = self.root / "installed" / "deps"  # installed outside the pack (F2)
        deps.mkdir(parents=True)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        p = checkout(c["repo"], c["base"], self.root / "plain", self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse((self.root / "plain" / "deps").exists())
        p = checkout(c["repo"], c["base"], self.root / "linked", self.env, "--pack", str(pack), "--link", f"deps={deps}")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((self.root / "linked" / "deps").is_symlink())
        self.assertEqual((self.root / "linked" / "deps").resolve(), deps.resolve())
        self.assertEqual(sh(["git", "status", "--porcelain"], self.root / "linked", self.env).stdout.strip(), "")

    def test_historyless_checkout_refuses_a_link_that_reaches_the_pack(self):
        # F2: a link into the pack (or its repository) hands the candidate a path to the accepted fix
        pack, c = make_pack(self.root, self.env)
        (c["repo"] / "node_modules").mkdir()
        shares, bare = "holds the accepted fix", "--link takes NAME=DIR"
        cases = [
            (shares, "--pack", str(pack), "--link", f"node_modules={c['repo'] / 'node_modules'}"),  # inside the pack
            (shares, "--link", f"node_modules={c['repo'] / 'node_modules'}"),  # inside SOURCE_REPO, with no --pack
            (shares, "--pack", str(pack), "--link", f"up={self.root}"),  # a directory holding the pack
            (shares, "--pack", str(pack), "--link", "node_modules=/"),  # N2: the root holds everything, the pack too
            (shares, "--link", "node_modules=/"),  # N2: and SOURCE_REPO, with no --pack
            (shares, "--pack", str(pack), "--link", "node_modules=//"),  # N3: bash keeps a leading '//' from pwd -P; it is the root
            (shares, "--link", "node_modules=//"),  # N3: and with no --pack
            *([(shares, "--pack", "/" + str(pack), "--link", f"node_modules={pack / 'repo'}")]  # N3: the pack spelled //abs/... still holds the link
              if str(pack).startswith("/") else []),  # (a Windows path has no //abs spelling: there '//' starts a UNC name)
            (bare, "--pack", str(pack), "--link", "node_modules"),  # no directory: the old form linked into SOURCE_REPO
        ]
        for i, (reason, *flags) in enumerate(cases):
            target = self.root / f"refused-{i}"
            p = checkout(c["repo"], c["base"], target, self.env, *flags)
            self.assertEqual(p.returncode, 2, f"{flags}: {p.stdout}{p.stderr}")
            self.assertIn(reason, p.stderr, flags)
            self.assertFalse(target.exists(), flags)

    @NEEDS_PY_LINKS
    def test_historyless_checkout_refuses_a_symlink_that_resolves_into_the_pack(self):
        pack, c = make_pack(self.root, self.env)
        (c["repo"] / "node_modules").mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "via").symlink_to(c["repo"] / "node_modules")  # outside by name, inside by its real path
        target = self.root / "refused"
        p = checkout(c["repo"], c["base"], target, self.env, "--pack", str(pack), "--link", f"node_modules={outside / 'via'}")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("holds the accepted fix", p.stderr)
        self.assertFalse(target.exists())

    def assert_link_refused(self, c, d, reason, *flags, name="node_modules"):
        """--link name=d is refused with exit 2 and the reason, and nothing is made: not the target, not its parent."""
        parent = self.root / f"refused-{len(list(self.root.glob('refused-*')))}"
        target = parent / "cand"
        p = checkout(c["repo"], c["base"], target, self.env, *flags, "--link", f"{name}={d}")
        self.assertEqual(p.returncode, 2, f"{d} {flags}: {p.stdout}{p.stderr}")
        self.assertIn(reason, p.stderr, f"{d} {flags}")
        self.assertFalse(parent.exists(), f"{d} {flags}")

    def other_repositories(self) -> tuple[Path, Path, Path]:
        """Repositories that are not the pack: a work tree with a commit, a linked worktree of it (its .git is a file)
        and a bare repository, each beside the pack under the temporary directory."""
        other, wt, bare = self.root / "other", self.root / "wt", self.root / "bare.git"
        (other / "node_modules" / "pkg").mkdir(parents=True)
        (other / "README.md").write_text("other\n")
        sh(["git", "init", "-q"], other, self.env)
        commit_all(other, self.env, "other")
        sh(["git", "worktree", "add", "-q", str(wt)], other, self.env)
        (wt / "node_modules").mkdir()
        sh(["git", "init", "-q", "--bare", str(bare)], self.root, self.env)
        self.assertTrue((wt / ".git").is_file())
        self.assertFalse((bare / ".git").exists())
        return other, wt, bare

    @NEEDS_PY_LINKS
    def test_historyless_checkout_refuses_a_link_inside_a_git_repository(self):
        # IC4-1: a dependency tree inside any repository reaches that repository's files and history through '..'
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        other, wt, bare = self.other_repositories()
        inside = "is inside the git repository"
        for d in (other,  # the directory is a repository's work tree
                  other / "node_modules", other / "node_modules" / "pkg",  # a directory in a work tree, at any depth
                  other / ".git" / "info",  # a directory in a .git directory
                  wt / "node_modules",  # a linked worktree, whose .git is a file
                  bare, bare / "refs"):  # a bare repository, and a directory in one
            for flags in (("--pack", str(pack)), ()):  # with and without --pack
                self.assert_link_refused(c, d, inside, *flags)
        self.assert_link_refused(c, other / "node_modules", "lets the checkout reach that repository's history and files through '..'",
                                 "--pack", str(pack))
        # outside every repository the link is made as before
        outside = self.root / "installed" / "node_modules"
        outside.mkdir(parents=True)
        target = self.root / "accepted" / "cand"
        p = checkout(c["repo"], c["base"], target, native_links(self.env), "--pack", str(pack), "--link", f"node_modules={outside}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue((target / "node_modules").is_symlink())
        self.assertEqual((target / "node_modules").resolve(), outside.resolve())
        self.assertEqual(sh(["git", "status", "--porcelain"], target, self.env).stdout.strip(), "")

    @NEEDS_PY_LINKS
    def test_historyless_checkout_checks_the_symlinks_at_the_top_of_a_linked_directory(self):
        # a symlink among DIR's own entries is checked like DIR: it must not reach the pack or a repository
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        other, wt, bare = self.other_repositories()
        free = self.root / "free"  # a directory outside every repository
        free.mkdir()
        cases = [
            ("lib", other / "node_modules", "is inside the git repository"),  # a directory in a work tree
            ("readme", other / "README.md", "is inside the git repository"),  # a file in a work tree
            (".hidden", wt, "is inside the git repository"),  # a dot entry, to a linked worktree
            ("objs", bare / "objects", "is inside the git repository"),  # into a bare repository
            ("src", c["repo"] / "src", "holds the accepted fix"),  # into the pack's repository
            ("gone", self.root / "missing", "does not resolve"),  # a dangling link: refused, not skipped
        ]
        for i, (entry, to, reason) in enumerate(cases):
            deps = self.root / f"deps-{i}"
            (deps / "plain").mkdir(parents=True)
            (deps / entry).symlink_to(to)
            for flags in (("--pack", str(pack)), ()):
                self.assert_link_refused(c, deps, reason, *flags)
        # a chain of file links through a linked directory: the kernel follows sub before the '..' in b's target, so a
        # reaches the repository far/y, though DIR holds a y of its own (outside every repository) that a '..' taken by
        # spelling would reach instead
        far = self.root / "far"
        (far / "x").mkdir(parents=True)
        (far / "y").mkdir()
        sh(["git", "init", "-q"], far / "y", self.env)
        (far / "y" / "file").write_text("in a repository\n")
        (far / "x" / "b").symlink_to(Path("..") / "y" / "file")
        deps = self.root / "deps-chain"
        (deps / "y").mkdir(parents=True)
        (deps / "sub").symlink_to(far / "x", target_is_directory=True)
        (deps / "a").symlink_to(Path("sub") / "b")
        self.assertEqual((deps / "a").read_text(), "in a repository\n")
        self.assertIsNone(repo_holding(far / "x"))
        # and a link whose own target walks '..' after a linked directory (sub/../y/file): bash reads it through sub,
        # as a POSIX kernel does (Windows' own API takes that '..' by spelling, so Python is not asked here; nor is
        # bash given a C:\ spelling, which Git Bash hands to that API: it reads c from inside the directory)
        dotdot = self.root / "deps-dotdot"
        (dotdot / "y").mkdir(parents=True)
        (dotdot / "sub").symlink_to(far / "x", target_is_directory=True)
        (dotdot / "c").symlink_to(Path("sub") / ".." / "y" / "file")
        read = subprocess.run(["bash", "-c", 'cd -- "$1" && cat -- c', "cat", str(dotdot)], capture_output=True, text=True, timeout=60)
        self.assertEqual(read.stdout, "in a repository\n", read.stderr)
        for d in (deps, dotdot):
            for flags in (("--pack", str(pack)), ()):
                self.assert_link_refused(c, d, "far/y; a dependency tree inside a repository", *flags)
        # links that stay inside DIR (a pnpm-style store) or reach a directory outside every repository are fine
        deps = self.root / "deps-ok"
        (deps / ".store" / "pkg").mkdir(parents=True)
        (deps / "pkg").symlink_to(deps / ".store" / "pkg")
        (deps / "free").symlink_to(free)
        target = self.root / "accepted" / "cand"
        p = checkout(c["repo"], c["base"], target, native_links(self.env), "--pack", str(pack), "--link", f"node_modules={deps}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual((target / "node_modules").resolve(), deps.resolve())

    def test_historyless_checkout_refuses_an_existing_target_and_one_inside_the_pack(self):
        pack, c = make_pack(self.root, self.env)
        (self.root / "taken").mkdir()
        p = checkout(c["repo"], c["base"], self.root / "taken", self.env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        p = checkout(c["repo"], c["base"], pack / "cand", self.env, "--pack", str(pack))
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("pack", p.stderr)
        self.assertFalse((pack / "cand").exists())
        p = checkout(c["repo"], c["base"], self.root / "under-root", self.env, "--pack", "/")  # N2: every target is inside /
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("is inside the pack /", p.stderr)
        p = checkout(c["repo"], c["base"], self.root / "under-root-2", self.env, "--pack", "//")  # N3: '//' is the root too
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("is inside the pack /", p.stderr)
        self.assertFalse((self.root / "under-root-2").exists())
        p = checkout(c["repo"], c["base"], pack / "cand-2", self.env, "--pack", "/" + str(pack))  # N3: a //-spelled pack
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("pack", p.stderr)
        self.assertFalse((pack / "cand-2").exists())
        self.assertFalse((self.root / "under-root").exists())
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
        self.assertEqual((cand / "src" / "mod.py").read_text(encoding="utf-8"), "def add(a, b):\n    return a - b\n")

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

    def test_grade_a_same_size_swap_with_the_bytecode_cache_on(self):
        # F1: the base (a - b) and the accepted fix (a + b) have the same size; a runner that caches by mtime and size
        # (Python's __pycache__) must still run the version each step swapped in. The cache is warmed first.
        self.assertNotIn("PYTHONDONTWRITEBYTECODE", self.env)
        pack, c = make_pack(self.root, self.env)
        self.assertEqual(len(show_bytes(c, c["base"])), len(show_bytes(c, c["accepted"])))
        fix = self.candidate(c, "fix-same-size")
        self.fix_like_the_accepted_one(fix)
        commit_all(fix, self.env, "fix")
        pin = self.candidate(c, "pin-same-size")
        (pin / "tests" / "test_pin.py").write_text(
            "import unittest\nfrom src.mod import add\n\n\nclass P(unittest.TestCase):\n    def test_sum(self):\n        self.assertEqual(add(2, 3), 5)\n")
        commit_all(pin, self.env, "pin")
        for cand in (fix, pin):
            sh([sys.executable, "-m", "unittest", "tests/test_mod.py"], cand, self.env, check=False)  # warm the cache
            self.assertTrue(list((cand / "src" / "__pycache__").glob("mod.*.pyc")), "the bytecode cache is on")
        for run in range(3):
            code, d, out = grade(pack / "manifest.json", "fix", fix, self.env)
            self.assertEqual(code, 0, out)
            self.assertEqual((d["candidateGreen"], d["guardRed"], d["acceptedPinGreen"]), (True, True, True), f"run {run}: {out}")
            self.assertIs(d["PASS"], True, out)
            code, d, out = grade(pack / "manifest.json", "pin", pin, self.env)
            self.assertEqual(code, 0, out)
            self.assertEqual((d["redAtHead"], d["greenWithFix"]), (True, True), f"run {run}: {out}")
            self.assertIs(d["PASS"], True, out)

    def test_grade_gives_every_swapped_version_its_own_mtime_and_puts_the_original_back(self):
        # F1, deterministic: the test command logs the source's mtime at each run. Each run must see an mtime at least
        # two seconds from every other run's (a cache keyed on whole seconds and size cannot confuse them), and the
        # original mtime is back after the grade.
        pack, c = make_pack(self.root, self.env)
        log = self.root / "mtimes.log"
        m = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        m["commands"]["test"] = (f"python3 -c \"import os; print(os.stat('src/mod.py').st_mtime_ns)\" >> {shlex.quote(str(log))}; "
                                 + m["commands"]["test"])
        (pack / "manifest.json").write_text(json.dumps(m, indent=1))
        for task in ("fix", "pin"):
            cand = self.candidate(c, f"{task}-mtime")
            if task == "fix":
                self.fix_like_the_accepted_one(cand)
            else:
                (cand / "tests" / "test_pin.py").write_text(
                    "import unittest\nfrom src.mod import add\n\n\nclass P(unittest.TestCase):\n    def test_sum(self):\n        self.assertEqual(add(2, 3), 5)\n")
            commit_all(cand, self.env, task)
            before = (cand / "src" / "mod.py").stat().st_mtime_ns
            log.write_text("")
            code, d, out = grade(pack / "manifest.json", task, cand, self.env)
            self.assertEqual(code, 0, out)
            seen = [int(x) for x in log.read_text(encoding="utf-8").split()]
            self.assertEqual(len(seen), 3 if task == "fix" else 2, out)
            for i, a in enumerate(seen):
                for b in seen[i + 1:]:
                    self.assertGreaterEqual(abs(a - b), 2_000_000_000, f"{task}: mtimes {seen}")
            self.assertEqual((cand / "src" / "mod.py").stat().st_mtime_ns, before, task)
            self.assertIs(d["restored"], True, out)

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
        doc = json.loads((KIT / "protocol.template.json").read_text(encoding="utf-8"))
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
        tpl = json.loads((KIT / "protocol.template.json").read_text(encoding="utf-8"))
        filled = json.loads((FIX / "protocol.json").read_text(encoding="utf-8"))
        self.assertEqual(set(filled) - {"_comment"}, set(tpl) - {"_lineage"})
        for key in ("subject_pack", "accounting", "classification", "judging_profile", "usage_window_readings"):
            self.assertEqual(set(filled[key]), set(tpl[key]), key)
        self.assertNotIn("{{", json.dumps(filled), "a placeholder left in a filled protocol")

    def test_classification_names_three_prongs_the_s4_rule_and_the_rules_runs_produced(self):
        text = (KIT / "classification.md").read_text(encoding="utf-8")
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
            text = (KIT / f"{name}.prompt.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("<!-- Lineage:"), name)
            schema = md_schema(text)
            self.assertEqual(schema["type"], "object", name)
            self.assertEqual(set(schema["required"]), required, name)
            used = set(re.findall(r"\{\{([a-z_]+)\}\}", md_section(text, "Prompt")))
            self.assertTrue(used, f"{name}: no {{{{placeholder}}}} in the prompt")
            documented = set(re.findall(r"^- `\{\{([a-z_]+)\}\}`", md_section(text, "Placeholders"), re.M))
            self.assertEqual(used - documented, set(), f"{name}: placeholders used but not documented")

    def test_lens_votes_real_only_on_all_three_prongs(self):
        text = (KIT / "lens.prompt.md").read_text(encoding="utf-8")
        schema = md_schema(text)
        self.assertEqual(schema["properties"]["forbidden"]["type"], "boolean")
        self.assertIn("forbidden", schema["required"])
        self.assertIn("a lens votes real only when holds is true, reachable is not no, and forbidden is true", md_section(text, "Vote rule"))
        for lens in ("reproduce", "reachability", "refute"):
            self.assertTrue(md_section(text, f"Lens: {lens}"), lens)
        self.assertIn("{{classification}}", md_section(text, "Prompt"))
        self.assertIn("{{classification}}", md_section((KIT / "grader.prompt.md").read_text(encoding="utf-8"), "Prompt"))

    def test_cluster_prompt_has_the_assignment_variant(self):
        text = (KIT / "cluster.prompt.md").read_text(encoding="utf-8")
        self.assertIn("{{existing_clusters}}", md_section(text, "Assignment prompt"))


# K3: no provider call, no credential, no host path, no session or run id anywhere in the kit.
HYGIENE = [
    ("an absolute host path", re.compile(r"(?<![\w.~$}{-])/(?:home|tmp|root|Users|var|opt|mnt|srv|versions|private)/")),
    ("a /home/ or /tmp/ string", re.compile(r"/home/|/tmp/")),
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
                        break  # one hit per line: the first rule it breaks
        return hits

    def test_the_kit_has_no_host_path_session_id_key_or_provider_call(self):
        self.assertTrue(KIT.is_dir())
        self.assertEqual(self.scan(KIT), [])

    def test_the_scan_catches_each_kind(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.md"
            samples = ["see /" + "home/user/x", "cache x/" + "tmp/y", "id session" + "_01ABC", "run " + "a" * 32, "run " + "wf_" + "4e9ef48d-066",
                       "Moon" + "Aliza", "os." + "environ['X']", "fetch" + "(url)", "C:" + "\\\\Users"]
            bad.write_text("\n".join(["# x"] + samples + ["{{/" + "tmp/ok}}", "EXAMPLE: /" + "tmp/ok"]) + "\n")
            self.assertEqual(len(self.scan(Path(d))), len(samples))


NEEDS_NODE = unittest.skipUnless(shutil.which("node"), "node is not installed: the workflow template cannot be executed here")


class RunTemplate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_template_has_the_fill_slots_lineage_and_harness_markers(self):
        text = (KIT / "run.template.js").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("// Lineage:"))
        self.assertEqual((text.count("null // {{RUN}}"), text.count("null // {{PROMPTS}}")), (1, 1))
        self.assertGreaterEqual(text.count("// HARNESS:"), 4)
        self.assertTrue("retry limit 0" in text.lower(), "the template states its retry limit")

    @NEEDS_NODE
    def test_filled_template_runs_every_cell_then_grades_clusters_and_adjudicates(self):
        out = execute_template(run_config(self.root), self.root)
        self.assertIsNone(out["error"])
        labels = [c["label"] for c in out["calls"]]
        self.assertEqual(sorted(x for x in labels if x.split(":")[0] in ("pin", "fix", "review")),
                         ["fix:alpha-low", "pin:alpha-low", "review:alpha-low", "review:beta-max"])
        self.assertEqual(sorted(x for x in labels if x.startswith(("grade:", "cluster:", "lens:"))),
                         ["cluster:others", "grade:alpha-low", "grade:beta-max", "lens:C-1:reachability", "lens:C-1:refute", "lens:C-1:reproduce"])
        for c in out["calls"]:
            self.assertNotIn("{{", c["prompt"], c["label"])
            self.assertIn("schema", c, c["label"])
            if c["label"].split(":")[0] in ("pin", "fix", "review"):
                task, key = c["label"].split(":")
                self.assertIn(f"{self.root / 'checkouts'}/cal-{task}-{key}", c["prompt"])  # <checkout_root>/<name>, as the template joins it
                self.assertIn("the operator launched this calibration", c["prompt"])  # A-1: a relayed request is reconciled
                self.assertNotIn(str(self.root / "pack"), c["prompt"])  # Item 2: the prompt names only the checkout
                self.assertNotIn("accepted0", c["prompt"])
                self.assertNotIn("bound check", c["prompt"]) if task == "review" else None  # no ground truth in a review prompt
                prof = {"alpha-low": ("alpha", "low"), "beta-max": ("beta", "max")}[key]
                self.assertEqual((c["model"], c["effort"]), prof)
            else:
                self.assertEqual((c["model"], c["effort"]), ("gamma", "high"), c["label"])  # the judging profile
        grader = next(c for c in out["calls"] if c["label"] == "grade:beta-max")
        self.assertIn("D-1 (S3): add raises on a negative argument", grader["prompt"])
        self.assertIn("at most S4", grader["prompt"])  # the Definition, verbatim
        self.assertIn("truth", grader["schema"]["required"])
        refute = next(c for c in out["calls"] if c["label"] == "lens:C-1:refute")
        self.assertIn("YOUR LENS: REFUTE", refute["prompt"])
        self.assertIn("forbidden", refute["schema"]["required"])
        fix = next(c for c in out["calls"] if c["label"] == "fix:alpha-low")
        self.assertIn("add(a, b) answers a + b", fix["prompt"])  # the required behaviour, stated without the fix
        self.assertIn("fix(mod): D-2 - ", fix["prompt"])
        adj = out["result"]["adjudications"][0]
        self.assertEqual((adj["real"], adj["realVotes"]), (True, "2/3"))

    @NEEDS_NODE
    def test_a_lens_vote_needs_the_forbidden_prong(self):
        out = execute_template(run_config(self.root), self.root, canned_outputs(forbidden=(True, False, False)))
        adj = out["result"]["adjudications"][0]
        self.assertEqual((adj["real"], adj["realVotes"]), (False, "1/3"))  # all three hold and are reachable: not enough

    @NEEDS_NODE
    def test_launch_refuses_checkouts_that_share_a_path_with_the_pack(self):
        for host in ({"checkout_root": str(self.root / "pack" / "checkouts")}, {"pack_dir": str(self.root / "checkouts" / "pack")},
                     {"adjudication_checkout": str(self.root / "pack" / "adj")},
                     {"checkout_root": f"{self.root}//pack/co"},  # N3: a doubled separator spells the same path
                     {"checkout_root": f"{self.root}/./pack/co"},  # N3: and so does a '.' segment
                     {"pack_dir": f"{self.root}//checkouts/pack"}):
            out = execute_template(run_config(self.root, **host), self.root)
            self.assertIn("pack", out["error"] or "", host)
            self.assertEqual(out["calls"], [], host)

    @NEEDS_NODE
    def test_launch_refuses_an_unrecorded_relayed_text_or_an_unfrozen_protocol(self):
        for drop in ("text", None):  # the text key missing, or the whole record missing: Item 3.2
            cfg = run_config(self.root)
            if drop:
                del cfg["protocol"]["relayed_operator_text"][drop]
            else:
                del cfg["protocol"]["relayed_operator_text"]
            out = execute_template(cfg, self.root)
            self.assertIn("does not record relayed_operator_text.text", out["error"] or "", drop)
            self.assertEqual(out["calls"], [])
        cfg = run_config(self.root)
        cfg["protocol"]["frozen_at"] = "{{ISO-8601 UTC time of the freeze commit}}"
        out = execute_template(cfg, self.root)
        self.assertIn("frozen", out["error"] or "")
        self.assertEqual(out["calls"], [])
        cfg = run_config(self.root)
        cfg["protocol"]["classification"]["prongs"] = ["holds", "reachable"]
        out = execute_template(cfg, self.root)
        self.assertIn("prongs", out["error"] or "")
        self.assertEqual(out["calls"], [])

    def launch(self, mutate) -> dict:
        cfg = run_config(self.root)
        mutate(cfg["protocol"])
        return execute_template(cfg, self.root)

    @NEEDS_NODE
    def test_launch_treats_a_placeholder_qualification_as_unset(self):
        # F3: the template ships qualification and limitation as {{...}} strings; neither is a qualification or the line
        tmpl = json.loads((KIT / "protocol.template.json").read_text(encoding="utf-8"))["judging_profile"]
        for lim in (tmpl["limitation"], None):
            out = self.launch(lambda p: p["judging_profile"].update(qualification=tmpl["qualification"], limitation=lim))
            self.assertIn("neither its qualification nor the bootstrap limitation line", out["error"] or "", lim)
            self.assertEqual(out["calls"], [])

    @NEEDS_NODE
    def test_launch_requires_the_bootstrap_limitation_line_itself(self):
        # F3, Item 3.3: with no qualification, the limitation is the line, not any text
        out = self.launch(lambda p: p["judging_profile"].update(qualification=None, limitation="trust me"))
        self.assertIn("neither its qualification nor the bootstrap limitation line", out["error"] or "")
        self.assertEqual(out["calls"], [])
        line = "judging profile not independently qualified, host-declared by the operator"
        out = self.launch(lambda p: p["judging_profile"].update(qualification=None, limitation=line))
        self.assertIsNone(out["error"])

    @NEEDS_NODE
    def test_launch_requires_the_relayed_text_statement(self):
        # F3, Item 3.2: the record is the text (or null) and the statement of what the harness relays
        for rec in ({"text": None}, {"text": None, "statement": ""}, {"text": None, "statement": "{{statement}}"}):
            out = self.launch(lambda p: p.update(relayed_operator_text=rec))
            self.assertIn("relayed_operator_text.statement", out["error"] or "", rec)
            self.assertEqual(out["calls"], [])

    @NEEDS_NODE
    def test_launch_refuses_any_placeholder_left_in_the_protocol(self):
        # F3: "fill every placeholder" - a {{...}} anywhere in the protocol stops the launch, and the error names where
        tmpl = json.loads((KIT / "protocol.template.json").read_text(encoding="utf-8"))
        out = self.launch(lambda p: p.update(profiles=tmpl["profiles"]))
        self.assertIn("unfilled placeholder at protocol.profiles[0].key", out["error"] or "")
        self.assertEqual(out["calls"], [])
        out = self.launch(lambda p: p["accounting"].update(statement="{{how tokens are read}}"))
        self.assertIn("unfilled placeholder at protocol.accounting", out["error"] or "")
        self.assertEqual(out["calls"], [])
        # N1: a placeholder can be a key - the template ships rates_per_mtok keyed by '{{model alias}}'
        def rekey(p):
            rates = p["accounting"]["rates_per_mtok"]
            rates["{{model alias}}"] = rates.pop("alpha")
        out = self.launch(rekey)
        self.assertIn("unfilled placeholder at protocol.accounting.rates_per_mtok.{{model alias}}", out["error"] or "")
        self.assertEqual(out["calls"], [])
        out = self.launch(lambda p: p.update({"{{extra}}": 1}))
        self.assertIn("unfilled placeholder at protocol.{{extra}}", out["error"] or "")
        self.assertEqual(out["calls"], [])
        # the relayed text is the operator's words verbatim: a '{{' in it is data, not a placeholder
        out = self.launch(lambda p: p.update(relayed_operator_text={"text": "keep {{this}} as typed", "statement": "the harness relays this operator text"}))
        self.assertIsNone(out["error"])
        # the template as shipped, with only the freeze time and the judging profile filled (the reviewer's case)
        shipped = copy.deepcopy(tmpl)
        shipped.pop("_lineage", None)
        shipped.pop("sources", None)
        shipped["frozen_at"] = "2026-01-01T00:00:00Z"
        shipped["judging_profile"].update(key="gamma-high", model="gamma", effort="high", qualification="qualified by revision 1", limitation=None)
        cfg = run_config(self.root)
        cfg["protocol"] = shipped
        out = execute_template(cfg, self.root)
        self.assertIn("unfilled placeholder", out["error"] or "")
        self.assertEqual(out["calls"], [])

    @NEEDS_NODE
    def test_a_recorded_relayed_text_reaches_every_candidate_verbatim(self):
        cfg = run_config(self.root)
        cfg["protocol"]["relayed_operator_text"] = {"text": "focus on the router for now", "statement": "the harness relays this operator text"}
        out = execute_template(cfg, self.root)
        for c in out["calls"]:
            if c["label"].split(":")[0] in ("pin", "fix", "review"):
                self.assertIn("focus on the router for now", c["prompt"])

    @NEEDS_NODE
    def test_supplementary_run_reruns_only_the_void_cells_and_keeps_known_verdicts(self):
        known = json.loads((FIX / "run.json").read_text(encoding="utf-8"))["result"]["adjudications"][0]
        cfg = run_config(self.root, supplementary={"cells": ["review:beta-max"], "main_clusters": [{k: known["cluster"][k] for k in ("id", "title", "claim")}],
                                                    "main_adjudications": [known]})
        out = execute_template(cfg, self.root)
        self.assertIsNone(out["error"])
        self.assertEqual([c["label"] for c in out["calls"]], ["review:beta-max", "grade:beta-max", "cluster:others"])
        self.assertIn("EXISTING CLUSTERS", out["calls"][2]["prompt"])
        adj = out["result"]["adjudications"][0]
        self.assertEqual((adj["real"], adj["fromMainRun"]), (True, True))


class Request(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, folder: Path, *extra) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(KIT / "request.py"), str(folder), "--repo-root", str(self.root), *extra],
                              capture_output=True, text=True, timeout=60)

    def test_prints_branch_files_the_template_sections_and_asks_the_operator(self):
        folder = results_folder(self.root)
        p = self.request(folder)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = p.stdout
        self.assertIn("Branch: evidence/fixture-host-calibration-1", out)
        for name in ("protocol.json", "observations.json", "scores.json", "results-table.md", "void-cells.json"):
            self.assertIn(f"docs/evidence/2026-01-01/fixture-host-calibration-1/{name}", out)
        headings = re.findall(r"^## .+$", (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8"), re.M)
        self.assertEqual(len(headings), 4)
        positions = [out.find(h + "\n") for h in headings]
        self.assertTrue(all(x >= 0 for x in positions), headings)
        self.assertEqual(positions, sorted(positions), "the sections are in the template's order")
        self.assertIn("run-main-1", out)
        self.assertIn("pin: 1 of 1 PASS", out)
        self.assertIn("judging profile gamma-high", out)
        self.assertIn("the harness relays no operator text into workers", out)
        last = out.strip().splitlines()[-1]
        self.assertIn("please open the pull request yourself", last)
        self.assertIn("never pushes", last)

    def test_a_two_prong_pass_is_named_as_one(self):
        run = json.loads((FIX / "run.json").read_text(encoding="utf-8"))
        for lens in run["result"]["adjudications"][0]["lenses"]:
            del lens["forbidden"]
        path = self.root / "run-two-prong.json"
        path.write_text(json.dumps(run))
        p = self.request(results_folder(self.root, run=path))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("review:beta-max PASS (2-prong, would fail)", p.stdout)
        self.assertIn("missing from the lens schema: forbidden", p.stdout)

    def test_never_runs_git_or_any_command(self):
        src = (KIT / "request.py").read_text(encoding="utf-8")
        for word in ("subprocess", "os.system", "Popen", "os.exec"):
            self.assertNotIn(word, src)

    def test_refuses_a_folder_without_scores(self):
        (self.root / "empty").mkdir()
        p = self.request(self.root / "empty")
        self.assertEqual(p.returncode, 2)
        self.assertIn("scores.json", p.stderr)


class SharedPack(unittest.TestCase):
    """P5: the shared synthetic subject pack builds, behaves and grades as its manifest says."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.env = git_env(cls.root)
        cls.pack = cls.root / "pack"
        cls.built, cls.ids = build_shared(cls.pack, cls.env)
        cls.repo = cls.pack / "repo"
        cls.n = 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.assertEqual(self.built.returncode, 0, self.built.stdout + self.built.stderr)

    def at(self, name: str) -> Path:
        """A fresh history-less checkout of the pack commit <name>0, outside the pack."""
        type(self).n += 1
        target = self.root / "checkouts" / f"{name}-{self.n}"
        p = checkout(self.repo, self.ids[f"{name}0"], target, self.env, "--pack", str(self.pack))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return target

    def test_make_repo_builds_three_commits_holding_the_trees(self):
        self.assertEqual(sorted(self.ids), ["accepted0", "base0", "review0"], self.built.stdout)
        g = lambda *a: sh(["git", *a], self.repo, self.env).stdout.strip()
        self.assertEqual(g("rev-list", "--reverse", "main").split(), [self.ids["review0"], self.ids["base0"], self.ids["accepted0"]])
        self.assertEqual(g("rev-list", "--max-parents=0", "main"), self.ids["review0"])
        for name in TREES:
            rev = self.ids[f"{name}0"]
            self.assertEqual(g("rev-parse", f"{name}0"), rev, f"the tag {name}0")
            self.assertEqual(tree_files(self.repo, self.env, rev), tree_files(PACK / "trees" / name, self.env), name)
            self.assertEqual(g("ls-tree", "-r", "--format=%(objectmode)", rev).split(), ["100644"] * len(tree_files(PACK / "trees" / name, self.env)))
        self.assertIn("D-1", g("log", "-1", "--format=%B", self.ids["base0"]))
        self.assertIn("D-2", g("log", "-1", "--format=%B", self.ids["accepted0"]))
        self.assertEqual(g("status", "--porcelain"), "")

    def test_make_repo_ids_do_not_depend_on_the_host(self):
        # a hostile host: its own identity and dates in the environment, a clean filter on every file, CRLF conversion,
        # commit and tag signing on (with a signer that fails), a legacy commit encoding and another default branch; the
        # build succeeds and the ids are the same as on a clean one
        home = self.root / "hostile"
        home.mkdir()
        (home / "attributes").write_text("* filter=hostile text eol=crlf\n")
        (home / "gitconfig").write_text(
            "[user]\n\tname = h\n\temail = h@localhost\n[init]\n\tdefaultBranch = trunk\n[core]\n\tautocrlf = true\n"
            f"\tattributesFile = {(home / 'attributes').as_posix()}\n[filter \"hostile\"]\n\tclean = sed s/a/b/\n\tsmudge = cat\n"
            "[i18n]\n\tcommitEncoding = ISO-8859-1\n[commit]\n\tgpgSign = true\n[tag]\n\tgpgSign = true\n[gpg]\n\tprogram = false\n")
        env = git_env(home)
        env.update(GIT_AUTHOR_NAME="x", GIT_AUTHOR_EMAIL="x@x", GIT_AUTHOR_DATE="2001-02-03T04:05:06Z",
                   GIT_COMMITTER_NAME="y", GIT_COMMITTER_EMAIL="y@y", GIT_COMMITTER_DATE="2001-02-03T04:05:06Z", TZ="Asia/Kolkata",
                   GIT_EDITOR="false")  # a step that wants an editor fails here instead of waiting for one
        p, ids = build_shared(self.root / "hostile-pack", env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(ids, self.ids)
        p, again = build_shared(self.root / "hostile-pack", self.env, self.root / "elsewhere" / "repo")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(again, self.ids, "a second build elsewhere gives the same ids")

    def test_make_repo_refuses_an_existing_target_and_a_bad_call(self):
        (self.root / "taken").mkdir(exist_ok=True)
        for args in ([str(self.root / "taken")], [], ["a", "b"]):
            p = subprocess.run(["bash", str(self.pack / "make-repo.sh"), *args], env=self.env, capture_output=True, text=True, timeout=60)
            self.assertEqual(p.returncode, 2, f"{args}: {p.stdout}{p.stderr}")
        self.assertEqual(list((self.root / "taken").iterdir()), [])

    def test_the_shipped_harness_is_green_on_every_tree(self):
        for name in TREES:
            p = run_pack_tests(self.at(name), self.env, "tests/test_bounded.py")
            self.assertEqual(p.returncode, 0, f"{name}: {p.stdout}{p.stderr}")
            self.assertRegex(p.stderr, r"Ran (?:[89]|1[0-9]) tests", name)

    def test_the_runner_reads_red_on_a_failure_a_broken_file_or_no_test(self):
        cand = self.at("accepted")
        (cand / "tests" / "zz_red.py").write_text("import unittest\n\n\nclass R(unittest.TestCase):\n    def test_r(self):\n        self.fail('red')\n")
        (cand / "tests" / "zz_broken.py").write_text("import nothing_by_this_name\n")
        (cand / "tests" / "zz_empty.py").write_text("X = 1\n")
        for f in ("tests/zz_red.py", "tests/zz_broken.py", "tests/zz_empty.py"):
            self.assertEqual(run_pack_tests(cand, self.env, f).returncode, 1, f)
        self.assertEqual(run_pack_tests(cand, self.env).returncode, 2)
        self.assertEqual(run_pack_tests(cand, self.env, "tests/test_bounded.py", "tests/zz_red.py").returncode, 1)

    def test_d2_the_accepted_pin_is_red_at_base_and_review_and_green_at_accepted(self):
        pin = (PACK / "trees" / "accepted" / "tests" / "test_pin.py").read_bytes()
        for name, code in (("review", 1), ("base", 1), ("accepted", 0)):
            cand = self.at(name)
            (cand / "tests" / "zz_accepted_pin.py").write_bytes(pin)
            p = run_pack_tests(cand, self.env, "tests/zz_accepted_pin.py")
            self.assertEqual(p.returncode, code, f"{name}: {p.stdout}{p.stderr}")
            if code:
                self.assertIn("AssertionError", p.stderr, name)  # red by the rule, not by a crash

    def test_d1_a_memoryview_chunk_raises_at_review_only(self):
        probe = ("import sys; sys.path.insert(0, '.')\nfrom src.bounded import read_bounded\n"
                 "try:\n    print('returned', read_bounded([memoryview(b'abc'), b'def'], 4))\n"
                 "except Exception as e:\n    print('raised', type(e).__name__)\n")
        seen = {}
        for name in TREES:
            p = subprocess.run([sys.executable, "-c", probe], cwd=self.at(name), env=self.env, capture_output=True, text=True, timeout=60)
            seen[name] = p.stdout.strip()
        self.assertEqual(seen, {"review": "raised TypeError", "base": "returned b'abcd'", "accepted": "returned b'abcd'"})


    def test_the_spec_states_the_edges_of_the_promise_the_accepted_tree_keeps(self):
        # the edges a review could otherwise report as other findings: the spec says how each behaves, and the accepted
        # tree behaves so (a released memoryview holds no bytes; a limit of 0 still reads the first chunk, and no more)
        for name in TREES:
            spec = (PACK / "trees" / name / "SPEC.md").read_text(encoding="utf-8")
            self.assertIn("released", spec, name)
            self.assertIn("with a limit of 0", spec, name)
            none = re.search(r"(?ms)^- \*\*none\*\*:.*?(?=^\S|^- )", spec).group(0)  # R-3: Python calls these bytes-like too
            for kind in ("`array.array`", "`mmap`"):
                self.assertIn(kind, none, name)
        probe = ("import sys; sys.path.insert(0, '.')\nfrom src.bounded import read_bounded\n"
                 "v = memoryview(b'abc'); v.release()\n"
                 "try:\n    read_bounded([v], 4)\nexcept ValueError:\n    print('released: ValueError')\n"
                 "pulled = []\ndef gen():\n    for c in (b'a', b'b'):\n        pulled.append(c)\n        yield c\n"
                 "print('limit 0:', read_bounded(gen(), 0), len(pulled))\n"
                 "import array, mmap\nfor c in (array.array('b', [65, 66]), mmap.mmap(-1, 2)):\n"
                 "    try:\n        read_bounded([c], 4)\n    except TypeError:\n        print(type(c).__name__ + ': TypeError')\n")
        p = subprocess.run([sys.executable, "-c", probe], cwd=self.at("accepted"), env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.stdout.split("\n")[:4], ["released: ValueError", "limit 0: b'' 1", "array: TypeError", "mmap: TypeError"], p.stdout + p.stderr)

    # ---- the manifest (P3, P4) and grade.sh on this pack (P5) --------------------------------------------------------
    def manifest(self) -> dict:
        return json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))

    def test_the_manifest_carries_the_built_ids(self):
        m, ids = self.manifest(), self.ids
        self.assertEqual(m["repository"], "repo")
        self.assertEqual((m["cases"]["review"]["base"], m["cases"]["pin"]["base"], m["cases"]["fix"]["base"], m["accepted_fix"]),
                         (ids["review0"], ids["base0"], ids["base0"], ids["accepted0"]))
        truth = {f["id"]: f for f in m["findings"]}
        self.assertEqual(sorted(truth), ["D-1", "D-2"])
        self.assertEqual((truth["D-1"]["present_at"], truth["D-1"]["accepted_fix"]), ([ids["review0"]], ids["base0"]))
        self.assertEqual((truth["D-2"]["present_at"], truth["D-2"]["accepted_fix"]), ([ids["review0"], ids["base0"]], ids["accepted0"]))
        self.assertIn("make-repo: the ids equal manifest.json's", self.built.stderr)

    def test_make_repo_fails_when_the_ids_differ_from_the_manifest(self):
        dest = self.root / "changed-pack"
        shutil.copytree(PACK, dest, ignore=shutil.ignore_patterns("__pycache__", "repo"))
        with (dest / "trees" / "base" / "SPEC.md").open("a", encoding="utf-8") as f:
            f.write("\nchanged\n")
        p, ids = build_shared(dest, self.env)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("differ from manifest.json", p.stderr)
        self.assertIn("cases.pin.base", p.stderr)
        self.assertNotIn("cases.review.base", p.stderr)  # review0 is built from trees/review, which did not change

    def test_the_manifest_carries_every_field_of_the_format(self):
        m, fixture = self.manifest(), json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
        # every field the format documents (subject-pack/README.md), optional ones included, is present
        section = md_section((KIT / "subject-pack" / "README.md").read_text(encoding="utf-8"), "manifest.json")
        fields = set(re.findall(r"^\s*- `([a-z_.\[\]]+)`", section, re.M))
        for line in re.findall(r"^\s*- (`cases\.pin\.[a-z_]+`.*?):", section, re.M):  # "`cases.pin.x`, `cases.fix.x`: ..."
            fields |= set(re.findall(r"`([a-z_.]+)`", line))
        self.assertGreater(len(fields), 40, fields)
        # run 4's keys (a pin case's mutants, the gate case kind, a fix case's cause_in_prompt) are optional and the shared
        # pack, a pin/fix/review pack, carries none (its fix prompt prints the cause, as before): each is checked on the
        # shape the kit's own fixtures use (GATE_CASE, add_mutant's list, FixCauseInPrompt's false)
        run4 = {"cases": {"pin": {"mutants": [{"id": "M-1", "commit": "0" * 40}]}, "gate": GATE_CASE, "fix": {"cause_in_prompt": False}}}
        self.assertTrue({"cases.pin.mutants", "cases.gate.commands.gate", "cases.gate.invariants", "cases.fix.cause_in_prompt"} <= fields, fields)
        for field in sorted(fields):
            node = run4 if field.startswith(("cases.pin.mutants", "cases.gate", "cases.fix.cause_in_prompt")) else m
            for part in field.replace("[]", "").split("."):
                node = node[0] if isinstance(node, list) else node
                self.assertIn(part, node, field)
                node = node[part]
        keys = lambda d: {k for k in d if not k.startswith("_")}
        self.assertEqual(keys(m), keys(fixture))
        for f in m["findings"]:
            self.assertEqual(keys(f), keys(fixture["findings"][0]), f["id"])
            self.assertEqual(f["severity"], "S3", f["id"])
        for case in ("pin", "fix", "review"):
            self.assertTrue(keys(fixture["cases"][case]) <= keys(m["cases"][case]), case)
            self.assertEqual(m["cases"][case]["tier"], "T1", case)
            self.assertEqual(m["cases"][case]["pass_rule"], fixture["cases"][case]["pass_rule"], case)  # the kit's rule shapes
            self.assertEqual(m["cases"][case]["category"], fixture["cases"][case]["category"], case)
        self.assertEqual((m["kind"], m["pack_version"]), ("shared", "1"))
        self.assertEqual((m["cases"]["pin"]["finding"], m["cases"]["fix"]["finding"], m["cases"]["review"]["findings"]), ("D-2", "D-2", ["D-1", "D-2"]))
        self.assertIn("two-row", m["cases"]["pin"]["instructions"])
        self.assertTrue(m["cases"]["fix"]["commit_prefix"].startswith("fix(bounded): D-2"))
        for name in ("read_bounded", "chunk_kind", "join_parts"):
            self.assertIn(name, m["cases"]["review"]["scope"])
        paths = m["paths"]
        self.assertEqual((paths["source"], paths["source_dir"], paths["test_file"], paths["new_test_pattern"], paths["accepted_test"], paths["scratch_test"]),
                         (["src/bounded.py"], "src", "tests/test_bounded.py", "^tests/test_pin.*\\.py$",
                          {"from": "tests/test_pin.py", "to": "tests/zz_accepted_pin.py"}, "tests/scratch_{name}.py"))
        self.assertRegex(m["cases"]["pin"]["test_file"], paths["new_test_pattern"])
        self.assertNotRegex(paths["accepted_test"]["to"], paths["new_test_pattern"])
        self.assertEqual(m["commands"], {"test": "python3 tests/run.py {files}", "test_report": "exit-code", "run_one": "python3 tests/run.py {file}",
                                         "lint": "python3 -m py_compile {files}", "timeout_seconds": 120})
        self.assertEqual(m["checkout"], {"links": []})
        self.assertEqual(m["subject"]["module"], "src/bounded.py")
        self.assertEqual(m["subject"]["promise"], PROMISE)
        for name in TREES:  # the module states the promise the manifest names
            doc = " ".join((PACK / "trees" / name / "src" / "bounded.py").read_text(encoding="utf-8").split('"""')[1].split())
            self.assertIn(PROMISE, doc, name)
        self.assertIn("history-less", m["isolation"])

    def test_no_manifest_text_states_an_accepted_fix(self):
        m = self.manifest()
        text = "\n".join(strings({k: v for k, v in m.items() if k != "source_hashes"}))
        g = lambda *a: sh(["git", *a], self.repo, self.env).stdout
        for a, b in (("review0", "base0"), ("base0", "accepted0")):
            added = [ln[1:].strip() for ln in g("diff", a, b, "--", "src/bounded.py").splitlines() if ln.startswith("+") and not ln.startswith("+++")]
            self.assertTrue(added, (a, b))
            for line in added:
                self.assertNotIn(line, text, f"the manifest states the fix line {line!r}")

    def test_source_hashes_cover_every_pack_file(self):
        hashes = self.manifest()["source_hashes"]
        self.assertEqual(sorted(hashes), [f for f in pack_files(PACK) if f != "manifest.json"])
        for f, h in hashes.items():
            self.assertEqual(h, text_hash(PACK / f), f)

    def grade_cell(self, task: str, prepare) -> dict:
        cand = self.at("base")
        prepare(cand)
        commit_all(cand, self.env, f"fix(bounded): D-2 - {task} cell" if task == "fix" else "test(bounded): pin")
        code, d, out = grade(self.pack / "manifest.json", task, cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertIs(d["restored"], True, out)
        self.assertFalse((cand / "tests" / "zz_accepted_pin.py").exists())
        return d

    def accepted(self, path: str) -> bytes:
        return (PACK / "trees" / "accepted" / path).read_bytes()

    def test_grade_pin_the_accepted_pin_passes(self):
        d = self.grade_cell("pin", lambda c: (c / "tests" / "test_pin.py").write_bytes(self.accepted("tests/test_pin.py")))
        self.assertEqual(d["testFiles"], ["tests/test_pin.py"])
        self.assertEqual((d["redAtHead"], d["greenWithFix"], d["srcClean"], d["lint"], d["committed"]), (True, True, True, "ok", True), d)
        self.assertIs(d["PASS"], True)

    def test_grade_pin_a_wrong_pin_fails(self):
        weak = ("import unittest\nfrom src.bounded import read_bounded\n\n\nclass P(unittest.TestCase):\n    def test_text(self):\n"
                "        self.assertEqual(read_bounded([\"ab\"], 4), b\"ab\")\n")
        d = self.grade_cell("pin", lambda c: (c / "tests" / "test_pin.py").write_text(weak))  # green at the base: not the rule
        self.assertEqual((d["redAtHead"], d["greenWithFix"]), (False, True), d)
        self.assertIs(d["PASS"], False)

        def pin_and_fix(c):  # the rule, but the source fixed too: a pin cell changes nothing under src/
            (c / "tests" / "test_pin.py").write_bytes(self.accepted("tests/test_pin.py"))
            (c / "src" / "bounded.py").write_bytes(self.accepted("src/bounded.py"))
        d = self.grade_cell("pin", pin_and_fix)
        self.assertEqual((d["redAtHead"], d["srcClean"], d["srcTouched"]), (False, False, ["src/bounded.py"]), d)
        self.assertIs(d["PASS"], False)

    TWO_CHUNK_ROWS = ("        self.assertEqual(read_bounded([\"abc\", \"def\"], 4), b\"abcd\")\n"
                      "        self.assertEqual(read_bounded([b\"ab\", \"cd\\u00e9\", b\"f\"], 4), b\"abcd\")\n")
    # a candidate's own pin that cuts only one text chunk, and never one after earlier bytes (N-3 of re-review 2)
    ONE_CHUNK_ROWS = ("        self.assertEqual(read_bounded([\"abcdef\"], 4), b\"abcd\")\n"
                      "        self.assertEqual(read_bounded([b\"ab\", \"cd\"], 4), b\"abcd\")\n")

    def fix_like_the_accepted_one(self, cand: Path, source: bytes | None = None, rows: str | None = None):
        (cand / "src" / "bounded.py").write_bytes(source if source is not None else self.accepted("src/bounded.py"))
        with (cand / "tests" / "test_bounded.py").open("a", encoding="utf-8") as f:
            f.write("\n\nclass TextCountsAgainstTheLimit(unittest.TestCase):\n    def test_rows(self):\n" + (rows or self.TWO_CHUNK_ROWS))

    def test_grade_fix_the_accepted_source_with_a_pin_passes(self):
        d = self.grade_cell("fix", self.fix_like_the_accepted_one)
        self.assertEqual((d["candidateGreen"], d["guardRed"], d["acceptedPinGreen"], d["scopeOk"], d["lint"]), (True, True, True, True, "ok"), d)
        self.assertEqual((d["srcDiffLines"], d["committedWithMap"], d["outOfScope"]), (3, None, []), d)
        self.assertIs(d["PASS"], True)

    def test_grade_fix_a_scope_breaking_fix_fails(self):
        def and_the_spec(c):
            self.fix_like_the_accepted_one(c)
            with (c / "SPEC.md").open("a", encoding="utf-8") as f:
                f.write("\nA str chunk counts too.\n")
        d = self.grade_cell("fix", and_the_spec)
        self.assertEqual((d["candidateGreen"], d["guardRed"], d["acceptedPinGreen"]), (True, True, True), d)
        self.assertEqual((d["scopeOk"], d["outOfScope"]), (False, ["SPEC.md"]), d)
        self.assertIs(d["PASS"], False)

    def wrong_fix(self, name: str) -> bytes:
        """base0's source with a fix of D-2 that passes a pin which never cuts inside a character or never tests the stop,
        yet still breaks the promise or SPEC.md's result (R-1 of the sr-pack review, N-1 and N-2 of its re-review)."""
        src = (PACK / "trees" / "base" / "src" / "bounded.py").read_text(encoding="utf-8")
        text = '            parts.append(chunk.encode("utf-8", "replace"))\n            continue\n'
        self.assertEqual(src.count(text), 1)
        if name == "chars":  # counts a str chunk by its characters, not its UTF-8 bytes
            src = src.replace(text, '            piece = chunk[:limit - taken]\n            parts.append(piece.encode("utf-8", "replace"))\n'
                                    '            taken += len(piece)\n            if taken >= limit:\n                break\n            continue\n')
        elif name == "boundary":  # takes whole characters while they fit and stops at the first that does not, so a
            # result never ends inside a character, where SPEC.md cuts at limit bytes
            src = src.replace(text, '            fits, whole = b"", True\n            for ch in chunk:\n'
                                    '                b = ch.encode("utf-8", "replace")\n'
                                    '                if taken + len(fits) + len(b) > limit:\n'
                                    '                    whole = False\n                    break\n'
                                    '                fits += b\n            parts.append(fits)\n            taken += len(fits)\n'
                                    '            if not whole or taken >= limit:\n                break\n            continue\n')
        elif name == "topcheck":  # counts a str chunk's bytes, but tests the bound at the top of the loop, so it pulls
            # one chunk past limit bytes and drops it, where SPEC.md says no further chunk is read
            src = src.replace(text, '            chunk = chunk.encode("utf-8", "replace")\n')
            for a, b in (("    for chunk in chunks:\n", "    for chunk in chunks:\n        if taken >= limit:\n            break\n"),
                         ("        taken += len(piece)\n        if taken >= limit:\n            break\n", "        taken += len(piece)\n")):
                self.assertEqual(src.count(a), 1, a)
                src = src.replace(a, b)
        elif name == "slicelimit":  # counts a str chunk's bytes and stops, but cuts it at enc[:limit] instead of
            # enc[:limit - taken], so a text chunk after earlier bytes overflows the limit (N-3 of re-review 2)
            src = src.replace(text, '            piece = chunk.encode("utf-8", "replace")[:limit]\n            parts.append(piece)\n'
                                    '            taken += len(piece)\n            if taken >= limit:\n                break\n            continue\n')
        else:  # "trunc": cuts the joined result at the end, so str chunks are still neither counted nor stopped at
            self.assertEqual(src.count("    return join_parts(parts)\n"), 1)
            src = src.replace("    return join_parts(parts)\n", "    return join_parts(parts)[:limit]\n")
        return src.encode("utf-8")

    def test_grade_fix_wrong_fixes_of_d2_fail_on_the_accepted_pin(self):
        # the pin case's rule names both halves the accepted pin tests: the UTF-8 bytes count, and the stop
        rule = {f["id"]: f for f in self.manifest()["findings"]}["D-2"]["required_behaviour"]
        self.assertIn("UTF-8 bytes count against limit", rule)
        self.assertIn("reads no further chunk", rule)
        # each passes its own test and is red with base0's source, so only the accepted pin can tell it from the fix
        probes = {"chars": "print(len(read_bounded(['\\u00e9' * 4], 4)))",  # a non-ASCII text chunk crosses the bound
                  "trunc": "print(read_bounded(['ab', 'cd', 3], 4))",  # reads past limit bytes, into a chunk it rejects
                  "boundary": "print(read_bounded(['\\u00e9\\u00e9', b'x'], 3))",  # 2 bytes, not the 3 SPEC.md cuts at
                  "topcheck": "pulls = []\ndef g():\n    for c in ('ab', 'cd', 'ef'):\n        pulls.append(c)\n        yield c\n"
                              "print(read_bounded(g(), 4), len(pulls))",  # pulls 'ef' though 'cd' reached the limit
                  "slicelimit": "print(read_bounded(['abc', 'abc'], 4))"}  # 6 bytes: the second chunk is cut at limit, not at the room left
        for name, probe in probes.items():
            with self.subTest(fix=name):
                cand = []
                rows = self.ONE_CHUNK_ROWS if name == "slicelimit" else None  # its own test cuts one chunk, so only the accepted pin can tell
                d = self.grade_cell("fix", lambda c: (cand.append(c), self.fix_like_the_accepted_one(c, self.wrong_fix(name), rows)))
                self.assertEqual((d["candidateGreen"], d["guardRed"], d["scopeOk"], d["lint"]), (True, True, True, "ok"), d)
                self.assertIs(d["acceptedPinGreen"], False, d)
                self.assertIs(d["PASS"], False, d)
                p = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, '.')\nfrom src.bounded import read_bounded\n" + probe],
                                   cwd=cand[0], env=self.env, capture_output=True, text=True, timeout=60)
                want = {"chars": p.stdout.strip() == "8", "trunc": "TypeError" in p.stderr,
                        "boundary": p.stdout.strip() == "b'\\xc3\\xa9'", "topcheck": p.stdout.strip() == "b'abcd' 3",
                        "slicelimit": p.stdout.strip() == "b'abcabc'"}
                self.assertTrue(want[name], p.stdout + p.stderr)

    # ---- the workflow template filled with this pack (P5) ------------------------------------------------------------
    def shared_run_config(self, **host) -> dict:
        co = self.root / "launch" / "checkouts"
        cfg = run_config(self.root / "launch", **{"pack_dir": str(self.pack), "checkout_root": str(co),
                                                   "adjudication_checkout": str(co / "cal-adjudication"), **host})
        cfg["manifest"] = self.manifest()
        return cfg

    @NEEDS_NODE
    def test_the_workflow_template_launches_on_this_pack(self):
        m = self.manifest()
        out = execute_template(self.shared_run_config(), self.root)
        self.assertIsNone(out["error"])
        labels = sorted(c["label"] for c in out["calls"])
        self.assertEqual([x for x in labels if x.split(":")[0] in ("pin", "fix", "review")],
                         ["fix:alpha-low", "pin:alpha-low", "review:alpha-low", "review:beta-max"])
        truth = {f["id"]: f for f in m["findings"]}
        for c in out["calls"]:
            self.assertNotIn("{{", c["prompt"], c["label"])
            task = c["label"].split(":")[0]
            if task not in ("pin", "fix", "review"):
                continue
            prompt = c["prompt"]
            self.assertIn(f"{self.root / 'launch' / 'checkouts'}/cal-{c['label'].replace(':', '-')}", prompt)
            self.assertIn(m["subject"]["promise"], prompt)
            self.assertIn("python3 tests/run.py <file>", prompt)
            for secret in (str(self.pack), "trees/", "make-repo", "zz_accepted_pin", self.ids["accepted0"], self.ids["base0"], self.ids["review0"]):
                self.assertNotIn(secret, prompt, f"{c['label']} names {secret}")  # Item 2: the prompt names only the checkout
            if task == "review":
                self.assertIn(m["cases"]["review"]["scope"], prompt)
                for f in truth.values():  # no ground truth in a review prompt
                    for field in ("summary", "cause", "required_behaviour"):
                        self.assertNotIn(f[field], prompt, f"{f['id']}.{field}")
        pin = next(c["prompt"] for c in out["calls"] if c["label"] == "pin:alpha-low")
        self.assertIn("NEW file tests/test_pin.py", pin)
        self.assertIn(truth["D-2"]["required_behaviour"], pin)
        self.assertIn(m["cases"]["pin"]["instructions"], pin)
        self.assertNotIn(truth["D-1"]["summary"], pin)
        fix = next(c["prompt"] for c in out["calls"] if c["label"] == "fix:alpha-low")
        for field in ("summary", "cause", "required_behaviour"):
            self.assertIn(truth["D-2"][field], fix, field)
        self.assertIn("'fix(bounded): D-2 - '", fix)
        self.assertIn("python3 -m py_compile src/bounded.py tests/test_bounded.py", fix)
        self.assertNotIn(truth["D-1"]["summary"], fix)
        grader = next(c["prompt"] for c in out["calls"] if c["label"] == "grade:beta-max")
        for f in truth.values():
            self.assertIn(f"{f['id']} (S3): {f['summary']}", grader)

    @NEEDS_NODE
    def test_the_launch_refusals_hold_on_this_pack(self):
        for host in ({"checkout_root": str(self.pack / "checkouts")}, {"adjudication_checkout": str(self.pack / "repo" / "adj")},
                     {"pack_dir": str(self.root / "launch" / "checkouts" / "pack")}):
            out = execute_template(self.shared_run_config(**host), self.root)
            self.assertIn("shares a filesystem path with the pack directory", out["error"] or "", host)
            self.assertEqual(out["calls"], [], host)
        cfg = self.shared_run_config()
        cfg["protocol"]["frozen_at"] = "{{ISO-8601 UTC time of the freeze commit}}"
        out = execute_template(cfg, self.root)
        self.assertIn("frozen", out["error"] or "")
        self.assertEqual(out["calls"], [])

class Docs(unittest.TestCase):
    def readme(self) -> str:
        return (KIT / "README.md").read_text(encoding="utf-8")

    def test_every_kit_file_has_a_lineage_header(self):
        for f in sorted(KIT.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts and not in_shared_trees(f):  # the subject a candidate reads
                head = "\n".join(f.read_text(encoding="utf-8").splitlines()[:3])
                self.assertIn("lineage", head.lower(), f.relative_to(KIT))  # protocol.template.json carries it as its _lineage key

    def test_readme_lists_every_kit_file(self):
        text = self.readme()
        for f in sorted(KIT.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts and f != KIT / "README.md" and not in_shared_pack(f):
                self.assertIn(f"`{f.relative_to(KIT).as_posix()}`", text)

    def test_readme_documents_the_observation_keys_the_adapter_reads(self):
        section = md_section(self.readme(), "observations.json: the flat profile map")
        for key in sorted(OBSERVATION_KEYS | USAGE_KEYS | {"tier", "score", "result"}):
            self.assertIn(f"`{key}`", section, key)

    def test_readme_numbers_the_run_protocol_rules(self):
        section = md_section(self.readme(), "The run protocol")
        for n in range(1, 6):
            self.assertRegex(section, rf"(?m)^{n}\. \*\*.+\*\* \(Item 3\.{n}\)")

    def test_readme_walks_the_onboarding_steps(self):
        section = md_section(self.readme(), "How a host onboards a profile")
        for step in ("Pack", "Protocol freeze", "Checkouts", "Fill", "Launch", "Grade", "Build", "Results", "Request"):
            self.assertRegex(section, rf"(?m)^\d+\. \*\*{step}", step)

    def test_readme_fill_command_matches_the_fill(self):
        steps = md_section(self.readme(), "How a host onboards a profile")
        blocks = [textwrap.dedent(b) for b in re.findall(r"^([ \t]*```bash\n.*?^[ \t]*```)", steps, re.S | re.M)]
        block = next((b for b in blocks if "run-config.json > run.js" in b), "")
        m = re.search(r"^python3 -c '(.*?)' tools/calibration run-config\.json > run\.js$", block, re.S | re.M)
        self.assertIsNotNone(m, "the fill command")
        with tempfile.TemporaryDirectory() as d:
            cfg = run_config(Path(d))
            (Path(d) / "run-config.json").write_text(json.dumps(cfg))
            p = subprocess.run([sys.executable, "-c", m.group(1), str(KIT), str(Path(d) / "run-config.json")], capture_output=True, text=True, timeout=60)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(p.stdout, fill_template(cfg))

    def test_subject_pack_readme_documents_every_manifest_field(self):
        text = (KIT / "subject-pack" / "README.md").read_text(encoding="utf-8")
        manifest = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
        keys = {k for k in manifest if not k.startswith("_")}
        for group in ("subject", "paths", "commands", "checkout"):
            keys |= {f"{group}.{k}" for k in manifest[group]}
        keys |= {f"findings[].{k}" for k in manifest["findings"][0]}
        keys |= {f"cases.{c}.{k}" for c in manifest["cases"] for k in manifest["cases"][c]}
        for k in sorted(keys):
            self.assertIn(f"`{k}`", text, k)
        self.assertIn("Isolation", text)

    def test_shared_pack_holds_its_trees_and_the_script_that_builds_its_repository(self):
        self.assertTrue({"README.md", "make-repo.sh", "manifest.json", "trees"} <= {f.name for f in PACK.iterdir()})
        self.assertEqual(sorted(f.name for f in (PACK / "trees").iterdir()), sorted(TREES))

    def test_shared_pack_readme_describes_the_pack(self):
        text = (PACK / "README.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("<!-- Lineage:"))
        self.assertNotIn("stub", text.lower())
        m = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn(f"Version {m['pack_version']}", text)
        for heading in ("The two defects", "Files", "How a host runs it", "What it does not discriminate", "When it is rewritten"):
            md_section(text, heading)
        defects = md_section(text, "The two defects")
        for f in m["findings"]:
            self.assertRegex(defects, rf"(?m)^- \*\*{f['id']}\*\* \({f['severity']}", f["id"])
        for a, b in (("review", "base"), ("base", "accepted")):  # never a fix line (P6: summary and cause only)
            old_lines = set((PACK / "trees" / a / "src" / "bounded.py").read_text(encoding="utf-8").splitlines())
            for line in (PACK / "trees" / b / "src" / "bounded.py").read_text(encoding="utf-8").splitlines():
                if line not in old_lines:
                    self.assertNotIn(line.strip(), text, f"the README states the fix line {line.strip()!r}")
        files = md_section(text, "Files")
        for f in pack_files(PACK):
            parts = f.split("/")
            if parts[0] == "trees":
                self.assertIn(f"`{'/'.join(parts[2:])}`", files, f)
            else:
                self.assertIn(f"`{f}`", files, f)
        for name in TREES:
            self.assertIn(f"`trees/{name}/`", files, name)
        run = md_section(text, "How a host runs it")
        for word in ("make-repo.sh", "historyless-checkout.sh", "grade.sh", "manifest.json", "pack_dir", "outside the kit"):
            self.assertIn(word, run, word)
        # R-2: the guards compare paths with pack_dir only, so step 3 leaves the kit's own trees/ to the host
        step3 = re.search(r"(?ms)^3\. \*\*Checkouts\*\*.*?(?=^4\. )", run).group(0)
        for words in ("the guards cover the pack directory only", "`historyless-checkout.sh --pack`", "`run.template.js`",
                      "the host checks the kit's path itself"):
            self.assertIn(words.lower(), " ".join(step3.lower().split()), words)
        self.assertIn("T1", md_section(text, "What it does not discriminate"))
        self.assertIn("pack_version", md_section(text, "When it is rewritten"))

    def test_the_kit_and_format_readmes_name_the_shared_pack(self):
        kit = self.readme()
        self.assertNotIn("a stub: the shared synthetic pack", kit)
        self.assertNotIn("built by its own unit", kit)
        paragraph = md_section(kit, "The shared pack")
        for word in ("subject-pack/shared/", "make-repo.sh", "D-1", "D-2", "T1"):
            self.assertIn(word, paragraph, word)
        fmt = md_section((KIT / "subject-pack" / "README.md").read_text(encoding="utf-8"), "The shared pack")
        for word in ("shared/", "make-repo.sh", "manifest.json", "repository"):
            self.assertIn(word, fmt, word)

    def test_changelog_and_readme_name_the_kit(self):
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = changelog.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
        lines = [ln for ln in unreleased.splitlines() if "tools/calibration/" in ln]
        self.assertEqual(len(lines), 2)
        kit = [ln for ln in lines if ln.startswith("- **Calibration kit**")]
        self.assertEqual(len(kit), 1)
        self.assertIn("calibration-first-onboarding", kit[0])
        pack = [ln for ln in lines if ln.startswith("- **Shared synthetic subject pack**")]
        self.assertEqual(len(pack), 1)
        self.assertIn("tools/calibration/subject-pack/shared/", pack[0])
        self.assertIn("(tools/calibration/README.md)", (ROOT / "README.md").read_text(encoding="utf-8"))


# ---- run 4's kit cases (sr-kit-cases, K1-K4): a category on the task object, mutants for a pin case, a gate case ----

GOLDEN = FIX / "golden-no-category"  # the builder's output, before K1, on the fixture inputs with every category removed
GATE_CASE = {"base": "base0", "category": "docs-mechanical", "tier": "T1",
             "pass_rule": "commands.gate exits 0 in the candidate's checkout AND every invariants path hashes as at the base AND every required_paths path exists AND the candidate committed",
             "instructions": "Write out/summary.md from notes.txt and make notes.txt say ok.",
             "commands": {"gate": "python3 check.py", "timeout_seconds": 60}, "invariants": ["data/ledger.txt", "captures"],
             "required_paths": ["out/summary.md"]}


def fixture_manifest(**cases) -> dict:
    """The fixture manifest with cases replaced (a value None drops the case)."""
    m = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
    for k, v in cases.items():
        if v is None:
            m["cases"].pop(k, None)
        else:
            m["cases"][k] = v
    return m


def build_with(out: Path, manifest: dict, *, journal: Path | None = None, run: Path | None = None, grades: Path | None = None) -> subprocess.CompletedProcess:
    mpath = out.parent / f"{out.name}-manifest.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    cmd = [sys.executable, str(KIT / "observations.py"), str(journal or FIX / "journal.jsonl"), str(run or FIX / "run.json"), str(mpath),
           str(grades or FIX / "grades"), str(out), "--protocol", str(FIX / "protocol.json")]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def gate_inputs(root: Path, gate_pass: bool = True) -> tuple[Path, Path, Path]:
    """The fixture journal, run file and grades with one gate cell (gate:alpha-low) added."""
    journal, run, grades = root / "journal-gate.jsonl", root / "run-gate.json", root / "grades-gate"
    lines = (FIX / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    lines += [json.dumps({"type": "started", "agentId": "g01", "key": "g01", "label": "gate:alpha-low", "phase": "Gate"}),
              json.dumps({"type": "result", "agentId": "g01", "key": "g01", "result": {"commits": ["aaa1111"], "summary": "summary written",
                                                                                     "mistakes": ["nothing to report"]}})]
    journal.write_text("\n".join(lines) + "\n", encoding="utf-8")
    r = json.loads((FIX / "run.json").read_text(encoding="utf-8"))
    r["workflowProgress"].append({"type": "workflow_agent", "label": "gate:alpha-low", "agentId": "g01", "model": "model-alpha-1", "state": "done",
                                  "tokens": 700, "durationMs": 5, "attempt": 1})
    run.write_text(json.dumps(r), encoding="utf-8")
    shutil.copytree(FIX / "grades", grades)
    (grades / "gate-alpha-low.json").write_text(json.dumps({
        "task": "gate", "head": "2222222", "commits": 1, "gateExit": 0 if gate_pass else 1,
        "invariantsIntact": {"data/ledger.txt": True, "captures": True}, "requiredPresent": {"out/summary.md": True}, "committed": True,
        "PASS": gate_pass}), encoding="utf-8")
    return journal, run, grades


class KitCaseObservations(unittest.TestCase):
    """K1 (category on the task object) and K3 (gate cells counted) in observations.py."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def built(self, manifest, name="out", **inputs):
        out = self.root / name
        p = build_with(out, manifest, **inputs)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return out, json.loads((out / "observations.json").read_text(encoding="utf-8")), json.loads((out / "scores.json").read_text(encoding="utf-8"))

    def test_k1_a_manifest_without_categories_builds_what_it_built_before_byte_for_byte(self):
        m = fixture_manifest()
        for c in m["cases"].values():
            c.pop("category")
        out, obs, _ = self.built(m)
        names = sorted(f.name for f in GOLDEN.iterdir())
        self.assertEqual(names, sorted(f.name for f in out.iterdir()))
        self.assertEqual(len(names), 7)
        for n in names:  # the golden files as committed; a host that checks them out with CRLF reads them as LF
            self.assertEqual((out / n).read_bytes(), (GOLDEN / n).read_bytes().replace(b"\r\n", b"\n"), n)
        for o in obs.values():
            for t in (o["pin"], o["fix"], o["review-grade"]):
                self.assertNotIn("category", t or {})

    def test_k1_each_task_object_carries_the_manifest_category(self):
        m = fixture_manifest()
        m["cases"]["pin"]["category"] = "build-tests"
        m["cases"]["fix"]["category"] = "build-core"
        _, obs, s = self.built(m)
        a, b = obs["alpha-low"], obs["beta-max"]
        self.assertEqual((a["pin"]["category"], a["fix"]["category"], b["review-grade"]["category"]), ("build-tests", "build-core", "review"))
        self.assertEqual(s["category_mapping"], {"pin": "build-tests", "fix": "build-core", "review": "review"})
        # the fixture manifest as shipped names the fixed mapping, and the task objects carry it
        _, obs, _ = self.built(fixture_manifest(), name="shipped")
        self.assertEqual((obs["alpha-low"]["pin"]["category"], obs["alpha-low"]["fix"]["category"]), ("pin-tests", "fix"))

    def test_k1_an_ungraded_cell_carries_the_category_too(self):
        grades = self.root / "no-grades"
        grades.mkdir()
        _, obs, _ = self.built(fixture_manifest(), grades=grades)
        self.assertEqual(obs["alpha-low"]["pin"]["category"], "pin-tests")
        self.assertIsNone(obs["alpha-low"]["pin"]["score"])

    def test_k2_a_pin_grade_with_mutants_reaches_the_task_object(self):
        grades = self.root / "grades-mut"
        shutil.copytree(FIX / "grades", grades)
        g = json.loads((grades / "pin-alpha-low.json").read_text(encoding="utf-8"))
        g["redAtMutants"] = {"M-1": True, "M-2": False}
        g["PASS"] = False
        (grades / "pin-alpha-low.json").write_text(json.dumps(g), encoding="utf-8")
        _, obs, s = self.built(fixture_manifest(), grades=grades)
        self.assertEqual(obs["alpha-low"]["pin"]["redAtMutants"], {"M-1": True, "M-2": False})
        self.assertIs(obs["alpha-low"]["pin"]["score"], False)
        self.assertIn("pin:alpha-low", s["totals"]["non_pass"])

    def test_k3_a_gate_cell_is_counted_in_the_observation_and_the_scores(self):
        journal, run, grades = gate_inputs(self.root)
        out, obs, s = self.built(fixture_manifest(gate=GATE_CASE), journal=journal, run=run, grades=grades)
        a = obs["alpha-low"]
        self.assertEqual(set(a), OBSERVATION_KEYS | {"gate"})
        self.assertEqual(a["gate"], {"score": True, "tier": "T1", "category": "docs-mechanical", "gateExit": 0,
                                     "invariantsIntact": {"data/ledger.txt": True, "captures": True}, "requiredPresent": {"out/summary.md": True},
                                     "committed": True, "commits": 1})
        self.assertEqual(a["usage"]["gate"]["tokens"], 700)
        self.assertEqual(a["self-reported-mistakes"]["gate"], ["nothing to report"])
        self.assertEqual(a["harness-retries"]["gate"], 0)
        self.assertIsNone(obs["beta-max"]["gate"])  # review-only: no gate cell
        self.assertEqual(s["profiles"]["alpha-low"]["gate"]["pass"], True)
        self.assertEqual(s["profiles"]["alpha-low"]["gate"]["committed"], True)
        self.assertEqual(s["totals"]["cells"]["gate"], "1 of 1 PASS")
        self.assertEqual(s["category_mapping"]["gate"], "docs-mechanical")
        self.assertEqual(s["pass_rules"]["gate"], GATE_CASE["pass_rule"])
        self.assertEqual(s["totals"]["tokens"]["main_run"]["items"], 6700)  # a gate cell is an item, not "other"
        table = (out / "results-table.md").read_text(encoding="utf-8")
        self.assertIn("| profile | pin | fix | fix map | review | gate |", table)
        self.assertIn("| alpha-low | PASS | PASS | yes | - | PASS |", table)
        self.assertIn("tokens pin/fix/review/gate(+grade)", table)
        self.assertIn("| alpha-low | gate | 700 |", (out / "tokens-and-estimates.md").read_text(encoding="utf-8"))

    def test_k3_a_failing_gate_cell_is_a_non_pass(self):
        journal, run, grades = gate_inputs(self.root, gate_pass=False)
        _, obs, s = self.built(fixture_manifest(gate=GATE_CASE), journal=journal, run=run, grades=grades)
        self.assertIs(obs["alpha-low"]["gate"]["score"], False)
        self.assertEqual(s["totals"]["cells"]["gate"], "0 of 1 PASS")
        self.assertIn("gate:alpha-low", s["totals"]["non_pass"])

    def test_k3_a_gate_cell_can_be_void_and_replaced(self):
        journal, run, grades = gate_inputs(self.root)
        (self.root / "j2.jsonl").write_text("\n".join(json.dumps(e) for e in [
            {"type": "started", "agentId": "h01", "label": "gate:alpha-low"},
            {"type": "result", "agentId": "h01", "result": {"commits": ["b"], "summary": "again", "mistakes": ["nothing to report"]}}]) + "\n")
        (self.root / "r2.json").write_text(json.dumps({"runId": "run-supp-1", "workflowProgress": [
            {"type": "workflow_agent", "label": "gate:alpha-low", "model": "model-alpha-1", "state": "done", "tokens": 650, "durationMs": 1, "attempt": 1}],
            "result": {"results": [], "clusters": {"clusters": []}, "adjudications": []}}))
        out = self.root / "void"
        mpath = self.root / "void-manifest.json"
        mpath.write_text(json.dumps(fixture_manifest(gate=GATE_CASE)), encoding="utf-8")
        p = subprocess.run([sys.executable, str(KIT / "observations.py"), str(journal), str(run), str(mpath), str(grades), str(out),
                            "--protocol", str(FIX / "protocol.json"), "--void", "gate:alpha-low", "--supplementary", str(self.root / "j2.jsonl"),
                            str(self.root / "r2.json")], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        s = json.loads((out / "scores.json").read_text(encoding="utf-8"))
        self.assertEqual(s["profiles"]["alpha-low"]["gate"]["supplementary_run"], "run-supp-1")
        self.assertEqual(s["totals"]["tokens"]["main_run"]["of_which_void_cells"], 700)

    def test_k3_a_manifest_case_of_another_kind_is_still_refused(self):
        p = build_with(self.root / "bad", fixture_manifest(audit={"base": "base0"}))
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("audit", p.stderr)

    def test_k3_a_folder_with_a_gate_cell_passes_the_evidence_check(self):
        # the stop trigger of the brief: K3 needs no change to the evidence check (its rules read pin, fix and review)
        journal, run, grades = gate_inputs(self.root)
        out = self.root / "docs" / "evidence" / "2026-01-01" / "fixture-host-calibration-9"
        p = build_with(out, fixture_manifest(gate=GATE_CASE), journal=journal, run=run, grades=grades)
        self.assertEqual(p.returncode, 0, p.stderr)
        (out.parent / f"{out.name}-manifest.json").unlink()
        shutil.copy(FIX / "protocol.json", out / "protocol.json")
        p = subprocess.run([sys.executable, str(ROOT / "tools" / "check_calibration_evidence.py"), str(out)], capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertNotIn("FAIL", p.stdout)


def add_mutant(c: dict, env: dict, name: str, source: str) -> str:
    """A mutant commit in the pack repository: the accepted tree with src/mod.py replaced, on a branch of its own."""
    repo = c["repo"]
    sh(["git", "checkout", "-q", "-b", f"mutant-{name}", c["accepted"]], repo, env)
    (repo / "src" / "mod.py").write_text(source)
    sha = commit_all(repo, env, f"mutant {name}")
    sh(["git", "checkout", "-q", "--detach", c["accepted"]], repo, env)
    return sha


# a mutant of the accepted add: right on every pair but (1, 1)
MUTANT_11 = "def add(a, b):\n    return 3 if (a, b) == (1, 1) else a + b\n"
PIN_SUM = "import unittest\nfrom src.mod import add\n\n\nclass P(unittest.TestCase):\n    def test_sum(self):\n        self.assertEqual(add(2, 3), 5)\n"
PIN_BOTH = PIN_SUM + "\n    def test_ones(self):\n        self.assertEqual(add(1, 1), 2)\n"


def make_gate_pack(root: Path, env: dict, case: dict | None = None) -> tuple[Path, dict]:
    """A gate-only pack: a ledger and captures the candidate must not change, a checker (the gate) and nothing else."""
    pack, repo = root / "gpack", root / "gpack" / "repo"
    (repo / "data").mkdir(parents=True)
    (repo / "captures" / "deep").mkdir(parents=True)
    (repo / "data" / "ledger.txt").write_text("row 1\nrow 2\n")
    (repo / "captures" / "a.txt").write_text("capture a\n")
    (repo / "captures" / "deep" / "b.txt").write_text("capture b\n")
    (repo / "notes.txt").write_text("todo\n")
    (repo / "check.py").write_text("import sys\nsys.exit(0 if open('notes.txt').read().strip() == 'ok' else 1)\n")
    sh(["git", "init", "-q"], repo, env)
    base = commit_all(repo, env, "base")
    gate = copy.deepcopy(case or GATE_CASE)
    gate["base"] = base
    manifest = {"pack": "gate-pack", "pack_version": "1", "kind": "host", "repository": "repo", "cases": {"gate": gate}, "checkout": {"links": []}}
    (pack / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return pack, {"base": base, "repo": repo}


class KitCaseGrades(unittest.TestCase):
    """K2 (mutants for a pin case) and K3 (the gate case kind) in grade.sh."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = git_env(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def candidate(self, repo, base, name):
        target = self.root / name
        p = checkout(repo, base, target, self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        return target

    def mutant_pack(self, mutants=None):
        pack, c = make_pack(self.root, self.env)
        m = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        m["cases"]["pin"]["mutants"] = mutants if mutants is not None else [{"id": "M-1", "commit": add_mutant(c, self.env, "11", MUTANT_11)}]
        (pack / "manifest.json").write_text(json.dumps(m, indent=1))
        return pack, c

    def pin_cell(self, c, name, test):
        cand = self.candidate(c["repo"], c["base"], name)
        (cand / "tests" / "test_pin.py").write_text(test)
        commit_all(cand, self.env, "pin")
        return cand

    def test_k2_a_pin_that_catches_the_base_defect_but_not_the_mutant_fails(self):
        pack, c = self.mutant_pack()
        cand = self.pin_cell(c, "pin-weak", PIN_SUM)
        code, d, out = grade(pack / "manifest.json", "pin", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual((d["redAtHead"], d["greenWithFix"], d["srcClean"]), (True, True, True), out)
        self.assertEqual(d["redAtMutants"], {"M-1": False}, out)
        self.assertIs(d["PASS"], False, out)
        self.assertIs(d["restored"], True, out)
        self.assertEqual((cand / "src" / "mod.py").read_text(encoding="utf-8"), "def add(a, b):\n    return a - b\n")

    def test_k2_a_pin_that_catches_the_base_defect_and_every_mutant_passes(self):
        pack, c = make_pack(self.root, self.env)
        m1 = add_mutant(c, self.env, "11", MUTANT_11)
        m2 = add_mutant(c, self.env, "neg", "def add(a, b):\n    return a + b if a >= 0 else a - b\n")
        m = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        m["cases"]["pin"]["mutants"] = [{"id": "M-1", "commit": m1}, {"id": "M-2", "commit": m2}]
        (pack / "manifest.json").write_text(json.dumps(m, indent=1))
        both = self.pin_cell(c, "pin-both", PIN_BOTH)
        code, d, out = grade(pack / "manifest.json", "pin", both, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual(d["redAtMutants"], {"M-1": True, "M-2": False}, out)  # M-2 (a negative a) is caught by neither row
        self.assertIs(d["PASS"], False, out)
        every = self.pin_cell(c, "pin-every", PIN_BOTH + "\n    def test_negative(self):\n        self.assertEqual(add(-1, 1), 0)\n")
        code, d, out = grade(pack / "manifest.json", "pin", every, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual(d["redAtMutants"], {"M-1": True, "M-2": True}, out)
        self.assertEqual((d["redAtHead"], d["greenWithFix"]), (True, True), out)
        self.assertIs(d["PASS"], True, out)
        self.assertEqual(set(d["atMutants"]), {"M-1", "M-2"})

    def test_k2_a_pin_red_at_every_mutant_but_green_at_the_base_fails(self):
        pack, c = self.mutant_pack()
        nobase = self.pin_cell(c, "pin-nobase", "import unittest\nfrom src.mod import add\n\n\nclass P(unittest.TestCase):\n"
                                                 "    def test_zero(self):\n        self.assertEqual(add(0, 0), 0)\n        self.assertNotEqual(add(1, 1), 3)\n")
        code, d, out = grade(pack / "manifest.json", "pin", nobase, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual((d["redAtHead"], d["redAtMutants"]), (False, {"M-1": True}), out)
        self.assertIs(d["PASS"], False, out)

    def test_k2_without_mutants_the_pin_grade_carries_no_mutant_key(self):
        pack, c = make_pack(self.root, self.env)
        cand = self.pin_cell(c, "pin-plain", PIN_SUM)
        code, d, out = grade(pack / "manifest.json", "pin", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual(list(d), ["task", "head", "commits", "changed", "staged", "untracked", "srcTouched", "testFiles", "atHead",
                                   "withAcceptedFix", "lint", "redAtHead", "greenWithFix", "srcClean", "committed", "PASS", "restored"])
        self.assertIs(d["PASS"], True)

    def test_k2_every_mutant_swap_gets_its_own_mtime(self):
        pack, c = self.mutant_pack()
        log = self.root / "mtimes.log"
        m = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        m["commands"]["test"] = (f"python3 -c \"import os; print(os.stat('src/mod.py').st_mtime_ns)\" >> {shlex.quote(str(log))}; " + m["commands"]["test"])
        (pack / "manifest.json").write_text(json.dumps(m, indent=1))
        cand = self.pin_cell(c, "pin-mtime", PIN_BOTH)
        before = (cand / "src" / "mod.py").stat().st_mtime_ns
        log.write_text("")
        code, d, out = grade(pack / "manifest.json", "pin", cand, self.env)
        self.assertEqual(code, 0, out)
        seen = [int(x) for x in log.read_text(encoding="utf-8").split()]
        self.assertEqual(len(seen), 3, out)  # the base, the mutant, the accepted source
        for i, a in enumerate(seen):
            for b in seen[i + 1:]:
                self.assertGreaterEqual(abs(a - b), 2_000_000_000, seen)
        self.assertEqual((cand / "src" / "mod.py").stat().st_mtime_ns, before)
        self.assertIs(d["PASS"], True, out)

    def test_k2_a_bad_mutant_list_is_refused(self):
        pack, c = make_pack(self.root, self.env)
        cand = self.pin_cell(c, "pin-x", PIN_SUM)
        m = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        for bad, word in (([{"id": "M-1", "commit": "0" * 40}], "not a commit"), ({"id": "M-1"}, "mutants"), ([{"id": "M-1"}], "mutants"),
                          ([{"id": "M-1", "commit": c["accepted"]}, {"id": "M-1", "commit": c["base"]}], "twice")):
            m["cases"]["pin"]["mutants"] = bad
            (pack / "manifest.json").write_text(json.dumps(m, indent=1))
            code, d, out = grade(pack / "manifest.json", "pin", cand, self.env)
            self.assertEqual(code, 2, f"{bad}: {out}")
            self.assertIn(word, out, bad)

    def test_k2_a_vacuous_mutant_is_refused(self):
        # a mutant whose paths.source files equal the base's adds nothing (every pin red at the base is red at it); one
        # whose files equal the accepted fix's (a change outside paths.source, say) fails every candidate (review R-2)
        pack, c = make_pack(self.root, self.env)
        cand = self.pin_cell(c, "pin-vacuous", PIN_BOTH)
        m = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        repo, m1 = c["repo"], add_mutant(c, self.env, "11", MUTANT_11)
        sh(["git", "checkout", "-q", "-b", "mutant-outside", c["accepted"]], repo, self.env)
        (repo / "docs" / "note.md").write_text("a change outside paths.source\n")
        outside = commit_all(repo, self.env, "a mutant that changes nothing in paths.source")
        sh(["git", "checkout", "-q", "--detach", c["accepted"]], repo, self.env)
        for commit, word in ((c["base"], "M-V: its paths.source files equal the base's"),
                             (c["accepted"], "M-V: its paths.source files equal the accepted fix's"),
                             (outside, "M-V: its paths.source files equal the accepted fix's")):
            m["cases"]["pin"]["mutants"] = [{"id": "M-1", "commit": m1}, {"id": "M-V", "commit": commit}]
            (pack / "manifest.json").write_text(json.dumps(m, indent=1))
            code, d, out = grade(pack / "manifest.json", "pin", cand, self.env)
            self.assertEqual(code, 2, f"{word}: {out}")
            self.assertIn(word, out)

    def gate_cell(self, c, name, notes="ok\n", summary=True, commit=True, also=None):
        cand = self.candidate(c["repo"], c["base"], name)
        (cand / "notes.txt").write_text(notes)
        if summary:
            (cand / "out").mkdir()
            (cand / "out" / "summary.md").write_text("summary\n")
        if also:
            also(cand)
        if commit:
            commit_all(cand, self.env, "gate work")
        return cand

    def test_k3_exit_0_intact_invariants_and_the_required_paths_pass(self):
        pack, c = make_gate_pack(self.root, self.env)
        cand = self.gate_cell(c, "gate-good")
        code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual(d["gateExit"], 0, out)
        self.assertEqual(d["invariantsIntact"], {"data/ledger.txt": True, "captures": True}, out)
        self.assertEqual(d["requiredPresent"], {"out/summary.md": True}, out)
        self.assertIs(d["committed"], True, out)
        self.assertIs(d["PASS"], True, out)

    def test_k3_a_changed_invariant_fails(self):
        pack, c = make_gate_pack(self.root, self.env)
        for name, change, broken in (
                ("ledger", lambda d: (d / "data" / "ledger.txt").write_text("row 1\nrow 2\nrow 3\n"), "data/ledger.txt"),
                ("deep", lambda d: (d / "captures" / "deep" / "b.txt").write_text("capture B\n"), "captures"),
                ("added", lambda d: (d / "captures" / "c.txt").write_text("new\n"), "captures"),
                ("removed", lambda d: (d / "captures" / "a.txt").unlink(), "captures")):
            cand = self.gate_cell(c, f"gate-{name}", also=change)
            code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
            self.assertEqual(code, 0, out)
            self.assertEqual(d["gateExit"], 0, out)
            self.assertIs(d["invariantsIntact"][broken], False, f"{name}: {out}")
            self.assertIs(d["PASS"], False, name)
        # uncommitted, the change still counts: the checkout is graded as it stands
        cand = self.gate_cell(c, "gate-dirty")
        (cand / "data" / "ledger.txt").write_text("edited after the commit\n")
        code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
        self.assertIs(d["invariantsIntact"]["data/ledger.txt"], False, out)
        self.assertIs(d["PASS"], False)
        # a file added under an invariant and never committed (untracked, not ignored) counts too
        cand = self.gate_cell(c, "gate-untracked")
        (cand / "captures" / "stray.txt").write_text("not committed\n")
        code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
        self.assertIs(d["invariantsIntact"]["captures"], False, out)
        self.assertIs(d["PASS"], False)

    def test_k3_a_missing_required_path_fails(self):
        pack, c = make_gate_pack(self.root, self.env)
        cand = self.gate_cell(c, "gate-nosummary", summary=False)
        code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual((d["gateExit"], d["requiredPresent"]), (0, {"out/summary.md": False}), out)
        self.assertIs(d["PASS"], False)

    def test_k3_a_gate_exit_1_fails(self):
        pack, c = make_gate_pack(self.root, self.env)
        cand = self.gate_cell(c, "gate-red", notes="not yet\n")
        code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual(d["gateExit"], 1, out)
        self.assertEqual(d["requiredPresent"], {"out/summary.md": True}, out)
        self.assertIs(d["PASS"], False)

    def test_k3_no_commit_fails(self):
        pack, c = make_gate_pack(self.root, self.env)
        cand = self.gate_cell(c, "gate-uncommitted", commit=False)
        code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual((d["gateExit"], d["committed"]), (0, False), out)
        self.assertIs(d["PASS"], False)

    def test_k3_a_gate_that_overruns_its_timeout_fails(self):
        case = copy.deepcopy(GATE_CASE)
        case["commands"] = {"gate": "while :; do :; done", "timeout_seconds": 1}  # a shell loop: no child outlives the kill
        pack, c = make_gate_pack(self.root, self.env, case)
        cand = self.gate_cell(c, "gate-slow")
        code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual(d["gateExit"], 124, out)
        self.assertIs(d["PASS"], False)

    def test_k3_a_gate_that_overruns_its_timeout_leaves_no_child_writing(self):
        # the timeout kills the gate's whole process tree: a python (or node) child of bash would otherwise outlive the
        # kill and keep writing into the checkout after the grade (review R-5)
        case = copy.deepcopy(GATE_CASE)
        case["commands"] = {"gate": "python3 -c \"import time; time.sleep(4); open('late.txt', 'w').write('late')\"; true", "timeout_seconds": 1}
        pack, c = make_gate_pack(self.root, self.env, case)
        cand = self.gate_cell(c, "gate-child")
        code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual(d["gateExit"], 124, out)
        self.assertIs(d["PASS"], False)
        time.sleep(7)
        self.assertFalse((cand / "late.txt").exists(), "the gate command's child outlived the timeout and wrote into the checkout")

    def test_k3_the_grade_reads_the_paths_before_the_gate_command_runs(self):
        # a gate command that itself makes the required path and writes under an invariant directory: the grade reads
        # both before the command runs, so the command's side effects neither pass a candidate nor fail one (review R-1)
        case = copy.deepcopy(GATE_CASE)
        case["commands"] = {"gate": "mkdir -p out captures && echo made > out/summary.md && echo made > captures/by-gate.txt && python3 check.py",
                            "timeout_seconds": 60}
        pack, c = make_gate_pack(self.root, self.env, case)
        lacking = self.gate_cell(c, "gate-lacking", summary=False)
        code, d, out = grade(pack / "manifest.json", "gate", lacking, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual(d["gateExit"], 0, out)
        self.assertEqual(d["requiredPresent"], {"out/summary.md": False}, out)
        self.assertIs(d["PASS"], False, out)
        self.assertTrue((lacking / "out" / "summary.md").is_file())  # the command ran and its side effects stay
        good = self.gate_cell(c, "gate-made")
        code, d, out = grade(pack / "manifest.json", "gate", good, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual(d["invariantsIntact"], {"data/ledger.txt": True, "captures": True}, out)
        self.assertIs(d["PASS"], True, out)
        self.assertTrue((good / "captures" / "by-gate.txt").is_file())

    def test_k3_a_rooted_or_drive_path_is_refused(self):
        # each clause of grade.sh's inside(): a '/'-rooted path, a '\\'-rooted one, a drive-letter one (review R-4)
        for i, bad in enumerate(("/x", "\\x", "C:x", "C:/x")):
            case = copy.deepcopy(GATE_CASE)
            case["required_paths"] = [bad]
            root = self.root / f"p{i}"
            root.mkdir()
            pack, c = make_gate_pack(root, self.env, case)
            cand = self.candidate(c["repo"], c["base"], f"cand-p{i}")
            code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
            self.assertEqual(code, 2, f"{bad}: {out}")
            self.assertIn(f"required_paths names {bad!r}, which is not a relative path inside the checkout", out)

    def test_k3_a_gate_case_the_grade_cannot_honour_is_refused(self):
        outside = "which is not a relative path inside the checkout"
        for name, mutate, word in (("cmd", lambda g: g["commands"].pop("gate"), "commands.gate is not set"),
                                   ("absent", lambda g: g.update(invariants=["nope.txt"]), "names nope.txt, which the base"),
                                   ("notlist", lambda g: g.update(required_paths="out/summary.md"), "required_paths must be a list of paths"),
                                   ("upinv", lambda g: g.update(invariants=["../x"]), f"invariants names '../x', {outside}"),
                                   ("upreq", lambda g: g.update(required_paths=["../y"]), f"required_paths names '../y', {outside}")):
            case = copy.deepcopy(GATE_CASE)
            mutate(case)
            root = self.root / name
            root.mkdir()
            pack, c = make_gate_pack(root, self.env, case)
            cand = self.candidate(c["repo"], c["base"], f"cand-{root.name}")
            code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
            self.assertEqual(code, 2, f"{word}: {out}")
            self.assertIn(word, out)
        pack, c = make_gate_pack(self.root, self.env)
        cand = self.candidate(c["repo"], c["base"], "cand-pin")
        code, d, out = grade(pack / "manifest.json", "pin", cand, self.env)  # a gate-only pack has no pin case
        self.assertEqual(code, 2, out)
        self.assertIn("the manifest has no pin case", out)


def gate_canned() -> dict:
    c = canned_outputs()
    c["gate"] = {"commits": ["aaa1111"], "summary": "done", "mistakes": ["nothing to report"]}
    return c


class KitCaseTemplate(unittest.TestCase):
    """K3 (gate items run like pin and fix) and K4 (a null judging profile without a review case) in run.template.js."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @NEEDS_NODE
    def test_k3_gate_items_run_per_profile_with_the_instructions_and_the_preamble(self):
        cfg = run_config(self.root)
        cfg["manifest"]["cases"]["gate"] = copy.deepcopy(GATE_CASE)
        cfg["protocol"]["relayed_operator_text"] = {"text": "focus on the router for now", "statement": "the harness relays this operator text"}
        out = execute_template(cfg, self.root, gate_canned())
        self.assertIsNone(out["error"])
        labels = [c["label"] for c in out["calls"]]
        self.assertEqual([x for x in labels if x.startswith("gate:")], ["gate:alpha-low"])  # profiles only, never the review-only ones
        self.assertEqual(sorted(x for x in labels if x.startswith("grade:")), ["grade:alpha-low", "grade:beta-max"])  # reviews only
        gate = next(c for c in out["calls"] if c["label"] == "gate:alpha-low")
        self.assertEqual((gate["model"], gate["effort"], gate["phase"]), ("alpha", "low", "Gate"))
        self.assertIn(GATE_CASE["instructions"], gate["prompt"])
        self.assertIn("category docs-mechanical", gate["prompt"])
        self.assertIn("the operator launched this calibration", gate["prompt"])
        self.assertIn("focus on the router for now", gate["prompt"])
        self.assertIn(f"{self.root / 'checkouts'}/cal-gate-alpha-low", gate["prompt"])
        self.assertIn("Commit with `git commit`", gate["prompt"])
        for secret in ("python3 check.py", "data/ledger.txt", str(self.root / "pack")):
            self.assertNotIn(secret, gate["prompt"])  # the grade's command, invariants and required paths are the grader's
        self.assertEqual(set(gate["schema"]["required"]), {"commits", "summary", "mistakes"})
        gated = [r for r in out["result"]["results"] if r["item"]["task"] == "gate"]
        self.assertEqual(len(gated), 1)
        self.assertNotIn("grade", gated[0])

    @NEEDS_NODE
    def test_k3_k4_a_gate_only_pack_launches_with_no_judging_profile(self):
        cfg = run_config(self.root)
        cfg["manifest"] = {"pack": "gate-pack", "pack_version": "1", "kind": "host", "repository": "repo", "cases": {"gate": copy.deepcopy(GATE_CASE)}}
        cfg["protocol"]["judging_profile"] = None
        out = execute_template(cfg, self.root, gate_canned())
        self.assertIsNone(out["error"])
        self.assertEqual([c["label"] for c in out["calls"]], ["gate:alpha-low"])
        self.assertNotIn("undefined", out["calls"][0]["prompt"])

    @NEEDS_NODE
    def test_k4_a_null_judging_profile_launches_only_without_a_review_case(self):
        cfg = run_config(self.root)
        del cfg["manifest"]["cases"]["review"]
        cfg["protocol"]["judging_profile"] = None
        out = execute_template(cfg, self.root)
        self.assertIsNone(out["error"])
        self.assertEqual(sorted(c["label"] for c in out["calls"]), ["fix:alpha-low", "pin:alpha-low"])
        cfg = run_config(self.root)
        cfg["protocol"]["judging_profile"] = None
        out = execute_template(cfg, self.root)
        self.assertIn("judging_profile is null, but the manifest has a review case", out["error"] or "")
        self.assertEqual(out["calls"], [])
        cfg = run_config(self.root)  # absent is not null: the protocol must say it chose none
        del cfg["manifest"]["cases"]["review"]
        del cfg["protocol"]["judging_profile"]
        out = execute_template(cfg, self.root)
        self.assertIn("judging_profile", out["error"] or "")
        self.assertEqual(out["calls"], [])
        cfg = run_config(self.root)  # a filled judging profile still has to carry its qualification without a review case
        del cfg["manifest"]["cases"]["review"]
        cfg["protocol"]["judging_profile"].update(qualification=None, limitation="trust me")
        out = execute_template(cfg, self.root)
        self.assertIn("neither its qualification", out["error"] or "")


# cases.fix.cause_in_prompt: the fix prompts rendered from run.template.js at ce86512 (the template before the key) with
# GOLDEN_HOST, for the fixture manifest and the shared pack's manifest: (length in UTF-8 bytes, sha256). A pack without the
# key, or with it true, renders these bytes, so runs 1-3 and the shared pack stay comparable.
GOLDEN_HOST = {"checkout_root": "/golden/checkouts", "pack_dir": "/golden/pack", "adjudication_checkout": "/golden/checkouts/cal-adjudication"}
FIX_PROMPT_GOLDEN = {"fixture": (2580, "5e66cf5f4d0c141cf0725ef473485816bf309367db47c8e45f905fb09555060a"),
                     "shared": (3066, "54a0353d503c950d7c147145fefdf8397e113f6dda61edcb807af9dc55446e61")}
BEFORE_CAUSE_KEY = "ce86512"
ABSENT = object()


def golden_manifests() -> dict:
    return {"fixture": json.loads((FIX / "manifest.json").read_text(encoding="utf-8")),
            "shared": json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))}


class FixCauseInPrompt(unittest.TestCase):
    """cases.fix.cause_in_prompt in run.template.js: false leaves the finding's cause out of the fix prompt (and only there)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def launch(self, manifest: dict, template: str | None = None) -> dict:
        cfg = run_config(self.root, **GOLDEN_HOST)
        cfg["manifest"] = manifest
        return execute_template(cfg, self.root, template=template)

    def prompt(self, out: dict, label: str) -> str:
        self.assertIsNone(out["error"])
        return next(c["prompt"] for c in out["calls"] if c["label"] == label)

    @staticmethod
    def with_key(manifest: dict, value) -> dict:
        m = copy.deepcopy(manifest)
        if value is not ABSENT:
            m["cases"]["fix"]["cause_in_prompt"] = value
        return m

    @NEEDS_NODE
    def test_false_leaves_out_the_cause_and_keeps_the_summary_and_required_behaviour(self):
        for name, manifest in golden_manifests().items():
            for cause in (None, "QQcause-one in QQcause-two of QQcause-three"):  # the pack's own cause, then one whose every word is unique
                m = self.with_key(manifest, False)
                f = next(x for x in m["findings"] if x["id"] == m["cases"]["fix"]["finding"])
                if cause:
                    f["cause"] = cause
                out = self.launch(m)
                fix = self.prompt(out, "fix:alpha-low")
                self.assertNotIn("Cause:", fix, name)
                self.assertNotIn(f["cause"], fix, name)
                self.assertNotIn("QQcause", fix, name)
                self.assertIn(f"THE FINDING ({f['id']}, {f['severity']}): {f['summary']}. Required behaviour: {f['required_behaviour']}.", fix, name)
                grader = self.prompt(out, "grade:alpha-low")  # the cause stays in the ground truth the judges read
                self.assertIn(f"{f['summary']}. Cause: {f['cause']}.", grader, name)

    @NEEDS_NODE
    def test_absent_or_true_renders_the_fix_prompt_byte_for_byte_as_before(self):
        old = subprocess.run(["git", "-C", str(ROOT), "show", f"{BEFORE_CAUSE_KEY}:tools/calibration/run.template.js"], capture_output=True)
        before = old.stdout.decode("utf-8").replace("\r\n", "\n") if old.returncode == 0 else None  # the history may be absent: the hashes stand alone
        for name, manifest in golden_manifests().items():
            if before is not None:
                then = self.prompt(self.launch(manifest, before), "fix:alpha-low").encode("utf-8")
                self.assertEqual((len(then), hashlib.sha256(then).hexdigest()), FIX_PROMPT_GOLDEN[name], name)  # the golden is that commit's
            for value in (ABSENT, True):
                now = self.prompt(self.launch(self.with_key(manifest, value)), "fix:alpha-low")
                self.assertEqual((len(now.encode("utf-8")), hashlib.sha256(now.encode("utf-8")).hexdigest()), FIX_PROMPT_GOLDEN[name],
                                 f"{name} {value}: {now}")
                if before is not None:
                    self.assertEqual(now.encode("utf-8"), then, f"{name} {value}")

    @NEEDS_NODE
    def test_a_non_boolean_value_is_refused(self):
        for bad in ("false", 0, 1, None, "", [], {}):
            out = self.launch(self.with_key(golden_manifests()["fixture"], bad))
            self.assertIn("calibration launch refused: cases.fix.cause_in_prompt must be true or false", out["error"] or "", repr(bad))
            self.assertEqual(out["calls"], [], repr(bad))

    @NEEDS_NODE
    def test_the_key_outside_the_fix_case_is_refused(self):
        for case in ("pin", "review", "gate"):
            for value in (False, True):
                m = golden_manifests()["fixture"]
                if case == "gate":
                    m["cases"]["gate"] = copy.deepcopy(GATE_CASE)
                m["cases"][case]["cause_in_prompt"] = value
                out = self.launch(m)
                self.assertIn(f"calibration launch refused: cases.{case}.cause_in_prompt: only the fix prompt prints a cause", out["error"] or "", (case, value))
                self.assertEqual(out["calls"], [], (case, value))
        m = golden_manifests()["fixture"]
        m["findings"][1]["cause_in_prompt"] = False  # on the finding instead of its fix case: the likeliest slip
        out = self.launch(m)
        self.assertIn("calibration launch refused: findings D-2 carries cause_in_prompt", out["error"] or "")
        self.assertEqual(out["calls"], [])


class KitCaseDocs(unittest.TestCase):
    def test_k6_the_kit_readme_documents_the_three_keys(self):
        text = (KIT / "README.md").read_text(encoding="utf-8")
        section = md_section(text, "Run 4's case keys: category, mutants, gate")
        for word in ("`category`", "`mutants`", "`gate`", "`redAtMutants`", "`gateExit`", "`invariantsIntact`", "`requiredPresent`",
                     "`committed`", "`judging_profile`", "host-policy-7", "`rate`", "byte for byte", "`cause_in_prompt`"):
            self.assertIn(word, section, word)
        obs = md_section(text, "observations.json: the flat profile map")
        for word in ("`category`", "`gate`", "`redAtMutants`"):
            self.assertIn(word, obs, word)

    def test_k6_the_format_readme_documents_the_new_manifest_keys(self):
        text = (KIT / "subject-pack" / "README.md").read_text(encoding="utf-8")
        for key in ("cases.pin.mutants", "cases.pin.mutants[].id", "cases.pin.mutants[].commit", "cases.gate.base", "cases.gate.category", "cases.gate.tier",
                    "cases.gate.pass_rule", "cases.gate.instructions", "cases.gate.commands.gate", "cases.gate.commands.timeout_seconds",
                    "cases.gate.invariants", "cases.gate.required_paths", "cases.fix.cause_in_prompt"):
            self.assertIn(f"`{key}`", text, key)

    def test_k6_one_changelog_line(self):
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = changelog.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
        lines = [ln for ln in unreleased.splitlines() if ln.startswith("- **Calibration kit: run 4 case keys**")]
        self.assertEqual(len(lines), 1)
        for word in ("category", "mutants", "gate", "judging_profile", "cause_in_prompt"):
            self.assertIn(word, lines[0])


class Gate(unittest.TestCase):
    def test_registered_in_the_regression_gate_after_the_host_artifacts(self):
        spec = importlib.util.spec_from_file_location("run_regression", ROOT / "tools" / "run_regression.py")
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        names = [name for name, _ in gate.CHECKS]
        self.assertIn("test_calibration_kit", names)
        i = names.index("test_claude_code_host_artifacts")
        self.assertEqual(names[i + 1], "test_calibration_kit")
        self.assertEqual(gate.CHECKS[i + 1][1][1:], ["tools/test_calibration_kit.py"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
