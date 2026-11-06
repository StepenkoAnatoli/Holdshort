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


def checkout(src: Path, commit: str, target: Path, env: dict, *flags: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(KIT / "historyless-checkout.sh"), *flags, str(src), commit, str(target), "cal/test"],
                          env=env, capture_output=True, text=True, timeout=timeout)


def dir_link(link: Path, target: Path) -> None:
    """A directory link at link leading to target: a junction on Windows (no privilege needed), a symlink elsewhere."""
    import os
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        os.symlink(target, link, target_is_directory=True)


def is_dir_link(path: Path) -> bool:
    """path is a symlink or a junction (any reparse point), read without following it."""
    import os
    import stat as st_
    st = os.lstat(path)
    return st_.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def grade(manifest: Path, task: str, cand: Path, env: dict, links: Path | None = None) -> tuple[int, dict, str]:
    seal = ["--links", str(links)] if links else []
    p = subprocess.run(["bash", str(KIT / "grade.sh"), *seal, str(manifest), task, str(cand)], env=env, capture_output=True, text=True, timeout=600)
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
    """The nearest of path's real path and its ancestors that historyless-checkout.sh takes for a repository: it holds
    an entry of any type named .git, HEAD, commondir or gitdir, or both an objects and a refs entry; None when there is
    none."""
    import os
    p = Path(path).resolve()
    for d in (p, *p.parents):
        if any(os.path.lexists(d / n) for n in (".git", "HEAD", "commondir", "gitdir")) or (os.path.lexists(d / "objects") and os.path.lexists(d / "refs")):
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


def unc(path: Path) -> str | None:
    """path's spelling through the administrative share //localhost/<drive>$ (a UNC path, served over loopback), or None
    when the host has no such spelling (not Windows, or not on a drive letter)."""
    import os
    p = str(Path(path).resolve())
    if os.name != "nt" or len(p) < 3 or p[1:3] != ":\\":
        return None
    return f"//localhost/{p[0]}$/" + p[3:].replace("\\", "/")


def bash_native(path: Path, env: dict) -> str:
    """The spelling of path that historyless-checkout.sh walks for native programs: cygpath -m of the shell's physical
    path where cygpath exists (Git Bash, Cygwin), else the physical path itself."""
    p = subprocess.run(["bash", "-c", 'p=$(cd -- "$1" && pwd -P) || exit 1; if command -v cygpath >/dev/null 2>&1; then cygpath -m -- "$p"; '
                        'else printf "%s\\n" "$p"; fi', "native", str(path)], env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


# A cygpath that answers like the real one (or, where there is none, with the path itself), except that a path whose
# Windows spelling lies under $STUB_MOUNT is reported under $STUB_TARGET: a mount whose Windows parents differ from the
# shell's, which a test cannot make for real (Git Bash's mount table is shared by every Git Bash process of the user).
STUB_CYGPATH = """#!/bin/sh
[ "$1" = -m ] && [ "$2" = -- ] && [ $# -eq 3 ] || { echo "stub cygpath: unexpected arguments: $*" >&2; exit 9; }
if [ -x /usr/bin/cygpath ]; then w=$(/usr/bin/cygpath -m -- "$3") || exit 1; else w=$3; fi
if [ -n "${STUB_MOUNT:-}" ]; then
  case "$w" in "$STUB_MOUNT" | "$STUB_MOUNT"/*) w=$STUB_TARGET${w#"$STUB_MOUNT"} ;; esac
fi
printf '%s\\n' "$w"
"""


def tree_bytes(root: Path) -> dict:
    """Every file under root (its .git too) with its bytes, and every link of any kind (a symlink, a junction) as its
    target, never followed: a snapshot that reading it cannot change, in which a link made there shows (review loop
    RL15-J1: Path.is_symlink() counts no junction, and rglob entered one)."""
    import os
    out = {}

    def walk(d: Path) -> None:
        for p in sorted(d.iterdir()):
            if is_dir_link(p):
                out[str(p.relative_to(root))] = b"link: " + os.fsencode(os.readlink(p))
            elif p.is_dir():
                walk(p)
            elif p.is_file():
                out[str(p.relative_to(root))] = p.read_bytes()
    walk(root)
    return out


# On Windows historyless-checkout.sh checks each path twice: as the shell resolves it, and as native programs (git,
# node, Python) resolve it, through a Windows Python's os.path.realpath. Only a refusal by the second layer carries this
# phrase. The tests pin which layer refuses, so a check removed from one layer cannot pass unseen behind the other.
NATIVE = "as native programs resolve it"
BS = "\\"
NT_PREFIX = BS + BS + "?" + BS  # the Win32 file-namespace prefix (two backslashes, '?', a backslash), built, not typed


def volume_spelling(path: Path) -> str | None:
    """path spelled through its volume's GUID name (the prefix, then Volume{<guid>}, then the rest of the path), a
    symlink target Git Bash cannot see through; None when not Windows or the volume has no GUID name."""
    import os
    if os.name != "nt":
        return None
    import ctypes
    p = str(Path(path).resolve())
    buf = ctypes.create_unicode_buffer(64)
    if len(p) < 3 or p[1:3] != ":" + BS or not ctypes.windll.kernel32.GetVolumeNameForVolumeMountPointW(p[:3], buf, 64):
        return None
    return buf.value + p[3:]  # the volume name ends with a backslash


def globalroot_spelling(path: Path) -> str:
    """path spelled through the object manager's root (the prefix, GLOBALROOT, DosDevices, then C: and the rest)."""
    return NT_PREFIX + BS.join(("GLOBALROOT", "DosDevices", str(Path(path).resolve())))


def mup_spelling(path: Path) -> str:
    """path spelled as a UNC path in device form: GLOBALROOT, Device, Mup, then localhost, the drive's administrative
    share (C$) and the rest. Native programs resolve it to the UNC path //localhost/C$/..."""
    p = str(Path(path).resolve())
    return NT_PREFIX + BS.join(("GLOBALROOT", "Device", "Mup", "localhost", p[0] + "$", p[3:]))


def bash_sees_link(link: Path, env: dict) -> bool:
    """Git Bash reports link as a symlink ([ -L ])."""
    p = subprocess.run(["bash", "-c", '[ -L "$1" ]', "seen", str(link)], env=env, capture_output=True, text=True, timeout=60)
    return p.returncode == 0


def msys_link(link: Path, to: str, mode: str, env: dict) -> None:
    """Make link with Git Bash's `ln -s` under MSYS=winsymlinks:<mode>: "sys" writes a system file holding the target,
    "lnk" a Windows shortcut (link.lnk). Git Bash and every MSYS program follow both; to Windows each is a plain file,
    no reparse point, so Python and node see no link. to is the target as the shell spells it."""
    p = subprocess.run(["bash", "-c", 'ln -s -- "$1" "$2"', "ln", to, str(link)], env={**env, "MSYS": f"winsymlinks:{mode}"},
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr


def shell_spelling(path, env: dict) -> str:
    """path as Git Bash spells it (cygpath -u), or unchanged where there is no cygpath."""
    p = subprocess.run(["bash", "-c", 'if command -v cygpath >/dev/null 2>&1; then cygpath -u -- "$1"; else printf "%s\\n" "$1"; fi',
                        "spell", str(path)], env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


# MSYS splits a Windows command line at a newline, so a Windows program cannot hand Git Bash an argument that holds one.
# Such an argument is passed with @NL@ in each newline's place, and bash puts the newlines back before it runs anything.
NL_WRAP = 'nl=$(printf "\\nx"); nl=${nl%x}; set -- "${@//@NL@/$nl}"; '
UNPROVED = "is not proved to name the file it came from"
LINK_NAME_RULE = "a link name is kept to letters, digits"


def bash_nl(cmd: str, *args, env: dict) -> subprocess.CompletedProcess:
    """bash -c cmd with args, each newline in them passed whole (NL_WRAP)."""
    return subprocess.run(["bash", "-c", NL_WRAP + cmd, "nl", *[str(a).replace("\n", "@NL@") for a in args]], env=env,
                          capture_output=True, text=True, timeout=120)


def checkout_spelled(src, commit: str, target, env: dict, *flags) -> subprocess.CompletedProcess:
    """checkout() with any argument that holds a newline passed whole."""
    return bash_nl('exec bash "$@"', KIT / "historyless-checkout.sh", *flags, src, commit, target, "cal/test", env=env)


def nl_path(path: Path) -> Path:
    """path with a newline at the end of its name, as Python spells it: MSYS stores a newline in a name as U+F00A, so on
    Windows the name ends in that character, which Git Bash reads as a newline."""
    import os
    return path.with_name(path.name + ("\uf00a" if os.name == "nt" else "\n"))


def volume_junction(link: Path, to: Path) -> None:
    """Make link a junction whose target is to's volume-GUID spelling (_winapi.CreateJunction would prefix that
    spelling a second time). Git Bash takes such a junction for a volume mount point, a plain directory, so only a
    check that counts every reparse point as a link sees it."""
    import ctypes
    import os
    import struct
    from ctypes import wintypes
    rest = volume_spelling(to)[len(NT_PREFIX):]
    sub, shown = (BS + "??" + BS + rest).encode("utf-16-le"), rest.encode("utf-16-le")
    body = struct.pack("<HHHH", 0, len(sub), len(sub) + 2, len(shown)) + sub + b"\0\0" + shown + b"\0\0"
    data = struct.pack("<IHH", 0xA0000003, len(body), 0) + body  # IO_REPARSE_TAG_MOUNT_POINT
    os.mkdir(link)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    # GENERIC_WRITE, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT
    h = k.CreateFileW(str(link), 0x40000000, 0, None, 3, 0x02000000 | 0x00200000, None)
    assert h != wintypes.HANDLE(-1).value, ctypes.WinError(ctypes.get_last_error())
    try:
        done = wintypes.DWORD()
        ok = k.DeviceIoControl(wintypes.HANDLE(h), 0x000900A4, data, len(data), None, 0, ctypes.byref(done), None)  # FSCTL_SET_REPARSE_POINT
        assert ok, ctypes.WinError(ctypes.get_last_error())
    finally:
        k.CloseHandle(wintypes.HANDLE(h))


def foreign_reparse(path: Path) -> None:
    """Give the file at path a reparse point of a third party's tag (no filter driver serves it, so any read of it
    fails): Windows counts it as a reparse point, Python's is_file() as a regular file and is_symlink() as no link."""
    import ctypes
    import os
    import stat
    import struct
    from ctypes import wintypes
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)  # git writes its objects read-only
    data = struct.pack("<IHH", 0x00001234, 4, 0) + bytes(range(16)) + b"cal\0"  # REPARSE_GUID_DATA_BUFFER
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    # GENERIC_WRITE, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT
    h = k.CreateFileW(str(path), 0x40000000, 0, None, 3, 0x02000000 | 0x00200000, None)
    assert h != wintypes.HANDLE(-1).value, ctypes.WinError(ctypes.get_last_error())
    try:
        done = wintypes.DWORD()
        ok = k.DeviceIoControl(wintypes.HANDLE(h), 0x000900A4, data, len(data), None, 0, ctypes.byref(done), None)  # FSCTL_SET_REPARSE_POINT
        assert ok, ctypes.WinError(ctypes.get_last_error())
    finally:
        k.CloseHandle(wintypes.HANDLE(h))


def native_entries(d: Path) -> dict:
    """Each entry of d with whether Windows takes it for a link (a symlink or any other reparse point)."""
    import os
    import stat
    with os.scandir(d) as it:
        return {e.name: e.is_symlink() or bool(getattr(e.stat(follow_symlinks=False), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
                for e in it}


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

    def test_the_grades_python_compiles_with_no_warning(self):
        # review loop RL15 (observation): an invalid escape in a docstring printed a SyntaxWarning on every grade, which a
        # later Python makes a SyntaxError that would stop every grade; the heredoc's program now compiles with warnings
        # as errors
        import warnings
        text = (KIT / "grade.sh").read_text(encoding="utf-8")
        start = text.index("<<'PY'\n") + len("<<'PY'\n")
        program = text[start:text.index("\nPY\n", start)]
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            compile(program, "grade.sh", "exec")

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
            self.assertNotIn(NATIVE, p.stderr, flags)
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
        self.assertNotIn(NATIVE, p.stderr)
        self.assertFalse(target.exists())

    def assert_link_refused(self, c, d, reason, *flags, name="node_modules", env=None, native=False):
        """--link name=d is refused with exit 2 and the reason, and nothing is made: not the target, not its parent. The
        refusal comes from the native layer exactly when native is true."""
        parent = self.root / f"refused-{len(list(self.root.glob('refused-*')))}"
        target = parent / "cand"
        p = checkout(c["repo"], c["base"], target, env or self.env, *flags, "--link", f"{name}={d}")
        self.assertEqual(p.returncode, 2, f"{d} {flags}: {p.stdout}{p.stderr}")
        self.assertIn(reason, p.stderr, f"{d} {flags}")
        (self.assertIn if native else self.assertNotIn)(NATIVE, p.stderr, f"{d} {flags}: the layer that refused")
        self.assertFalse(parent.exists(), f"{d} {flags}")

    def assert_target_refused(self, c, target, reason, *flags, made, env=None, native=False):
        """target is refused with exit 2 and the reason (by the native layer exactly when native is true), and made, the
        first directory a checkout of target would create, does not exist afterwards."""
        p = checkout(c["repo"], c["base"], target, env or self.env, *flags)
        self.assertEqual(p.returncode, 2, f"{target} {flags}: {p.stdout}{p.stderr}")
        self.assertIn(reason, p.stderr, f"{target} {flags}")
        (self.assertIn if native else self.assertNotIn)(NATIVE, p.stderr, f"{target} {flags}: the layer that refused")
        self.assertFalse(Path(made).exists(), f"{target} {flags}: {made} was made")

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

    @NEEDS_PY_LINKS
    def test_historyless_checkout_refuses_a_unc_path(self):
        # LC2-1: on Git Bash //host/share/... is a UNC path; the checks once ran on /host/share/..., which does not exist,
        # so a link into a repository or the source repository spelled through //localhost/C$ was accepted
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        u = unc(self.root)
        if u is None or not Path(u).is_dir():
            self.skipTest("no UNC spelling of the temporary directory: not Windows, or the share //localhost/<drive>$ is unreachable")
        other, wt, bare = self.other_repositories()
        free = self.root / "installed" / "node_modules"  # outside every repository: accepted when spelled locally
        free.mkdir(parents=True)
        local = "is not a local path"
        win = lambda p: unc(p).replace("/", "\\")
        for flags in (("--pack", str(pack)), ()):
            self.assert_link_refused(c, unc(other / "node_modules"), local, *flags)  # once checked as /localhost/...: "ok", a dangling link
            self.assert_link_refused(c, unc(free), local, *flags)  # fail closed: a UNC path is refused, not walked
        cases = [
            ("lib", win(other / "node_modules")),  # a top-level link into a work tree, spelled UNC
            ("src", win(c["repo"])),  # the source repository itself, spelled UNC (its history holds the accepted fix)
            ("free", win(free)),  # a directory outside every repository, spelled UNC: refused all the same
        ]
        for i, (entry, to) in enumerate(cases):
            deps = self.root / f"deps-unc-{i}"
            (deps / "plain").mkdir(parents=True)
            (deps / entry).symlink_to(to, target_is_directory=True)
            read = subprocess.run(["bash", "-c", 'readlink -- "$1"', "readlink", str(deps / entry)], capture_output=True, text=True, timeout=60)
            self.assertTrue(read.stdout.startswith("//localhost/"), read.stdout + read.stderr)  # the shell sees the UNC spelling
            for flags in (("--pack", str(pack)), ()):
                self.assert_link_refused(c, deps, local, *flags)
        # the pack, the source repository and the target's parent are compared with the links or the pack, so a UNC
        # spelling of any of them is refused too, before anything is made
        for src, flags, what in ((c["repo"], ("--pack", unc(pack)), "the pack"), (unc(c["repo"]), ("--pack", str(pack)), "the source repository")):
            parent = self.root / f"refused-{len(list(self.root.glob('refused-*')))}"
            p = checkout(src, c["base"], parent / "cand", self.env, *flags, "--link", f"node_modules={free}")
            self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
            self.assertIn(f"{what} ", p.stderr)
            self.assertIn(local, p.stderr)
            self.assertNotIn(NATIVE, p.stderr)
            self.assertFalse(parent.exists(), what)
        p = checkout(c["repo"], c["base"], unc(self.root) + "/cand-unc", self.env, "--pack", str(pack))
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn(local, p.stderr)
        self.assertNotIn(NATIVE, p.stderr)
        self.assertFalse((self.root / "cand-unc").exists())
        # spelled locally, the same directory is accepted
        target = self.root / "accepted" / "cand"
        p = checkout(c["repo"], c["base"], target, native_links(self.env), "--pack", str(pack), "--link", f"node_modules={free}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_historyless_checkout_compares_the_pack_by_identity_not_spelling(self):
        # LC2-2: on a case-insensitive filesystem a spelling in another case names the same directory
        pack, c = make_pack(self.root, self.env)
        (pack / "extra").mkdir()  # a directory in the pack, outside its repository
        upper = self.root / "PACK"
        if not (upper.is_dir() and upper.samefile(pack)):
            self.skipTest("the filesystem is case-sensitive: no other-case spelling names the pack")
        self.assertIsNone(repo_holding(pack / "extra"), TEMP_IN_REPO.format(pack / "extra", repo_holding(pack / "extra")))
        root_upper = self.root.parent / self.root.name.swapcase()
        self.assertTrue(root_upper.samefile(self.root))
        shares = "holds the accepted fix"
        for d, pack_flag in ((upper, pack),  # the pack itself, in another case
                             (upper / "extra", pack),  # a directory in the pack, in another case
                             (pack / "extra", upper),  # the pack spelled in another case
                             (root_upper, pack)):  # a directory holding the pack, in another case
            self.assert_link_refused(c, d, shares, "--pack", str(pack_flag))
        if makes_links(lambda link, target: link.symlink_to(target)):  # a top-level link into the pack, in another case
            deps = self.root / "deps-case"
            (deps / "plain").mkdir(parents=True)
            (deps / "lib").symlink_to(upper / "extra", target_is_directory=True)
            self.assert_link_refused(c, deps, shares, "--pack", str(pack))
        # a target inside the pack, with the pack spelled in another case
        p = checkout(c["repo"], c["base"], pack / "cand-case", self.env, "--pack", str(upper))
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("is inside the pack", p.stderr)
        self.assertNotIn(NATIVE, p.stderr)
        self.assertFalse((pack / "cand-case").exists())

    def test_historyless_checkout_walks_the_windows_parents_of_a_mounted_directory(self):
        # a mount such as Git Bash's / or /tmp: the shell walks its own parents, native programs the Windows ones, and
        # the checks walk both (a stub cygpath models the mount; on a host without cygpath the stub is the only one).
        # A mount's Windows spelling is the same directory under other parents, so each spelling the stub gives is a
        # link to mnt/deps (a junction on Windows, which needs no privilege): the script proves, by file identity, that
        # the Windows spelling names the directory it came from (LC6-1)
        import os
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        other, wt, bare = self.other_repositories()
        mnt = self.root / "mnt"
        (mnt / "deps").mkdir(parents=True)  # outside every repository, as the shell sees it
        (other / "inside").mkdir()

        def same_dir(link: Path) -> None:
            if os.name == "nt":
                import _winapi
                _winapi.CreateJunction(str(mnt / "deps"), str(link))
            else:
                link.symlink_to(mnt / "deps", target_is_directory=True)

        for to in (other / "inside", c["repo"], pack):
            same_dir(to / "deps")
        stub = self.root / "stub-bin"
        stub.mkdir()
        (stub / "cygpath").write_bytes(STUB_CYGPATH.encode())
        (stub / "cygpath").chmod(0o755)
        env = {**native_links(self.env), "PATH": str(stub) + os.pathsep + self.env.get("PATH", ""), "STUB_MOUNT": bash_native(mnt, self.env)}
        for to, reason, with_pack in ((other / "inside", "is inside the git repository", False),  # the Windows parents hold a repository
                                      (c["repo"], "holds the accepted fix", False),  # the Windows spelling is in the source repository
                                      (pack, "holds the accepted fix", True)):  # ... or in the pack (compared by identity), under --pack
            mounted = dict(env, STUB_TARGET=bash_native(to, self.env))
            for flags in (("--pack", str(pack)), *([] if with_pack else [()])):
                self.assert_link_refused(c, mnt / "deps", reason, *flags, env=mounted)
        self.assert_link_refused(c, mnt / "deps", "is not a local path", env=dict(env, STUB_TARGET="//server/share/x"))  # a mount of a UNC path
        # a Windows spelling that names another directory than the shell's is no spelling of it: its parents say nothing
        # about the directory's, so it is refused as unproved, not walked. Walked, a free one was accepted, and one
        # inside a repository would be refused for a repository that is not the directory's
        free = self.root / "free-mount"
        (free / "deps").mkdir(parents=True)
        (other / "elsewhere" / "deps").mkdir(parents=True)
        for to in (free, other / "elsewhere"):
            for flags in (("--pack", str(pack)), ()):
                self.assert_link_refused(c, mnt / "deps", UNPROVED, *flags, env=dict(env, STUB_TARGET=bash_native(to, self.env)))
        target = self.root / "accepted" / "cand"  # the stub with no mount: the same directory is accepted
        p = checkout(c["repo"], c["base"], target, {**env, "STUB_MOUNT": ""}, "--pack", str(pack), "--link", f"node_modules={mnt / 'deps'}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_historyless_checkout_ignores_the_hosts_git_repository_variables(self):
        # LC2-3: with GIT_DIR / GIT_WORK_TREE naming another repository, git init re-initialised it and reset --hard
        # rewrote its work tree; the script drops the variables git lists as local to a repository
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        g2 = self.root / "g2"  # holds the base commit, so a lookup through GIT_DIR finds it
        sh(["git", "clone", "-q", str(c["repo"]), str(g2)], self.root, self.env)
        (g2 / "local.txt").write_text("not in the source\n")
        free = self.root / "installed" / "node_modules"
        free.mkdir(parents=True)
        before = tree_bytes(g2)
        dotgit = g2 / ".git"
        env = {**native_links(self.env), "GIT_DIR": str(dotgit), "GIT_WORK_TREE": str(g2), "GIT_INDEX_FILE": str(dotgit / "index"),
               "GIT_OBJECT_DIRECTORY": str(dotgit / "objects"), "GIT_COMMON_DIR": str(dotgit)}
        for i, flags in enumerate((("--pack", str(pack), "--link", f"node_modules={free}"), ())):
            target = self.root / f"cand-env-{i}"
            p = checkout(c["repo"], c["base"], target, env, *flags)
            self.assertEqual(tree_bytes(g2), before, f"{flags}: {p.stdout}{p.stderr}")  # nothing in the other repository changed
            self.assertEqual(p.returncode, 0, f"{flags}: {p.stdout}{p.stderr}")
            g = lambda *a: sh(["git", *a], target, self.env).stdout.strip()
            self.assertEqual(g("rev-list", "--all", "--count"), "1")
            self.assertEqual(g("rev-parse", "HEAD^{tree}"), sh(["git", "rev-parse", f"{c['base']}^{{tree}}"], c["repo"], self.env).stdout.strip())
            self.assertEqual(g("status", "--porcelain"), "")

    @NEEDS_PY_LINKS
    def test_historyless_checkout_checks_the_paths_native_programs_resolve(self):
        # LC3-1: a symlink to a volume-GUID or GLOBALROOT path is a plain directory to Git Bash (no -L, no readlink, and
        # pwd -P keeps the link's own path), while git, node and Python follow it. So every path is also resolved as
        # native programs resolve it, and the checks run again on that path
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        if volume_spelling(self.root) is None:
            self.skipTest("no volume-GUID spelling of the temporary directory: not Windows, or its volume has no GUID name")
        other, wt, bare = self.other_repositories()
        (other / "sub").mkdir()
        (pack / "extra").mkdir()  # in the pack, outside its repository
        (pack / "work" / "deeper").mkdir(parents=True)
        free = self.root / "installed" / "node_modules"  # outside every repository
        free.mkdir(parents=True)
        links = self.root / "L"
        links.mkdir()

        def hidden_link(name, to, spell=volume_spelling):
            link = links / name
            link.symlink_to(spell(to), target_is_directory=True)
            self.assertFalse(bash_sees_link(link, self.env), f"{name}: Git Bash sees this link; the case no longer needs the native layer")
            return link

        both, with_pack = (("--pack", str(pack)), ()), (("--pack", str(pack)),)
        inside, holds = "is inside the git repository", "holds the accepted fix"
        # DIR is such a link: into a work tree (the IC4-1 shape), a linked worktree, a bare repository, the source, the pack
        for d, reason, flagsets in ((hidden_link("v-clone", other / "node_modules"), inside, both),
                                    (hidden_link("g-clone", other / "node_modules", globalroot_spelling), inside, both),
                                    (hidden_link("v-wt", wt / "node_modules"), inside, both),
                                    (hidden_link("v-bare", bare / "refs"), inside, both),
                                    (hidden_link("v-src", c["repo"] / "src"), holds, both),
                                    (hidden_link("v-pack", pack / "extra"), holds, with_pack)):
            for flags in flagsets:
                self.assert_link_refused(c, d, reason, *flags, native=True)
        chain = links / "chain"  # an ordinary symlink, which Git Bash follows, to such a link, which it does not
        chain.symlink_to(links / "v-clone", target_is_directory=True)
        for flags in both:
            self.assert_link_refused(c, chain, inside, *flags, native=True)
        # such a link at the top of a clean DIR: to the source, into a work tree, to a directory holding the pack and the
        # source, and to nothing (refused, not skipped)
        for i, (to, spell, reason) in enumerate(((c["repo"], volume_spelling, holds),
                                                 (other / "node_modules", volume_spelling, inside),
                                                 (other / "node_modules", globalroot_spelling, inside),
                                                 (self.root, volume_spelling, holds),
                                                 (self.root / "missing", volume_spelling, "does not resolve"))):
            deps = self.root / f"deps-native-{i}"
            (deps / "plain").mkdir(parents=True)
            (deps / "s").symlink_to(spell(to), target_is_directory=True)
            self.assertFalse(bash_sees_link(deps / "s", self.env), f"{to}: Git Bash sees this link")
            for flags in both:
                self.assert_link_refused(c, deps, reason, *flags, native=True)
        # a link that native programs resolve to a UNC path: as a top-level entry, as the pack, as the source repository
        u = unc(self.root)
        if u is not None and Path(u).is_dir():
            deps = self.root / "deps-native-unc"
            (deps / "plain").mkdir(parents=True)
            (deps / "s").symlink_to(mup_spelling(free), target_is_directory=True)
            self.assertFalse(bash_sees_link(deps / "s", self.env))
            for flags in both:
                self.assert_link_refused(c, deps, "is not a local path", *flags, native=True)
            for src, flags, what in ((c["repo"], ("--pack", str(hidden_link("m-pack", pack, mup_spelling))), "the pack "),
                                     (hidden_link("m-src", c["repo"], mup_spelling), ("--pack", str(pack)), "the source repository ")):
                parent = self.root / f"refused-{len(list(self.root.glob('refused-*')))}"
                p = checkout(src, c["base"], parent / "cand", self.env, *flags, "--link", f"node_modules={free}")
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                for words in (what, "is not a local path", NATIVE):
                    self.assertIn(words, p.stderr, what)
                self.assertFalse(parent.exists(), what)
        # the target's parent reached through such a link: inside the pack (under --pack), inside a repository (always)
        deeper = hidden_link("v-deeper", pack / "work" / "deeper")
        self.assert_target_refused(c, deeper / "co-x", "is inside the pack", "--pack", str(pack), made=pack / "work" / "deeper" / "co-x", native=True)
        sub = hidden_link("v-sub", other / "sub")
        for flags in both:
            self.assert_target_refused(c, sub / "new" / "co-y", inside, *flags, made=other / "sub" / "new", native=True)
        # controls: such links to directories outside every repository are accepted, as DIR, at DIR's top and on the
        # target's path, and the checkout is made
        deps = self.root / "deps-native-ok"
        (deps / "plain").mkdir(parents=True)
        (deps / "s").symlink_to(volume_spelling(free), target_is_directory=True)
        for i, d in enumerate((hidden_link("v-free", free), deps)):
            out = self.root / f"out-{i}"
            out.mkdir()
            p = checkout(c["repo"], c["base"], hidden_link(f"v-out-{i}", out) / "cand", native_links(self.env), "--pack", str(pack), "--link", f"node_modules={d}")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(sh(["git", "rev-list", "--all", "--count"], out / "cand", self.env).stdout.strip(), "1")

    def test_historyless_checkout_refuses_without_a_native_path_resolver_on_windows(self):
        # the native layer needs a Windows Python (os.path.realpath resolves through GetFinalPathNameByHandle); with none,
        # or with only a POSIX one (MSYS2, Cygwin), the checks cannot be made, so every checkout is refused
        import os
        if os.name != "nt":
            self.skipTest("not Windows: the shell's physical path is the one native programs resolve")
        pack, c = make_pack(self.root, self.env)
        stub = self.root / "stub-bin"
        stub.mkdir()
        for name in ("python3", "python"):  # answers like a POSIX Python asked for os.name
            (stub / name).write_bytes(b"#!/bin/sh\nprintf posix\n")
            (stub / name).chmod(0o755)
        names = ("python3", "python3.exe", "python", "python.exe")
        dirs = [d for d in self.env.get("PATH", "").split(os.pathsep) if d and not any(os.path.lexists(os.path.join(d, n)) for n in names)]
        for i, path in enumerate((dirs, [str(stub), *dirs])):
            parent = self.root / f"refused-{i}"
            for flags in ((), ("--pack", str(pack))):
                p = checkout(c["repo"], c["base"], parent / "cand", {**self.env, "PATH": os.pathsep.join(path)}, *flags)
                self.assertEqual(p.returncode, 2, f"{path[0]} {flags}: {p.stdout}{p.stderr}")
                self.assertIn("no native path resolver", p.stderr)
                self.assertFalse(parent.exists())
        crash = self.root / "stub-crash"  # a resolver that passes the probe but fails the check: refused all the same
        crash.mkdir()
        (crash / "python3").write_bytes(b'#!/bin/sh\n[ "$2" = -c ] && { printf nt; exit 0; }\nexit 3\n')
        (crash / "python3").chmod(0o755)
        parent = self.root / "refused-crash"
        p = checkout(c["repo"], c["base"], parent / "cand", {**self.env, "PATH": os.pathsep.join([str(crash), *dirs])})
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("the native path check failed (exit 3)", p.stderr)
        self.assertFalse(parent.exists())

    def test_historyless_checkout_copies_no_git_template(self):
        # LC3-2: git init copies a template into the new .git; one holding objects/info/alternates made the source's
        # objects, the accepted fix among them, readable in the checkout. No template is copied, and the proof counts
        # every object the checkout's git can read
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        tpl = self.root / "template"
        for d in ("objects/info", "info", "hooks"):
            (tpl / d).mkdir(parents=True)
        # bytes, not text: on Windows a CRLF line names a directory ending in CR, and git skips that alternate
        (tpl / "objects" / "info" / "alternates").write_bytes(((c["repo"] / ".git" / "objects").resolve().as_posix() + "\n").encode())
        (tpl / "info" / "exclude").write_text("")
        (tpl / "hooks" / "post-commit").write_text("#!/bin/sh\nexit 0\n")
        (tpl / "description").write_text("from the template\n")
        cfg = self.root / "gitconfig-template"
        cfg.write_text((self.root / "gitconfig").read_text() + f"[init]\n\ttemplateDir = {tpl.as_posix()}\n")
        free = self.root / "installed" / "node_modules"
        free.mkdir(parents=True)
        live = self.root / "template-live"  # the template works: a plain git init with it reads the accepted fix
        sh(["git", "init", "-q", f"--template={tpl}", str(live)], self.root, self.env)
        self.assertEqual(sh(["git", "cat-file", "-t", c["accepted"]], live, self.env).stdout.strip(), "commit")
        g = lambda target, *a: sh(["git", *a], target, self.env).stdout.split()
        objects = {sh(["git", "rev-parse", f"{c['base']}^{{tree}}"], c["repo"], self.env).stdout.strip()}  # the base tree and all under it
        objects |= {line.split()[2] for line in sh(["git", "ls-tree", "-r", "-t", c["base"]], c["repo"], self.env).stdout.splitlines()}
        for i, (env, flags) in enumerate(((dict(native_links(self.env), GIT_TEMPLATE_DIR=str(tpl)), ()),
                                          (dict(native_links(self.env), GIT_CONFIG_GLOBAL=str(cfg)), ("--pack", str(pack), "--link", f"node_modules={free}")))):
            target = self.root / f"cand-template-{i}"
            p = checkout(c["repo"], c["base"], target, env, *flags)
            self.assertEqual(p.returncode, 0, f"{flags}: {p.stdout}{p.stderr}")
            for f in ("objects/info/alternates", "hooks", "description"):
                self.assertFalse((target / ".git" / f).exists(), f"{flags}: {f} copied from the template")
            self.assertNotEqual(sh(["git", "cat-file", "-e", c["accepted"]], target, self.env, check=False).returncode, 0, flags)
            self.assertEqual(set(g(target, "cat-file", "--batch-all-objects", "--batch-check=%(objectname)")), objects | set(g(target, "rev-parse", "HEAD")), flags)
            self.assertEqual(g(target, "status", "--porcelain"), [], flags)

    def test_historyless_checkout_makes_nothing_when_it_refuses_a_target(self):
        # LC3-3: the target's parent was made before the target checks ran, so a refused target left directories behind,
        # inside the pack too. Every check now runs first, on the nearest parent that exists
        pack, c = make_pack(self.root, self.env)
        self.assert_target_refused(c, pack / "new" / "sub" / "co", "is inside the pack", "--pack", str(pack), made=pack / "new")
        u = unc(self.root)
        if u is not None and Path(u).is_dir():
            for flags in (("--pack", str(pack)), ()):
                self.assert_target_refused(c, u + "/new-unc/sub/co", "is not a local path", *flags, made=self.root / "new-unc")
        # the part that does not exist yet is made as it is spelled, so it may hold no '.' or '..' segment
        self.assert_target_refused(c, self.root / "m1" / "m2" / ".." / "co", "without '.' or '..'", made=self.root / "m1")
        target = self.root / "m3" / "m4" / "co"  # spelled plainly, the parents are made and the checkout is
        p = checkout(c["repo"], c["base"], target, self.env, "--pack", str(pack))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(sh(["git", "rev-list", "--all", "--count"], target, self.env).stdout.strip(), "1")

    def test_historyless_checkout_refuses_a_target_inside_a_git_repository(self):
        # LC3-4: a checkout inside another repository reaches that repository's files and history through '..', as a
        # linked dependency tree did (IC4-1)
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        other, wt, bare = self.other_repositories()
        inside = "is inside the git repository"
        for target, made in ((other / "co", other / "co"),  # in a work tree
                             (other / "node_modules" / "pkg" / "co", other / "node_modules" / "pkg" / "co"),  # at any depth
                             (other / "new" / "sub" / "co", other / "new"),  # under parents that do not exist yet
                             (other / ".git" / "co", other / ".git" / "co"),  # in a .git directory
                             (wt / "co", wt / "co"),  # in a linked worktree, whose .git is a file
                             (bare / "co", bare / "co"), (bare / "refs" / "co", bare / "refs" / "co")):  # in a bare repository
            for flags in (("--pack", str(pack)), ()):
                self.assert_target_refused(c, target, inside, *flags, made=made)
        self.assert_target_refused(c, c["repo"] / "co", inside, made=c["repo"] / "co")  # in the source (under --pack: the pack)
        self.assert_target_refused(c, other / "co", "a checkout inside a repository reaches that repository's history and files through '..'",
                                   made=other / "co")
        if makes_links(lambda link, target: link.symlink_to(target)):  # through a symlink the shell follows
            (self.root / "to-other").symlink_to(other, target_is_directory=True)
            self.assert_target_refused(c, self.root / "to-other" / "co", inside, made=other / "co")
        target = self.root / "beside" / "co"  # beside the repositories, the checkout is made
        p = checkout(c["repo"], c["base"], target, self.env, "--pack", str(pack))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    REPRODUCED = ("commondir", "symlink HEAD", "refs file", "gitfile")

    def git_directory_shapes(self) -> dict:
        """Directories that hold no .git directory and are no plain bare repository, yet git takes them for a repository
        (check 4, LC4-1: a linked worktree's admin directory, a HEAD that is a dangling symlink, a refs file), a work tree
        whose .git file names a git directory elsewhere, and the shapes only the wider rule of historyless-checkout.sh
        names. Each is first shown to be what it claims: git takes it for a repository (under the environment given), or
        git does not and only the wider rule does. Needs other_repositories() first. Maps a name to the directory the
        rule must find; each holds an empty deps/ to link or check out into."""
        import os
        other = self.root / "other"
        common = (other / ".git").resolve().as_posix()
        common_env = {**self.env, "GIT_COMMON_DIR": common}
        nt = os.name == "nt"
        cgd = self.root / "commondir-gd"  # HEAD and a commondir file naming another repository's git directory
        cgd.mkdir()
        (cgd / "HEAD").write_text("ref: refs/heads/main\n")
        (cgd / "commondir").write_text(common + "\n")
        sym = self.root / "symhead.git"  # HEAD a dangling symlink into refs/ (core.preferSymlinkRefs, then pack-refs)
        sh(["git", "clone", "-q", "--bare", str(other), str(sym)], self.root, self.env)
        sh(["git", "pack-refs", "--all"], sym, self.env)
        (sym / "HEAD").unlink()
        (sym / "HEAD").symlink_to("refs/heads/main")
        rf = self.root / "refsfile.git"  # refs a file, the refs in packed-refs (Git for Windows' access() ignores X_OK)
        sh(["git", "clone", "-q", "--bare", str(other), str(rf)], self.root, self.env)
        sh(["git", "pack-refs", "--all"], rf, self.env)
        shutil.rmtree(rf / "refs")
        (rf / "refs").write_text("")
        sep = self.root / "sep"  # a work tree whose .git file names a git directory elsewhere
        (self.root / "store").mkdir()
        sh(["git", "init", "-q", f"--separate-git-dir={self.root / 'store' / 'sep.git'}", str(sep)], self.root, self.env)
        self.assertTrue((sep / ".git").is_file())
        head = self.root / "head-only"  # git takes HEAD alone for a repository when GIT_COMMON_DIR names a common directory
        head.mkdir()
        (head / "HEAD").write_text("ref: refs/heads/main\n")
        symonly = self.root / "symhead-only"  # and a dangling HEAD symlink alone, likewise
        symonly.mkdir()
        (symonly / "HEAD").symlink_to("refs/heads/main")
        cd = self.root / "commondir-only"  # wider than git: a commondir file alone, a gitdir file alone (a linked
        cd.mkdir()  # worktree's admin files), and objects and refs without HEAD (objects a '..' reads without git)
        (cd / "commondir").write_text(common + "\n")
        gd = self.root / "gitdir-only"
        gd.mkdir()
        (gd / "gitdir").write_text(common + "\n")
        objref = self.root / "objects-refs"
        (objref / "objects").mkdir(parents=True)
        (objref / "refs").mkdir()
        # name: (directory, the environment under which git takes it for a repository; False when git never does; None
        # when not asserted: on a POSIX host access() honours X_OK, so a refs file is no repository to git there)
        shapes = {"commondir": (cgd, self.env), "symlink HEAD": (sym, self.env), "refs file": (rf, self.env if nt else None),
                  "gitfile": (sep, self.env), "HEAD only": (head, common_env), "dangling HEAD only": (symonly, common_env),
                  "commondir only": (cd, False), "gitdir only": (gd, False), "objects and refs": (objref, False)}
        for name, (d, git_view) in shapes.items():
            (d / "deps").mkdir()
            if git_view is None:
                continue
            p = sh(["git", "rev-parse", "--absolute-git-dir"], d / "deps", git_view or self.env, check=False)
            if git_view is False:
                self.assertNotEqual(p.returncode, 0, f"{name}: git takes {d} for a repository: {p.stdout}")
            else:
                self.assertEqual(p.returncode, 0, f"{name}: git does not take {d} for a repository: {p.stderr}")
        return {name: d for name, (d, _) in shapes.items()}

    @NEEDS_PY_LINKS
    def test_historyless_checkout_refuses_every_directory_git_takes_for_a_repository(self):
        # LC4-1: is_repo once asked for a regular HEAD file and objects/ and refs/ directories, so a linked worktree's
        # admin directory (HEAD and commondir), a HEAD that is a dangling symlink into refs/ and a refs file passed as
        # "outside every repository", though git takes each for one and the checkout read that repository's history.
        # The rule is now wider than git's own; the shell layer refuses each shape as DIR, at DIR's top and as the
        # target's parent
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        self.other_repositories()
        for i, (name, d) in enumerate(self.git_directory_shapes().items()):
            reason = f"{d.name}; a "  # the refusal names the nearest repository, then its reason
            self.assert_link_refused(c, d / "deps", reason, "--pack", str(pack))
            self.assert_target_refused(c, d / "deps" / "co", reason, made=d / "deps" / "co")
            if name in self.REPRODUCED:  # a symlink the shell sees, at the top of a clean DIR
                deps = self.root / f"deps-top-{i}"
                (deps / "plain").mkdir(parents=True)
                (deps / "s").symlink_to(d / "deps", target_is_directory=True)
                self.assert_link_refused(c, deps, reason)

    @NEEDS_PY_LINKS
    def test_historyless_checkout_refuses_every_directory_git_takes_for_a_repository_as_native_programs_resolve_it(self):
        # LC4-1 in the native layer: the same shapes reached through links Git Bash cannot see. LC4-4: a junction at
        # DIR's top, which Git Bash sees, but which leads to such a link, so the shell resolves it to a plain directory
        # outside every repository; only the native layer, which takes any reparse point for a link (a junction is no
        # symlink to Python's is_symlink), follows it to the repository
        import os
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        if volume_spelling(self.root) is None:
            self.skipTest("no volume-GUID spelling of the temporary directory: not Windows, or its volume has no GUID name")
        other, wt, bare = self.other_repositories()
        links = self.root / "L"
        links.mkdir()

        def hidden_link(name, to):
            link = links / name
            link.symlink_to(volume_spelling(to), target_is_directory=True)
            self.assertFalse(bash_sees_link(link, self.env), f"{name}: Git Bash sees this link; the case no longer needs the native layer")
            return link

        for i, (name, d) in enumerate(self.git_directory_shapes().items()):
            reason = f"{d.name}; a "
            v = hidden_link(f"v-{i}", d / "deps")
            self.assert_link_refused(c, v, reason, "--pack", str(pack), native=True)
            self.assert_target_refused(c, v / "co", reason, made=d / "deps" / "co", native=True)
            if name in self.REPRODUCED:  # such a link at the top of a clean DIR
                deps = self.root / f"deps-native-top-{i}"
                (deps / "plain").mkdir(parents=True)
                (deps / "s").symlink_to(volume_spelling(d / "deps"), target_is_directory=True)
                self.assertFalse(bash_sees_link(deps / "s", self.env))
                self.assert_link_refused(c, deps, reason, native=True)
        import _winapi
        deps = self.root / "deps-junction"
        (deps / "plain").mkdir(parents=True)
        _winapi.CreateJunction(str(hidden_link("v-junction", other / "node_modules")), str(deps / "j"))
        with os.scandir(deps) as it:
            self.assertFalse(next(e for e in it if e.name == "j").is_symlink(), "a junction is no symlink to Python")
        self.assertTrue(bash_sees_link(deps / "j", self.env), "Git Bash sees the junction")
        for flags in (("--pack", str(pack)), ()):
            self.assert_link_refused(c, deps, "other; a ", *flags, native=True)
        # a junction whose own target is a volume-GUID path: Git Bash takes it for a volume mount point, a plain
        # directory, so the shell never resolves it; only the native layer, counting it as a reparse point, follows it
        deps = self.root / "deps-volume-junction"
        (deps / "plain").mkdir(parents=True)
        volume_junction(deps / "j", other / "node_modules")
        self.assertFalse(bash_sees_link(deps / "j", self.env), "Git Bash sees this junction; the case no longer needs the native layer")
        with os.scandir(deps) as it:
            self.assertFalse(next(e for e in it if e.name == "j").is_symlink(), "a junction is no symlink to Python")
        for flags in (("--pack", str(pack)), ()):
            self.assert_link_refused(c, deps, "other; a ", *flags, native=True)
        free = self.root / "installed" / "node_modules"  # control: a junction outside every repository is accepted
        free.mkdir(parents=True)
        ok = self.root / "deps-junction-ok"
        (ok / "plain").mkdir(parents=True)
        _winapi.CreateJunction(str(free), str(ok / "j"))
        target = self.root / "out" / "cand"
        p = checkout(c["repo"], c["base"], target, native_links(self.env), "--pack", str(pack), "--link", f"node_modules={ok}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(sh(["git", "rev-list", "--all", "--count"], target, self.env).stdout.strip(), "1")

    def test_historyless_checkout_native_layer_counts_an_entry_it_cannot_read_as_a_marker(self):
        # the native layer fails closed: a marker entry whose lstat fails for any reason but "not there" counts as held,
        # so an unreadable HEAD makes its directory a repository. Its code runs here with lstat failing for HEAD only
        text = (KIT / "historyless-checkout.sh").read_text(encoding="utf-8")
        code = text.split("<<'PY'\n", 1)[1].split("\nargs = sys.argv[1:]\n", 1)[0]
        empty = self.root / "empty"
        empty.mkdir()
        harness = textwrap.dedent("""
            import errno
            _lstat = os.lstat
            def _failing(p, *a, **k):
                if os.path.basename(p) == "HEAD" and FAIL:
                    raise PermissionError(errno.EACCES, "denied", p)
                return _lstat(p, *a, **k)
            os.lstat = _failing
            sys.stdout.write(f"{is_repo(D)}")
            """)
        for fail, expected in ((False, "False"), (True, "True")):
            p = subprocess.run([sys.executable, "-I", "-c", f"{code}\nFAIL = {fail}\nD = {str(empty)!r}\n{harness}"],
                               capture_output=True, text=True, timeout=60)
            self.assertEqual((p.returncode, p.stdout), (0, expected), p.stderr)
        # LC5-4 (U1): an entry at DIR's top whose stat fails counts as a link, so the native layer resolves and checks it
        # rather than skipping it. A DirEntry's methods cannot be patched, so a stand-in with the same two methods is used
        entry = textwrap.dedent("""
            import errno
            import types
            class Entry:
                def is_symlink(self):
                    return False
                def stat(self, follow_symlinks=True):
                    if FAIL:
                        raise PermissionError(errno.EACCES, "denied", "x")
                    return types.SimpleNamespace(st_file_attributes=0)
            sys.stdout.write(f"{is_link(Entry())}")
            """)
        for fail, expected in ((False, "False"), (True, "True")):
            p = subprocess.run([sys.executable, "-I", "-c", f"{code}\nFAIL = {fail}\n{entry}"], capture_output=True, text=True, timeout=60)
            self.assertEqual((p.returncode, p.stdout), (0, expected), p.stderr)

    def test_historyless_checkout_refuses_a_link_name_that_names_dot_git(self):
        # LC4-4: --link .git/hooks=DIR put a host directory in the checkout's own git directory, whose hooks a candidate's
        # commit runs. No segment of NAME may name .git, by any spelling Windows resolves to it
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        free = self.root / "installed" / "hooks"
        free.mkdir(parents=True)
        for name in (".git", ".git/hooks", ".git/objects/info", ".GIT", ".Git/hooks", ".git.", ".git ", ".git. .", "GIT~1",
                     "git~1/hooks", "vendor/.git", "a/./.git/x"):
            self.assert_link_refused(c, free, "may not name .git", "--pack", str(pack), name=name)
        for name in ("a" + BS + "b", BS + "x", "c:x", "x:y"):  # a Windows separator, a drive or a stream
            self.assert_link_refused(c, free, "a plain relative name", name=name)
        # LC5-4 (U2): every --link's NAME is checked, not only the first one's
        for name in (".git/hooks", ".GIT"):
            self.assert_link_refused(c, free, "may not name .git", "--pack", str(pack), "--link", f"a={free}", name=name)
        self.assert_link_refused(c, free, "a plain relative name", "--link", f"a={free}", "--link", f"b={free}", name="c:x")
        target = self.root / "accepted" / "cand"  # names that only look alike are linked
        p = checkout(c["repo"], c["base"], target, native_links(self.env), "--pack", str(pack), "--link", f".github={free}",
                     "--link", f"git={free}", "--link", f"gitdir={free}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        for name in (".github", "git", "gitdir"):
            self.assertTrue((target / name).exists(), name)
        self.assertEqual(sh(["git", "status", "--porcelain"], target, self.env).stdout.strip(), "")

    def test_historyless_checkout_needs_a_windows_python_3_10_for_the_native_layer(self):
        # LC4-2: the native layer calls os.path.realpath(path, strict=True), and strict came in Python 3.10. A 3.9 passed
        # the old probe (3.8+) and then failed every check; the probe now asks for 3.10 and says so
        import os
        if os.name != "nt":
            self.skipTest("not Windows: there is no native layer")
        pack, c = make_pack(self.root, self.env)
        stub = self.root / "py39"
        stub.mkdir()
        emulate = stub / "emulate39.py"  # a Windows Python that reports 3.9 and has 3.9's realpath (no strict)
        emulate.write_text(textwrap.dedent("""\
            import os
            import sys
            sys.version_info = (3, 9, 18, "final", 0)
            _realpath = os.path.realpath
            os.path.realpath = lambda path: _realpath(path)
            args = sys.argv[1:]
            if args[:1] == ["-I"]:
                args = args[1:]
            if args[:1] == ["-c"]:
                sys.argv = ["-c", *args[2:]]
                exec(compile(args[1], "<string>", "exec"), {"__name__": "__main__"})
            elif args[:1] == ["-"]:
                sys.argv = ["-", *args[1:]]
                exec(compile(sys.stdin.read(), "<stdin>", "exec"), {"__name__": "__main__"})
            else:
                sys.exit(9)
            """))
        run39 = lambda code: subprocess.run([sys.executable, "-I", str(emulate), "-I", "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(run39("import sys; print(sys.version_info >= (3, 10))").stdout.strip(), "False")
        self.assertIn("TypeError", run39("import os; os.path.realpath('.', strict=True)").stderr)  # as a 3.9 fails
        (stub / "python3").write_bytes(f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" -I "{emulate.as_posix()}" "$@"\n'.encode())
        (stub / "python3").chmod(0o755)
        names = ("python3", "python3.exe", "python", "python.exe")
        dirs = [d for d in self.env.get("PATH", "").split(os.pathsep) if d and not any(os.path.lexists(os.path.join(d, n)) for n in names)]
        for flags in ((), ("--pack", str(pack))):
            parent = self.root / f"refused-{len(flags)}"
            p = checkout(c["repo"], c["base"], parent / "cand", {**self.env, "PATH": os.pathsep.join([str(stub), *dirs])}, *flags)
            self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
            self.assertIn("no native path resolver", p.stderr)
            self.assertIn("Python 3.10+", p.stderr)
            self.assertFalse(parent.exists())

    def subst_drive(self, path: Path) -> str | None:
        """A drive letter that subst maps to path for the rest of this test (removed at cleanup), or None when no letter
        is free. subst refuses a letter in use, so two tests running at once never share one."""
        import os
        for letter in "RSTUVWXYQPONMLKJIHG":
            if os.path.exists(f"{letter}:{BS}"):
                continue
            if subprocess.run(["subst", f"{letter}:", str(Path(path).resolve())], capture_output=True, text=True, timeout=60).returncode == 0:
                self.addCleanup(subprocess.run, ["subst", f"{letter}:", "/D"], capture_output=True, timeout=60)
                return letter
        return None

    @NEEDS_PY_LINKS
    def test_historyless_checkout_checks_where_a_link_only_the_shell_sees_leads_as_native_programs_resolve_it(self):
        # LC5-1: Git Bash makes "sys" symlinks (MSYS=winsymlinks:sys) and shortcut symlinks (:lnk). Git Bash and every MSYS
        # tool follow them, but to Windows they are plain files, so the native layer's scan of DIR's top saw no link. The
        # shell layer resolved such a link and checked the path in its own view, which cannot see through a volume-GUID
        # link or a subst drive. So a link at DIR's top to such a path into a repository passed both layers, and a
        # candidate's `cd node_modules/s && git log` read that repository's history. Every path the shell resolves is
        # now also checked as native programs resolve it
        import os
        if os.name != "nt" or volume_spelling(self.root) is None:
            self.skipTest("not Windows, or the temporary directory's volume has no GUID name: no MSYS-only link, no native layer")
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        other, wt, bare = self.other_repositories()
        free = self.root / "installed" / "node_modules"  # outside every repository
        (free / "pkg").mkdir(parents=True)
        letter = self.subst_drive(other / "node_modules")
        if letter is None:
            self.skipTest("no free drive letter for subst")
        self.assertTrue(Path(f"{letter}:{BS}pkg").is_dir())
        links = self.root / "L"
        links.mkdir()
        for name, to in (("g", other / "node_modules"), ("g-free", free)):
            (links / name).symlink_to(volume_spelling(to), target_is_directory=True)
            self.assertFalse(bash_sees_link(links / name, self.env), f"{name}: Git Bash sees this link")
        cases = [("sys", shell_spelling(links / "g", self.env)),  # a sys symlink to a GUID link into a work tree
                 ("lnk", shell_spelling(links / "g", self.env)),  # a shortcut symlink to it
                 ("sys", f"/{letter.lower()}/pkg"),  # a sys symlink to a subst drive mapped into a work tree
                 ("lnk", f"/{letter.lower()}/pkg")]  # a shortcut symlink to it
        both = (("--pack", str(pack)), ())
        for i, (mode, to) in enumerate(cases):
            deps = self.root / f"deps-msys-{i}"
            (deps / "plain").mkdir(parents=True)
            msys_link(deps / "s", to, mode, self.env)
            self.assertTrue(bash_sees_link(deps / "s", self.env), f"{mode} {to}: Git Bash does not see the link")
            self.assertFalse(any(native_entries(deps).values()), f"{mode} {to}: Windows sees a link: {native_entries(deps)}")
            for flags in both:
                self.assert_link_refused(c, deps, "other; a dependency tree inside a repository", *flags, native=True)
        # controls: the same links to a directory outside every repository are accepted, and the checkout is made
        letter_free = self.subst_drive(free)
        controls = [("sys", shell_spelling(links / "g-free", self.env)), ("lnk", shell_spelling(links / "g-free", self.env)),
                    ("sys", shell_spelling(free, self.env)), *([("sys", f"/{letter_free.lower()}/pkg")] if letter_free else [])]
        for i, (mode, to) in enumerate(controls):
            deps = self.root / f"deps-msys-ok-{i}"
            (deps / "plain").mkdir(parents=True)
            msys_link(deps / "s", to, mode, self.env)
            for j, flags in enumerate(both):
                target = self.root / f"out-{i}-{j}" / "cand"
                p = checkout(c["repo"], c["base"], target, native_links(self.env), *flags, "--link", f"node_modules={deps}")
                self.assertEqual(p.returncode, 0, f"{mode} {to} {flags}: {p.stdout}{p.stderr}")
                self.assertEqual(sh(["git", "rev-list", "--all", "--count"], target, self.env).stdout.strip(), "1")

    def test_historyless_checkout_proves_each_path_string_names_the_file_it_came_from(self):
        # LC6-1: every path the checks read is a string the shell made of a path ($(pwd -P), $(dirname), $(basename),
        # $(readlink)), and a command substitution drops every trailing newline. With x/repo<LF>, a work tree, beside a
        # free directory x/repo, a link at DIR's top to x/repo<LF> was resolved, checked and found free as x/repo, and a
        # candidate's `cd node_modules/s && git log` read the work tree's history. Each such string is now proved, by
        # file identity, to name the file it came from, or the path is refused; and the strings that name a file not
        # made yet (the target, a link's parent) keep their exact spelling
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        other, wt, bare = self.other_repositories()
        env = native_links(self.env)
        x = self.root / "x"
        x.mkdir()
        work = nl_path(x / "repo")  # a work tree with history, beside a free twin x/repo
        work.mkdir()
        (work / "brief.md").write_text("SECRET-BRIEF\n")
        sh(["git", "init", "-q"], work, self.env)
        commit_all(work, self.env, "SECRET-FIX-COMMIT")
        (x / "repo").mkdir()
        (x / "repo" / "brief.md").write_text("free twin\n")
        (x / "t").write_text("free\n")
        sx = shell_spelling(x, self.env)
        made = bash_nl('ln -s -- "$1" "$2"', shell_spelling(other / "README.md", self.env), sx + "/t\n", env={**env, "MSYS": "winsymlinks:sys"})
        self.assertEqual(made.returncode, 0, made.stderr)  # x/t<LF>: a link to a file in the repository other, beside a free x/t
        both = (("--pack", str(pack)), ())

        def refused(reason, *flags, target=None, link=None, src=None):
            parent = self.root / f"refused-{len(list(self.root.glob('refused-*')))}"
            p = checkout_spelled(src or c["repo"], c["base"], target or parent / "cand", env, *flags, *(("--link", link) if link else ()))
            self.assertEqual(p.returncode, 2, f"{src} {link} {target} {flags}: {p.stdout}{p.stderr}")
            self.assertIn(reason, p.stderr, f"{src} {link} {target} {flags}")
            self.assertNotIn(NATIVE, p.stderr, f"{src} {link} {target} {flags}: the layer that refused")
            self.assertFalse(parent.exists(), f"{src} {link} {target} {flags}")

        # a link to the link x/t<LF>, the readlink hop: its text was cut to x/t by $(readlink) and refused as unproved;
        # the text is now read exactly (LC7-1), so the hop is followed to where x/t<LF> leads, a file in the repository
        # other, and refused for that repository
        cases = [("sys", sx + "/repo\n", UNPROVED),  # a link at DIR's top to the work tree x/repo<LF>
                 ("lnk", sx + "/repo\n", UNPROVED),  # ... a shortcut symlink (on a host without MSYS, a symlink all the same)
                 ("sys", sx + "/repo\n/brief.md", UNPROVED),  # a link to a file in it: the join of $(dirname) and $(basename)
                 ("sys", sx + "/t\n", f"resolving to {shell_spelling(other, self.env)}/README.md, is inside the git repository")]
        for i, (mode, to, reason) in enumerate(cases):
            deps = self.root / f"deps-nl-{i}"
            (deps / "plain").mkdir(parents=True)
            ln = bash_nl('ln -s -- "$1" "$2"', to, shell_spelling(deps, self.env) + "/s", env={**env, "MSYS": f"winsymlinks:{mode}"})
            self.assertEqual(ln.returncode, 0, ln.stderr)
            for flags in both:
                refused(reason, *flags, link=f"node_modules={deps}")
        for flags in both:
            refused(UNPROVED, *flags, link=f"node_modules={sx}/repo\n")  # DIR itself: $(pwd -P)
        # the pack: --pack pk<LF> beside a free twin pk, with the target inside pk<LF>
        pk = nl_path(self.root / "pk")
        pk.mkdir()
        (self.root / "pk").mkdir()
        refused(UNPROVED, "--pack", shell_spelling(self.root, self.env) + "/pk\n", target=shell_spelling(self.root, self.env) + "/pk\n/cand")
        self.assertEqual(list(pk.iterdir()) + list((self.root / "pk").iterdir()), [])
        # a target whose nearest existing parent is x/p<LF>, a link into the repository other, beside a free x/p:
        # checked, and made, at x/p
        ln = bash_nl('ln -s -- "$1" "$2"', shell_spelling(other / "node_modules", self.env), sx + "/p\n", env={**env, "MSYS": "winsymlinks:sys"})
        self.assertEqual(ln.returncode, 0, ln.stderr)
        (x / "p").mkdir()
        for flags in both:
            refused("is inside the git repository", *flags, target=sx + "/p\n/cand")
        self.assertEqual(list((x / "p").iterdir()), [])
        # a link's parent: --link a<LF>=hostdir --link a<LF>/x=dep2 made the second link in hostdir (its parent was
        # checked as the checkout's a, which did not exist, and made where a<LF> leads). A newline in a link name is
        # now refused before anything is made (LC7-2); the parent a link is made in is still spelled exactly: in a
        # checkout cand<LF> beside a host directory cand it is cand<LF>, which pwd -P cannot spell, so the link is
        # refused as unproved (never checked as cand, which would be "not inside the checkout") and nothing is left
        hostdir, dep2 = self.root / "hostdir", self.root / "dep2"
        hostdir.mkdir()
        (hostdir / "keep").write_text("keep\n")
        dep2.mkdir()
        for flags in both:
            target = self.root / f"made-{len(flags)}" / "cand"
            p = checkout_spelled(c["repo"], c["base"], target, env, *flags, "--link", f"a\n={hostdir}", "--link", f"a\n/x={dep2}")
            self.assertEqual(p.returncode, 2, f"{flags}: {p.stdout}{p.stderr}")
            self.assertIn(LINK_NAME_RULE, p.stderr, flags)
            self.assertFalse(target.parent.exists(), flags)
            self.assertEqual(sorted(q.name for q in hostdir.iterdir()), ["keep"], flags)
            twin = self.root / f"twin-{len(flags)}"
            (twin / "cand").mkdir(parents=True)
            (twin / "cand" / "keep").write_text("keep\n")
            p = checkout_spelled(c["repo"], c["base"], shell_spelling(twin, self.env) + "/cand\n", env, *flags, "--link", f"node_modules={dep2}")
            self.assertEqual(p.returncode, 2, f"{flags}: {p.stdout}{p.stderr}")
            self.assertIn("--link node_modules: its parent ", p.stderr, flags)
            self.assertIn(UNPROVED, p.stderr, flags)
            self.assertEqual(sorted(q.name for q in twin.iterdir()), ["cand"], flags)
            self.assertEqual(sorted(q.name for q in (twin / "cand").iterdir()), ["keep"], flags)
        # controls: a target spelled with newlines is made exactly there, and a link to a free directory is accepted
        target = nl_path(nl_path(nl_path(self.root / "n") / "m") / "cand")
        p = checkout_spelled(c["repo"], c["base"], shell_spelling(self.root, self.env) + "/n\n/m\n/cand\n", env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(target.is_dir())
        self.assertFalse((self.root / "n").exists())
        self.assertEqual(sh(["git", "rev-list", "--all", "--count"], target, self.env).stdout.strip(), "1")
        # the source repository srcnl<LF> beside a clone srcnl: $(pwd -P) cannot spell a name that ends in a newline,
        # so the source is refused, and the clone is not read in its place
        for name in (nl_path(self.root / "srcnl"), self.root / "srcnl"):
            sh(["git", "clone", "-q", str(c["repo"]), str(name)], self.root, self.env)
        refused(UNPROVED, src=shell_spelling(self.root, self.env) + "/srcnl\n")
        # a target whose last segment is '.' or '..' names another directory than the one made for it: 'nx/..' was
        # host itself, where git init and reset --hard wrote the checkout
        host = self.root / "host"
        host.mkdir()
        (host / "host.txt").write_bytes(b"HOST\n")
        for last in (".", ".."):
            refused(f"its last segment is '{last}'", target=shell_spelling(host, self.env) + f"/nx/{last}")
            self.assertEqual(tree_bytes(host), {"host.txt": b"HOST\n"}, last)
            self.assertFalse((host / "nx").exists(), last)
        free = self.root / "installed" / "node_modules"
        (free / "pkg").mkdir(parents=True)
        deps = self.root / "deps-nl-ok"
        (deps / "plain").mkdir(parents=True)
        msys_link(deps / "s", shell_spelling(free, self.env), "sys", self.env)
        for j, flags in enumerate(both):
            target = self.root / f"ok-{j}" / "cand"
            p = checkout_spelled(c["repo"], c["base"], target, env, *flags, "--link", f"node_modules={deps}")
            self.assertEqual(p.returncode, 0, f"{flags}: {p.stdout}{p.stderr}")

    def test_historyless_checkout_proves_the_directory_of_a_file_a_link_leads_to(self):
        # LC7-1: resolve took the directory of a file a link leads to as physd "$(dirname)". The inner command
        # substitution dropped the trailing newline of x/hl<LF> before physd, which proves pwd -P only against its own
        # argument, so it proved x/hl; and the file check ([ -ef ]) holds through a hard link. A link at DIR's top to
        # x/hl<LF>/brief.md, in a work tree whose brief.md has a hard link in a free x/hl, was checked at x/hl, and the
        # checkout's link text named the work tree, whose history a candidate read. Every part of a path resolve takes is
        # now spelled exactly (the directory, the name, each link's text), and what it resolves to is set, not printed
        import os
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        env = native_links(self.env)
        x = self.root / "x"
        x.mkdir()
        work = nl_path(x / "hl")  # a work tree with history, beside a free twin x/hl
        work.mkdir()
        (work / "brief.md").write_text("SECRET-BRIEF\n")
        sh(["git", "init", "-q"], work, self.env)
        commit_all(work, self.env, "SECRET-HL")
        (x / "hl").mkdir()
        os.link(work / "brief.md", x / "hl" / "brief.md")  # the same file under the free twin
        self.assertTrue(os.path.samefile(work / "brief.md", x / "hl" / "brief.md"))
        sx = shell_spelling(x, self.env)
        both = (("--pack", str(pack)), ())
        for i, mode in enumerate(("sys", "lnk")):  # links only the shell sees (on a host without MSYS, symlinks all the same)
            deps = self.root / f"deps-hl-{i}"
            (deps / "plain").mkdir(parents=True)
            ln = bash_nl('ln -s -- "$1" "$2"', sx + "/hl\n/brief.md", shell_spelling(deps, self.env) + "/s", env={**env, "MSYS": f"winsymlinks:{mode}"})
            self.assertEqual(ln.returncode, 0, ln.stderr)
            for flags in both:
                self.assert_link_refused(c, deps, UNPROVED, *flags, env=env)
        # controls: a link to a file whose own name ends in a newline, in a free directory, is accepted. Its link text and
        # its name were cut to ff/f, which does not exist, so it was refused as unproved; and on Windows the path the
        # shell resolved is handed to the native layer as resolved, not cut by a command substitution on the way
        ff = self.root / "ff"
        ff.mkdir()
        nl_path(ff / "f").write_text("free\n")
        free = self.root / "installed" / "node_modules"
        (free / "pkg").mkdir(parents=True)
        for i, to in enumerate((shell_spelling(ff, self.env) + "/f\n", shell_spelling(free, self.env))):
            deps = self.root / f"deps-hl-ok-{i}"
            (deps / "plain").mkdir(parents=True)
            ln = bash_nl('ln -s -- "$1" "$2"', to, shell_spelling(deps, self.env) + "/s", env={**env, "MSYS": "winsymlinks:sys"})
            self.assertEqual(ln.returncode, 0, ln.stderr)
            for j, flags in enumerate(both):
                target = self.root / f"ok-hl-{i}-{j}" / "cand"
                p = checkout(c["repo"], c["base"], target, env, *flags, "--link", f"node_modules={deps}")
                self.assertEqual(p.returncode, 0, f"{to!r} {flags}: {p.stdout}{p.stderr}")
                self.assertEqual(sh(["git", "rev-list", "--all", "--count"], target, self.env).stdout.strip(), "1")

    def test_historyless_checkout_proves_git_ignores_each_link(self):
        # LC7-2: each link's NAME went into the checkout's .git/info/exclude as a line git reads as a pattern, and
        # nothing proved it ignored the link. '[x]' is a character class, MSYS stores '?' and '<' in a name as other
        # characters, a trailing space is dropped, and 'a<LF>b' wrote the lines '/a' and 'b': the link stayed untracked
        # and a candidate's `git add -A` committed it (a symlink holding the host's absolute path), or the line hid other
        # files ('b' hid every b in the tree, '/nm*' every name starting nm). NAME is now kept to characters no pattern
        # reads specially, and each link is proved ignored by git itself (check-ignore), or the checkout is refused and
        # removed: the base tree's own .gitignore outranks info/exclude and can re-include the name
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        env = native_links(self.env)
        free = self.root / "installed" / "deps"
        free.mkdir(parents=True)
        both = (("--pack", str(pack)), ())
        # forward slashes: MSYS globs a Windows command-line argument that holds '[', '?' or '*', and reads each backslash
        # in it as an escape
        sfree = shell_spelling(free, self.env)
        for name in ("[x]", "q?m", "a\nb", "trs ", "lt<", "nm*", "#c", "!n", "s p", "a\tb", "xé", "a//b", "./x", "x/", "a.",
                     ".", "src/v.", "src/./v"):
            for flags in both:
                parent = self.root / f"refused-{len(list(self.root.glob('refused-*')))}"
                p = checkout_spelled(c["repo"], c["base"], parent / "cand", env, *flags, "--link", f"{name}={sfree}")
                self.assertEqual(p.returncode, 2, f"{name!r} {flags}: {p.stdout}{p.stderr}")
                self.assertIn(LINK_NAME_RULE, p.stderr, f"{name!r} {flags}")
                self.assertFalse(parent.exists(), f"{name!r} {flags}")
        self.assertEqual(list(free.iterdir()), [])
        # a base tree whose .gitignore re-includes the name ('!' outranks info/exclude): git would not ignore the link
        repo = c["repo"]
        (repo / ".gitignore").write_text("__pycache__/\n!/deps\n!/src/vendor\n")
        c2 = {**c, "base": commit_all(repo, self.env, "re-include")}
        for name in ("deps", "src/vendor"):
            for flags in both:
                parent = self.root / f"refused-{len(list(self.root.glob('refused-*')))}"
                p = checkout(c2["repo"], c2["base"], parent / "cand", env, *flags, "--link", f"{name}={free}")
                self.assertEqual(p.returncode, 2, f"{name} {flags}: {p.stdout}{p.stderr}")
                self.assertIn(f"--link {name}: git does not ignore the link", p.stderr, f"{name} {flags}")
                self.assertNotIn(NATIVE, p.stderr, f"{name} {flags}")
                self.assertFalse(parent.exists(), f"{name} {flags}: the refused checkout was left")
        self.assertEqual(list(free.iterdir()), [])
        # controls: names of the safe kind are linked and ignored, and their lines hide nothing else, a file beside a
        # link, named like it deeper down or starting like it
        names = ("node_modules", ".venv", "@scope", "a+b_c-d.e", "src/vendor")
        target = self.root / "accepted" / "cand"
        p = checkout(c["repo"], c["base"], target, env, "--pack", str(pack), *[a for n in names for a in ("--link", f"{n}={free}")])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        for n in names:
            self.assertTrue((target / n).is_symlink(), n)
        others = ["node_modulesx", "src/node_modules", "docs/.venv", ".venvx", "@scopex", "a+b_c-d", "src/vendorx", "b"]
        for rel in others:
            (target / rel).write_text("new\n")
        sh(["git", "add", "-A"], target, self.env)
        staged = sh(["git", "diff", "--cached", "--name-only"], target, self.env).stdout.split()
        self.assertEqual(sorted(staged), sorted(others))

    @NEEDS_PY_LINKS
    def test_historyless_checkout_proves_native_programs_read_each_path_string_as_the_same_file(self):
        # LC6-1, the native layer: Windows drops a trailing space or dot from a name, so 'gs ' (a link into a
        # repository) beside a free 'gs' was resolved by native programs as 'gs' and found free, while the checkout's
        # node and git, and Git Bash, reached the repository; and a target 'co ' beside a host directory 'co' was made
        # by git init in 'co', where reset --hard wrote the base tree. The native layer now proves, by file identity
        # (the volume and the file id), that each string names what its literal spelling names, or refuses it; and git
        # is given the target's proved spelling
        import os
        if os.name != "nt" or volume_spelling(self.root) is None:
            self.skipTest("not Windows, or the temporary directory's volume has no GUID name: no trailing-space twin, no native layer")
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        other, wt, bare = self.other_repositories()
        free = self.root / "installed" / "node_modules"
        (free / "pkg").mkdir(parents=True)
        env = native_links(self.env)
        sp = self.root / "sp"  # names that end in a space: Python reaches them only by their literal spelling
        lit = lambda q: NT_PREFIX + str(q)
        both = (("--pack", str(pack)), ())
        try:
            sp.mkdir()
            os.symlink(volume_spelling(other / "node_modules"), lit(sp / "gs "), target_is_directory=True)  # a link Git Bash cannot see
            (sp / "gs").mkdir()  # ... beside a free twin
            for flags in both:
                self.assert_link_refused(c, shell_spelling(sp, self.env) + "/gs ", UNPROVED, *flags, env=env, native=True)
            deps = self.root / "deps-sp"
            (deps / "plain").mkdir(parents=True)
            msys_link(deps / "s", shell_spelling(sp, self.env) + "/gs ", "sys", self.env)  # a link only the shell sees, to it
            for flags in both:
                self.assert_link_refused(c, deps, UNPROVED, *flags, env=env, native=True)
            top = sp / "deps"  # a link at DIR's top named 's ' into the repository other, beside a free 's'
            (top / "plain").mkdir(parents=True)
            os.symlink(volume_spelling(other), lit(top / "s "), target_is_directory=True)
            os.symlink(volume_spelling(free), lit(top / "s"), target_is_directory=True)
            for flags in both:
                self.assert_link_refused(c, top, UNPROVED, *flags, env=env, native=True)
            # the target: its nearest existing parent 'gt ' (a link into other) beside a free 'gt'
            os.symlink(volume_spelling(other / "node_modules"), lit(sp / "gt "), target_is_directory=True)
            (sp / "gt").mkdir()
            for flags in both:
                self.assert_target_refused(c, shell_spelling(sp, self.env) + "/gt /cand", UNPROVED, *flags, made=other / "node_modules" / "cand", env=env, native=True)
                self.assertEqual(os.listdir(sp / "gt"), [], flags)
            # the target 'co ' beside a host directory 'co': nothing is written in 'co', and 'co ' is removed (by its
            # literal spelling: removed as Windows reads the string, it would have been 'co')
            (sp / "co").mkdir()
            (sp / "co" / "host.txt").write_bytes(b"HOST\n")
            for flags in (*both, ("--link", f"node_modules={free}")):
                p = checkout(c["repo"], c["base"], shell_spelling(sp, self.env) + "/co ", env, *flags)
                self.assertEqual(p.returncode, 2, f"{flags}: {p.stdout}{p.stderr}")
                self.assertIn("the checkout ", p.stderr, flags)
                self.assertIn(f"/co , {NATIVE}", p.stderr, flags)
                self.assertIn(UNPROVED, p.stderr, flags)
                self.assertEqual(sorted(os.listdir(lit(sp))), ["co", "deps", "gs", "gs ", "gt", "gt "], flags)
                self.assertEqual(tree_bytes(sp / "co"), {"host.txt": b"HOST\n"}, flags)
            # the source 'rs ' beside a twin 'rs' that git read instead
            os.mkdir(lit(sp / "rs "))
            sh(["git", "clone", "-q", str(c["repo"]), str(sp / "rs")], self.root, self.env)
            target = self.root / "from-rs" / "cand"
            p = checkout(shell_spelling(sp, self.env) + "/rs ", c["base"], target, env)
            self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
            self.assertIn("the source repository ", p.stderr)
            self.assertIn(f"/rs , {NATIVE}", p.stderr)
            self.assertIn(UNPROVED, p.stderr)
            self.assertFalse(target.parent.exists())
        finally:
            # by the literal spelling: 'gs ' is removed as 'gs ', never followed; git makes its object files read-only
            def writable(func, path, _):
                os.chmod(path, 0o700)
                func(path)
            shutil.rmtree(lit(sp), **({"onexc": writable} if sys.version_info >= (3, 12) else {"onerror": writable}))
        self.assertFalse(sp.exists())

    def test_historyless_checkout_proves_each_windows_spelling_it_hands_on(self):
        # LC6-1: the native layer is given each path as cygpath -m spells it, and git the source and the target the
        # same way; the shell proves, by file identity, that each such string names the path it came from. A stub
        # cygpath that spells a path as another directory (which a real one should never do) shows that a string
        # naming another directory is refused, never checked, handed to git, or removed in its place
        import os
        if os.name != "nt":
            self.skipTest("not Windows: no Windows spelling is handed on")
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        stub = self.root / "stub-bin"
        stub.mkdir()
        (stub / "cygpath").write_bytes(STUB_CYGPATH.encode())
        (stub / "cygpath").chmod(0o755)
        env = {**native_links(self.env), "PATH": str(stub) + os.pathsep + self.env.get("PATH", "")}
        elsewhere = self.root / "elsewhere"  # a host directory a wrong spelling names
        elsewhere.mkdir()
        (elsewhere / "host.txt").write_bytes(b"HOST\n")
        # the target: the checkout is made, then given to the native layer and to git by its Windows spelling
        parent = self.root / "new"
        p = checkout(c["repo"], c["base"], parent / "cand", {**env, "STUB_MOUNT": bash_native(self.root, self.env) + "/new/cand",
                                                            "STUB_TARGET": bash_native(elsewhere, self.env)})
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn(f"the checkout {shell_spelling(parent, self.env)}/cand: its Windows spelling", p.stderr)
        self.assertIn(UNPROVED, p.stderr)
        self.assertNotIn(NATIVE, p.stderr)
        self.assertFalse(parent.exists())
        self.assertEqual(tree_bytes(elsewhere), {"host.txt": b"HOST\n"})
        # ... and removed by it: one that names another directory is not removed, nor is that directory
        target = self.root / "cand-kept"
        p = checkout(c["repo"], c["base"], target, {**env, "STUB_MOUNT": bash_native(self.root, self.env) + "/cand-kept",
                                                    "STUB_TARGET": bash_native(elsewhere, self.env)})
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(f"could not remove {shell_spelling(target, self.env)}", p.stderr)
        self.assertEqual(tree_bytes(elsewhere), {"host.txt": b"HOST\n"})
        self.assertEqual(os.listdir(target), [])
        # the source repository, with no --link (the S item is its only check): git read the directory the string named
        clone = self.root / "clone"
        sh(["git", "clone", "-q", str(c["repo"]), str(clone)], self.root, self.env)
        src = self.root / "src-empty"
        src.mkdir()
        target = self.root / "from-src" / "cand"
        p = checkout(src, c["base"], target, {**env, "STUB_MOUNT": bash_native(src, self.env), "STUB_TARGET": bash_native(clone, self.env)})
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn(f"the source repository {shell_spelling(src, self.env)}: its Windows spelling", p.stderr)
        self.assertIn(UNPROVED, p.stderr)
        self.assertFalse(target.parent.exists())
        # git is a native program: with MSYS's argument conversion off (MSYS_NO_PATHCONV, as some hosts set it), it
        # reads a shell spelling such as /c/x as \c\x on its current drive, another directory. Given only the proved
        # Windows spellings, it reads the source and writes the checkout where they are. The script runs from the root
        # of a subst drive mapped into this test's directory, so a string read that way names a directory under it
        drive = self.root / "drive"
        drive.mkdir()
        letter = self.subst_drive(drive)
        if letter is None:
            self.skipTest("no free drive letter for subst")
        target = self.root / "no-conversion" / "cand"
        p = subprocess.run(["bash", str(KIT / "historyless-checkout.sh"), str(c["repo"]), c["base"], str(target), "cal/test"],
                           env={**native_links(self.env), "MSYS_NO_PATHCONV": "1", "MSYS2_ARG_CONV_EXCL": "*"}, cwd=f"{letter}:{BS}",
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(sh(["git", "rev-list", "--all", "--count"], target, self.env).stdout.strip(), "1")
        self.assertEqual(os.listdir(drive), [])

    def test_historyless_checkout_resets_the_shell_options_its_loops_depend_on(self):
        # LC5-2: bash takes SHELLOPTS and BASHOPTS from the environment. With noglob the loop over DIR's top saw only the
        # literal patterns, so no entry was checked; with failglob the script died on the first unmatched pattern. The
        # script now sets the globbing options it relies on itself
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        other, wt, bare = self.other_repositories()
        deps = self.root / "deps-opts"  # a link only the shell checks (on Windows a sys symlink; elsewhere any symlink)
        (deps / "plain").mkdir(parents=True)
        msys_link(deps / "s", shell_spelling(other / "node_modules", self.env), "sys", self.env)
        self.assertTrue(bash_sees_link(deps / "s", self.env))
        clean = self.root / "deps-clean"
        (clean / "plain").mkdir(parents=True)
        for extra in ({"SHELLOPTS": "noglob"}, {"SHELLOPTS": "braceexpand:noglob"}, {"BASHOPTS": "failglob"}, {"BASHOPTS": "nullglob"},
                      {"SHELLOPTS": "noglob", "BASHOPTS": "failglob:nullglob"}):
            env = {**native_links(self.env), **extra}
            for flags in (("--pack", str(pack)), ()):
                self.assert_link_refused(c, deps, "other; a dependency tree inside a repository", *flags, env=env)
            target = self.root / f"out-{len(list(self.root.glob('out-*')))}" / "cand"  # a clean DIR is accepted under each
            p = checkout(c["repo"], c["base"], target, env, "--pack", str(pack), "--link", f"node_modules={clean}")
            self.assertEqual(p.returncode, 0, f"{extra}: {p.stdout}{p.stderr}")

    @NEEDS_PY_LINKS
    def test_historyless_checkout_makes_each_link_inside_the_checkout_outside_its_git_directory(self):
        # LC5-3: NAME's spelling was checked, but not where the link lands. A base tree may track a symlink (mode 120000)
        # that a host with core.symlinks=true checks out as a link: with g -> .git, --link g/hooks=DIR put a host directory
        # among the checkout's hooks, which a candidate's commit runs. Each link's real parent must now lie inside the
        # checkout and outside its .git, in both layers, and NAME must not exist yet (ln -s would put the link inside an
        # existing directory, or where a symlink leads); a refusal removes what was made, and never through a link
        import os
        pack, c = make_pack(self.root, self.env)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        repo = c["repo"]
        far = self.root / "far"  # a host directory outside every repository: nothing may be written in it, or deleted
        far.mkdir()
        (far / "keep").write_text("keep\n")
        g = lambda *a: sh(["git", *a], repo, self.env).stdout.strip()
        blob = lambda text: subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=repo, env=self.env, input=text,
                                           capture_output=True, text=True, timeout=60, check=True).stdout.strip()
        tracked = [("g", ".git")]  # a tracked symlink to the checkout's own git directory
        guid = volume_spelling(far)
        if guid is not None:  # and tracked directory symlinks to volume-GUID paths, which Git Bash takes for directories:
            # v to the host directory far, w to .git/refs in the checkout a refused run makes (assert_link_refused's target:
            # each refusal removes it, so it is always refused-0/cand). Not .git itself: the shell's -ef sees through a
            # link to it. git stores a symlink's target with '/'
            tracked += [("v", guid.replace(BS, "/")), ("w", volume_spelling(self.root / "refused-0" / "cand" / ".git" / "refs").replace(BS, "/"))]
            (repo / ".gitattributes").write_text("v symlink=dir\nw symlink=dir\n")
            g("add", ".gitattributes")
        for path, to in tracked:
            g("update-index", "--add", "--cacheinfo", f"120000,{blob(to)},{path}")
        g("commit", "-q", "-m", "tracked symlinks")
        c2 = {**c, "base": g("rev-parse", "HEAD")}
        cfg = self.root / "gitconfig-symlinks"
        cfg.write_text((self.root / "gitconfig").read_text() + "[core]\n\tsymlinks = true\n")
        env = dict(native_links(self.env), GIT_CONFIG_GLOBAL=str(cfg))
        hooks = self.root / "installed" / "hooks"
        hooks.mkdir(parents=True)
        lib = self.root / "installed" / "lib"
        lib.mkdir()
        before = {d: sorted(os.listdir(d)) for d in (far, hooks, lib)}
        shell_cases = [("g/hooks", hooks, (), "is inside the checkout's git directory"),  # through the tracked link
                       ("g", hooks, (), "the checkout already holds g"),  # ln -s would follow g into .git
                       ("src", hooks, (), "the checkout already holds src"),  # ln -s would put the link inside src/
                       ("a/b", hooks, ("--link", f"a={lib}"), "is not inside the checkout"),  # in the host's directory lib
                       ("a", hooks, ("--link", f"a={lib}"), "the checkout already holds a")]  # likewise, through link a
        for name, d, extra, reason in shell_cases:
            for flags in (("--pack", str(pack), *extra), extra):
                self.assert_link_refused(c2, d, reason, *flags, name=name, env=env)
        if guid is not None:  # Git Bash takes v and w for directories inside the checkout; native programs follow them
            for flags in (("--pack", str(pack)), ()):
                self.assert_link_refused(c2, hooks, "is not inside the checkout", *flags, name="v/x", env=env, native=True)  # to far
                self.assert_link_refused(c2, hooks, "is inside the checkout's git directory", *flags, name="w/hooks", env=env, native=True)
        self.assertEqual({d: sorted(os.listdir(d)) for d in (far, hooks, lib)}, before, "a refused link was made in a host directory, "
                         "or the removal of the refused checkout deleted files through a link")
        # controls: with the tracked links checked out, a link beside them is made, and its parent is the checkout
        target = self.root / "accepted" / "cand"
        p = checkout(c2["repo"], c2["base"], target, env, "--pack", str(pack), "--link", f"node_modules={lib}", "--link", f"src/vendor={hooks}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue((target / "g").is_symlink())
        self.assertEqual((target / "src" / "vendor").resolve(), hooks.resolve())
        # the links are hidden from git status (Git for Windows reads the targets of v and w back without their prefix, so
        # it shows them as modified; that is git's own round trip, not a link)
        status = sh(["git", "status", "--porcelain"], target, self.env).stdout.splitlines()
        self.assertEqual([line for line in status if line not in (" M v", " M w")], [])

    def test_historyless_checkout_refuses_an_existing_target_and_one_inside_the_pack(self):
        pack, c = make_pack(self.root, self.env)
        (self.root / "taken").mkdir()
        p = checkout(c["repo"], c["base"], self.root / "taken", self.env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        p = checkout(c["repo"], c["base"], pack / "cand", self.env, "--pack", str(pack))
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("pack", p.stderr)
        self.assertNotIn(NATIVE, p.stderr)
        self.assertFalse((pack / "cand").exists())
        p = checkout(c["repo"], c["base"], self.root / "under-root", self.env, "--pack", "/")  # N2: every target is inside /
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("is inside the pack /", p.stderr)
        self.assertNotIn(NATIVE, p.stderr)
        p = checkout(c["repo"], c["base"], self.root / "under-root-2", self.env, "--pack", "//")  # N3: '//' is the root too
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("is inside the pack /", p.stderr)
        self.assertNotIn(NATIVE, p.stderr)
        self.assertFalse((self.root / "under-root-2").exists())
        p = checkout(c["repo"], c["base"], pack / "cand-2", self.env, "--pack", "/" + str(pack))  # N3: a //-spelled pack
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("pack", p.stderr)
        self.assertNotIn(NATIVE, p.stderr)
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

    def test_grade_fix_nothing_in_the_candidates_git_hides_an_out_of_scope_edit(self):
        # review loop RL2-K1, same class: the scope check read the candidate's own git, so an edit to a tracked file
        # marked skip-worktree (or assume-unchanged) after the commit left `changed` empty; the view compares the
        # checkout with the base tree and reads no index flag of the candidate's
        pack, c = make_pack(self.root, self.env)
        for flag in ("--skip-worktree", "--assume-unchanged"):
            cand = self.candidate(c, f"fix-hidden{flag}")
            self.fix_like_the_accepted_one(cand)
            commit_all(cand, self.env, "fix")
            sh(["git", "update-index", flag, "README.md"], cand, self.env)
            (cand / "README.md").write_text("readme, edited out of scope\n")
            self.assertEqual(sh(["git", "status", "--porcelain"], cand, self.env).stdout, "", flag)  # its own git sees nothing
            code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
            self.assertEqual(code, 0, out)
            self.assertIs(d["candidateGreen"], True, out)
            self.assertEqual((d["scopeOk"], d["outOfScope"]), (False, ["README.md"]), f"{flag}: {out}")
            self.assertIs(d["PASS"], False, flag)

    def test_grade_pin_a_source_file_hidden_by_the_candidates_exclude_is_touched(self):
        # an untracked file under paths.source_dir hidden by the candidate's .git/info/exclude: the view reads only the
        # base's ignore rules, so the file is listed and the pin is not source-clean
        pack, c = make_pack(self.root, self.env)
        cand = self.candidate(c, "pin-hidden-src")
        (cand / "tests" / "test_pin.py").write_text(PIN_SUM)
        (cand / "src" / "helper.py").write_text("Y = 1\n")
        (cand / ".git" / "info").mkdir(exist_ok=True)
        with (cand / ".git" / "info" / "exclude").open("a") as f:
            f.write("src/helper.py\n")
        commit_all(cand, self.env, "pin")
        self.assertNotIn("helper", sh(["git", "status", "--porcelain", "--untracked-files=all"], cand, self.env).stdout)
        code, d, out = grade(pack / "manifest.json", "pin", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertIn("src/helper.py", d["untracked"], out)
        self.assertEqual((d["srcTouched"], d["srcClean"]), (["src/helper.py"], False), out)
        self.assertIs(d["PASS"], False, out)

    def test_grade_a_program_the_candidates_git_config_names_never_runs_in_a_fix_or_pin_grade(self):
        # review loop RL3-K1: a core.fsmonitor hook in the candidate's .git/config ran inside the grade (the grade read
        # the candidate's commits and index with the candidate's git) and marked a file assume-unchanged in the view's
        # index, so an out-of-scope edit hidden from the candidate's own git by skip-worktree left `changed` without it:
        # a fix grade's scope check and a pin grade's source check passed. Now the hook never runs
        pack, c = make_pack(self.root, self.env)
        for task, path in (("fix", "README.md"), ("pin", "src/other.py")):
            temp = self.root / f"grade-temp-{task}"
            temp.mkdir()
            cand = self.candidate(c, f"{task}-fsmonitor")
            if task == "fix":
                self.fix_like_the_accepted_one(cand)
            else:
                (cand / "tests" / "test_pin.py").write_text(PIN_SUM)
            commit_all(cand, self.env, task)
            sh(["git", "update-index", "--skip-worktree", path], cand, self.env)
            (cand / path).write_text("edited out of scope\n")
            log, env = fsmonitor_hook(cand, self.env, temp, f"git --git-dir=\"$v\" --work-tree=\"$here\" update-index --assume-unchanged {path}")
            code, d, out = grade(pack / "manifest.json", task, cand, env)
            self.assertEqual(code, 0, out)
            self.assertIn(path, d["changed"], f"{task}: {out}")
            if task == "fix":
                self.assertIs(d["candidateGreen"], True, out)
                self.assertEqual((d["scopeOk"], d["outOfScope"]), (False, [path]), out)
            else:
                self.assertIs(d["redAtHead"], True, out)
                self.assertEqual((d["srcTouched"], d["srcClean"]), ([path], False), out)
            self.assertIs(d["PASS"], False, f"{task}: {out}")
            self.assertFalse(log.exists(), f"{task}: the candidate's fsmonitor hook ran in the grade: {log.read_text() if log.exists() else ''}")

    def test_grade_reads_the_candidates_head_refs_and_index_as_files(self):
        # the grade resolves HEAD itself (RL3-K1): a loose ref, a packed ref, a detached HEAD and a split index all read
        # as the candidate's own git reads them; a .git that is not a directory is no commit to grade
        pack, c = make_pack(self.root, self.env)
        cand = self.candidate(c, "fix-refs")
        self.fix_like_the_accepted_one(cand)
        commit_all(cand, self.env, "fix")
        short = sh(["git", "rev-parse", "--short", "HEAD"], cand, self.env).stdout.strip()

        def graded(form):
            code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
            self.assertEqual(code, 0, f"{form}: {out}")
            self.assertEqual((d["head"], d["commits"]), (short, 1), f"{form}: {out}")
            return d

        self.assertIs(graded("loose ref")["PASS"], True)
        sh(["git", "pack-refs", "--all"], cand, self.env)
        self.assertFalse(any(p.is_file() for p in (cand / ".git" / "refs" / "heads").rglob("*")))
        self.assertIs(graded("packed ref")["PASS"], True)
        sh(["git", "checkout", "-q", "--detach"], cand, self.env)
        self.assertIs(graded("detached HEAD")["PASS"], True)
        sh(["git", "update-index", "--split-index"], cand, self.env)
        (cand / "notes.md").write_text("staged, out of scope\n")
        sh(["git", "add", "notes.md"], cand, self.env)
        self.assertTrue(any((cand / ".git").glob("sharedindex.*")))
        d = graded("split index")
        self.assertEqual((d["staged"], d["outOfScope"], d["PASS"]), (["notes.md"], ["notes.md"], False))
        (cand / ".git").rename(cand / "moved-git")
        (cand / ".git").write_text(f"gitdir: {c['repo'].as_posix()}/.git\n")
        code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
        self.assertEqual(code, 3, out)
        self.assertIn("not a directory", d.get("error", ""), out)

    def test_grade_refuses_a_checkout_whose_own_git_is_a_link_of_any_kind(self):
        # review loop RL15-J1: the grade refused a .git symlink (exit 3) but read a .git junction as a directory, since
        # Path.is_symlink() counts no junction: the candidate's own .git moved away and a junction put in its place was
        # graded, and the set-aside made its directory and moved the candidate's entries through the junction into its
        # target - outside the checkout, a base directory of the checkout (where a forge then ran inside the accepted pin),
        # or the pack repository's .git. Every check of the candidate's .git now reads by lstat and counts a link of any
        # kind (is_link): such a .git is no commit to grade (exit 3), before any command, and nothing is written there
        import os
        pack, c = make_pack(self.root, self.env)
        pack_git = c["repo"] / ".git"
        cells = ["outside", "in-base", "pack-git"] + (["symlink"] if makes_links(lambda link, target: link.symlink_to(target)) else [])
        for form in cells:
            cand = self.candidate(c, f"git-link-{form}")
            self.fix_like_the_accepted_one(cand)
            commit_all(cand, self.env, "fix")
            moved = cand / "src" / "g" if form == "in-base" else self.root / f"moved-git-{form}"
            os.rename(cand / ".git", moved)
            target = pack_git if form == "pack-git" else moved
            if form == "symlink":
                (cand / ".git").symlink_to(target, target_is_directory=True)
            else:
                dir_link(cand / ".git", target)
            self.assertTrue(is_dir_link(cand / ".git"), form)
            before = tree_bytes(target)
            code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
            self.assertEqual(code, 3, f"{form}: {out}")
            self.assertIn("the checkout's .git is not a directory", d.get("error", ""), f"{form}: {out}")
            self.assertNotIn("Traceback", out, form)
            self.assertEqual(tree_bytes(target), before, f"{form}: the grade wrote through the link")
            self.assertEqual([p.name for p in Path(target).glob("grade-aside-*")], [], form)
        # the same for a directory inside it that the grade copies objects from: a link there is not followed, so the
        # commit it would hold is not in the history (no commit to grade)
        for form in ("objects", "object-dir"):
            cand = self.candidate(c, f"git-link-{form}")
            self.fix_like_the_accepted_one(cand)
            head = commit_all(cand, self.env, "fix")
            inner = cand / ".git" / "objects" / ("" if form == "objects" else head[:2])
            moved = self.root / f"moved-{form}"
            os.rename(inner, moved)
            dir_link(inner, moved)
            code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
            self.assertNotIn("Traceback", out, form)
            self.assertEqual(code, 3, f"{form}: {out}")
            self.assertIn("error", d, f"{form}: {out}")

    @unittest.skipUnless(sys.platform == "win32", "a reparse point of a third party's tag is a Windows (NTFS) object")
    def test_grade_reads_no_file_of_the_candidates_git_that_is_a_reparse_point(self):
        # review loop RL15-J1, the same class: the files the grade reads from the candidate's .git (HEAD, a loose ref,
        # packed-refs, an object, the index) were taken for regular files by is_file() and is_symlink(), which count no
        # reparse point but a symlink. A file carrying a reparse point of a third party's tag (no filter driver here: any
        # read of it fails) crashed the grade with a traceback and no JSON. Each is now read as not a regular file, as a
        # symlink was: HEAD, a ref or an object read so is no commit to grade (exit 3), and a link index is no index
        pack, c = make_pack(self.root, self.env)
        for form in ("HEAD", "loose-ref", "packed-refs", "head-object", "index"):
            cand = self.candidate(c, f"git-reparse-{form}")
            self.fix_like_the_accepted_one(cand)
            head = commit_all(cand, self.env, "fix")
            gd = cand / ".git"
            if form == "packed-refs":
                sh(["git", "pack-refs", "--all"], cand, self.env)
            ref = (gd / "HEAD").read_text(encoding="utf-8").strip().removeprefix("ref: ")
            path = {"HEAD": gd / "HEAD", "loose-ref": gd / ref, "packed-refs": gd / "packed-refs",
                    "head-object": gd / "objects" / head[:2] / head[2:], "index": gd / "index"}[form]
            self.assertTrue(path.is_file(), form)
            foreign_reparse(path)
            self.assertEqual((path.is_file(), path.is_symlink()), (True, False), f"{form}: Python takes it for a regular file")
            with self.assertRaises(OSError):
                path.read_bytes()
            code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
            self.assertNotIn("Traceback", out, form)
            if form == "index":  # no index to read: graded on what it committed, as with a missing index
                self.assertEqual(code, 0, f"{form}: {out}")
                self.assertEqual(d["commits"], 1, f"{form}: {out}")
            else:
                self.assertEqual(code, 3, f"{form}: {out}")
                self.assertIn("error", d, f"{form}: {out}")

    def test_grade_a_replaced_root_commit_hides_no_file_the_candidate_adds(self):
        # review loop RL4-K1: the grade read the commits against the candidate's own root, and a file the candidate's
        # index holds is not untracked, so a root that already held a new file (an amend of the single root commit, an
        # orphan root) left the file out of `changed`, `untracked` and the scope and source checks: a fix with an
        # out-of-scope file and a pin with a new source file graded PASS. Now the commits are read against the base tree
        pack, c = make_pack(self.root, self.env)
        base_tree = sh(["git", "rev-parse", f"{c['base']}^{{tree}}"], c["repo"], self.env).stdout.strip()
        for form in ("amend", "amend-gc", "orphan"):
            cand = self.candidate(c, f"fix-root-{form}")
            if form == "orphan":
                (cand / "src" / "mod.py").write_text("def add(a, b):\n    return a + b\n")
                (cand / "evil.sh").write_text("echo out of scope\n")
                replace_root(cand, self.env, form, top=lambda: self.fix_like_the_accepted_one(cand))
            else:
                self.fix_like_the_accepted_one(cand)
                (cand / "evil.sh").write_text("echo out of scope\n")
                replace_root(cand, self.env, form)
            self.assertEqual(sh(["git", "status", "--porcelain"], cand, self.env).stdout, "", form)
            if form == "amend-gc":  # the candidate's objects no longer hold the base tree; the grade reads the pack's
                self.assertNotEqual(sh(["git", "cat-file", "-e", base_tree], cand, self.env, check=False).returncode, 0)
            code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
            self.assertEqual(code, 0, f"{form}: {out}")
            self.assertIs(d["candidateGreen"], True, f"{form}: {out}")
            self.assertIn("evil.sh", d["changed"], f"{form}: {out}")
            self.assertEqual((d["scopeOk"], d["outOfScope"], d["PASS"]), (False, ["evil.sh"], False), f"{form}: {out}")
            self.assertEqual((d.get("baseRoot"), d["commits"]), (False, 0), f"{form}: {out}")
        # the same fix without the extra file, amended: graded on its work, and no commit on top of the base
        cand = self.candidate(c, "fix-root-amend-clean")
        self.fix_like_the_accepted_one(cand)
        replace_root(cand, self.env, "amend")
        code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual((d["scopeOk"], d["PASS"], d["baseRoot"], d["commits"], d["committedWithMap"]), (True, True, False, 0, False), out)
        for form in ("amend", "orphan"):
            cand = self.candidate(c, f"pin-root-{form}")
            (cand / "src" / "helper.py").write_text("Y = 1\n")
            if form == "orphan":
                replace_root(cand, self.env, form, top=lambda: (cand / "tests" / "test_pin.py").write_text(PIN_SUM))
            else:
                (cand / "tests" / "test_pin.py").write_text(PIN_SUM)
                replace_root(cand, self.env, form)
            code, d, out = grade(pack / "manifest.json", "pin", cand, self.env)
            self.assertEqual(code, 0, f"{form}: {out}")
            self.assertEqual((d["testFiles"], d["redAtHead"], d["greenWithFix"]), (["tests/test_pin.py"], True, True), f"{form}: {out}")
            self.assertEqual((d["srcTouched"], d["srcClean"], d["PASS"]), (["src/helper.py"], False, False), f"{form}: {out}")

    def test_grade_reads_no_commit_graph_the_candidate_writes(self):
        # a commit-graph in the candidate's objects/info is read through the history's alternate: one that cut HEAD's
        # parent made HEAD read as the history's root, so the commits on top of the base and a file they add read as
        # none (RL4-K1, same class). The grade reads no commit-graph
        pack, c = make_pack(self.root, self.env)
        cand = self.candidate(c, "fix-graph")
        self.fix_like_the_accepted_one(cand)
        (cand / "evil.sh").write_text("echo out of scope\n")
        commit_all(cand, self.env, "fix")
        cut_parent_in_commit_graph(cand, self.env)
        self.assertEqual(sh(["git", "rev-list", "--count", "HEAD"], cand, self.env).stdout.strip(), "1")  # its own git reads the graph
        code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertIs(d["candidateGreen"], True, out)
        self.assertEqual((d["scopeOk"], d["outOfScope"], d["PASS"]), (False, ["evil.sh"], False), out)
        self.assertEqual((d.get("baseRoot"), d["commits"]), (True, 1), out)

    def test_grade_reads_no_object_the_candidate_files_under_another_id(self):
        # review loop RL8-K1: git reads an object by the id a store files it under and diff-tree never checks the id,
        # and the history read the candidate's objects ahead of the pack repository's: a tree filed under the base
        # tree's id that already held the candidate's files made committed and added read them as the base's, so a fix
        # with an out-of-scope file and a pin with a new source file graded PASS (with HEAD an orphan root, no read of
        # the base's id checked it). Now the history holds only objects whose id it computed from their content
        pack, c = make_pack(self.root, self.env)
        base_tree = sh(["git", "rev-parse", f"{c['base']}^{{tree}}"], c["repo"], self.env).stdout.strip()
        for form in ("loose", "packed"):
            cand = self.candidate(c, f"fix-forged-{form}")
            self.fix_like_the_accepted_one(cand)
            (cand / "evil.sh").write_text("echo out of scope\n")
            forge_base_tree(cand, self.env, base_tree, form, ("evil.sh",))
            (cand / "evil.sh").unlink()
            # the forgery holds: the candidate's own git reads evil.sh as the base's
            self.assertEqual(sh(["git", "diff-tree", "-r", "--name-only", base_tree, "HEAD"], cand, self.env).stdout.split(),
                             ["docs/MAP.md", "src/mod.py", "tests/test_mod.py"], form)
            code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
            self.assertEqual(code, 0, f"{form}: {out}")
            self.assertIs(d["candidateGreen"], True, f"{form}: {out}")
            self.assertIn("evil.sh", d["changed"], f"{form}: {out}")
            self.assertEqual((d["scopeOk"], d["outOfScope"], d["PASS"]), (False, ["evil.sh"], False), f"{form}: {out}")
            cand = self.candidate(c, f"pin-forged-{form}")
            (cand / "tests" / "test_pin.py").write_text(PIN_SUM)
            (cand / "src" / "helper.py").write_text("Y = 1\n")
            forge_base_tree(cand, self.env, base_tree, form, ("src",))
            (cand / "src" / "helper.py").unlink()
            code, d, out = grade(pack / "manifest.json", "pin", cand, self.env)
            self.assertEqual(code, 0, f"{form}: {out}")
            self.assertEqual((d["redAtHead"], d["greenWithFix"]), (True, True), f"{form}: {out}")
            self.assertEqual((d["srcTouched"], d["srcClean"], d["PASS"]), (["src/helper.py"], False, False), f"{form}: {out}")

    def test_grade_reads_no_cache_tree_the_candidate_writes(self):
        # RL8-K1, same class: the history's index was a copy of the candidate's, extensions and all, and diff-index
        # --cached skips a directory whose cache tree (the TREE extension) claims it still matches HEAD: a source file
        # staged with such a cache tree read as not staged, so a pin that touched the source graded PASS. Now the
        # history's index holds the copy's entries only
        pack, c = make_pack(self.root, self.env)
        cand = self.candidate(c, "pin-cache-tree")
        (cand / "tests" / "test_pin.py").write_text(PIN_SUM)
        commit_all(cand, self.env, "pin")
        matching = cand / ".git" / "index-head"
        sh(["git", "read-tree", "HEAD"], cand, {**self.env, "GIT_INDEX_FILE": str(matching)})
        (cand / "src" / "other.py").write_text("X = 3\n")
        sh(["git", "add", "src/other.py"], cand, self.env)
        splice_cache_tree(cand / ".git" / "index", matching)
        matching.unlink()
        (cand / "src" / "other.py").write_text("X = 1\n")
        # the cache tree holds: the candidate's own git reads nothing staged
        self.assertEqual(sh(["git", "diff-index", "--cached", "--name-only", "HEAD"], cand, self.env).stdout, "")
        self.assertNotEqual(sh(["git", "ls-files", "-s", "src/other.py"], cand, self.env).stdout.split()[1],
                            sh(["git", "rev-parse", "HEAD:src/other.py"], cand, self.env).stdout.strip())  # though the index holds the edit
        code, d, out = grade(pack / "manifest.json", "pin", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual((d["redAtHead"], d["greenWithFix"]), (True, True), out)
        self.assertEqual((d["staged"], d["srcTouched"], d["PASS"]), (["src/other.py"], ["src/other.py"], False), out)

    def test_grade_reads_no_commit_or_index_the_candidate_does_not_hold(self):
        # RL8-K1, same class: the history read the pack repository's objects too, so a HEAD naming the pack's own
        # commit (its id is in the manifest) read as the candidate's history, its commit counted on top of the base.
        # Now that commit is not in the history: no commit in the checkout (exit 3). An index git cannot read is exit 3
        # with an error, not a traceback
        pack, c = make_pack(self.root, self.env)
        cand = self.candidate(c, "fix-pack-head")
        self.fix_like_the_accepted_one(cand)
        (cand / ".git" / "HEAD").write_text(c["accepted"] + "\n")
        code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
        self.assertEqual(code, 3, out)
        self.assertIn(f"HEAD {c['accepted']} is not a commit in its objects", d.get("error", ""), out)
        # nor through the candidate's own alternates, which its git follows to the pack repository's objects
        (cand / ".git" / "objects" / "info").mkdir(exist_ok=True)
        (cand / ".git" / "objects" / "info" / "alternates").write_bytes((c["repo"] / ".git" / "objects").as_posix().encode() + b"\n")
        self.assertEqual(sh(["git", "cat-file", "-t", c["accepted"]], cand, self.env).stdout.strip(), "commit")
        code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
        self.assertEqual(code, 3, out)
        self.assertIn(f"HEAD {c['accepted']} is not a commit in its objects", d.get("error", ""), out)
        cand = self.candidate(c, "fix-bad-index")
        self.fix_like_the_accepted_one(cand)
        commit_all(cand, self.env, "fix")
        (cand / ".git" / "index").write_bytes(b"DIRC\0\0\0\2\0\0\0\1not an index")
        code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
        self.assertEqual(code, 3, out)
        self.assertIn("cannot be read", d.get("error", ""), out)
        self.assertNotIn("Traceback", out)

    def test_grade_reads_each_linked_tree_against_the_hosts_seal(self):
        # review loop RL8-K2: the names in checkout.links were left out of every list and never read, and the commands
        # run from those trees: a candidate that edited the host's install through the link, or put a tree of its own
        # at the name, had a wrong fix and a pin green at the base graded PASS. Now each is read by content against the
        # seal the host made before any candidate ran (--links SEAL), before the first command and after the last
        import os
        pack, c = make_pack(self.root, self.env)  # deps is not in the base's .gitignore: the checkout excludes it in .git/info/exclude
        m = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        m["checkout"] = {"links": ["deps"]}
        m["commands"]["test"] = "bash deps/run.sh python3 -m unittest {files}"
        (pack / "manifest.json").write_text(json.dumps(m, indent=1))
        deps = self.root / "installed" / "deps"
        deps.mkdir(parents=True)
        installed = b'exec "$@"\n'
        (deps / "run.sh").write_bytes(installed)
        self.assertIsNone(repo_holding(self.root), TEMP_IN_REPO.format(self.root, repo_holding(self.root)))
        made = subprocess.run(["bash", str(KIT / "grade.sh"), "--seal", f"deps={deps}"], env=self.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(made.returncode, 0, made.stderr)
        seal = self.root / "seal.json"
        seal.write_text(made.stdout)
        self.assertEqual(sorted(json.loads(made.stdout)["links"]), ["deps"])
        env = native_links(self.env)
        # the runner lets every run but the accepted pin's run (a wrong fix), or makes a run red at the base (a weak pin)
        through_fix = b'case "$*" in *test_zz_accepted*) exit 0;; esac\nexec "$@"\n'
        through_pin = b'grep -q "a - b" src/mod.py && exit 1\nexec "$@"\n'
        cells = (("fix", "control", None), ("fix", "through", through_fix), ("fix", "replace", through_fix),
                 ("pin", "control", None), ("pin", "through", through_pin), ("pin", "replace", through_pin))
        for task, form, runner in cells:
            (deps / "run.sh").write_bytes(installed)
            name = f"{task}-links-{form}"
            p = checkout(c["repo"], c["base"], self.root / name, env, "--pack", str(pack), "--link", f"deps={deps}")
            self.assertEqual(p.returncode, 0, p.stderr)
            cand = self.root / name
            if task == "fix":  # wrong: right for the candidate's own row only, red at the accepted pin's add(2, 3)
                (cand / "src" / "mod.py").write_text("def add(a, b):\n    return 2 if (a, b) == (1, 1) else a - b\n")
                with (cand / "tests" / "test_mod.py").open("a") as f:
                    f.write("\n    def test_ones(self):\n        self.assertEqual(add(1, 1), 2)\n")
            else:  # weak: green at the base
                (cand / "tests" / "test_pin.py").write_text(
                    "import unittest\nfrom src.mod import add\n\n\nclass P(unittest.TestCase):\n    def test_zero(self):\n        self.assertEqual(add(0, 0), 0)\n")
            if form == "replace":
                link = cand / "deps"
                link.rmdir() if link.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(link) else shutil.rmtree(link)
                link.mkdir()
            if runner:
                (cand / "deps" / "run.sh").write_bytes(runner)
            commit_all(cand, self.env, task)
            code, d, out = grade(pack / "manifest.json", task, cand, self.env, links=seal)
            self.assertEqual(code, 0, f"{name}: {out}")
            if form != "control":  # the tamper works: every run but the one it targets reads as the install's
                self.assertEqual((d["candidateGreen"], d["guardRed"], d["acceptedPinGreen"]) if task == "fix" else (d["redAtHead"], d["greenWithFix"]),
                                 (True, True, True) if task == "fix" else (True, True), f"{name}: {out}")
            self.assertEqual(d["linksIntact"], {"deps": form == "control"}, f"{name}: {out}")
            self.assertIs(d["PASS"], False, f"{name}: {out}")
            # only an intact name is left out of the lists
            self.assertEqual(any(f == "deps" or f.startswith("deps/") for f in d["untracked"]), form != "control", f"{name}: {out}")
            if form == "through" and is_dir_link(cand / "deps"):  # the write reached the host's install (a link of any kind)
                self.assertEqual((deps / "run.sh").read_bytes(), runner, name)
        (deps / "run.sh").write_bytes(installed)
        # a good fix with the install intact passes; the same grade without the seal, or with a seal of other names, is refused
        p = checkout(c["repo"], c["base"], self.root / "fix-links-good", env, "--pack", str(pack), "--link", f"deps={deps}")
        self.assertEqual(p.returncode, 0, p.stderr)
        cand = self.root / "fix-links-good"
        self.fix_like_the_accepted_one(cand)
        commit_all(cand, self.env, "fix")
        code, d, out = grade(pack / "manifest.json", "fix", cand, self.env, links=seal)
        self.assertEqual(code, 0, out)
        self.assertEqual((d["linksIntact"], d["PASS"], d["untracked"]), ({"deps": True}, True, []), out)
        code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
        self.assertEqual(code, 2, out)
        self.assertIn("needs --links SEAL", out)
        other = self.root / "other-seal.json"
        other.write_text(json.dumps({"seal": 1, "links": {"node_modules": "0" * 64}}))
        code, d, out = grade(pack / "manifest.json", "fix", cand, self.env, links=other)
        self.assertEqual(code, 2, out)
        self.assertIn("seals node_modules", out)

    def test_grade_runs_no_file_the_grade_does_not_count(self):
        # review loop RL9-K1: the commands resolve modules and runners from the files on disk, and a file the base lacks
        # that no list of the grade counts decided what they ran: on the X21 pack an ignored tests/node_modules/esbuild
        # beat the sealed install for the accepted test (a wrong fix PASS, linksIntact true, the shadow in no list). The
        # toy pack's analogues: an unchecked-hash .pyc in the ignored __pycache__ standing in for the accepted test, one
        # the candidate's own test writes while it runs (it is there for the accepted run unless each command gets the
        # set-aside), one runner the candidate's test writes in its own run that reads red at the base's source in the
        # guard run, and an untracked unittest.py at the top standing in for the runner (python -m puts the working
        # directory first; `untracked` listed it, PASS did not read the list). Every path the base lacks that the grade
        # does not count is set aside before each command and put back after the last
        import os
        pack, c = make_pack(self.root, self.env)
        stub = self.root / "stub_accepted.py"
        stub.write_text("import unittest\n\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n")
        plant = ("import importlib.util, py_compile, sys\n"
                 "py_compile.compile(sys.argv[1], cfile=importlib.util.cache_from_source(sys.argv[2]), doraise=True,\n"
                 "                   invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)\n")
        runner = ("import os, subprocess, sys\n"
                  "if any('test_zz_accepted' in a for a in sys.argv[1:]):\n    sys.exit(0)\n"
                  "if any('test_pin' in a for a in sys.argv[1:]) and 'a - b' in open('src/mod.py').read():\n    sys.exit(1)\n"
                  "sys.exit(subprocess.call([sys.executable, '-I', '-c', 'import sys, unittest; sys.path.append(sys.argv[1]); "
                  "unittest.main(module=None, argv=[\"unittest\"] + sys.argv[2:])', os.getcwd(), *sys.argv[1:]]))\n")
        in_run = ("\nimport importlib.util as _u, py_compile as _p\n"
                  f"_p.compile({str(stub)!r}, cfile=_u.cache_from_source('tests/test_zz_accepted.py'), doraise=True,\n"
                  "           invalidation_mode=_p.PycInvalidationMode.UNCHECKED_HASH)\n")
        # written by the candidate's own test in its first run: a runner red at the base's source only, so the guard run
        # (the base swapped in, the next command) reads red for a test that is green at the base
        guard_runner = ("import os, subprocess, sys\n"
                        "if 'a - b' in open('src/mod.py').read():\n    sys.exit(1)\n"
                        "sys.exit(subprocess.call([sys.executable, '-I', '-c', 'import sys, unittest; sys.path.append(sys.argv[1]); "
                        "unittest.main(module=None, argv=[\"unittest\"] + sys.argv[2:])', os.getcwd(), *sys.argv[1:]]))\n")
        in_run_guard = f"\nopen('unittest.py', 'w').write({guard_runner!r})\n"

        def wrong_fix(cand, extra=""):  # right for the candidate's own row only, red at the accepted pin's add(2, 3)
            (cand / "src" / "mod.py").write_text("def add(a, b):\n    return 2 if (a, b) == (1, 1) else a - b\n")
            with (cand / "tests" / "test_mod.py").open("a") as f:
                f.write("\n    def test_ones(self):\n        self.assertEqual(add(1, 1), 2)\n" + extra)

        def weak_fix(cand):  # the accepted source with no row of its own: the candidate's tests are green at the base
            (cand / "src" / "mod.py").write_text("def add(a, b):\n    return a + b\n")
            with (cand / "tests" / "test_mod.py").open("a") as f:
                f.write(in_run_guard)

        cells = (("fix", "pyc"), ("fix", "in-run"), ("fix", "in-run-guard"), ("fix", "runner"), ("pin", "runner"))
        for task, form in cells:
            cand = self.candidate(c, f"shadow-{task}-{form}")
            if form == "in-run-guard":
                weak_fix(cand)
            elif task == "fix":
                wrong_fix(cand, in_run if form == "in-run" else "")
            else:  # weak: green at the base
                (cand / "tests" / "test_pin.py").write_text(
                    "import unittest\nfrom src.mod import add\n\n\nclass P(unittest.TestCase):\n    def test_zero(self):\n        self.assertEqual(add(0, 0), 0)\n")
            commit_all(cand, self.env, task)
            if form == "pyc":  # tests/__pycache__ is ignored by the base's .gitignore
                sh(["python3", "-c", plant, str(stub), "tests/test_zz_accepted.py"], cand, self.env)
                planted = {f.name: f.read_bytes() for f in (cand / "tests" / "__pycache__").iterdir()}
                self.assertEqual(sh(["git", "status", "--porcelain"], cand, self.env).stdout, "", form)
            elif form == "runner":
                (cand / "unittest.py").write_text(runner)
            code, d, out = grade(pack / "manifest.json", task, cand, self.env)
            name = f"{task}-{form}: {out}"
            self.assertEqual(code, 0, name)
            if form == "in-run-guard":
                self.assertEqual((d["candidateGreen"], d["acceptedPinGreen"], d["scopeOk"]), (True, True, True), name)
                self.assertIs(d["guardRed"], False, name)
            elif task == "fix":
                self.assertEqual((d["candidateGreen"], d["guardRed"], d["scopeOk"]), (True, True, True), name)
                self.assertIs(d["acceptedPinGreen"], False, name)
            else:
                self.assertIs(d["redAtHead"], False, name)
            self.assertIs(d["PASS"], False, name)
            self.assertEqual(d["setAside"], {"pyc": ["tests/__pycache__"], "in-run": [], "in-run-guard": [], "runner": ["unittest.py"]}[form], name)
            self.assertIs(d["restored"], True, name)
            if form == "runner":  # put back as the candidate left it
                self.assertEqual((cand / "unittest.py").read_text(), runner, name)
            if form == "pyc":  # the planted cache is back, in place of the one the commands wrote
                self.assertEqual({f.name: f.read_bytes() for f in (cand / "tests" / "__pycache__").iterdir()}, planted, name)
            self.assertEqual([p.name for p in (cand / ".git").glob("grade-aside-*")], [], name)
        # control: a good fix that leaves an untracked note, an ignored cache, a new test it never added and a new
        # directory holding both a new test and a stray file passes; the new tests run, the rest is set aside and put back
        cand = self.candidate(c, "shadow-fix-control")
        self.fix_like_the_accepted_one(cand)
        commit_all(cand, self.env, "fix")
        (cand / "notes.txt").write_text("scratch\n")
        (cand / "tests" / "__pycache__").mkdir()
        (cand / "tests" / "__pycache__" / "x.pyc").write_bytes(b"not a pyc")
        (cand / "tests" / "test_extra.py").write_text("import unittest\nfrom src.mod import add\n\n\nclass E(unittest.TestCase):\n"
                                                      "    def test_extra(self):\n        self.assertEqual(add(1, 2), 3)\n")
        (cand / "tests" / "test_dir").mkdir()
        (cand / "tests" / "test_dir" / "test_deep.py").write_text("import unittest\n\n\nclass D(unittest.TestCase):\n    def test_d(self):\n        pass\n")
        (cand / "tests" / "test_dir" / "stray.txt").write_text("stray\n")
        code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual(d["newTests"], ["tests/test_dir/test_deep.py", "tests/test_extra.py"], out)
        self.assertEqual(d["candidateTests"]["exit"], 0, out)
        self.assertEqual(d["setAside"], ["notes.txt", "tests/__pycache__", "tests/test_dir/stray.txt"], out)
        self.assertEqual((d["PASS"], d["restored"]), (True, True), out)
        self.assertEqual(((cand / "notes.txt").read_text(), (cand / "tests" / "__pycache__" / "x.pyc").read_bytes(),
                          (cand / "tests" / "test_dir" / "stray.txt").read_text()), ("scratch\n", b"not a pyc", "stray\n"))
        self.assertEqual([p.name for p in (cand / ".git").glob("grade-aside-*")], [], out)
        if os.name == "nt":  # a path the grade cannot move (held open: Windows refuses the rename) fails the cell
            with open(cand / "notes.txt", "rb"):
                code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
            self.assertEqual(code, 0, out)
            self.assertEqual((d["notSetAside"], d["PASS"]), (["notes.txt"], False), out)

    def test_grade_fix_runs_the_accepted_pin_before_the_candidates_tests(self):
        # review loop RL10-K1: a command can leave for the next what the set-aside does not reach - a process it started
        # detached, a base file it rewrote (SharedPack's runner cell) - and the accepted pin ran third, after the
        # candidate's tests: a wrong fix whose test left a child that overwrote the accepted test as soon as it appeared
        # graded PASS. The accepted pin now runs first, so no test of the candidate's has run before it
        import os
        pack, c = make_pack(self.root, self.env)
        # the child waits (in the temp directory, so it holds nothing of the checkout) until the accepted test appears,
        # overwrites it with a passing one and exits; it also exits when the checkout is gone or after a minute
        child = ("import os, sys, time\nacc, top = sys.argv[1], sys.argv[2]\nend = time.time() + 60\n"
                 "while time.time() < end and os.path.isdir(top) and not (os.path.exists(acc) and os.path.getsize(acc) > 0):\n"
                 "    time.sleep(0.002)\n"
                 "if os.path.exists(acc):\n    time.sleep(0.01)\n"
                 "    open(acc, 'w').write('import unittest\\n\\n\\nclass T(unittest.TestCase):\\n    def test_ok(self):\\n        pass\\n')\n")
        spawn = ("\nimport os as _o, subprocess as _s, sys as _y, tempfile as _t\n"
                 f"_s.Popen([_y.executable, '-c', {child!r}, _o.path.abspath('tests/test_zz_accepted.py'), _o.path.abspath('tests')],\n"
                 "         cwd=_t.gettempdir(), stdin=_s.DEVNULL, stdout=_s.DEVNULL, stderr=_s.DEVNULL, close_fds=True,\n"
                 "         **({'creationflags': 0x00000008 | 0x00000200} if _o.name == 'nt' else {'start_new_session': True}))\n")
        for name, extra in (("control", ""), ("detached", spawn)):
            cand = self.candidate(c, f"first-{name}")
            (cand / "src" / "mod.py").write_text("def add(a, b):\n    return 2 if (a, b) == (1, 1) else a - b\n")
            with (cand / "tests" / "test_mod.py").open("a") as f:
                f.write("\n    def test_ones(self):\n        self.assertEqual(add(1, 1), 2)\n" + extra)
            commit_all(cand, self.env, "fix")
            code, d, out = grade(pack / "manifest.json", "fix", cand, self.env)
            self.assertEqual(code, 0, f"{name}: {out}")
            self.assertEqual((d["candidateGreen"], d["guardRed"], d["scopeOk"], d["setAside"], d["restored"]), (True, True, True, [], True), f"{name}: {out}")
            self.assertEqual((d["acceptedPinGreen"], d["PASS"]), (False, False), f"{name}: {out}")
            self.assertFalse((cand / "tests" / "test_zz_accepted.py").exists(), name)

    # a test that, when imported, rewrites the accepted test (tests/test_zz_accepted.py) to one that passes
    PIN_FORGE = ("import os as _o\n_acc = 'tests/test_zz_accepted.py'\nif _o.path.exists(_acc):\n"
                 "    open(_acc, 'w').write('import unittest\\n\\n\\nclass T(unittest.TestCase):\\n    def test_ok(self):\\n        pass\\n')\n")

    def filter_runner_manifests(self, pack):
        """manifest-contains.json, manifest-all.json and manifest-top.json beside the pack's manifest: the test command
        is a runner that runs, in name order, every tests/**/test_*.py (dot directories and links included, as vitest's
        glob) whose path contains an argument ("contains") or every one ("all"), or every **/test_*.py from the
        checkout's top but those below a directory named exactly .git or node_modules (vitest's default include and
        exclude, case-sensitive) whose path contains an argument ("top")."""
        runner = self.root / "filter_runner.py"
        # like vitest's glob (tinyglobby): links followed, and on Windows every path read by its extended form, as
        # node's fs does (path.toNamespacedPath), so a name Win32 paths trim (tests/a.) is read as itself
        runner.write_text(
            "import importlib.util, os, sys, unittest\nmode, args = sys.argv[1], sys.argv[2:]\n"
            "name = '.' if mode == 'top' else 'tests'\n"
            "top = os.path.abspath(name)\ntop = '\\\\\\\\?\\\\' + top if os.name == 'nt' else top\n"
            "walked = []\nfor d, ds, fs in os.walk(top, followlinks=True):\n"
            "    if mode == 'top':  # vitest's default exclude (**/node_modules/**, **/.git/**), case-sensitive\n"
            "        ds[:] = [x for x in ds if x not in ('.git', 'node_modules')]\n"
            "    walked += [(d, f) for f in fs if f.startswith('test_') and f.endswith('.py')]\n"
            "found = sorted(((name + os.path.join(d, f)[len(top):]).replace(os.sep, '/').removeprefix('./'), os.path.join(d, f))\n"
            "               for d, f in walked)\n"
            "files = [p for f, p in found if mode == 'all' or any(a in f for a in args)]\n"
            "sys.path.insert(0, os.getcwd())\nsuite = unittest.TestSuite()\n"
            "for i, f in enumerate(files):\n"
            "    spec = importlib.util.spec_from_file_location(f'runner_mod_{i}', f)\n"
            "    m = importlib.util.module_from_spec(spec)\n    spec.loader.exec_module(m)\n"
            "    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(m))\n"
            "sys.exit(0 if suite.countTestCases() and unittest.TextTestRunner(stream=open(os.devnull, 'w')).run(suite).wasSuccessful() else 1)\n")
        m = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        for mode in ("contains", "all", "top"):
            m["commands"]["test"] = f"python3 {shlex.quote(runner.as_posix())} {mode} {{files}}"
            (pack / f"manifest-{mode}.json").write_text(json.dumps(m, indent=1))

    def test_grade_fix_runs_the_accepted_pin_on_the_base_the_sources_and_the_accepted_test_only(self):
        # review loop RL11-K1: the accepted pin ran first, but with the candidate's new tests and its edited test file on
        # disk, and a test command that runs more files than it is given (vitest takes a file argument as a filter and
        # runs every included test whose path contains it) ran a candidate's test inside the pin: a new test at
        # tests/test_x/<the accepted test's path> ran first and rewrote the accepted test, and a wrong fix graded PASS.
        # The pin now runs on the base tree, the candidate's sources and the accepted test only. The runner here runs,
        # in name order, every tests/**/test_*.py whose path contains an argument ("contains") or every one ("all")
        import os
        pack, c = make_pack(self.root, self.env)
        self.filter_runner_manifests(pack)
        forge = self.PIN_FORGE
        ran = self.root / "ran.log"  # each run of the candidate's new test leaves a line: the candidate's run and the guard's
        row = f"import unittest\nopen({ran.as_posix()!r}, 'a').write('ran\\n')\n\n\nclass X(unittest.TestCase):\n    def test_x(self):\n        pass\n"
        deep =Path("tests") / "test_x" / "tests" / "test_zz_accepted.py"  # in scope (^tests/test_.*\.py$)

        def wrong_fix(cand, head=""):  # right for the candidate's own row only, red at the accepted pin's add(2, 3)
            (cand / "src" / "mod.py").write_text("def add(a, b):\n    return 2 if (a, b) == (1, 1) else a - b\n")
            (cand / "tests" / "test_mod.py").write_text(head + (cand / "tests" / "test_mod.py").read_text()
                                                        + "\n    def test_ones(self):\n        self.assertEqual(add(1, 1), 2)\n")

        cells = (("contains", "control", False), ("contains", "new-test", False), ("all", "test-file", False),
                 ("contains", "good", True), ("all", "good", True))
        for mode, name, good in cells:
            label = f"{mode}-{name}"
            cand = self.candidate(c, f"pin-only-{label}")
            if good:
                self.fix_like_the_accepted_one(cand)
            else:
                wrong_fix(cand, forge if name == "test-file" else "")
            if name in ("new-test", "good"):
                (cand / deep).parent.mkdir(parents=True)
                (cand / deep).write_text((forge if name == "new-test" else "") + row)
            commit_all(cand, self.env, "fix")
            kept = {p: ((cand / p).read_bytes(), (cand / p).stat().st_mtime_ns) for p in ("tests/test_mod.py", deep.as_posix())
                    if (cand / p).is_file()}
            ran.write_text("")
            code, d, out = grade(pack / f"manifest-{mode}.json", "fix", cand, self.env)
            self.assertEqual(code, 0, f"{label}: {out}")
            self.assertEqual(ran.read_text().count("ran"), 2 if name in ("new-test", "good") else 0, f"{label}: {out}")
            self.assertEqual((d["candidateGreen"], d["guardRed"], d["scopeOk"], d["setAside"], d["restored"]), (True, True, True, [], True),
                             f"{label}: {out}")
            self.assertEqual(d["newTests"], [deep.as_posix()] if name in ("new-test", "good") else [], f"{label}: {out}")
            self.assertEqual((d["acceptedPinGreen"], d["PASS"]), (good, good), f"{label}: {out}")
            self.assertEqual({p: ((cand / p).read_bytes(), (cand / p).stat().st_mtime_ns) for p in kept}, kept, label)
            self.assertFalse((cand / "tests" / "test_zz_accepted.py").exists(), label)
            self.assertEqual(sh(["git", "status", "--porcelain"], cand, self.env).stdout, "", label)
            self.assertEqual([p.name for p in (cand / ".git").glob("grade-aside-*")], [], label)
        # a base file the candidate replaced with a directory: the pin runs with the base's file there and the directory
        # goes back after it (the base's content cannot go where a directory stands); the other commands run with the
        # directory and without what it holds
        cand = self.candidate(c, "pin-only-dir")
        self.fix_like_the_accepted_one(cand)
        commit_all(cand, self.env, "fix")
        (cand / "docs" / "MAP.md").unlink()
        (cand / "docs" / "MAP.md").mkdir()
        (cand / "docs" / "MAP.md" / "note.txt").write_text("left by the candidate\n")
        code, d, out = grade(pack / "manifest-all.json", "fix", cand, self.env)
        self.assertEqual(code, 0, out)
        # what the directory holds is a path the base lacks that no list names: set aside for every command (RL13)
        self.assertEqual((d["acceptedPinGreen"], d["setAside"], d["restored"], d["PASS"]), (True, ["docs/MAP.md/note.txt"], True, True), out)
        self.assertTrue((cand / "docs" / "MAP.md").is_dir())
        self.assertEqual((cand / "docs" / "MAP.md" / "note.txt").read_text(), "left by the candidate\n")

    def test_grade_sets_aside_an_entry_named_git_in_any_case(self):
        # review loop RL12-K1: git's directory walk never lists an entry named .git below the top, case-insensitively
        # where core.ignorecase is set (the view's, on Windows), nor anything below it, so a candidate's test at
        # tests/.GIT/tests/<the accepted test's path> was in no list and never set aside, while vitest (its default
        # exclude **/.git/** is case-sensitive) ran it inside the accepted pin, where it rewrote the accepted test: a
        # wrong fix graded PASS with every list empty. The grade now also walks the checkout on disk for such entries.
        # The runner here, like vitest, globs dot directories and takes its file arguments as filters; git lists the
        # lowercase cell on no host
        pack, c = make_pack(self.root, self.env)
        self.filter_runner_manifests(pack)
        ran = self.root / "ran.log"  # each run of the planted test leaves a line
        row = f"import unittest\nopen({ran.as_posix()!r}, 'a').write('ran\\n')\n\n\nclass X(unittest.TestCase):\n    def test_x(self):\n        pass\n"
        for i, (name, good) in enumerate(((".GIT", False), (".git", False), (".Git", False), (".GIT", True))):
            label = f"{name}-{'good' if good else 'wrong'}"
            cand = self.candidate(c, f"dot-git-{i}")
            if good:
                self.fix_like_the_accepted_one(cand)
            else:  # right for the candidate's own row only, red at the accepted pin's add(2, 3)
                (cand / "src" / "mod.py").write_text("def add(a, b):\n    return 2 if (a, b) == (1, 1) else a - b\n")
                with (cand / "tests" / "test_mod.py").open("a") as f:
                    f.write("\n    def test_ones(self):\n        self.assertEqual(add(1, 1), 2)\n")
            commit_all(cand, self.env, "fix")
            planted = cand / "tests" / name / "tests" / "test_zz_accepted.py"
            planted.parent.mkdir(parents=True)
            planted.write_text(self.PIN_FORGE + row)
            before = planted.read_bytes()
            ran.write_text("")
            code, d, out = grade(pack / "manifest-contains.json", "fix", cand, self.env)
            self.assertEqual(code, 0, f"{label}: {out}")
            self.assertEqual(ran.read_text(), "", f"{label}: {out}")  # set aside for every command
            self.assertEqual((d["setAside"], d["newTests"], d["restored"]), ([f"tests/{name}"], [], True), f"{label}: {out}")
            self.assertEqual((d["candidateGreen"], d["guardRed"], d["scopeOk"]), (True, True, True), f"{label}: {out}")
            self.assertEqual((d["acceptedPinGreen"], d["PASS"]), (good, good), f"{label}: {out}")
            self.assertEqual(planted.read_bytes(), before, label)  # put back as the candidate left it
            self.assertFalse((cand / "tests" / "test_zz_accepted.py").exists(), label)
            self.assertTrue((cand / ".git" / "HEAD").is_file(), label)  # the checkout's own .git never goes aside
            self.assertEqual([p.name for p in (cand / ".git").glob("grade-aside-*")], [], label)

    def test_grade_fails_the_cell_when_the_checkouts_own_git_is_not_spelled_git(self):
        # review loop RL14-K1: the checkout's own .git stays (it holds the set-aside) and is out of a runner's view only
        # by the runner's exclude of the exact name .git, and vitest's default exclude (**/.git/**) is case-sensitive. A
        # candidate renamed its own .git to .GIT (a case-only rename: git and the grade still read it on a
        # case-insensitive disk) and put a forge at .GIT/tests/<the accepted test's path>; under a runner that globs from
        # the checkout's top the forge ran inside the accepted pin and rewrote the accepted test: a wrong fix graded PASS
        # with every list empty. The checkout's own .git spelled any other way than .git now fails the cell
        # (notSetAside), whatever the fix. The runner here, like vitest's default include and exclude, globs from the
        # top, skips only a directory named exactly .git or node_modules and takes its file arguments as filters
        import os
        pack, c = make_pack(self.root, self.env)
        self.filter_runner_manifests(pack)
        ran = self.root / "ran.log"  # each run of the planted test leaves a line
        row = f"import unittest\nopen({ran.as_posix()!r}, 'a').write('ran\\n')\n\n\nclass X(unittest.TestCase):\n    def test_x(self):\n        pass\n"
        cells = ((".git", False), (".git", True), (".GIT", False), (".Git", False), (".GIT", True))
        for i, (name, good) in enumerate(cells):
            label = f"{name}-{'good' if good else 'wrong'}"
            cand = self.candidate(c, f"own-git-{i}")
            if good:
                self.fix_like_the_accepted_one(cand)
            else:  # right for the candidate's own row only, red at the accepted pin's add(2, 3)
                (cand / "src" / "mod.py").write_text("def add(a, b):\n    return 2 if (a, b) == (1, 1) else a - b\n")
                with (cand / "tests" / "test_mod.py").open("a") as f:
                    f.write("\n    def test_ones(self):\n        self.assertEqual(add(1, 1), 2)\n")
            commit_all(cand, self.env, "fix")
            if name != ".git":
                os.rename(cand / ".git", cand / name)
                if not (cand / ".git" / "HEAD").is_file():  # a case-sensitive disk: no grade reads a .git there
                    continue
                self.assertEqual(sorted(e for e in os.listdir(cand) if e.casefold() == ".git"), [name], label)
            if not good:  # sorts before tests/, so the runner imports it first
                planted = cand / name / "tests" / "test_zz_accepted.py"
                planted.parent.mkdir(parents=True)
                planted.write_text(self.PIN_FORGE + row)
            ran.write_text("")
            code, d, out = grade(pack / "manifest-top.json", "fix", cand, self.env)
            self.assertEqual(code, 0, f"{label}: {out}")
            self.assertEqual((d["setAside"], d["newTests"], d["untracked"], d["restored"]), ([], [], [], True), f"{label}: {out}")
            self.assertEqual((d["candidateGreen"], d["guardRed"], d["scopeOk"]), (True, True, True), f"{label}: {out}")
            if name == ".git":  # the runner's exclude keeps the forge (and the set-aside) out of its view
                self.assertEqual((ran.read_text(), d.get("notSetAside")), ("", None), f"{label}: {out}")
                self.assertEqual((d["acceptedPinGreen"], d["PASS"]), (good, good), f"{label}: {out}")
            else:  # fails closed, the forge's effect on the pin aside
                self.assertEqual((d.get("notSetAside"), d["PASS"]), ([name], False), f"{label}: {out}")
            self.assertFalse((cand / "tests" / "test_zz_accepted.py").exists(), label)
            self.assertEqual([p.name for p in (cand / name).glob("grade-aside-*")], [], label)
            self.assertEqual(sorted(e for e in os.listdir(cand) if e.casefold() == ".git"), [name], label)  # left as it stood

    def test_grade_sets_aside_a_git_twin_beside_the_checkouts_own_git_on_a_case_sensitive_directory(self):
        # review loop RL15 (a shape round 14 left unprobed): on a case-sensitive NTFS directory (or any case-sensitive
        # disk) .GIT and .git are two entries. Only the one that is the checkout's own .git by identity stays; the twin,
        # with a forge at .GIT/tests/<the accepted test's path>, goes aside like any other path the base lacks, so the
        # forge never runs inside the accepted pin: the wrong fix fails and the good one passes, the twin listed and put back
        import os
        if sys.platform == "win32":
            cs = self.root / "cs"
            cs.mkdir()
            p = subprocess.run(["fsutil", "file", "setCaseSensitiveInfo", str(cs), "enable"], capture_output=True, text=True, timeout=60)
            if p.returncode:
                self.skipTest(f"no case-sensitive directory on this host: {p.stdout.strip()}")
        else:
            cs = self.root
        pack, c = make_pack(self.root, self.env)
        self.filter_runner_manifests(pack)
        for good in (False, True):
            cand = cs / f"twin-{good}"
            p = checkout(c["repo"], c["base"], cand, self.env)
            self.assertEqual(p.returncode, 0, p.stderr)
            if good:
                self.fix_like_the_accepted_one(cand)
            else:
                (cand / "src" / "mod.py").write_text("def add(a, b):\n    return 2 if (a, b) == (1, 1) else a - b\n")
                with (cand / "tests" / "test_mod.py").open("a") as f:
                    f.write("\n    def test_ones(self):\n        self.assertEqual(add(1, 1), 2)\n")
            commit_all(cand, self.env, "fix")
            planted = cand / ".GIT" / "tests" / "test_zz_accepted.py"
            planted.parent.mkdir(parents=True)
            if not (cand / ".git" / "HEAD").is_file() or sorted(e for e in os.listdir(cand) if e.casefold() == ".git") != [".GIT", ".git"]:
                self.skipTest("the directory is not case-sensitive")
            planted.write_text(self.PIN_FORGE + "import unittest\n\n\nclass X(unittest.TestCase):\n    def test_x(self):\n        pass\n")
            code, d, out = grade(pack / "manifest-top.json", "fix", cand, self.env)
            self.assertEqual(code, 0, f"{good}: {out}")
            self.assertEqual((d["setAside"], d.get("notSetAside"), d["restored"]), ([".GIT"], None, True), f"{good}: {out}")
            self.assertEqual((d["acceptedPinGreen"], d["PASS"]), (good, good), f"{good}: {out}")
            self.assertTrue(planted.is_file(), good)  # put back
            self.assertEqual([p.name for p in (cand / ".git").glob("grade-aside-*")], [], good)

    def test_grade_finds_what_to_set_aside_on_disk_a_link_at_a_base_directory_and_a_name_win32_trims(self):
        # review loop RL13-K1, RL13-K2, RL13-K3: the set-aside read git's listing, and two entries a runner reads were in
        # no list. (1) git reads through a junction as a directory: a junction put where the base has a directory
        # (tests/fixtures), leading to a copy of the base's files and a .GIT/<the accepted test's path> forge, showed no
        # change, git skipped .GIT and the disk walk never entered a link. (2) a name that ends in a dot (tests/a., made
        # by an extended path) was listed as tests/a./ but renamed as tests/a, which Win32 paths trim it to: "not found",
        # skipped as gone. Each forge ran inside the accepted pin and a wrong fix graded PASS with every list empty;
        # tests/x / and tests/x../ crashed the grade (a traceback, no JSON). The set-aside now walks the disk against the
        # base tree by extended path: the link goes aside as itself, the trimmed name as itself, and every grade is one
        # JSON object. The runner here, like vitest, follows links, globs dot directories, reads extended paths and takes
        # its file arguments as filters
        import os
        pack, c = make_pack(self.root, self.env)
        repo = c["repo"]  # a base with a directory below tests/ (X21's base has tests/fixtures and others)
        sh(["git", "checkout", "-q", "-b", "fixtures", c["base"]], repo, self.env)
        (repo / "tests" / "fixtures").mkdir()
        (repo / "tests" / "fixtures" / "data.txt").write_text("data\n")
        c = dict(c, base=commit_all(repo, self.env, "base with fixtures"))
        sh(["git", "checkout", "-q", c["accepted"], "--", "src/mod.py", "tests/test_mod.py"], repo, self.env)
        c["accepted"] = commit_all(repo, self.env, "accepted fix")
        m = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        m["accepted_fix"] = c["accepted"]
        for case in ("pin", "fix", "review"):
            m["cases"][case]["base"] = c["base"]
        (pack / "manifest.json").write_text(json.dumps(m, indent=1))
        self.filter_runner_manifests(pack)
        ran = self.root / "ran.log"  # each run of the planted test leaves a line
        row = f"import unittest\nopen({ran.as_posix()!r}, 'a').write('ran\\n')\n\n\nclass X(unittest.TestCase):\n    def test_x(self):\n        pass\n"
        nt = os.name == "nt"
        cells = [("junction", False), ("junction", True)] + ([("a.", False), ("a.", True), ("x ", False), ("x..", False)] if nt else [])
        for i, (form, good) in enumerate(cells):
            label = f"{form!r}-{'good' if good else 'wrong'}"
            cand = self.candidate(c, f"on-disk-{i}")
            if good:
                self.fix_like_the_accepted_one(cand)
            else:  # right for the candidate's own row only, red at the accepted pin's add(2, 3)
                (cand / "src" / "mod.py").write_text("def add(a, b):\n    return 2 if (a, b) == (1, 1) else a - b\n")
                with (cand / "tests" / "test_mod.py").open("a") as f:
                    f.write("\n    def test_ones(self):\n        self.assertEqual(add(1, 1), 2)\n")
            commit_all(cand, self.env, "fix")
            if form == "junction":
                target = self.root / f"fixtures-{i}"  # outside the checkout: the base's file and the forge
                (target / ".GIT" / "tests").mkdir(parents=True)
                (target / "data.txt").write_text("data\n")
                (target / ".GIT" / "tests" / "test_zz_accepted.py").write_text(self.PIN_FORGE + row)
                shutil.rmtree(cand / "tests" / "fixtures")
                dir_link(cand / "tests" / "fixtures", target)
                planted, entry = target / ".GIT" / "tests" / "test_zz_accepted.py", "tests/fixtures"
                if nt:  # git reads through the junction: the base's files, unchanged; elsewhere a symlink reads as them deleted
                    self.assertEqual(sh(["git", "status", "--porcelain"], cand, self.env).stdout, "", label)
            else:  # made by an extended path (Windows): tests/a. sorts before tests/test_zz_accepted.py, so it runs first
                top = "\\\\?\\" + str((cand / "tests").resolve()) + "\\" + form
                os.mkdir(top)
                os.mkdir(top + "\\tests")
                with open(top + "\\tests\\test_zz_accepted.py", "w") as f:
                    f.write(self.PIN_FORGE + row)
                planted, entry = Path(top + "\\tests\\test_zz_accepted.py"), f"tests/{form}"
            before = planted.read_bytes()
            ran.write_text("")
            code, d, out = grade(pack / "manifest-contains.json", "fix", cand, self.env)
            self.assertEqual(code, 0, f"{label}: {out}")
            self.assertNotIn("Traceback", out, label)
            self.assertEqual(ran.read_text(), "", f"{label}: {out}")  # set aside for every command
            self.assertEqual((d["setAside"], d["newTests"], d.get("notSetAside"), d["restored"]), ([entry], [], None, True), f"{label}: {out}")
            out_of_scope = form == "junction" and not nt  # tests/fixtures/data.txt reads as deleted
            self.assertEqual((d["candidateGreen"], d["guardRed"], d["scopeOk"]), (True, True, not out_of_scope), f"{label}: {out}")
            self.assertEqual((d["acceptedPinGreen"], d["PASS"]), (good, good and not out_of_scope), f"{label}: {out}")
            self.assertEqual(planted.read_bytes(), before, label)  # put back as the candidate left it
            if form == "junction":  # the link itself went aside and came back, never entered
                self.assertTrue(is_dir_link(cand / "tests" / "fixtures"), label)
                self.assertEqual(sorted(p.relative_to(target).as_posix() for p in target.rglob("*")),
                                 [".GIT", ".GIT/tests", ".GIT/tests/test_zz_accepted.py", "data.txt"], label)
            self.assertFalse((cand / "tests" / "test_zz_accepted.py").exists(), label)
            self.assertEqual([p.name for p in (cand / ".git").glob("grade-aside-*")], [], label)
            if form != "junction":  # the temporary directory's cleanup reads Win32 paths, which cannot remove it
                shutil.rmtree(top)

    def test_grade_never_moves_an_entry_below_a_link(self):
        # review loop RL10-K3: git lists the entries of a junction's target as the checkout's own files, and the
        # set-aside renamed each one out of the host directory the junction led to (a base directory, docs/, replaced by
        # a junction) into the checkout's .git; the put-back refused to return them through the link, the host directory
        # was left empty and the cell still passed. Nothing below a link is moved now: the link itself is set aside and
        # put back, and PASS needs `restored`
        pack, c = make_pack(self.root, self.env)
        host = self.root / "host-dir"
        (host / "sub").mkdir(parents=True)
        for n in ("precious-1.txt", "precious-2.txt", "sub/deep.txt"):
            (host / n).write_text(n + "\n")
        listing = lambda: sorted(p.relative_to(host).as_posix() for p in host.rglob("*"))
        before = listing()
        for task in ("pin", "fix"):
            cand = self.candidate(c, f"link-{task}")
            if task == "pin":
                (cand / "tests" / "test_pin.py").write_text(PIN_SUM)
            else:
                self.fix_like_the_accepted_one(cand)
            commit_all(cand, self.env, task)
            shutil.rmtree(cand / "docs")
            dir_link(cand / "docs", host)
            code, d, out = grade(pack / "manifest.json", task, cand, self.env)
            self.assertEqual(code, 0, f"{task}: {out}")
            self.assertEqual(listing(), before, f"{task}: {out}")
            self.assertEqual((d["setAside"], d["restored"], d["PASS"]), (["docs"], True, True), f"{task}: {out}")
            self.assertNotIn("WARNING", out, task)
            self.assertTrue(is_dir_link(cand / "docs"), task)
            self.assertEqual([p.name for p in (cand / ".git").glob("grade-aside-*")], [], task)
        # a path the put-back cannot return fails the cell: here the last command (a lint that leaves a file where the
        # directory docs/ was; nothing runs after it to set that aside) blocks the candidate's docs/stray.txt
        m = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        m["commands"]["lint"] += " && python3 -c \"import shutil; shutil.rmtree('docs'); open('docs', 'w').close()\""
        (pack / "manifest-blocking-lint.json").write_text(json.dumps(m, indent=1))
        cand = self.candidate(c, "link-putback")
        self.fix_like_the_accepted_one(cand)
        commit_all(cand, self.env, "fix")
        (cand / "docs" / "stray.txt").write_text("left by the candidate\n")
        code, d, out = grade(pack / "manifest-blocking-lint.json", "fix", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual((d["candidateGreen"], d["guardRed"], d["acceptedPinGreen"], d["scopeOk"], d["setAside"]),
                         (True, True, True, True, ["docs/stray.txt"]), out)
        self.assertEqual((d["lint"], d["restored"], d["PASS"]), ("ok", False, False), out)
        self.assertIn("docs/stray.txt was not put back", out)

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
            if task == "fix":  # the accepted pin and then the candidate's tests both run the candidate's own source, as it
                # stands (RL10-K1: the pin runs first); only the guard's swap gets a new mtime
                self.assertEqual(seen[:2], [before, before], f"{task}: mtimes {seen}")
                seen = seen[1:]
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


def hygiene_scan(root: Path) -> list[str]:
    """K3 over every file under root. A host pack (subject-pack/host/<pack>/) is about its host's repository, so it may
    name it (the MoonAliza rule); every other rule holds there too."""
    hits = []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or "__pycache__" in f.parts:
            continue  # a bytecode cache is not kit content (and is git-ignored)
        rules = [r for r in HYGIENE if r[0] != "a MoonAliza name"] if (KIT / "subject-pack" / "host") in f.resolve().parents else HYGIENE
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if n == 1 and line.startswith("#!"):
                continue  # the interpreter line
            if "EXAMPLE:" in line:
                continue  # an example clearly marked as one
            bare = re.sub(r"\{\{[^}]*\}\}", "", line)  # a {{placeholder}} may name anything
            for what, rx in rules:
                if rx.search(bare):
                    hits.append(f"{f.relative_to(root)}:{n}: {what}: {line.strip()[:120]}")
                    break  # one hit per line: the first rule it breaks
    return hits


class Hygiene(unittest.TestCase):
    def scan(self, root: Path):
        return hygiene_scan(root)

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
            # the mode is ls-tree's first field; reading it that way, instead of with --format= (Git 2.36+), keeps the
            # assertion identical on the older Git releases a contributor may have
            modes = [entry.split()[0] for entry in g("ls-tree", "-r", "-z", rev).split("\0") if entry]
            self.assertEqual(modes, ["100644"] * len(tree_files(PACK / "trees" / name, self.env)))
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

    def test_grade_fix_a_test_that_rewrites_the_runner_does_not_reach_the_accepted_pin(self):
        # review loop RL10-K1: the candidate's own test file (in scope) rewrote the pack's runner, tests/run.py - a base
        # file, which the set-aside does not reset - into one that passes any run of the accepted test and puts itself
        # back; the accepted pin ran after the candidate's tests and read green for a wrong fix (PASS, `changed` holding
        # only the source and the test file). The accepted pin now runs first
        forge = ("\n\nimport pathlib as _pl\n_run = _pl.Path('tests/run.py')\n_orig = _run.read_bytes()\n"
                 "if b'_ORIG' not in _orig:\n"
                 "    _run.write_bytes(b'import sys, pathlib\\n_ORIG = ' + repr(_orig).encode() + b'\\n'\n"
                 "                     b'if any(\"zz_accepted\" in a for a in sys.argv[1:]):\\n'\n"
                 "                     b'    pathlib.Path(__file__).write_bytes(_ORIG)\\n    sys.exit(0)\\n'\n"
                 "                     b'exec(compile(_ORIG, __file__, \"exec\"))\\n')\n")
        for name, extra in (("control", ""), ("runner", forge)):
            def wrong(c, extra=extra):  # right for the candidate's own row only: the source just gains a flag
                with (c / "src" / "bounded.py").open("a", encoding="utf-8") as f:
                    f.write("\nFIXED = True\n")
                with (c / "tests" / "test_bounded.py").open("a", encoding="utf-8") as f:
                    f.write("\n\nclass X(unittest.TestCase):\n    def test_fixed(self):\n        import src.bounded as b\n"
                            "        self.assertTrue(getattr(b, 'FIXED', False))\n" + extra)
            d = self.grade_cell("fix", wrong)
            self.assertEqual((d["candidateGreen"], d["guardRed"], d["scopeOk"], d["changed"], d["setAside"]),
                             (True, True, True, ["src/bounded.py", "tests/test_bounded.py"], []), f"{name}: {d}")
            self.assertEqual((d["acceptedPinGreen"], d["PASS"]), (False, False), f"{name}: {d}")

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

# The host pack moonaliza-x2-1 (tools/calibration/subject-pack/host/moonaliza-x2-1/): it ships no subject code, so its
# repository is built from a MoonAliza clone the host names in MOONALIZA_CLONE; without one, every test that needs the
# clone reports UNSUPPORTED (a skip, never a pass), and the tests of the pack's own files still run.
X21 = KIT / "subject-pack" / "host" / "moonaliza-x2-1"
X21_UNSUPPORTED = "UNSUPPORTED: MOONALIZA_CLONE is not set (a MoonAliza clone holding 16f637f and 01a8604); this test needs the subject"


def in_host_pack(f: Path) -> bool:
    """A file of a host pack: the pack's README lists it, not the kit's (the kit README names the shared pack only)."""
    return (KIT / "subject-pack" / "host") in f.parents


def x21_clone() -> Path | None:
    import os
    value = os.environ.get("MOONALIZA_CLONE", "")
    return Path(value) if value else None


NEEDS_X21 = unittest.skipUnless(x21_clone(), X21_UNSUPPORTED)

# The anchors the candidate changes below edit: lines of the base tree's three source files (MoonAliza 16f637f).
X21_RECONCILE_CALL = "  await vault.reconcile(new Set([...references, ...collectorSettings.references(), ...githubStore.references()]));"
X21_SIGNATURE = "  reconcile(committedReferences: ReadonlySet<string>): Promise<void> {"
X21_DELETES = "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref))) {"
X21_COMMITS = "        if (entry.state === 'staged' && committedReferences.has(ref)) {"
X21_GETTER_AT = "  openedAppChanged(): boolean { return this.appChanged; }"
X21_KEEP_SIGNATURE = "  reconcile(committedReferences: ReadonlySet<string>, options: { keepStaged?: boolean } = {}): Promise<void> {"
X21_REFS = "new Set([...references, ...collectorSettings.references(), ...githubStore.references()])"
# integration 3 (the owner on F2: "fix it instead"): the manifest keeps the real cause, and cases.fix.cause_in_prompt false
# keeps it out of the candidate's fix prompt. These phrases are the cause's own words: each is checked to be in the manifest's
# cause, and together they hold every word of the cause that the finding's summary does not, so a summary, a required
# behaviour or instructions that restated the cause would put one of them into the prompt (sr-kit-cases N-1)
X21_CAUSE_PHRASES = ("during the start that cannot read", "the store names no references", "the vault reconcile that start runs",
                     "deletes every unreferenced staged entry", "so it deletes the new pair", "the unread file still names")
# integration 4 (IC3-1, lead decision D-IC3-1): MoonAliza's own orchestration records (docs/orchestration/ of 16f637f) name
# X2-1, state its cause and give the accepted fix line by line, so make-repo.sh exports both trees without that directory.
# The commits the pack is built from, the directory it leaves out, and the hints no file or path name of base0 may hold
# (lower case: the finding's id in both spellings, the accepted fix's two names, the cause's own phrases)
X21_BASE_SRC = "16f637f1a1eaf9879933a0020d676971a26b3c4b"
X21_ACCEPTED_SRC = "01a8604fa9c60fae9ae906e1e949a3f2cadb07de"
X21_EXCLUDED = "docs/orchestration/"
X21_HINTS = ("x2-1", "x2_1", "unreadatopen", "keepstaged", *X21_CAUSE_PHRASES)
# integration 5 (IC4-2): every file of MoonAliza 16f637f the hint scan finds, under X21_EXCLUDED. The first three match by
# their path names; the last three only by their content, so a scan that read path names alone would miss them.
X21_CLONE_HINT_PATHS = ("2026-10-13-github-sign-in/briefs/fix-x2-1.md", "smartrouter/trace/decisions/fix-x2-1-1.json",
                        "smartrouter/trace/decisions/sr-host-fix2-1.json", "2026-10-13-github-sign-in/RUN.md",
                        "2026-10-13-github-sign-in/reports/calibration-2-extra-findings.md", "smartrouter/trace/ledger.jsonl")

# re-review 2 RR2-1: the engine call of index.ts (base and accepted), and three shapes of a correct fix's index.ts that the
# journey test's slice of the startup lines must survive: the call wrapped over three lines, block comments whose inner
# lines name either anchor (above the call and between the anchors), and line comments that name either anchor.
# Integration 3 (IC-2, IC-3 and the hunt for more) adds the shapes after "line comments". Each probe is the accepted fix with
# more eslint-clean edits, so each is a correct fix that the journey test must grade green.
X21_ENGINE_CALL = "  const references = z.array(z.string()).parse(await engine.control({ method: 'vault.references' }));\n"
X21_LAST_FINISH = "  await githubStore.finishStartup();\n"
X21_ATTACH = "  void supervisor.attach();\n"
X21_ACCEPTED_RECONCILE = ("  await vault.reconcile(new Set([...references, ...collectorSettings.references(), ...githubStore.references()]), "
                          "{ keepStaged: githubStore.unreadAtOpen() });\n")  # the accepted fix's startup reconcile in index.ts
X21_KEEP_ARG = "{ keepStaged: githubStore.unreadAtOpen() }"
X21_STORE_IMPORT = "import { GitHubAccountStore } from './github-account-store';\n"
X21_SLICE_PROBES = {
    "wrapped engine call": [("src/main/index.ts", X21_ENGINE_CALL,
                             "  const references = z.array(z.string()).parse(\n    await engine.control({ method: 'vault.references' }),\n  );\n")],
    "block comments": [
        ("src/main/index.ts", X21_ENGINE_CALL,
         "  /*\n    X2-1: method: 'vault.references' gives the engine's references\n  */\n" + X21_ENGINE_CALL),
        ("src/main/index.ts", X21_LAST_FINISH,
         X21_LAST_FINISH + "  /* X2-1: the store's references are settled\n    before supervisor.attach() runs */\n")],
    "line comments": [
        ("src/main/index.ts", X21_ENGINE_CALL, "  // X2-1: method: 'vault.references' gives the engine's references\n" + X21_ENGINE_CALL),
        ("src/main/index.ts", X21_LAST_FINISH, X21_LAST_FINISH + "  // X2-1: settled before supervisor.attach() runs\n")],
    # IC-3: a string above the engine call that holds a comment opener (a slice that blanks comments must keep strings)
    "a string holding a comment opener above the engine call": [
        ("src/main/index.ts", X21_ENGINE_CALL, "  const _glob = 'logs/*.json'; void _glob;\n" + X21_ENGINE_CALL)],
    # IC-2a: the engine call without its ';' (the subject's eslint has no semi rule)
    "the engine call without its semicolon": [("src/main/index.ts", X21_ENGINE_CALL, X21_ENGINE_CALL.replace("}));\n", "}))\n"))],
    # IC-2b: the call split over two statements, references declared by the second
    "the engine call split over two statements": [
        ("src/main/index.ts", X21_ENGINE_CALL,
         "  const raw = await engine.control({ method: 'vault.references' });\n  const references = z.array(z.string()).parse(raw);\n")],
    # the hunt (integration 3): no ';' on any startup line, the call's expression continued on the next line, a statement after
    # the call on its line, a string holding a bracket between the anchors, the last startup statement on the line of
    # supervisor.attach(), a regex literal holding a comment opener above the call, and an imported helper whose import
    # carries comments between its names
    "no semicolon on any startup line": [
        ("src/main/index.ts", line, line.replace(";\n", "\n"))
        for line in (X21_ENGINE_CALL, X21_ACCEPTED_RECONCILE, "  await collectorSettings.finishStartup();\n", X21_LAST_FINISH)],
    "the engine call continued on the next line": [
        ("src/main/index.ts", X21_ENGINE_CALL,
         "  const references = await engine.control({ method: 'vault.references' })\n    .then(reply => z.array(z.string()).parse(reply));\n")],
    "a statement after the engine call on its line": [
        ("src/main/index.ts", X21_ENGINE_CALL, X21_ENGINE_CALL[:-1] + " const keep = githubStore.unreadAtOpen();\n"),
        ("src/main/index.ts", X21_KEEP_ARG, "{ keepStaged: keep }")],
    "a string holding a bracket between the anchors": [
        ("src/main/index.ts", X21_LAST_FINISH, X21_LAST_FINISH + "  const _mark = 'startup ['; void _mark;\n")],
    "the last startup statement on the line of supervisor.attach()": [
        ("src/main/index.ts", X21_LAST_FINISH + X21_ATTACH, "  await githubStore.finishStartup(); void supervisor.attach();\n")],
    "a regex literal holding a comment opener above the engine call": [
        ("src/main/index.ts", X21_ENGINE_CALL, "  const _slashes = /\\/*/g; void _slashes;\n" + X21_ENGINE_CALL)],
    "an imported helper whose import carries comments between its names": [
        ("src/main/github-account-store.ts", "export class GitHubAccountStore {\n",
         "/** X2-1: the startup reconcile's options for this store. */\n"
         "export function keepOnUnread(store: Pick<GitHubAccountStore, 'unreadAtOpen'>): { keepStaged: boolean } {\n"
         "  return { keepStaged: store.unreadAtOpen() };\n}\n\nexport class GitHubAccountStore {\n"),
        ("src/main/index.ts", X21_STORE_IMPORT,
         "import {\n  GitHubAccountStore, // the account file and its pair\n  keepOnUnread, /* X2-1 */\n} from './github-account-store';\n"),
        ("src/main/index.ts", X21_KEEP_ARG, "keepOnUnread(githubStore)")],
}


def x21_getter(name: str, body: str = "this.unread") -> tuple[str, str, str]:
    return ("src/main/github-account-store.ts", X21_GETTER_AT,
            f"{X21_GETTER_AT}\n  /** X2-1: whether open() could not read the account file. */\n  {name}(): boolean {{ return {body}; }}")


def x21_wire(call: str) -> tuple[str, str, str]:
    return ("src/main/index.ts", X21_RECONCILE_CALL, call)


X21_KEEP_UNREFERENCED = [  # the vault keeps unreferenced staged entries when asked (tombstones still go)
    ("src/main/vault.ts", X21_SIGNATURE, X21_KEEP_SIGNATURE),
    ("src/main/vault.ts", X21_DELETES,
     "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref) && !options.keepStaged)) {"),
]

# review loop 3 RL3-1, RL3-2: the vault keeps unreferenced staged entries when asked, or when asked to keep them beside a
# committed entry and the vault holds one (tombstones still go), and a second store getter for that ask
X21_KEEP_IF_COMMITTED = [
    ("src/main/vault.ts", X21_SIGNATURE + "\n    return this.serial(async () => {",
     "  reconcile(committedReferences: ReadonlySet<string>, options: { keepStaged?: boolean; keepIfCommitted?: boolean } = {}): Promise<void> {\n"
     "    return this.serial(async () => {\n"
     "      // X2-1: beside a committed entry, an account file this start did not take may name staged ones\n"
     "      const keep = options.keepStaged === true\n"
     "        || (options.keepIfCommitted === true && Object.values(this.index.entries).some(entry => entry.state === 'committed'));"),
    ("src/main/vault.ts", X21_DELETES,
     "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref) && !keep)) {"),
]


def x21_untaken(name: str, body: str) -> tuple[str, str, str]:
    return ("src/main/github-account-store.ts", X21_GETTER_AT,
            f"{X21_GETTER_AT}\n  /** X2-1: whether open() took no account from the file it found (or did not find). */\n  {name}(): boolean {{ return {body}; }}")


# review loop 2 RL2-1: two anchors of the base store that W-o3 and W-o4 edit
X21_CRYPTO_IMPORT = "import { randomUUID } from 'node:crypto';\n"
X21_CATCH_FLAGS = "        this.startupWrite = typeof code !== 'string'; this.unread = typeof code === 'string' && code !== 'ENOENT';"


# review loop 6 RL6-P1: W-r and W-r2 read an account file open() could not read a second time, another way, and the vault keeps
# only the staged refs that read names (none when it fails); W-r3 takes them from what its process wrote before. The helper with
# the second read `read` (which sets `text`); the store's field, set in open()'s catch from `named`, and its getter, the vault's
# keep set, the wiring and the candidate's startup line
def x21_named_refs(read: str) -> tuple[str, str, str]:
    return ("src/main/github-account-store.ts", "export class GitHubAccountStore {\n",
            "/** X2-1: the refs an account file names, read a second time, or none when that read fails too. */\n"
            "async function namedRefs(file: string): Promise<string[]> {\n"
            "  try {\n" + read +
            "    return refsOf(AccountFileSchema.parse(JSON.parse(text)).account);\n"
            "  } catch { return []; }\n"
            "}\n\nexport class GitHubAccountStore {\n")


def x21_keep_named(named: str = "await namedRefs(this.file)") -> list[tuple[str, str, str]]:
    return [
        ("src/main/github-account-store.ts", "  private unread = false;\n",
         "  private unread = false;\n  // X2-1: the refs the account file names, learnt another way when open() could not read it\n"
         "  private named: string[] = [];\n"),
        ("src/main/github-account-store.ts", X21_CATCH_FLAGS, X21_CATCH_FLAGS + f"\n        this.named = this.unread ? {named} : [];"),
        *X21_KEEP_NAMED_REST]


X21_KEEP_NAMED_REST = [
    ("src/main/github-account-store.ts", X21_GETTER_AT,
     X21_GETTER_AT + "\n  /** X2-1: the staged refs the unread account file names (none when it could not be read again). */\n"
     "  namedAtOpen(): string[] { return this.named; }"),
    ("src/main/vault.ts", X21_SIGNATURE, "  reconcile(committedReferences: ReadonlySet<string>, options: { keep?: ReadonlySet<string> } = {}): Promise<void> {"),
    ("src/main/vault.ts", X21_DELETES,
     "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref) && !options.keep?.has(ref))) {"),
    x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keep: new Set(githubStore.namedAtOpen()) }});"),
]
X21_KEEP_NAMED_RECONCILE = "await vault.reconcile(new Set(store.references()), { keep: new Set(store.namedAtOpen()) });"

# review loop 9 RL9-P1..P5: the store's and the vault's files, which the round-9 wrong fixes edit, the vault's entry type, the candidate's startup line
# that keeps on an unread start, and a store getter with its own doc comment
X21_STORE = "src/main/github-account-store.ts"
X21_VAULT = "src/main/vault.ts"
X21_ENTRY = "interface VaultEntry { state: 'staged' | 'committed' | 'tombstoned'; createdAt: number }"
X21_OF_RECONCILE = "await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });"


def x21_getter_doc(sig: str, body: str, doc: str) -> tuple[str, str, str]:
    return (X21_STORE, X21_GETTER_AT, f"{X21_GETTER_AT}\n  /** X2-1: {doc} */\n  {sig} {{ return {body}; }}")


# Each wrong fix of WRONG-FIXES.md as a candidate's change on the base: (path, base text, new text) edits, the startup
# lines of the candidate's own test (tests/x2_candidate.test.ts, the {{RECONCILE}} of X21_CANDIDATE_TEST), how long the
# candidate's test holds the read failure ("open" or "once") and what it checks ("journey": the next readable start finds
# the pair live; "index": the unread start leaves the pair staged in the index). Every one is green on its own tests, red
# with the sources restored, in scope and lint-clean, so only the accepted journey test can fail it.
# The store learns how the account file's directory failed when open() could not read the file: the code a stat of a name
# beside the file fails with ('' when none or ENOENT), in a field directoryFailed (W-y, W-j4, W-p3)
X21_DIRECTORY_CODE = [
    (X21_STORE, X21_CRYPTO_IMPORT, X21_CRYPTO_IMPORT + "import { statSync } from 'node:fs';\nimport { dirname, join } from 'node:path';\n"),
    (X21_STORE, "export class GitHubAccountStore {\n",
     "/** X2-1: the code a stat of a name beside the account file fails with, when it is not ENOENT: the directory's own failure ('' when none). */\n"
     "function directoryCode(file: string): string {\n"
     "  try { statSync(join(dirname(file), '.x2-probe')); return ''; }\n"
     "  catch (error) {\n"
     "    const code = (error as NodeJS.ErrnoException)?.code;\n"
     "    return typeof code === 'string' && code !== 'ENOENT' ? code : '';\n"
     "  }\n"
     "}\n\nexport class GitHubAccountStore {\n"),
    (X21_STORE, "  private unread = false;\n",
     "  private unread = false;\n  // X2-1: how the account file's directory failed, when open() could not read the file\n  private directoryFailed = '';\n"),
    (X21_STORE, X21_CATCH_FLAGS, X21_CATCH_FLAGS + "\n        this.directoryFailed = this.unread ? directoryCode(this.file) : '';"),
]
# The store says whether open() could not read the account file because its directory failed, and the reconcile takes it
# as atDirectory (W-p4, W-j6: the point of the start before)
X21_DIRECTORY_NOW = x21_getter_doc("directoryFailedNow(): boolean", "this.unread && this.directoryFailed !== ''",
                                   "whether open() could not read the account file because its directory itself failed.")
X21_DIRECTORY_RECONCILE = ("await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed(), "
                           "atDirectory: store.directoryFailedNow() });")
X21_DIRECTORY_SIGNATURE = (X21_VAULT, X21_SIGNATURE,
                           "  reconcile(committedReferences: ReadonlySet<string>, options: { keepStaged?: boolean; atDirectory?: boolean } = {}): Promise<void> {")
X21_DIRECTORY_WIRE = x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed(), atDirectory: githubStore.directoryFailedNow() }});")

X21_WRONG = {
    "W-a": dict(hold="once", check="journey", reconcile="await vault.reconcile(new Set(store.references()));", edits=[
        ("src/main/github-account-store.ts",
         "      try { this.disk = AccountFileSchema.parse(await boundedJson(this.file, 64 * 1024)); }\n      // finishStartup",
         "      const read = async () => AccountFileSchema.parse(await boundedJson(this.file, 64 * 1024));\n"
         "      try {\n"
         "        // X2-1: an I/O error at open() is taken for a transient one: the file is read once more before it counts as unread\n"
         "        this.disk = await read().catch(async (error: NodeJS.ErrnoException) => {\n"
         "          if (typeof error?.code !== 'string' || error.code === 'ENOENT') throw error;\n"
         "          await new Promise(resolve => setTimeout(resolve, 50));\n"
         "          return read();\n"
         "        });\n"
         "      }\n      // finishStartup")]),
    "W-b": dict(hold="open", check="journey", reconcile="if (!store.openFailed()) await vault.reconcile(new Set(store.references()));", edits=[
        x21_getter("openFailed"),
        x21_wire(f"  if (!githubStore.openFailed()) await vault.reconcile({X21_REFS});")]),
    "W-b2": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        x21_getter("openFailed"),
        ("src/main/vault.ts", X21_SIGNATURE, X21_KEEP_SIGNATURE),
        ("src/main/vault.ts", X21_DELETES,
         "        } else if (!options.keepStaged && (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref)))) {"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    "W-c": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()));", edits=[
        ("src/main/vault.ts", X21_DELETES,
         "        } else if (entry.state === 'tombstoned') {   // X2-1: a staged entry may be named by a file this start cannot read")],
        test_edits="W-c"),
    "W-d": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()));", edits=[
        ("src/main/vault.ts", "  async has(ref: string): Promise<boolean> {",
         "  /** X2-1: the refs a crash may have left staged. */\n"
         "  stagedReferences(): string[] { return Object.entries(this.index.entries).filter(([, entry]) => entry.state === 'staged').map(([ref]) => ref); }\n\n"
         "  async has(ref: string): Promise<boolean> {"),
        ("src/main/github-account-store.ts", "Pick<Vault, 'saveStaged' | 'commit' | 'tombstone' | 'remove' | 'has'>",
         "Pick<Vault, 'saveStaged' | 'commit' | 'tombstone' | 'remove' | 'has' | 'stagedReferences'>"),
        ("src/main/github-account-store.ts", "  references(): string[] { return refsOf(this.live); }",
         "  references(): string[] { return this.unread ? this.vault.stagedReferences() : refsOf(this.live); }")]),
    "W-e": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { commitStaged: store.openFailed() });", edits=[
        x21_getter("openFailed"),
        ("src/main/vault.ts", X21_SIGNATURE,
         "  reconcile(committedReferences: ReadonlySet<string>, options: { commitStaged?: boolean } = {}): Promise<void> {"),
        ("src/main/vault.ts", X21_COMMITS,
         "        if (entry.state === 'staged' && (committedReferences.has(ref) || options.commitStaged)) {"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ commitStaged: githubStore.openFailed() }});")]),
    "W-f": dict(hold="open", check="index", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        x21_getter("openFailed"),
        ("src/main/vault.ts", X21_SIGNATURE, X21_KEEP_SIGNATURE),
        ("src/main/vault.ts", X21_DELETES,
         "        } else if (options.keepStaged && entry.state === 'staged' && !committedReferences.has(ref)) {\n"
         "          // X2-1: the entry stays for the next readable start; its encrypted file is not needed until then\n"
         "          await unlink(this.secretPath(ref)).catch(() => undefined);\n"
         f"{X21_DELETES}"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    "W-g": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        x21_getter("openFailed"),
        ("src/main/vault.ts", X21_SIGNATURE + "\n    return this.serial(async () => {",
         X21_KEEP_SIGNATURE + "\n    return this.serial(async () => {\n"
         "      // X2-1: a crash during the first sign-in leaves no committed entry; only then is a staged one kept\n"
         "      const keep = options.keepStaged === true && !Object.values(this.index.entries).some(entry => entry.state === 'committed');"),
        ("src/main/vault.ts", X21_DELETES,
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref) && !keep)) {"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    "W-h1": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.keepStagedAtStart() });", edits=[
        x21_getter("keepStagedAtStart", "this.unread || this.appChanged"),
        *X21_KEEP_UNREFERENCED,
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.keepStagedAtStart() }});")]),
    "W-h2": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        x21_getter("openFailed", "this.disk === null && !this.startupWrite"),
        *X21_KEEP_UNREFERENCED,
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    "W-i": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.unreadAtOpen() });", edits=[
        x21_getter("unreadAtOpen"),
        *X21_KEEP_UNREFERENCED]),
    "W-j": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        x21_getter("openFailed"),
        ("src/main/vault.ts", "interface VaultEntry { state: 'staged' | 'committed' | 'tombstoned'; createdAt: number }",
         "interface VaultEntry { state: 'staged' | 'committed' | 'tombstoned'; createdAt: number; held?: boolean }"),
        ("src/main/vault.ts", X21_SIGNATURE, X21_KEEP_SIGNATURE),
        ("src/main/vault.ts", X21_DELETES,
         "        } else if (options.keepStaged && entry.state === 'staged' && !committedReferences.has(ref)) {\n"
         "          entry.held = true;   // X2-1: held until a start that can name its references\n"
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref) && !entry.held)) {"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review 1 F3: an unreferenced staged entry counts as abandoned once it is a day old, so a start long after the crash loses it
    "W-k": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        x21_getter("openFailed"),
        ("src/main/vault.ts", X21_SIGNATURE, X21_KEEP_SIGNATURE),
        ("src/main/vault.ts", X21_DELETES,
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref)\n"
         "            && !(options.keepStaged && Date.now() - entry.createdAt < 24 * 3_600_000))) {   // X2-1: a day-old staged entry is abandoned"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review 1 F7: only the errno codes taken for a held file (EACCES, EBUSY) keep; any other I/O error still deletes the pair
    "W-l": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        ("src/main/github-account-store.ts", "  private unread = false;\n",
         "  private unread = false;\n  // X2-1: open() met a lock or a permission error, which a later start can get past\n  private held = false;\n"),
        ("src/main/github-account-store.ts",
         "        this.startupWrite = typeof code !== 'string'; this.unread = typeof code === 'string' && code !== 'ENOENT';",
         "        this.startupWrite = typeof code !== 'string'; this.unread = typeof code === 'string' && code !== 'ENOENT';\n"
         "        this.held = code === 'EACCES' || code === 'EBUSY';"),
        x21_getter("openFailed", "this.held"),
        *X21_KEEP_UNREFERENCED,
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 5 RL5-P1: W-l's idea with a list of codes that holds every code the journey rows and the unreadable-run row
    # used before the other-errno row (EACCES, EBUSY, EIO): it graded PASS; EMFILE, EINVAL and UNKNOWN are not in its list
    "W-l2": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        ("src/main/github-account-store.ts", "  private unread = false;\n",
         "  private unread = false;\n  // X2-1: open() met an I/O error a later start can get past (a lock, a permission error, a busy or failing device)\n"
         "  private held = false;\n"),
        ("src/main/github-account-store.ts",
         "        this.startupWrite = typeof code !== 'string'; this.unread = typeof code === 'string' && code !== 'ENOENT';",
         "        this.startupWrite = typeof code !== 'string'; this.unread = typeof code === 'string' && code !== 'ENOENT';\n"
         "        this.held = typeof code === 'string' && ['EACCES', 'EPERM', 'EBUSY', 'EAGAIN', 'EIO'].includes(code);"),
        x21_getter("openFailed", "this.held"),
        *X21_KEEP_UNREFERENCED,
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # re-review 1 R1: a file that names no account (signed out) counts as one whose references may be incomplete, so an
    # orphan pair a crashed sign-in staged after a sign-out survives every readable start
    "W-m": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        x21_getter("openFailed", "this.unread || this.disk?.account === null"),
        *X21_KEEP_UNREFERENCED,
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # re-review 1 R2: W-k's idea with a year for the limit, which a start a month after the crash did not reach
    "W-n": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        x21_getter("openFailed"),
        ("src/main/vault.ts", X21_SIGNATURE, X21_KEEP_SIGNATURE),
        ("src/main/vault.ts", X21_DELETES,
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref)\n"
         "            && !(options.keepStaged && Date.now() - entry.createdAt < 365 * 24 * 3_600_000))) {   // X2-1: a year-old staged entry is abandoned"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 1 RL1-1: keep whenever open() found no usable file except a missing one, so a file that was read and refused
    # (invalid, oversized, an extra key) keeps too; narrower than re-review 2's probe W-o (this.unread || this.startupWrite),
    # it leaves the app-changed path alone, so only the refused-file row catches it
    "W-o2": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        x21_getter("openFailed", "this.unread || (this.disk === null && this.startupWrite)"),
        *X21_KEEP_UNREFERENCED,
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 2 RL2-P1: W-k's limit counted in starts, not in age: an unreferenced staged entry is kept through one start
    # that cannot read the file and marked kept, and a second such start in a row takes it for abandoned, so a file that
    # stays unreadable (a bad permission, a lock held for days) loses the pair
    "W-p": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        x21_getter("openFailed"),
        ("src/main/vault.ts", "interface VaultEntry { state: 'staged' | 'committed' | 'tombstoned'; createdAt: number }",
         "interface VaultEntry { state: 'staged' | 'committed' | 'tombstoned'; createdAt: number; kept?: boolean }"),
        ("src/main/vault.ts", X21_SIGNATURE, X21_KEEP_SIGNATURE),
        ("src/main/vault.ts", X21_DELETES,
         "        } else if (options.keepStaged && entry.state === 'staged' && !committedReferences.has(ref) && !entry.kept) {\n"
         "          entry.kept = true;   // X2-1: kept through one start that cannot name its references; a second one finds it abandoned\n"
         f"{X21_DELETES}"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 2, the hunt after RL2-P1: W-j's hold, earned by a run of unreadable starts: an unreferenced staged entry
    # that two such starts in a row kept is taken for one the file still needs, and no later start deletes it
    "W-q": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        x21_getter("openFailed"),
        ("src/main/vault.ts", "interface VaultEntry { state: 'staged' | 'committed' | 'tombstoned'; createdAt: number }",
         "interface VaultEntry { state: 'staged' | 'committed' | 'tombstoned'; createdAt: number; kept?: number }"),
        ("src/main/vault.ts", X21_SIGNATURE, X21_KEEP_SIGNATURE),
        ("src/main/vault.ts", X21_DELETES,
         "        } else if (options.keepStaged && entry.state === 'staged' && !committedReferences.has(ref)) {\n"
         "          entry.kept = (entry.kept ?? 0) + 1;   // X2-1: two unreadable starts in a row that kept it mean the file still needs it\n"
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref) && (entry.kept ?? 0) < 2)) {"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 2 RL2-1: a refused file that still names an account (a newer app's file, say) is taken for one whose
    # references are unknown: open() reads it again without the format and keeps the staged entries while it names an
    # account. The refused-file row's file names none, so only the named refused-file row catches it (at over 64 KiB, the
    # first form it can parse)
    "W-o3": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        ("src/main/github-account-store.ts", X21_CRYPTO_IMPORT, X21_CRYPTO_IMPORT + "import { readFile } from 'node:fs/promises';\n"),
        ("src/main/github-account-store.ts", "  private unread = false;\n",
         "  private unread = false;\n  // X2-1: open() refused a file that still names an account: its references are unknown\n  private refusedWithAccount = false;\n"),
        ("src/main/github-account-store.ts", "this.startupWrite = false; this.unread = false;",
         "this.startupWrite = false; this.unread = false; this.refusedWithAccount = false;"),
        ("src/main/github-account-store.ts", X21_CATCH_FLAGS,
         X21_CATCH_FLAGS + "\n"
         "        if (typeof code !== 'string') {\n"
         "          try {\n"
         "            const raw = JSON.parse(await readFile(this.file, 'utf8')) as { account?: unknown } | null;\n"
         "            this.refusedWithAccount = typeof raw?.account === 'object' && raw.account !== null;\n"
         "          } catch { /* not JSON: it names nothing */ }\n"
         "        }"),
        x21_getter("openFailed", "this.unread || this.refusedWithAccount"),
        *X21_KEEP_UNREFERENCED,
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 2 RL2-1: W-o3's idea keyed on the version alone: a file of another format version (a newer app's) keeps,
    # whatever it names; only the version-2 forms of the refused-file row and of the named refused-file row catch it
    "W-o4": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        ("src/main/github-account-store.ts", X21_CRYPTO_IMPORT, X21_CRYPTO_IMPORT + "import { readFile } from 'node:fs/promises';\n"),
        ("src/main/github-account-store.ts", "  private unread = false;\n",
         "  private unread = false;\n  // X2-1: open() refused a file of another format version (a newer app's): its references are unknown\n  private otherVersion = false;\n"),
        ("src/main/github-account-store.ts", "this.startupWrite = false; this.unread = false;",
         "this.startupWrite = false; this.unread = false; this.otherVersion = false;"),
        ("src/main/github-account-store.ts", X21_CATCH_FLAGS,
         X21_CATCH_FLAGS + "\n"
         "        if (typeof code !== 'string') {\n"
         "          try {\n"
         "            const raw = JSON.parse(await readFile(this.file, 'utf8')) as { version?: unknown } | null;\n"
         "            this.otherVersion = typeof raw?.version === 'number' && raw.version !== 1;\n"
         "          } catch { /* not JSON: no version */ }\n"
         "        }"),
        x21_getter("openFailed", "this.unread || this.otherVersion"),
        *X21_KEEP_UNREFERENCED,
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 3 RL3-1: a refused file is taken for one whose references are unknown only while the vault holds a
    # committed entry (a downgrade beside a signed-in vault, say): the named refused-file row's first sign-in leaves no
    # committed entry, so only its forms after a sign-in catch it
    "W-o5": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        x21_getter("openFailed"),
        x21_untaken("refusedAtOpen", "this.disk === null && this.startupWrite"),
        *X21_KEEP_IF_COMMITTED,
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed(), keepIfCommitted: githubStore.refusedAtOpen() }});")]),
    # review loop 3 RL3-2: W-o5's idea for a missing file: a lost file beside a committed entry is taken for one whose
    # references are unknown; the ENOENT row's first sign-in leaves no committed entry, so only its forms beside a
    # committed account catch it
    "W-h3": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        x21_getter("openFailed"),
        x21_untaken("missingAtOpen", "this.disk === null && !this.startupWrite && !this.unread"),
        *X21_KEEP_IF_COMMITTED,
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed(), keepIfCommitted: githubStore.missingAtOpen() }});")]),
    # review loop 6 RL6-P1: W-a's idea with the second read made another way and used only to learn which staged entries to
    # keep: open()'s catch reads the file again through a stream (createReadStream, which the subject's artifact-files.ts
    # imports) and the vault keeps the staged refs that read names, none when it fails. A real unreadable file fails the stream
    # too; the journey test's fault failed only the promise and sync forms, so the stream read it and W-r graded PASS
    "W-r": dict(hold="open", check="journey", reconcile=X21_KEEP_NAMED_RECONCILE, edits=[
        ("src/main/github-account-store.ts", X21_CRYPTO_IMPORT, X21_CRYPTO_IMPORT + "import { createReadStream } from 'node:fs';\n"),
        x21_named_refs("    const chunks: Buffer[] = [];\n"
                       "    for await (const chunk of createReadStream(file, { end: 64 * 1024 })) chunks.push(chunk as Buffer);\n"
                       "    const text = Buffer.concat(chunks).toString('utf8');\n"),
        *x21_keep_named()]),
    # review loop 6 RL6-P1: W-r with the second read through a function the store took as its module loaded
    # (promisify(readFile) of node:fs); a fault put on node:fs once the subject has loaded misses that reference
    "W-r2": dict(hold="open", check="journey", reconcile=X21_KEEP_NAMED_RECONCILE, edits=[
        ("src/main/github-account-store.ts", X21_CRYPTO_IMPORT,
         X21_CRYPTO_IMPORT + "import { readFile } from 'node:fs';\nimport { promisify } from 'node:util';\n"),
        ("src/main/github-account-store.ts", "export class GitHubAccountStore {\n",
         "const readAgain = promisify(readFile);   // X2-1: the second read of an account file open() could not read\n\n"
         "export class GitHubAccountStore {\n"),
        x21_named_refs("    const text = await readAgain(file, 'utf8');\n"),
        *x21_keep_named()]),
    # review loop 6 (the fix's own hunt): the refs come from memory, not from a read: the store keeps the refs of the last file
    # its process wrote in a module variable, and an unread start keeps those. The app's next start is a new process, which
    # remembers nothing; the journey test ran every start in the first session's module instance, so W-r3 passed it too
    "W-r3": dict(hold="open", check="journey", reconcile=X21_KEEP_NAMED_RECONCILE, edits=[
        ("src/main/github-account-store.ts", "export class GitHubAccountStore {\n",
         "/** X2-1: the refs the last account file this process wrote names, the ones an unread file most likely names too. */\n"
         "let lastWritten: string[] = [];\n\nexport class GitHubAccountStore {\n"),
        ("src/main/github-account-store.ts", "    await atomicJson(this.file, next); this.disk = next; return next;",
         "    await atomicJson(this.file, next); this.disk = next; lastWritten = refsOf(next.account); return next;"),
        *x21_keep_named("[...lastWritten]")]),
    # review loop 7 RL7-P1 (its W-g): W-r3 with the memory on globalThis, which vi.resetModules() keeps; the journey test ran
    # every start in the test's one process, so W-r4 passed it. Each later start now runs in a new process of its own
    "W-r4": dict(hold="open", check="journey", reconcile=X21_KEEP_NAMED_RECONCILE, edits=[
        ("src/main/github-account-store.ts", "export class GitHubAccountStore {\n",
         "/** X2-1: the refs the last account file this process wrote names, the ones an unread file most likely names too. */\n"
         "const memory = globalThis as typeof globalThis & { x2LastWritten?: string[] };\n\nexport class GitHubAccountStore {\n"),
        ("src/main/github-account-store.ts", "    await atomicJson(this.file, next); this.disk = next; return next;",
         "    await atomicJson(this.file, next); this.disk = next; memory.x2LastWritten = refsOf(next.account); return next;"),
        *x21_keep_named("[...(memory.x2LastWritten ?? [])]")]),
    # review loop 7 RL7-P2 (its W-s): W-r with the second read through a hard link to the file; the fault matched the path
    # string, so the link read it. A real lock or permission belongs to the file, not to its name: the fault now knows the
    # file by its identity
    "W-r5": dict(hold="open", check="journey", reconcile=X21_KEEP_NAMED_RECONCILE, edits=[
        ("src/main/github-account-store.ts", X21_CRYPTO_IMPORT,
         X21_CRYPTO_IMPORT + "import { link, readFile as readAlias, rm as rmAlias } from 'node:fs/promises';\n"),
        x21_named_refs("    const alias = `${file}.${randomUUID()}.read`;\n"
                       "    await link(file, alias);\n"
                       "    let text: string;\n"
                       "    try { text = await readAlias(alias, 'utf8'); } finally { await rmAlias(alias, { force: true }); }\n"),
        *x21_keep_named()]),
    # review loop 8 RL8-P1: W-r2's second read with the path as a Uint8Array (a TextEncoder's), which node:fs takes as a path but
    # which is not a Buffer; the fault knew a string, a Buffer and a URL instance. It now hands the argument to the real stat
    "W-t": dict(hold="open", check="journey", reconcile=X21_KEEP_NAMED_RECONCILE, edits=[
        ("src/main/github-account-store.ts", X21_CRYPTO_IMPORT,
         X21_CRYPTO_IMPORT + "import { readFile as readAgain } from 'node:fs/promises';\n"),
        x21_named_refs("    const text = await readAgain(new TextEncoder().encode(file) as unknown as Buffer, 'utf8');\n"),
        *x21_keep_named()]),
    # review loop 8 RL8-P1: the same read with the path as an object node:fs takes as a file: URL (href and protocol), not a URL
    "W-t2": dict(hold="open", check="journey", reconcile=X21_KEEP_NAMED_RECONCILE, edits=[
        ("src/main/github-account-store.ts", X21_CRYPTO_IMPORT,
         X21_CRYPTO_IMPORT + "import { readFile as readAgain } from 'node:fs/promises';\nimport { pathToFileURL } from 'node:url';\n"),
        x21_named_refs("    const { href, pathname } = pathToFileURL(file);\n"
                       "    const text = await readAgain({ href, protocol: 'file:', hostname: '', pathname } as unknown as URL, 'utf8');\n"),
        *x21_keep_named()]),
    # review loop 8 RL8-P2: W-k with the age taken from performance's clock (timeOrigin + now()), which the start's process did
    # not move; it moves now, with the other clocks the README names (not every clock a process can read: W-u7)
    "W-u": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        x21_getter("openFailed"),
        ("src/main/vault.ts", X21_SIGNATURE, X21_KEEP_SIGNATURE),
        ("src/main/vault.ts", X21_DELETES,
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref)\n"
         "            && !(options.keepStaged && performance.timeOrigin + performance.now() - entry.createdAt < 24 * 3_600_000))) {   // X2-1: a day-old staged entry is abandoned"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 8 RL8-P3: which errors keep, decided by where the error came from rather than by its code: a failed read (syscall
    # 'read', taken for a failing disk) deletes the pair, a failed open keeps it; the fault's error had no syscall. It now has a
    # real one's shape, and each code fails a start at the open and the next at the read
    "W-l3": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        ("src/main/github-account-store.ts", "  private unread = false;\n",
         "  private unread = false;\n  // X2-1: open() could not open the file (a lock, a permission), which a later start can get past; a failed read means a failing disk\n"
         "  private held = false;\n"),
        ("src/main/github-account-store.ts", X21_CATCH_FLAGS,
         X21_CATCH_FLAGS + "\n        this.held = this.unread && (error as NodeJS.ErrnoException)?.syscall !== 'read';"),
        x21_getter("openFailed", "this.held"),
        *X21_KEEP_UNREFERENCED,
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 8 RL8-P2 (class hunt): W-k's age from the date Intl.DateTimeFormat formats when given none, which reads V8's own clock, not Date
    "W-u2": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        x21_getter("openFailed"),
        ("src/main/vault.ts", X21_SIGNATURE, X21_KEEP_SIGNATURE),
        ("src/main/vault.ts", X21_DELETES,
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref)\n            && !(options.keepStaged && Date.parse(new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', year: 'numeric', month: '2-digit', day: '2-digit' }).format() + ' UTC') - entry.createdAt < 24 * 3_600_000))) {   // X2-1: a day-old staged entry is abandoned"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 8 RL8-P2 (class hunt): W-k's age from file times, a new file's modification time against the entry's file's
    "W-u3": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        x21_getter("openFailed"),
        ("src/main/vault.ts", X21_CRYPTO_IMPORT, "import { rmSync, statSync, writeFileSync } from 'node:fs';\n" + X21_CRYPTO_IMPORT),
        ("src/main/vault.ts", X21_SIGNATURE, X21_KEEP_SIGNATURE),
        ("src/main/vault.ts", X21_DELETES,
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref)\n            && !(options.keepStaged && (() => { const probe = join(this.directory, `.age-${randomUUID()}`); writeFileSync(probe, ''); const at = statSync(probe).mtimeMs; rmSync(probe); return at - statSync(join(this.directory, `${ref}.bin`)).mtimeMs; })() < 24 * 3_600_000))) {   // X2-1: a day-old staged entry is abandoned"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 8 RL8-P2 (class hunt): W-k's age counted from the system's boot time (Date.now() - os.uptime()), which a start does not move
    "W-u4": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        x21_getter("openFailed"),
        ("src/main/vault.ts", X21_CRYPTO_IMPORT, "import { uptime } from 'node:os';\n" + X21_CRYPTO_IMPORT),
        ("src/main/vault.ts", X21_SIGNATURE, X21_KEEP_SIGNATURE),
        ("src/main/vault.ts", X21_DELETES,
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref)\n            && !(options.keepStaged && entry.createdAt - (Date.now() - uptime() * 1000) > -24 * 3_600_000))) {   // X2-1: a day-old staged entry is abandoned"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 8 RL8-P3 (class hunt): W-l3 decided by the error's message (", read") rather than its syscall
    "W-l4": dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });", edits=[
        ("src/main/github-account-store.ts", "  private unread = false;\n",
         "  private unread = false;\n  // X2-1: open() could not open the file (a lock, a permission), which a later start can get past; a failed read means a failing disk\n"
         "  private held = false;\n"),
        ("src/main/github-account-store.ts", X21_CATCH_FLAGS,
         X21_CATCH_FLAGS + '\n        this.held = this.unread && !/, read\\b/.test(String((error as Error)?.message));'),
        x21_getter("openFailed", "this.held"),
        *X21_KEEP_UNREFERENCED,
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 9 RL9-P1: W-p2, W-p's limit keyed on the failure itself: a start that meets the SAME failure (code and syscall) as the start that kept the
    # entry takes the file for one that stays unreadable and the entry for abandoned. A real lasting permission error repeats the same
    # code at the same call every start; the rows never repeat a (code, syscall) pair two starts in a row.
    "W-p2": dict(hold="open", check="journey",
        reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed(), failure: store.unreadFailure() });", edits=[
        (X21_STORE, "  private unread = false;\n",
         "  private unread = false;\n  // X2-1: how open() failed to read the file (code and call), so a later start can tell the same failure again\n"
         "  private failure = '';\n"),
        (X21_STORE, X21_CATCH_FLAGS,
         X21_CATCH_FLAGS + "\n        this.failure = this.unread ? String(code) + ':' + String((error as NodeJS.ErrnoException)?.syscall) : '';"),
        x21_getter("openFailed"),
        x21_getter_doc("unreadFailure(): string", "this.failure", "how open() failed to read the account file (code:syscall), or '' when it read it."),
        (X21_VAULT, X21_ENTRY, "interface VaultEntry { state: 'staged' | 'committed' | 'tombstoned'; createdAt: number; keptAfter?: string }"),
        (X21_VAULT, X21_SIGNATURE, "  reconcile(committedReferences: ReadonlySet<string>, options: { keepStaged?: boolean; failure?: string } = {}): Promise<void> {"),
        (X21_VAULT, X21_DELETES,
         "        } else if (options.keepStaged && entry.state === 'staged' && !committedReferences.has(ref) && entry.keptAfter !== options.failure) {\n"
         "          entry.keptAfter = options.failure;   // X2-1: kept; the same failure at the next start means the file stays unreadable\n"
         f"{X21_DELETES}"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed(), failure: githubStore.unreadFailure() }});")]),
    # review loop 9 RL9-P2: W-b4, W-b (skip the reconcile on an unread start) unless the engine names references, whose staged entries need committing:
    # then the reconcile runs as before and deletes the pair. No journey row runs an unread start with engine references.
    "W-b4": dict(hold="open", check="journey", reconcile="if (!store.openFailed()) await vault.reconcile(new Set(store.references()));", edits=[
        x21_getter("openFailed"),
        x21_wire("  // X2-1: a start that cannot read the account file reconciles only when the engine has references to commit\n"
                   f"  if (!githubStore.openFailed() || references.length > 0) await vault.reconcile({X21_REFS});")]),
    # review loop 9 RL9-P3: W-b3, W-b2 (spare tombstoned entries too) only when the file was found and failed at its open or read (held by another process,
    # taken for another instance mid sign-out); the tombstone row fails its start at the stat only.
    "W-b3": dict(hold="open", check="journey",
        reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed(), keepTombstoned: store.heldElsewhere() });", edits=[
        (X21_STORE, "  private unread = false;\n",
         "  private unread = false;\n  // X2-1: the file was found but failed at its open or read: another process holds it, perhaps mid sign-out\n"
         "  private elsewhere = false;\n"),
        (X21_STORE, X21_CATCH_FLAGS,
         X21_CATCH_FLAGS + "\n        this.elsewhere = this.unread && ['open', 'read'].includes(String((error as NodeJS.ErrnoException)?.syscall));"),
        x21_getter("openFailed"),
        x21_getter_doc("heldElsewhere(): boolean", "this.elsewhere", "whether another process held the account file open() could not read."),
        (X21_VAULT, X21_SIGNATURE, "  reconcile(committedReferences: ReadonlySet<string>, options: { keepStaged?: boolean; keepTombstoned?: boolean } = {}): Promise<void> {"),
        (X21_VAULT, X21_DELETES,
         "        } else if ((entry.state === 'tombstoned' && !options.keepTombstoned) || (entry.state === 'staged' && !committedReferences.has(ref) && !options.keepStaged)) {"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed(), keepTombstoned: githubStore.heldElsewhere() }});")]),
    # review loop 9 RL9-P3: W-j2, W-j's hold (no later start deletes a held entry) only on EPERM, a code the orphan row does not use
    "W-j2": dict(hold="open", check="journey",
        reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed(), hold: store.unreadCode() === 'EPERM' });", edits=[
        (X21_STORE, "  private unread = false;\n",
         "  private unread = false;\n  // X2-1: the code open() met when it could not read the file\n  private failedWith = '';\n"),
        (X21_STORE, X21_CATCH_FLAGS, X21_CATCH_FLAGS + "\n        this.failedWith = this.unread ? String(code) : '';"),
        x21_getter("openFailed"),
        x21_getter_doc("unreadCode(): string", "this.failedWith", "the errno code open() met, or '' when it read the file."),
        (X21_VAULT, X21_ENTRY, "interface VaultEntry { state: 'staged' | 'committed' | 'tombstoned'; createdAt: number; held?: boolean }"),
        (X21_VAULT, X21_SIGNATURE, "  reconcile(committedReferences: ReadonlySet<string>, options: { keepStaged?: boolean; hold?: boolean } = {}): Promise<void> {"),
        (X21_VAULT, X21_DELETES,
         "        } else if (options.keepStaged && entry.state === 'staged' && !committedReferences.has(ref)) {\n"
         "          if (options.hold) entry.held = true;   // X2-1: EPERM (a file pending delete): another instance replaces it; hold its pair\n"
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref) && !entry.held)) {"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed(), hold: githubStore.unreadCode() === 'EPERM' }});")]),
    # review loop 9 RL9-P4: W-u5, W-k with "now" from the store's clock (the app gives the store Date.now; the journey test gives it a fixed one)
    "W-u5": dict(hold="open", check="journey",
        reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed(), now: store.now() });", edits=[
        x21_getter("openFailed"),
        x21_getter_doc("now(): number", "this.clock()", "the store's clock, so the reconcile ages a kept entry by the same clock the account file is dated by."),
        (X21_VAULT, X21_SIGNATURE, "  reconcile(committedReferences: ReadonlySet<string>, options: { keepStaged?: boolean; now?: number } = {}): Promise<void> {"),
        (X21_VAULT, X21_DELETES,
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref)\n"
         "            && !(options.keepStaged && (options.now ?? Date.now()) - entry.createdAt < 24 * 3_600_000))) {   // X2-1: a day-old staged entry is abandoned"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed(), now: githubStore.now() }});")]),
    # review loop 9 RL9-P5: W-s, W-r's idea with the refs read from a copy the store writes beside the account file (same directory), not from the file
    "W-s": dict(hold="open", check="journey", reconcile=X21_KEEP_NAMED_RECONCILE, edits=[
        (X21_STORE, X21_CRYPTO_IMPORT, X21_CRYPTO_IMPORT + "import { readFile as readRefs, writeFile as writeRefs } from 'node:fs/promises';\n"),
        (X21_STORE, "    await atomicJson(this.file, next); this.disk = next; return next;",
         "    await atomicJson(this.file, next); this.disk = next;\n"
         "    await writeRefs(`${this.file}.refs`, JSON.stringify(refsOf(account)));   // X2-1: the refs the file names, readable when it is not\n"
         "    return next;"),
        (X21_STORE, "export class GitHubAccountStore {\n",
         "/** X2-1: the refs the account file names, from the copy written beside it, or none when that copy cannot be read either. */\n"
         "async function namedRefs(file: string): Promise<string[]> {\n"
         "  try {\n"
         "    const refs: unknown = JSON.parse(await readRefs(`${file}.refs`, 'utf8'));\n"
         "    return Array.isArray(refs) ? refs.filter((ref): ref is string => typeof ref === 'string') : [];\n"
         "  } catch { return []; }\n"
         "}\n\nexport class GitHubAccountStore {\n"),
        *x21_keep_named()]),
    # review loop 9 RL9-P4: W-u6, W-k with Date reached through its prototype's constructor (the real Date)
    "W-u6": dict(hold="open", check="journey", reconcile=X21_OF_RECONCILE, edits=[
        x21_getter("openFailed"),
        (X21_VAULT, X21_SIGNATURE, X21_KEEP_SIGNATURE),
        (X21_VAULT, X21_DELETES,
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref)\n"
         "            && !(options.keepStaged && (Date.prototype.constructor as DateConstructor).now() - entry.createdAt < 24 * 3_600_000))) {   // X2-1: a day-old staged entry is abandoned"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 10 RL10-P1: W-j3, W-j's hold only while the vault holds no committed entry (a first sign-in's crash): no row
    # ran an unreadable start beside an orphan pair with no committed entry; the vault-state rows build that state
    "W-j3": dict(hold="open", check="journey", reconcile=X21_OF_RECONCILE, edits=[
        x21_getter("openFailed"),
        (X21_VAULT, X21_ENTRY, "interface VaultEntry { state: 'staged' | 'committed' | 'tombstoned'; createdAt: number; held?: boolean }"),
        (X21_VAULT, X21_SIGNATURE + "\n    return this.serial(async () => {",
         X21_KEEP_SIGNATURE + "\n    return this.serial(async () => {\n"
         "      // X2-1: with no committed entry (a first sign-in's crash) the staged pair is the only account there is: hold it\n"
         "      const lone = !Object.values(this.index.entries).some(entry => entry.state === 'committed');"),
        (X21_VAULT, X21_DELETES,
         "        } else if (options.keepStaged && entry.state === 'staged' && !committedReferences.has(ref)) {\n"
         "          if (lone) entry.held = true;   // X2-1: held until a start that can name its references commits it\n"
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref) && !entry.held)) {"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 10 RL10-P2: W-b5, W-b2's sparing only while the vault holds a committed entry (another instance may be
    # mid-refresh): no row ran an unreadable start beside a tombstoned pair and a committed one; the vault-state rows build it
    "W-b5": dict(hold="open", check="journey", reconcile=X21_OF_RECONCILE, edits=[
        x21_getter("openFailed"),
        (X21_VAULT, X21_SIGNATURE + "\n    return this.serial(async () => {",
         X21_KEEP_SIGNATURE + "\n    return this.serial(async () => {\n"
         "      // X2-1: beside a committed account an unread start may meet another instance mid-refresh: its tombstones wait too\n"
         "      const spare = options.keepStaged === true && Object.values(this.index.entries).some(entry => entry.state === 'committed');"),
        (X21_VAULT, X21_DELETES,
         "        } else if ((entry.state === 'tombstoned' && !spare) || (entry.state === 'staged' && !committedReferences.has(ref) && !options.keepStaged)) {"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 10 RL10-P3: W-x, keep only while existsSync still sees the file (one gone since is a deletion race, read as
    # missing); existsSync went to node's binding past the fault, which now fails every function that takes a path by default
    "W-x": dict(hold="open", check="journey", reconcile=X21_OF_RECONCILE, edits=[
        (X21_STORE, X21_CRYPTO_IMPORT, X21_CRYPTO_IMPORT + "import { existsSync } from 'node:fs';\n"),
        x21_getter_doc("openFailed(): boolean", "this.unread && existsSync(this.file)",
                       "whether open() could not read an account file that is still there (one gone since reads as missing)."),
        *X21_KEEP_UNREFERENCED,
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 11 RL11-P1: W-b6, W-b's skipped reconcile only on EIO (a failing disk: write nothing); every row's EIO start
    # came after a start that had already deleted the tombstone and committed the engine's entry. The tombstone-at-each-point
    # row now runs every code at every point on a fresh tombstone beside an engine entry
    "W-b6": dict(hold="open", check="journey",
                 reconcile="if (store.unreadCode() !== 'EIO') await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed() });",
                 edits=[
        (X21_STORE, "  private unread = false;\n",
         "  private unread = false;\n  // X2-1: the code open() met when it could not read the file\n  private failedWith = '';\n"),
        (X21_STORE, X21_CATCH_FLAGS, X21_CATCH_FLAGS + "\n        this.failedWith = this.unread ? String(code) : '';"),
        x21_getter("openFailed"),
        x21_getter_doc("unreadCode(): string", "this.failedWith", "the errno code open() met, or '' when it read the file."),
        *X21_KEEP_UNREFERENCED,
        x21_wire(f"  if (githubStore.unreadCode() !== 'EIO') await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});   // X2-1: a failing disk: write nothing")]),
    # review loop 11 RL11-P2: W-l5, W-l3 (a failed read is a failing disk: delete) unless the file reads again through a new
    # FileHandle's descriptor; the fault knew a FileHandle, not its fd. It now knows a descriptor by the file it is open on
    "W-l5": dict(hold="open", check="journey", reconcile=X21_OF_RECONCILE, edits=[
        (X21_STORE, X21_CRYPTO_IMPORT, X21_CRYPTO_IMPORT + "import { readSync } from 'node:fs';\nimport { open as openHandle } from 'node:fs/promises';\n"),
        (X21_STORE, "export class GitHubAccountStore {\n",
         "/** X2-1: whether the account file reads again through a fresh descriptor (the failed read was transient). */\n"
         "async function readsAgain(file: string): Promise<boolean> {\n"
         "  try {\n"
         "    const handle = await openHandle(file, 'r');\n"
         "    try { readSync(handle.fd, Buffer.alloc(1), 0, 1, 0); return true; } finally { await handle.close(); }\n"
         "  } catch { return false; }\n"
         "}\n\nexport class GitHubAccountStore {\n"),
        (X21_STORE, "  private unread = false;\n",
         "  private unread = false;\n  // X2-1: a failed read that does not read again is a failing disk; a lock or a permission at the stat or the open is held\n"
         "  private held = false;\n"),
        (X21_STORE, X21_CATCH_FLAGS,
         X21_CATCH_FLAGS + "\n        this.held = this.unread && ((error as NodeJS.ErrnoException)?.syscall !== 'read' || await readsAgain(this.file));"),
        x21_getter("openFailed", "this.held"),
        *X21_KEEP_UNREFERENCED,
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 11 RL11-P3: W-b7, the keep flag dropped while the vault holds a tombstoned entry (a sign-out or a refresh cut
    # short, a staged pair beside it taken for part of it); no row kept a pair beside a tombstone. The keep-side vault-state
    # rows build a pair to keep in every vault state
    "W-b7": dict(hold="open", check="journey", reconcile=X21_OF_RECONCILE, edits=[
        x21_getter("openFailed"),
        (X21_VAULT, X21_SIGNATURE + "\n    return this.serial(async () => {",
         X21_KEEP_SIGNATURE + "\n    return this.serial(async () => {\n"
         "      // X2-1: beside a tombstone (a sign-out or refresh cut short) a staged pair belongs to the abandoned operation\n"
         "      const keep = options.keepStaged === true && !Object.values(this.index.entries).some(entry => entry.state === 'tombstoned');"),
        (X21_VAULT, X21_DELETES,
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref) && !keep)) {"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 12 RL12-P1: W-y (the review's W-A), the keep only while the account file's directory is not lost: a stat of a
    # name beside the file that fails with any code but ENOENT and EACCES is taken for a lost volume. The keep side met the
    # directory only in the lasting row, with EACCES. The keep-side row at every code and every point fails it with each code
    "W-y": dict(hold="open", check="journey", reconcile=X21_OF_RECONCILE, edits=[
        *X21_DIRECTORY_CODE,
        # a directory that may not be searched (EACCES) keeps; a lost volume (any other code from the directory) does not
        x21_getter("openFailed", "this.unread && (this.directoryFailed === '' || this.directoryFailed === 'EACCES')"),
        *X21_KEEP_UNREFERENCED,
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 12 RL12-P2: W-z (the review's W-B), the keep only for staged entries at least as new as the newest committed
    # entry, a commit after them taken for a later session that finished; no row committed an entry newer than the pair to
    # keep. The engine row's sibling has the engine store a key during an unreadable session, which the next start commits
    "W-z": dict(hold="open", check="journey", reconcile=X21_OF_RECONCILE, edits=[
        x21_getter("openFailed"),
        (X21_VAULT, X21_SIGNATURE + "\n    return this.serial(async () => {",
         X21_KEEP_SIGNATURE + "\n    return this.serial(async () => {\n"
         "      // X2-1: a staged entry older than a committed one was left behind by a session that finished after it\n"
         "      const newest = Math.max(0, ...Object.values(this.index.entries).filter(entry => entry.state === 'committed').map(entry => entry.createdAt));"),
        (X21_VAULT, X21_DELETES,
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref) && !(options.keepStaged && entry.createdAt >= newest))) {"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 13 RL13-P1: W-j4 (the review's W-C, renamed: W-c already names a row), W-j2's hold (no later start deletes a
    # held staged entry) keyed on the point, not the code: when the account file's directory fails, with any code, the staged
    # entries kept are another instance's, mid-replace in a locked directory, and held for good. No row put an orphan pair
    # before a failure at the directory; the orphan-codes row now runs every code at every point, the directory included
    "W-j4": dict(hold="open", check="journey",
                 reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed(), hold: store.directoryLocked() });", edits=[
        *X21_DIRECTORY_CODE,
        x21_getter("openFailed"),
        x21_getter_doc("directoryLocked(): boolean", "this.unread && this.directoryFailed !== ''",
                       "whether open() could not read the account file because its directory itself failed."),
        (X21_VAULT, X21_ENTRY, "interface VaultEntry { state: 'staged' | 'committed' | 'tombstoned'; createdAt: number; held?: boolean }"),
        (X21_VAULT, X21_SIGNATURE, "  reconcile(committedReferences: ReadonlySet<string>, options: { keepStaged?: boolean; hold?: boolean } = {}): Promise<void> {"),
        (X21_VAULT, X21_DELETES,
         "        } else if (options.keepStaged && entry.state === 'staged' && !committedReferences.has(ref)) {\n"
         "          if (options.hold) entry.held = true;   // X2-1: a locked directory: another instance is mid-replace; hold its staged entries\n"
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref) && !entry.held)) {"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed(), hold: githubStore.directoryLocked() }});")]),
    # review loop 13 RL13-P2: W-p3 (the review's W-D, renamed: W-d already names a row), W-p2's "same failure twice" restricted
    # to the directory with a code other than EACCES (a lost volume): at the second such start in a row the entries already
    # kept once are dropped. The keep-at-each-point row ran one unreadable start per code and point; it now runs two
    "W-p3": dict(hold="open", check="journey",
                 reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed(), lostVolume: store.lostVolume() });", edits=[
        *X21_DIRECTORY_CODE,
        x21_getter("openFailed"),
        x21_getter_doc("lostVolume(): boolean", "this.unread && this.directoryFailed !== '' && this.directoryFailed !== 'EACCES'",
                       "whether the account file's directory failed with a code other than a permission (a lost volume)."),
        (X21_VAULT, X21_ENTRY, "interface VaultEntry { state: 'staged' | 'committed' | 'tombstoned'; createdAt: number; lostOnce?: boolean }"),
        (X21_VAULT, X21_SIGNATURE, "  reconcile(committedReferences: ReadonlySet<string>, options: { keepStaged?: boolean; lostVolume?: boolean } = {}): Promise<void> {"),
        (X21_VAULT, X21_DELETES,
         "        } else if (options.keepStaged && entry.state === 'staged' && !committedReferences.has(ref) && !(options.lostVolume && entry.lostOnce)) {\n"
         "          entry.lostOnce = options.lostVolume === true;   // X2-1: a volume lost at two starts in a row is gone: drop at the second\n"
         f"{X21_DELETES}"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed(), lostVolume: githubStore.lostVolume() }});")]),
    # review loop 14 RL14-P1: W-k2 (the review's W-F, renamed: W-f already names a row), W-k's bound on leftovers by count, not
    # age: only one replace is in flight at a time, so the pair an unreadable file names is the newest two staged entries nothing
    # names, and any older one is an earlier crash's leftover and goes, even at an unreadable start. Every row that put an orphan
    # pair beside the pair to keep staged it before the pair; the keep-side vault-state rows now stage a second one after it
    "W-k2": dict(hold="open", check="journey", reconcile=X21_OF_RECONCILE, edits=[
        x21_getter("openFailed"),
        (X21_VAULT, X21_SIGNATURE + "\n    return this.serial(async () => {",
         X21_KEEP_SIGNATURE + "\n    return this.serial(async () => {\n"
         "      // X2-1: one replace at a time: its pair is the newest two staged entries nothing names; older ones are an earlier crash's leftovers\n"
         "      const newest = new Set(Object.entries(this.index.entries)\n"
         "        .filter(([ref, entry]) => entry.state === 'staged' && !committedReferences.has(ref))\n"
         "        .map(([ref, entry], order) => ({ ref, at: entry.createdAt, order }))\n"
         "        .sort((a, b) => b.at - a.at || b.order - a.order)\n"
         "        .slice(0, 2)\n"
         "        .map(entry => entry.ref));"),
        (X21_VAULT, X21_DELETES,
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref) && !(options.keepStaged && newest.has(ref)))) {"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
    # review loop 14 RL14-P2: W-p4 (the review's W-G, renamed: W-g already names a row), W-p's limit keyed on the point of the start
    # before: when the account file's directory fails, with any code, at the start right after one where the file failed on its
    # own (at the stat, the open or the read), the volume under it was swapped in between and the pair kept at the file is gone with
    # it: drop it. The keep side met the directory only as the first start after the crash or right after a start at the
    # directory; the row of every ordered pair of points now meets it after each of the others
    "W-p4": dict(hold="open", check="journey", reconcile=X21_DIRECTORY_RECONCILE, edits=[
        *X21_DIRECTORY_CODE,
        x21_getter("openFailed"),
        X21_DIRECTORY_NOW,
        (X21_VAULT, X21_ENTRY, "interface VaultEntry { state: 'staged' | 'committed' | 'tombstoned'; createdAt: number; keptAtFile?: boolean }"),
        X21_DIRECTORY_SIGNATURE,
        (X21_VAULT, X21_DELETES,
         "        } else if (options.keepStaged && entry.state === 'staged' && !committedReferences.has(ref) && !(options.atDirectory && entry.keptAtFile)) {\n"
         "          entry.keptAtFile = !options.atDirectory;   // X2-1: kept at the file; if its whole directory fails next, the volume was swapped\n"
         f"{X21_DELETES}"),
        X21_DIRECTORY_WIRE]),
    # review loop 14 RL14-P2: W-j6 (the review's W-H, renamed: W-j5 is disclosed), W-j's hold (no later start deletes a held staged
    # entry) when the account file's directory fails, with any code, at the start right after one where the file failed on its
    # own: another instance took the directory over in between, mid-replace, so the staged entries kept are its own. The orphan
    # pair met the directory only on a fresh copy of the crash and right after a start at the directory; the row of every ordered
    # pair of points now meets it after each of the others
    "W-j6": dict(hold="open", check="journey", reconcile=X21_DIRECTORY_RECONCILE, edits=[
        *X21_DIRECTORY_CODE,
        x21_getter("openFailed"),
        X21_DIRECTORY_NOW,
        (X21_VAULT, X21_ENTRY,
         "interface VaultEntry { state: 'staged' | 'committed' | 'tombstoned'; createdAt: number; keptAtFile?: boolean; held?: boolean }"),
        X21_DIRECTORY_SIGNATURE,
        (X21_VAULT, X21_DELETES,
         "        } else if (options.keepStaged && entry.state === 'staged' && !committedReferences.has(ref)) {\n"
         "          if (options.atDirectory && entry.keptAtFile) entry.held = true;   // X2-1: the file failed, then its directory: another instance took it over\n"
         "          entry.keptAtFile = !options.atDirectory;\n"
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref) && !entry.held)) {"),
        X21_DIRECTORY_WIRE]),
    # review loop 15 RL15-P1: W-j5 (review loop 13's W-E, disclosed until now), W-j2's hold on EPERM only while the vault holds no
    # committed entry (W-j3's rule): no row built an orphan pair beside no committed entry at EPERM; the start-sequence rows do (a
    # session's sign-in after another's tombstones the committed pair and leaves the earlier session's pair staged, unnamed)
    "W-j5": dict(hold="open", check="journey",
        reconcile="await vault.reconcile(new Set(store.references()), { keepStaged: store.openFailed(), hold: store.unreadCode() === 'EPERM' });", edits=[
        (X21_STORE, "  private unread = false;\n",
         "  private unread = false;\n  // X2-1: the code open() met when it could not read the file\n  private failedWith = '';\n"),
        (X21_STORE, X21_CATCH_FLAGS, X21_CATCH_FLAGS + "\n        this.failedWith = this.unread ? String(code) : '';"),
        x21_getter("openFailed"),
        x21_getter_doc("unreadCode(): string", "this.failedWith", "the errno code open() met, or '' when it read the file."),
        (X21_VAULT, X21_ENTRY, "interface VaultEntry { state: 'staged' | 'committed' | 'tombstoned'; createdAt: number; held?: boolean }"),
        (X21_VAULT, X21_SIGNATURE + "\n    return this.serial(async () => {",
         "  reconcile(committedReferences: ReadonlySet<string>, options: { keepStaged?: boolean; hold?: boolean } = {}): Promise<void> {\n"
         "    return this.serial(async () => {\n"
         "      // X2-1: with no committed entry the staged pair is the only account there is\n"
         "      const lone = !Object.values(this.index.entries).some(entry => entry.state === 'committed');"),
        (X21_VAULT, X21_DELETES,
         "        } else if (options.keepStaged && entry.state === 'staged' && !committedReferences.has(ref)) {\n"
         "          if (options.hold && lone) entry.held = true;   // X2-1: EPERM (a file pending delete) beside no account: hold the lone pair\n"
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref) && !entry.held)) {"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed(), hold: githubStore.unreadCode() === 'EPERM' }});")]),
    # review loop 15 RL15-P1: W-C1 (the review's name), a rule whose state one start builds and a later one reads: an unreadable
    # start marks the staged entries it keeps, and a later unreadable start that finds marked ones keeps only those, taking any
    # other for one a session that could not write the file staged. Every other row stages the pair to keep before the first
    # unreadable start; the start-sequence rows stage it in a session between two (the file read again, then a crash)
    "W-C1": dict(hold="open", check="journey", reconcile=X21_OF_RECONCILE, edits=[
        x21_getter("openFailed"),
        (X21_VAULT, X21_ENTRY, "interface VaultEntry { state: 'staged' | 'committed' | 'tombstoned'; createdAt: number; keptUnread?: boolean }"),
        (X21_VAULT, X21_SIGNATURE + "\n    return this.serial(async () => {",
         X21_KEEP_SIGNATURE + "\n    return this.serial(async () => {\n"
         "      // X2-1: kept at an earlier unreadable start: what was staged since then was staged by a session that could not write the file\n"
         "      const run = Object.values(this.index.entries).some(entry => entry.state === 'staged' && entry.keptUnread === true);"),
        (X21_VAULT, X21_DELETES,
         "        } else if (options.keepStaged && entry.state === 'staged' && !committedReferences.has(ref) && (!run || entry.keptUnread === true)) {\n"
         "          entry.keptUnread = true;\n"
         f"{X21_DELETES}"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, {{ keepStaged: githubStore.openFailed() }});")]),
}

# The rows of the accepted journey test (zz_accepted_x2_1.test.ts): 12 journey rows and X21_PIN_ROWS - 12 others, 25 since review
# loop 15 (review loop 14 RL14-P3: this said 14 since review loop 9; review loop 1 RL1-1 added
# the refused-file row, review loop 2 RL2-P1 the unreadable-run row and RL2-1 the named refused-file row; review loop 3
# RL3-1 and RL3-2 added forms beside a committed account to the named refused-file row and the ENOENT row; review loop 5
# RL5-P1 added the other-errno row; review loop 9 RL9-P1..P3 added the lasting row, the engine row, the tombstone-at-each-point
# row and the orphan-codes row; review loop 10 RL10-P1, RL10-P2 the two vault-state rows; review loop 11 RL11-P3 the two
# keep-side vault-state rows; review loop 12 RL12-P1 the keep at every code and every point, RL12-P2 the engine's key stored
# during an unreadable session; review loop 13 RL13-P2 split the keep at every code and every point in two, a sign-in's crashes
# and a refresh's, as each now runs two unreadable starts per code and point; review loop 14 RL14-P2 the two point-pair rows, every
# ordered pair of points at two starts in a row; review loop 15 RL15-P1 the two start-sequence rows, every run of three events)
X21_PIN_ROWS = 37

# A correct fix the accepted one is not: another name for the store's flag and a positional vault parameter.
X21_ALTERNATIVE = dict(hold="open", check="journey", reconcile="await vault.reconcile(new Set(store.references()), store.fileUnreadable());", edits=[
    x21_getter("fileUnreadable"),
    ("src/main/vault.ts", X21_SIGNATURE, "  reconcile(committedReferences: ReadonlySet<string>, keepUnreferencedStaged = false): Promise<void> {"),
    ("src/main/vault.ts", X21_DELETES,
     "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref) && !keepUnreferencedStaged)) {"),
    x21_wire(f"  await vault.reconcile({X21_REFS}, githubStore.fileUnreadable());")])

# review 1 F1: a correct fix whose wiring calls a helper the store's module exports and index.ts imports (the decision made
# testable outside index.ts, which has no harness), with an options object under another name.
X21_ALTERNATIVE_HELPER = dict(
    hold="open", check="journey", imports=", startupReconcileOptions",
    reconcile="await vault.reconcile(new Set(store.references()), startupReconcileOptions(store));", edits=[
        x21_getter("fileUnreadable"),
        ("src/main/github-account-store.ts", "export class GitHubAccountStore {\n",
         "/** X2-1: the startup reconcile's options: a start whose open() could not read the account file spares unreferenced staged entries. */\n"
         "export function startupReconcileOptions(store: Pick<GitHubAccountStore, 'fileUnreadable'>): { spareStaged: boolean } {\n"
         "  return { spareStaged: store.fileUnreadable() };\n"
         "}\n\n"
         "export class GitHubAccountStore {\n"),
        ("src/main/vault.ts", X21_SIGNATURE,
         "  reconcile(committedReferences: ReadonlySet<string>, options: { spareStaged?: boolean } = {}): Promise<void> {"),
        ("src/main/vault.ts", X21_DELETES,
         "        } else if (entry.state === 'tombstoned' || (entry.state === 'staged' && !committedReferences.has(ref) && !options.spareStaged)) {"),
        ("src/main/index.ts", "import { GitHubAccountStore } from './github-account-store';\n",
         "import { GitHubAccountStore, startupReconcileOptions } from './github-account-store';\n"),
        x21_wire(f"  await vault.reconcile({X21_REFS}, startupReconcileOptions(githubStore));")])

# W-c keeps every unreferenced staged entry, so the shipped crash-window row whose crash leaves an orphan pair (staged,
# never written to the file) no longer holds; a candidate holding that idea drops the row as the change's consequence.
X21_TEST_EDITS = {"W-c": [(
    "tests/github-account-store.test.ts",
    "    { name: 'after staging, before the file write', arm: (h, take) => h.spy.after('saveStaged', (_ref, count) => "
    "{ if (count === 4) take(); }), expect: 'old' },\n",
    "",
)]}

# The candidate's own red-first test for its change (tests/x2_candidate.test.ts): a first sign-in that crashed before its
# first commit, a start whose open() cannot read the account file, then the check. Self-contained, as a candidate writes it.
X21_CANDIDATE_TEST = """\
import { afterEach, expect, test } from 'vitest';
import { randomBytes } from 'node:crypto';
import { cpSync, readFileSync } from 'node:fs';
import fsp, { mkdtemp, rm } from 'node:fs/promises';
import { syncBuiltinESMExports } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Vault } from '../src/main/vault';
import { GitHubAccountStore{{IMPORTS}} } from '../src/main/github-account-store';

// X2-1, written red-first by the candidate: a crash before the first commit, then a start that cannot read the account file.
const cryptor = { isEncryptionAvailable: () => true, encryptString: (v: string) => Buffer.from(v, 'utf8'), decryptString: (b: Buffer) => b.toString('utf8') };
const T0 = Date.UTC(2026, 9, 13, 10, 0, 0);
const roots: string[] = [];
afterEach(async () => { for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true }); });
const tokens = () => ({ access: `x2-a-${randomBytes(8).toString('hex')}`, refresh: `x2-r-${randomBytes(8).toString('hex')}`,
  accessExpiresInS: 28_800, refreshExpiresInS: 15_897_600 });

function busy(path: string, once: boolean): () => void {
  const real = fsp.lstat; let failed = false;
  (fsp as { lstat: unknown }).lstat = (target: string) => {
    if (target === path && !(once && failed)) { failed = true; return Promise.reject(Object.assign(new Error('EBUSY'), { code: 'EBUSY' })); }
    return real(target);
  };
  syncBuiltinESMExports();
  return () => { (fsp as { lstat: unknown }).lstat = real; syncBuiltinESMExports(); };
}

async function startup(dir: string, unread: boolean) {
  const file = join(dir, 'github', 'account.json');
  const vault = new Vault(join(dir, 'vault'), cryptor); await vault.initialize('epoch-2');
  const store = new GitHubAccountStore(file, vault, 'Iv1.x2-candidate', () => T0);
  const restore = unread ? busy(file, {{ONCE}}) : () => {};
  try { await store.open(); } finally { restore(); }
  {{RECONCILE}}
  await store.finishStartup();
  return { vault, store };
}

test('X2-1: a start that cannot read the account file keeps the staged pair the file names', async () => {
  const root = await mkdtemp(join(tmpdir(), 'x2-candidate-')); roots.push(root);
  const data = join(root, 'data'); const dir = join(root, 'crash');
  const vault = new Vault(join(data, 'vault'), cryptor); await vault.initialize('epoch-1');
  let crashed = false;
  const spy = new Proxy(vault, { get(target, key) {
    const value = Reflect.get(target, key, target) as unknown;
    if (typeof value !== 'function') return value;
    return (...args: unknown[]) => {
      if (key === 'commit' && !crashed) { crashed = true; cpSync(data, dir, { recursive: true }); }
      return (value as (...a: unknown[]) => unknown).apply(target, args);
    };
  } });
  const store = new GitHubAccountStore(join(data, 'github', 'account.json'), spy, 'Iv1.x2-candidate', () => T0);
  await store.open();
  const account = await store.replace(tokens(), T0, 'sign-in', () => true);
  const pair = [account!.accessRef, account!.refreshRef!];
  await startup(dir, true);
  const index = JSON.parse(readFileSync(join(dir, 'vault', 'index.json'), 'utf8')) as { entries: Record<string, { state: string }> };
  expect(Object.keys(index.entries)).toEqual(expect.arrayContaining(pair));
  {{CHECK}}
});
"""
X21_CHECKS = {
    "journey": "const next = await startup(dir, false);\n  expect([next.store.current()?.accessRef, next.store.current()?.refreshRef]).toEqual(pair);\n"
               "  for (const ref of pair) expect(await next.vault.has(ref)).toBe(true);",
    "index": "expect(pair.map(ref => index.entries[ref]?.state)).toEqual(['staged', 'staged']);",
}


def x21_edit(cand: Path, path: str, old: str, new: str) -> None:
    """Replace the one occurrence of old in a checkout file, whatever its line ends (a host with core.autocrlf writes CRLF)."""
    f = cand / path
    raw = f.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    if text.count(old) != 1:
        raise AssertionError(f"{path}: the anchor occurs {text.count(old)} times: {old[:80]!r}")
    text = text.replace(old, new)
    f.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


def x21_candidate(cand: Path, change: dict, env: dict, message: str) -> None:
    """Apply a candidate change on a history-less checkout of the base and commit it, as a candidate would."""
    for path, old, new in change["edits"]:
        x21_edit(cand, path, old, new)
    for path, old, new in X21_TEST_EDITS.get(change.get("test_edits", ""), []):
        x21_edit(cand, path, old, new)
    test = (X21_CANDIDATE_TEST.replace("{{IMPORTS}}", change.get("imports", ""))
            .replace("{{ONCE}}", "true" if change["hold"] == "once" else "false")
            .replace("{{RECONCILE}}", change["reconcile"]).replace("{{CHECK}}", X21_CHECKS[change["check"]]))
    (cand / "tests" / "x2_candidate.test.ts").write_text(test, encoding="utf-8", newline="\n")
    sh(["git", "add", "-A"], cand, env)
    sh(["git", "commit", "-q", "--no-verify", "-m", message], cand, env)  # the subject's hooks are not the candidate's grade


def x21_install(clone: Path, repo: Path, target: Path, env: dict) -> Path:
    """integration 5 (IC4-1): the install the README's build step 2 makes, returned as its node_modules: a directory of its
    own, outside the pack and outside every git repository, holding only base0's package.json and package-lock.json and
    their node_modules. Harness only, never a candidate's setup: instead of running npm ci, which needs the network, the
    node_modules is a copy of the clone's installed one (the clone is only read; the lockfile is the same blob at 16f637f,
    01a8604 and the clone's head, so npm ci there installs the same files). The copy holds no link, so nothing in the
    install leads back to the clone, and a checkout's node_modules/.. is this directory. A link from the checkouts to the
    clone's own node_modules, or to entries of it, is what --link now refuses: through node_modules/.. it reached the
    clone's docs/orchestration/ and its history. By default vitest and vite write .vite and .vite-temp into the
    node_modules a checkout links; the manifest's commands write nothing there (F5), which the class checks."""
    import os
    target.mkdir(parents=True)
    for name in ("package.json", "package-lock.json"):
        (target / name).write_bytes(subprocess.run(["git", "-C", str(repo), "show", f"base0:{name}"], env=env, capture_output=True, check=True).stdout)
    src = clone / "node_modules"
    shutil.copytree(src, target / "node_modules", symlinks=True,
                    ignore=lambda here, names: [n for n in names if n in (".vite", ".vite-temp")] if Path(here) == src else [])
    for here, dirs, files in os.walk(target / "node_modules"):
        for name in dirs + files:
            p = Path(here) / name
            assert not (p.is_symlink() or p.is_junction()), f"the install holds a link: {p}"
    return target / "node_modules"


def x21_reaches_no_records(checkout: Path) -> list[str]:
    """integration 5 (IC4-1): what a checkout's node_modules/.. reaches that it must not: the directory the link leads into
    and each of its parents, read as native programs resolve them, holding a .git or a docs/orchestration/. Empty for an
    install made as the README's build step 2 says."""
    import os
    up = Path(os.path.realpath(checkout / "node_modules", strict=True)).parent
    found = []
    for d in (up, *up.parents):
        found += [str(d / x) for x in (".git", "docs/orchestration") if os.path.lexists(d / x)]
    return found


def x21_manifest() -> dict:
    return json.loads((X21 / "manifest.json").read_text(encoding="utf-8"))


def x21_launch_config(root: Path, m: dict, pack: Path, **host) -> dict:
    """The workflow template's config for this manifest and a protocol whose only case is fix (stage 4a), checkouts under root."""
    co = root / "launch" / "checkouts"
    c = run_config(root / "launch", **{"pack_dir": str(pack), "checkout_root": str(co), "adjudication_checkout": str(co / "cal-adjudication"), **host})
    c["manifest"] = m
    p = c["protocol"]
    p["cases"] = [{"id": "fix", "category": "fix", "tier": "T3", "base": "base0", "grading": "mechanical (grade.sh fix)",
                   "pass_rule": m["cases"]["fix"]["pass_rule"]}]
    p["subject_pack"] = {"pack": m["pack"], "pack_version": m["pack_version"], "kind": "host", "manifest_sha256": text_hash(X21 / "manifest.json")}
    return c


def x21_tree(root: Path) -> dict[str, tuple[int, int]]:
    """Every entry under root, .git included, symlinks not followed: {relative path: (mtime_ns, size)}. A run that writes,
    creates or removes anything under root changes it; reading changes nothing."""
    import os
    state = {}
    for here, dirs, files in os.walk(root):
        for name in dirs + files:
            path = Path(here) / name
            try:
                st = path.lstat()
            except OSError:
                continue
            state[path.relative_to(root).as_posix()] = (st.st_mtime_ns, 0 if name in dirs else st.st_size)
    return state


def x21_clone_state(clone: Path, env: dict) -> tuple[str, list[str], dict]:
    """The clone as a run must leave it (owner F5): git status with ignored files (without optional locks, so the check
    itself writes no index), the node_modules/.vite* entries, and every entry's mtime and size."""
    status = subprocess.run(["git", "--no-optional-locks", "-C", str(clone), "status", "--porcelain", "--ignored"], env=env,
                            capture_output=True, text=True, check=True).stdout
    return status, sorted(p.name for p in (clone / "node_modules").glob(".vite*")), x21_tree(clone)


def x21_ls_tree(repo: Path, rev: str, env: dict) -> dict[str, tuple[str, str, str]]:
    """Every file of rev's tree, read only: {path: (mode, type, object id)}."""
    out = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "-z", rev], env=env, capture_output=True, check=True).stdout
    entries = {}
    for rec in filter(None, out.split(b"\0")):
        meta, path = rec.split(b"\t", 1)
        mode, kind, oid = meta.decode("ascii").split()
        entries[path.decode("utf-8")] = (mode, kind, oid)
    return entries


def x21_hint_hits(repo: Path, rev: str, env: dict) -> list[str]:
    """integration 4 (IC3-1, D-IC3-1): the paths of rev's tree whose name or bytes hold a hint of X2-1, its accepted fix or
    its cause (X21_HINTS), case-insensitive, with every run of whitespace read as one space (a phrase wrapped over two lines
    still counts). Read only: git ls-tree and git cat-file --batch."""
    blobs = [(path, oid) for path, (_, kind, oid) in x21_ls_tree(repo, rev, env).items() if kind == "blob"]
    out = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"], input="".join(f"{oid}\n" for _, oid in blobs).encode("ascii"),
                         env=env, capture_output=True, check=True).stdout
    hits, at = [], 0
    for path, oid in blobs:
        header_end = out.index(b"\n", at)
        got, kind, size = out[at:header_end].decode("ascii").split()
        assert (got, kind) == (oid, "blob"), (path, got, kind)
        body = out[header_end + 1:header_end + 1 + int(size)]
        at = header_end + 1 + int(size) + 1
        text = " ".join(body.decode("utf-8", "replace").lower().split())
        if any(h in path.lower() or h in text for h in X21_HINTS):
            hits.append(path)
    assert at == len(out), "every object read"
    return hits


def x21_wrong_rows() -> dict[str, list[str]]:
    """WRONG-FIXES.md's table: {id: [the wrong idea, the pin row that catches it, the grade]}."""
    rows = {}
    for line in (X21 / "WRONG-FIXES.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("| W-") and len(cells) == 4:
            rows[cells[0]] = cells[1:]
    return rows


class HostPackX21(unittest.TestCase):
    """H4: the host pack moonaliza-x2-1 builds from a MoonAliza clone, its accepted journey test and its wrong-fix
    matrix hold as WRONG-FIXES.md says, and the pack's own files are clean, shaped and hashed."""

    # ---- without the clone -----------------------------------------------------------------------------------------
    def test_the_pack_has_no_host_path_session_id_or_run_id(self):
        self.assertEqual(hygiene_scan(X21), [])

    def test_the_manifest_has_the_host_pack_shape(self):
        m = x21_manifest()
        self.assertEqual(next(iter(m)), "_lineage")
        self.assertEqual((m["kind"], m["pack"], m["pack_version"], m["repository"]), ("host", "moonaliza-x2-1", "1", "repo"))
        self.assertEqual(sorted(m["cases"]), ["fix"], "stage 4a is fix@T3 alone: no pin and no review case")
        fix = m["cases"]["fix"]
        self.assertEqual((fix["tier"], fix["category"], fix["finding"]), ("T3", "fix", "X2-1"))
        self.assertEqual(fix["pass_rule"],
                         "the candidate's tests are green at its head AND red again with the three source files restored to the base AND the "
                         "accepted journey test is green against the candidate's source AND every changed file is one of the three source files, "
                         "the two test files, the wiring test or the map, or a newly added test file matching the pattern AND eslint is clean on those files")
        [f] = m["findings"]
        self.assertEqual((f["id"], f["severity"], f["present_at"], f["accepted_fix"]), ("X2-1", "S3", [fix["base"]], m["accepted_fix"]))
        for rev in (fix["base"], m["accepted_fix"]):
            self.assertRegex(rev, r"^[0-9a-f]{40}$")
        for name in ("unreadAtOpen", "keepStaged"):  # the accepted fix's names stay out of every text a candidate or grader reads
            self.assertNotIn(name, json.dumps({k: v for k, v in m.items() if k != "source_hashes"}), name)
        p = m["paths"]
        self.assertEqual(p["source"], ["src/main/github-account-store.ts", "src/main/vault.ts", "src/main/index.ts"])
        self.assertEqual(p["test_file"], "tests/github-account-store.test.ts")
        self.assertEqual(p["allowed_extra"], ["tests/vault.test.ts", "tests/github-main-wiring.test.ts", "docs/ARCHITECTURE.md"])
        self.assertEqual(p["map_file"], "docs/ARCHITECTURE.md")
        self.assertEqual(p["new_test_pattern"], r"^tests/.*x2.*\.test\.ts$")
        self.assertEqual(p["accepted_test"], {"from": "tests/zz_accepted_x2_1.test.ts", "to": "tests/zz_accepted_x2_1.test.ts"})
        self.assertRegex(p["accepted_test"]["to"], p["new_test_pattern"], "grade.sh leaves the accepted test out of the candidate's new tests")
        c = m["commands"]
        # integration 3 (F5): --no-cache and --configLoader runner keep vitest and vite from writing into the node_modules a checkout links
        self.assertEqual((c["test"], c["run_one"], c["test_report"], c["lint"], c["timeout_seconds"]),
                         ("npx vitest run {files} --no-cache --configLoader runner --testTimeout=60000 --reporter=json --outputFile={report}",
                          "npx vitest run {file} --no-cache --configLoader runner", "vitest-json", "npx eslint {files}", 900))
        self.assertEqual(m["checkout"]["links"], ["node_modules", ".build"])
        self.assertIn("history-less", m["isolation"])
        self.assertIn("no MoonAliza code", m["isolation"])
        # integration 4 (D-IC3-1): the isolation text states the exclusion and the limit of the check that guards it
        for words in ("without its docs/orchestration/ directory", "copies no object of docs/orchestration/", "a paraphrase is not caught"):
            self.assertIn(words, m["isolation"], words)
        # integration 5 (IC4-1): the isolation text names the install the README's step 2 allows, and forbids a clone's
        for words in ("npm ci install in a directory of its own holding only base0's package.json and package-lock.json",
                      "outside the pack and outside every git repository's work tree",
                      "never the install of a MoonAliza clone or checkout"):
            self.assertIn(words, m["isolation"], words)
        fmt = (KIT / "subject-pack" / "README.md").read_text(encoding="utf-8")
        for k in ("subject", "commit_rule", "accepted_fix", "findings", "cases", "paths", "commands", "checkout", "source_hashes", "isolation"):
            self.assertIn(k, m, k)
            self.assertIn(f"`{k}`", fmt, k)
        for k in m["paths"]:
            self.assertIn(f"`paths.{k}`", fmt, k)

    @NEEDS_NODE
    def test_the_fix_prompt_carries_the_finding_but_not_its_cause(self):
        # integration 3 (F2, IC-1, IC-4, IC-5): the manifest keeps the real cause and sets cases.fix.cause_in_prompt false, so the
        # kit's fix prompt, rendered here through run.template.js, has the summary and the required behaviour but none of the
        # cause's phrases, and names no pack path or pack file; sr-kit-cases N-1: the template prints the summary, the required
        # behaviour and the instructions verbatim, so those must not restate the cause in other words either
        m = x21_manifest()
        [f] = m["findings"]
        self.assertIs(m["cases"]["fix"].get("cause_in_prompt"), False)
        words = lambda text: re.findall(r"[a-z0-9']+", text.lower())
        flat = lambda text: " ".join(words(text))
        for phrase in X21_CAUSE_PHRASES:
            self.assertIn(phrase, f["cause"], "a phrase of the real cause")
        self.assertEqual(set(words(f["cause"])) - set(words(f["summary"])) - set(words(" ".join(X21_CAUSE_PHRASES))), set(),
                         "the phrases hold every word of the cause that the summary does not")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        out = execute_template(x21_launch_config(root, m, X21), root)
        self.assertIsNone(out["error"])
        [call] = out["calls"]
        prompt = call["prompt"]
        self.assertIn(f"THE FINDING ({f['id']}, {f['severity']}): {f['summary']}. Required behaviour: {f['required_behaviour']}.", prompt)
        self.assertIn(m["cases"]["fix"]["instructions"], prompt)
        self.assertNotIn("Cause:", prompt)
        for phrase in (f["cause"], *X21_CAUSE_PHRASES):
            self.assertNotIn(flat(phrase), flat(prompt), "the fix prompt restates the cause")
        for secret in (str(X21), X21.as_posix(), X21.name, "subject-pack", *pack_files(X21)):
            self.assertNotIn(secret, prompt, "the fix prompt names the pack")
        journey = md_section((X21 / "README.md").read_text(encoding="utf-8"), "The journey")
        self.assertIn(f"**The cause** (`findings[].cause`): {f['cause']}.", " ".join(journey.split()), "the README states the manifest's cause")

    def test_the_instructions_state_the_grade_limit_without_pointing_at_the_fix(self):
        # integration D-R3: the limit review 1 F1 needed disclosed stays (the grade drives each start in the wiring's order,
        # with only the listed names in scope), framed as how every start is driven, not as where a change goes
        text = x21_manifest()["cases"]["fix"]["instructions"]
        for words in ("the vault reconcile", "finishStartup", "The grade runs the startup lines"):
            self.assertNotIn(words, text, words)
        # integration 3 (IC-2): the check parses index.ts, so the region is stated in statements, with the limits that are left
        for words in ("whichever files your change touches", "the store's open()", "the statements that follow the one that reads the engine's references",
                      "method: 'vault.references'", "a later statement that declares references if that call is split",
                      "up to the statement that calls supervisor.attach()", "in the one block that holds both",
                      "vault, references, collectorSettings, githubStore", "./github-account-store", "./vault", "any other name of index.ts",
                      "renames one of those four names"):
            self.assertIn(words, text, words)

    def test_the_source_hashes_cover_every_pack_file(self):
        m = x21_manifest()
        files = [f for f in pack_files(X21) if f != "manifest.json"]
        self.assertEqual(sorted(m["source_hashes"]), sorted(files))
        for f in files:
            self.assertEqual(m["source_hashes"][f], text_hash(X21 / f), f)

    def test_the_readme_lists_the_files_and_the_names_the_test_assumes(self):
        text = (X21 / "README.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("<!-- Lineage:"))
        files = md_section(text, "Files")
        for f in pack_files(X21):
            self.assertIn(f"`{f}`", files, f)
        for heading in ("The journey", "How a host builds the repository and the checkouts", "The names the journey test assumes",
                        "What the pack does not discriminate", "Why there is no pin and no review case"):
            md_section(text, heading)
        build = md_section(text, "How a host builds the repository and the checkouts")
        for word in ("make-repo.sh", "historyless-checkout.sh", "--link node_modules=", "grade.sh", "outside the pack",
                     "grade.sh --seal node_modules=", "grade.sh --links <seal>"):  # review loop 8 RL8-K2
            self.assertIn(word, build, word)
        # integration 5 (IC4-1): step 2 installs with npm ci in a directory holding only base0's package.json and
        # package-lock.json, outside every git repository, and allows no install in a MoonAliza clone or checkout; the
        # harness's copy of the clone's install is stated as the harness's alone
        deps = " ".join(build.split("2. **Dependencies.**", 1)[1].split("3. **Checkouts.**", 1)[0].split())
        for words in ("`npm ci` (Node 24)", "holds only MoonAliza's `package.json` and `package-lock.json` from `base0`",
                      "outside every git repository's work tree", "`node_modules/..`", "Never link the install of a MoonAliza clone or checkout",
                      "a history-less checkout of `base0` is no install site", "Harness only, never a candidate's setup"):
            self.assertIn(words, deps, words)
        for gone in ("linked as it is", "a MoonAliza checkout of `16f637f`", "symlinks to the clone's"):
            self.assertNotIn(gone, " ".join(build.split()), gone)
        harness = deps.split("Harness only, never a candidate's setup", 1)
        self.assertNotIn("clone", harness[0].replace("Never link the install of a MoonAliza clone or checkout", ""),
                         "before the harness note, step 2 names a clone only to forbid its install")
        test = (X21 / "zz_accepted_x2_1.test.ts").read_text(encoding="utf-8")
        for name in ("unreadAtOpen", "keepStaged"):
            self.assertNotIn(name, test, f"the accepted journey test names the accepted fix's {name}")
        # review 1 F1, F3, F7: the wiring binds index.ts's imports from the modules in scope, a later start runs a month after the
        # crash, and a third errno code is exercised; the README states the limit that is left
        self.assertIn("for (const code of ['EACCES', 'EBUSY', 'EIO'])", test)
        # review loop 8 RL8-P1: the journey rows and the other-errno row run three later starts each, ten, twenty and thirty years
        # on, failing at the stat, the open and the read in turn (W-l3 decides on where the error came from)
        self.assertEqual(test.count("for (const [index, phase] of PHASES.entries()) {"), 2,
                         "the journey rows and the other-errno row run a start at each phase (the orphan-codes row, review loop 9 "
                         "RL9-P3, runs every point on a fresh copy since review loop 13 RL13-P1)")
        self.assertIn("const PHASES: Phase[] = ['stat', 'open', 'read'];", test)
        self.assertNotIn("later(3650);", test)
        # review loop 5 RL5-P1: the journey rows' three codes are each in a list of codes a wrong fix may take for passing ones
        # (W-l2: EACCES, EPERM, EBUSY, EAGAIN, EIO), so the other-errno row fails the next start, at the four crash points,
        # with codes such a list is unlikely to hold; the README states the limit that is left
        self.assertIn("test('first sign-in before commit 1, sign-in or refresh before commit 3 and refresh before commit 4, then EPERM, "
                      "EMFILE, EINVAL or UNKNOWN at the next three starts (at the stat, the open, then the read): the pair survives all "
                      "three and is live and committed after the next'", test)
        self.assertIn("for (const [kind, at, states] of crashes) for (const code of ['EPERM', 'EMFILE', 'EINVAL', 'UNKNOWN']) {", test)
        # review loop 6 RL6-P1: the fault fails every node:fs read of the file, in the promise, callback and sync forms (a stream
        # opens through the callback open), whatever form its path takes, and is in place before the subject's modules load, so a
        # second read another way (W-r's stream) or through a function taken as the module loads (W-r2) meets it; the README says
        # so and states the limit that is left
        # review loop 7 RL7-P1, RL7-P2: the fault and the subject now live in each later start's own process (START_RUNNER), and
        # the fault knows the file by its identity, so a second name of it (W-r5's hard link) meets it too, and so does the
        # module loader
        self.assertIn("const START_RUNNER = String.raw`", test, "each later start runs in a process of its own")
        runner = test[test.index("const START_RUNNER = String.raw`"):test.index("\n`;\n", test.index("const START_RUNNER = String.raw`"))]
        # review loop 8 RL8-P1, RL8-P2, RL8-P3: the fault fails at the stat, at the open (its stat, lstat and access succeed) or at
        # the read of what the open gave (a descriptor's read and readv, a FileHandle's reads), with a real error's shape (libuv's
        # errno and message for the code, the syscall, the path); the path is read by the real stat in every form node:fs takes
        # (W-t's Uint8Array, W-t2's URL-shaped object); and the start's process moves the clocks the README names (W-u's performance,
        # W-u2's Intl, process.hrtime) while the test ages the data directory's file times (W-u3); the uptime stays (W-u4)
        # review loop 10 RL10-P3: every function of node:fs and node:fs/promises that takes a path is faulted by default, read
        # from the two modules as the running Node has them (W-x's existsSync answers false at the stat and the directory); the
        # table names how the known ones fail and which few are left out
        for line in ("for (const [module, promises] of [[fsp, true], [fs, false]]) {",
                     "  for (const key of Object.keys(module)) {",
                     "    if (NOT_FAULTED.has(name) || DESCRIPTOR.has(name)) continue;",
                     "      if (AT_STAT) answer(module, key, key === 'existsSync');",
                     "    if (AT_READ && name === 'open') { wrap(module, key, form, () => null, opened); continue; }",
                     "const METADATA = { access: 'access', exists: 'access', stat: 'stat', lstat: 'lstat', statfs: 'statfs', readlink: 'readlink',",
                     "const CONTENT = { open: 'open', readFile: 'open', copyFile: 'copyfile', cp: 'copyfile', openAsBlob: 'open' };",
                     "  return AT_READ ? 'read' : name.toLowerCase();",
                     "  fs[key].native = holder.native;",
                     "  keep(original, module[name]);",
                     "    wrap(fs, name, 'callback', args => faultedFd(args[0]) ? 'read' : null);",
                     # review loop 11 RL11-P2: any descriptor of the faulted file, however it was had (W-l5 reads a FileHandle's fd)
                     "  try { const stats = real.fstatSync(fd, { bigint: true }); return stats.ino !== 0n ? stats.dev + ':' + stats.ino : null; } catch { return null; }",
                     "const faultedFd = fd => typeof fd === 'number' && (openFds.has(fd) || (fault !== null && descriptorIdentity(fd) === fault));",
                     "const faultedHandle = handle => handle !== null && typeof handle === 'object' && (openHandles.has(handle) || faultedFd(handle.fd));",
                     "  for (const name of ['read', 'readv', 'readFile', 'readLines', 'createReadStream', 'readableWebStream']) {",
                     "const SYSTEM_ERRORS = getSystemErrorMap();",
                     "  const error = new Error(code + ': ' + text + ', ' + syscall + (path === undefined ? '' : \" '\" + path + \"'\"));",
                     "  return Object.assign(error, { errno, code, syscall }, path === undefined ? {} : { path });",
                     "  if (typeof path === 'number') return null;",
                     "    if (stats.ino !== 0n) return stats.dev + ':' + stats.ino;",
                     "  if (identity(arg) === fault || inside(arg)) return true;",
                     "    if (path !== null && (identity(path) === fault || inside(path))) throw failure(AT_READ ? 'read' : 'open', path);",
                     "  fault = identity(job.file);",
                     "  Object.defineProperty(performance, 'timeOrigin', { get: () => origin, configurable: true });",
                     "  formats.formatToParts = function (date) { return toParts.call(this, date === undefined ? now() : date); };",
                     "  hrtime.bigint = () => bigint() + shiftNs;",
                     "  process.hrtime = hrtime;"):
            self.assertIn(line, runner, line)
        for gone in ("fullPath(", "fault.target", "toLowerCase() : full; };", "namedPath(", "the account file cannot be read", "uptime =",
                     "const FORMS =", "const calls = [[", "const faultedFd = fd => typeof fd === 'number' && openFds.has(fd);"):
            self.assertNotIn(gone, runner, gone)  # no path-string match of the fault, no made-up error, no moved uptime
        for line in ("  const shift = Date.now() - vi.getRealSystemTime();\n  aged(dir, shift);",
                     "    if (!stats.isSymbolicLink()) fs.utimesSync(path, (stats.atimeMs - by) / 1000, (stats.mtimeMs - by) / 1000);"):
            self.assertIn(line, test, line)
        self.assertNotRegex(test, r"(?m)^import (?!type )[^\n]*'\.\./src/", "the subject's modules are imported only after the wrappers")
        subject_load = runner.index("  const subject = await import(subjectUrl);")
        for before in ("  fs[key].native = holder.native;\n}\n", "for (const [module, promises] of [[fsp, true], [fs, false]]) {",
                       "\nsyncBuiltinESMExports();\nif (AT_READ) {",
                       "\nregisterHooks({", "  fault = identity(job.file);", "  process.hrtime = hrtime;\n  syncBuiltinESMExports();"):
            self.assertLess(runner.index(before), subject_load, before)
        # each later start runs in a new process of its own, with an empty environment, so nothing the first session kept reaches it
        # (W-r3 kept the refs in a module variable, W-r4 on globalThis), and only a session loads the subject here: a first session, and
        # (review loop 15) the start-sequence rows' session in which the file reads again
        self.assertIn("interface Started { store: { current(): GitHubAccount | null; openedAppChanged(): boolean }; vault: { has(ref: string): Promise<boolean> } }", test)
        self.assertIn("    const child = spawn(process.execPath, [RUNNER_FILE, pathToFileURL(SUBJECT_FILE).href, jobFile], { env: NO_ENV, ", test)
        self.assertIn("\nconst NO_ENV: Record<string, string> = {};\n", test)
        self.assertIn("async function load() {\n  vi.resetModules();\n", test)
        self.assertEqual(test.count("  const subject = await load();\n"), 2, "only a session loads the subject in the test's process")
        for session in ("async function firstSession() {", "async function sessionCrash(dir: string"):
            body = test[test.index(session):]
            self.assertIn("  const subject = await load();\n", body[:body.index("\n}\n")], session)
        start = test[test.index("async function start(dir: string"):]
        start = start[:start.index("\n}\n")]
        self.assertNotIn("load()", start)
        self.assertIn("    wiring: wiring(), result: join(PROCESSES, `start-${n}.result.json`),", start)
        self.assertNotIn("MODULES", test)
        for gone in ("for (const name of ['lstat', 'stat', 'open', 'readFile'])", "lstatSync', 'statSync', 'openSync', 'readFileSync']",
                     "const run = wiring(subject.modules);"):
            self.assertNotIn(gone, test, gone)
        names = " ".join(md_section(text, "The names the journey test assumes").split())
        self.assertIn("So a fix that re-reads the file another way through `node:fs`, or by another name, still meets the error (W-a "
                      "retries the same read, W-r reads it by a stream, W-r2 through a `promisify(readFile)` taken as its module loads, "
                      "W-r5 through a hard link it makes to the file, W-t with the path as a `Uint8Array` and W-t2 with it as an object "
                      "shaped as a `file:` URL).", names)
        # review loop 8: the README names the phases, the error's shape and the clocks, and the wrong fixes that meet each
        for words in ("The error has a real one's shape: the code, libuv's errno and message for it, the syscall that failed",
                      "W-u2 by `Intl`'s, W-u3 by file times, W-u5 by the store's clock, W-u6 by `Date` reached through a date's constructor, "
                      "W-n for a year), and so does one that counts the age from the boot time (W-u4).",  # review loop 9 RL9-P4
                      "a later start's store is given none, as `index.ts` gives it none, so it reads the store's default, `Date.now`, which is moved.",
                      "W-l4 tells the read by the error's message"):
            self.assertIn(words, names, words)
        self.assertIn("The faulted file is known by its identity (its device and file index, which every name of the file shares), not "
                      "by its path", names)
        self.assertIn("and so does the module loader (an `import` or a `require` of the file).", names)
        self.assertNotIn("and their synchronous forms) for the whole start", names)
        self.assertIn("Each later start runs as the app's next start does, in a new process of its own", names)
        self.assertIn("and a fix that keeps the refs of the last file its process wrote fails (W-r3 keeps them in a module variable, W-r4 "
                      "on `globalThis`).", names)
        for gone in ("Each session and each start loads the subject's modules afresh", "nothing a module keeps outlives"):
            self.assertNotIn(gone, names, gone)
        limits_flat = " ".join(md_section(text, "What the pack does not discriminate").split())
        self.assertIn("**Reads outside `node:fs`.** The fault is on `node:fs` and the module loader in the main thread of the start's own "
                      "process.", limits_flat)
        # review loop 11 RL11-P4: any API outside the faulted layer that reads the file, process.loadEnvFile among them
        self.assertIn("Any API outside that layer that reads the file is not failed:", limits_flat)
        self.assertIn("(`process.loadEnvFile` reads it at every point, say)", limits_flat)
        # review loop 11 RL11-P2: a descriptor is known by the file it is open on, so a FileHandle's fd meets the fault (W-l5)
        for words in ("every read through a descriptor of the file fails, however the descriptor was had",
                      "A descriptor or a FileHandle names no path: it is known by the identity of the file it is open on, through "
                      "the real `fstat`, so a read through a FileHandle's `fd` meets the error too (W-l5 reads the file again that way).",
                      # review loop 11 RL11-P1, RL11-P3
                      "W-b6 skips the reconcile on EIO", "So a fix that drops the keep only in some of those states fails (W-b7 drops it "
                      "beside a tombstoned entry).",
                      # review loop 12 RL12-P1, RL12-P2
                      "So a fix that drops the keep for some code at some point fails (W-y drops it when the directory fails with any "
                      "code but EACCES, taken for a lost volume).",
                      "The engine-key row has the engine store a key during an unreadable session, as an engine that runs does:",
                      "The two keep-at-each-point rows run each of the seven codes at the stat, the open, the read and the directory",
                      # review loop 13 RL13-P1, RL13-P2
                      "The orphan-codes row runs each of the seven codes at the stat, the open, the read and the directory, at two "
                      "unreadable starts in a row",
                      "W-j4 holds it when the directory fails, with any code, taken for another instance mid-replace in a locked directory",
                      "So does one that drops it at the second of two such starts (W-p3",
                      "so a fix that keeps only the staged entries at least as new as the newest committed one fails (W-z)",
                      # review loop 14 RL14-P1, RL14-P2
                      "beside an orphan pair a second one is staged during the first unreadable start's session",
                      "So does one that keeps only the newest two staged entries nothing names, as if only one replace were ever in "
                      "flight (W-k2).",
                      "The two point-pair rows run seventeen unreadable starts in a row on one data directory, a year apart, whose "
                      "points run through every ordered pair of the stat, the open, the read and the directory",
                      "So a fix keyed on the point the start before failed at fails (W-p4 drops the pair when the directory fails "
                      "right after a start that failed at the file, taken for a swapped volume; W-j6 holds an orphan pair for good "
                      "then, taken for another instance that took the directory over).",
                      # review loop 15 RL15-P1: the start-sequence rows (W-C1)
                      "The two start-sequence rows (review loop 15) do not write their shapes row by row: they generate them.",
                      "in a de Bruijn order of five events that holds every ordered run of three of them once",
                      "three sessions in which the file reads again (a new store on the data directory, whose open() reads the file)",
                      "(W-C1 marks the staged entries an unreadable start keeps and, at a later unreadable start that finds marked "
                      "ones, keeps only those: a pair a session staged and wrote to the file since then is deleted"):
            self.assertIn(words, names, words)
        for gone in ("every read of what the open gave fails", "which only an open can give"):
            self.assertNotIn(gone, names, gone)
        # review loop 10 RL10-P3, RL10-P4: the functions the fault leaves out, and the clocks it does not move (W-u7)
        for words in ("**Functions the fault leaves out.**", "`watchFile` and `unwatchFile` are not failed",
                      "nor any other clock the start's process reads beyond the ones the journey names: the diagnostic report's "
                      "timestamps (`process.report`), a worker thread's `Date` and the like. So a fix that ages the pair by one of "
                      "them passes (W-u7", "The pack moves the clocks it names, not every clock a process can read."):
            self.assertIn(words, limits_flat, words)
        for words in ("The functions are read from the two modules as the running Node has them, not from a list of names",
                      "`exists` and `existsSync` answer false, as a real one does when the stat fails",
                      "(W-x keeps only while `existsSync` sees the file)", "runs with these clocks moved as much: `Date`,",
                      "(W-j3 holds an orphan pair for good only beside no committed entry, W-b5 spares tombstoned entries only "
                      "beside a committed one)"):
            self.assertIn(words, names, words)
        self.assertNotIn("every clock it reads", names)
        self.assertIn("**Paths beside the subject's own module.**", limits_flat)
        # review loop 2 RL2-P1: the unreadable-run row and the orphan row run four unreadable starts in a row (the same code twice
        # among them), each ten years after the one before, so neither a keep limited to a number of such starts (W-p) nor a
        # hold earned by a run of them (W-q) passes, up to four
        self.assertEqual(test.count("for (const [index, code] of ['EACCES', 'EACCES', 'EBUSY', 'EIO'].entries())"), 2)
        # (review loop 8: the journey rows and the other-errno row run three later starts each the same way; review loop 9 RL9-P1..P3:
        # the lasting row, the engine row and the orphan-codes row too, and the lasting row's readable start comes ten years after its fourth)
        # (review loop 10 RL10-P1, RL10-P2: the vault-state rows too, their readable start ten years after their third; review loop
        # 11 RL11-P3: and the keep-side vault-state rows; review loop 12 RL12-P2: and the engine-key row; review loop 13 RL13-P1,
        # RL13-P2: and the orphan-codes row and the keep-at-each-point rows, two unreadable starts per code and point, their readable
        # start ten years after the second)
        self.assertEqual((test.count("vi.useRealTimers(); later(3650 * (index + 1));"), test.count("vi.useRealTimers(); later(3650 * 5);")), (11, 3))
        self.assertEqual(test.count("vi.useRealTimers(); later(3650 * 4);"), 4)   # two before review loop 10, one in each kind of vault-state row, one in the engine-key row, less the orphan-codes row's
        self.assertEqual(test.count("vi.useRealTimers(); later(3650 * 3);"), 2)   # review loop 13: the orphan-codes row's and the keep-at-each-point rows'
        self.assertNotIn("later(3650 * 1);", test)   # review loop 12's one unreadable start per code and point is gone
        self.assertEqual(test.count("{ unread: code, at: PHASES[index % 3] }"), 2, "the unreadable-run and orphan rows' starts fail at each phase in turn")
        self.assertIn("test('first sign-in before commit 1 and refresh before commit 4, then EACCES, EACCES again, EBUSY and EIO at four "
                      "starts in a row, ten years apart, at the stat, the open and the read in turn: the pair survives all four and is "
                      "live and committed after the next'", test)
        self.assertIn("test('a crash after staging, before the file write: after four starts in a row that cannot read the file, the next "
                      "readable start deletes the orphan pair'", test)
        self.assertNotIn("later(30)", test)
        # review loop 9 RL9-P1..P3: the lasting row (the same failure at four starts in a row, W-p2), the engine row (a staged entry the
        # engine names beside the kept pair, W-b4), the tombstone at the open and the read (W-b3) and an orphan pair beside each of the
        # seven codes at each point (W-j2); RL9-P5: the 'dir' phase fails every path in the account file's directory (W-s); RL9-P4: a
        # later start's store gets the app's default clock (W-u5) and a date's constructor is the moved Date (W-u6)
        for title in ("test('first sign-in before commit 1, sign-in before commit 3 and refresh before commit 4, then the same failure at four starts in a row",
                      "test('first sign-in before commit 1 and refresh before commit 4, each beside a staged entry the engine names",
                      # review loop 11 RL11-P1: the tombstone at every code and every point, each start on a fresh copy (W-b6)
                      "test('a sign-out whose removals failed and a refresh whose removals failed, each beside a staged entry the engine "
                      "names, then EACCES, EBUSY, EIO, EPERM, EMFILE, EINVAL or UNKNOWN at the stat, the open, the read or the directory, "
                      "each start on a fresh copy",
                      # review loop 13 RL13-P1: the orphan pair at every code and every point, the directory included (W-j4)
                      "test('a crash after staging, before the file write, then two starts in a row that cannot read the file with one "
                      "code at one point (EACCES, EBUSY, EIO, EPERM, EMFILE, EINVAL or UNKNOWN; at the stat, the open, the read or the "
                      "directory), each code and point on a fresh copy of the crash",
                      # review loop 10 RL10-P1, RL10-P2: what an unreadable start deletes, built in every vault state (W-j3, W-b5)
                      "test('beside no committed entry (signed out): a tombstoned pair, an orphan pair or both, with or without a staged entry the engine names",
                      "test('beside the old committed pair (signed in): a tombstoned pair, an orphan pair or both, with or without a staged entry the engine names",
                      # review loop 11 RL11-P3: what an unreadable start must keep, built in every vault state (W-b7)
                      "test('a pair to keep beside no committed entry (a sign-in after a sign-out, crashed before its first commit): with or "
                      "without a tombstoned pair, a staged entry the engine names and an orphan pair",
                      "test('a pair to keep beside the old committed pair (a refresh, crashed before its first commit): with or without a "
                      "tombstoned pair, a staged entry the engine names and an orphan pair",
                      # review loop 12 RL12-P1: the pair to keep at every code and every point, the directory included (W-y); review
                      # loop 13 RL13-P2: at two starts in a row (W-p3), in two rows
                      "test('the pair to keep at every code and every point, after a sign-in: first sign-in before commit 1 and sign-in "
                      "before commit 3, then EACCES, EBUSY, EIO, EPERM, EMFILE, EINVAL or UNKNOWN at the stat, the open, the read or the "
                      "directory at two starts in a row, ten years apart, each on a fresh copy of the crash",
                      "test('the pair to keep at every code and every point, after a refresh: refresh before commit 3 and refresh before "
                      "commit 4, then EACCES, EBUSY, EIO, EPERM, EMFILE, EINVAL or UNKNOWN at the stat, the open, the read or the "
                      "directory at two starts in a row, ten years apart, each on a fresh copy of the crash",
                      # review loop 14 RL14-P1: an orphan pair staged after the pair to keep too (W-k2)
                      "and an orphan pair (and a second orphan pair staged during the first unreadable start\\'s session), then EACCES, "
                      "EBUSY and EIO at three starts in a row",
                      # review loop 14 RL14-P2: every ordered pair of points at two starts in a row (W-p4, W-j6)
                      "test('first sign-in before commit 1 and refresh before commit 4, then seventeen unreadable starts in a row, a year "
                      "apart, whose points run through every ordered pair of the stat, the open, the read and the directory, the code "
                      "moving on through EACCES, EBUSY, EIO, EPERM, EMFILE, EINVAL and UNKNOWN: the pair survives all seventeen and is "
                      "live and committed after the next'",
                      "test('a crash after staging, before the file write, beside a committed account, then seventeen unreadable starts "
                      "in a row, a year apart, whose points run through every ordered pair of the stat, the open, the read and the "
                      "directory, the code moving on through EACCES, EBUSY, EIO, EPERM, EMFILE, EINVAL and UNKNOWN: each keeps the "
                      "account, and the next readable start deletes the orphan pair'",
                      # review loop 15 RL15-P1: the start-sequence rows, every run of three events (W-C1)
                      "describe('X2-1: the shapes of a sequence of starts, every run of three events', ROW, () => {",
                      "test('first sign-in before commit 1, then 127 events a year apart in a de Bruijn order holding every run of three "
                      "of an unreadable start, a readable start, a sign-in crashed before its first commit, a refresh crashed before "
                      "its second and a sign-in crashed after staging (the file read again in each session), the codes and points "
                      "moving on: after each unreadable start the pair the file names is kept, after each readable start it is live "
                      "and committed, nothing else left'",
                      "test('refresh before commit 4, then 127 events a year apart in a de Bruijn order holding every run of three",
                      # review loop 12 RL12-P2: the engine stores a key during an unreadable session, committed by the next start (W-z)
                      "test('first sign-in before commit 1 and refresh before commit 4, the engine storing a key during the first of three "
                      "unreadable starts, ten years apart (EACCES at the stat, EBUSY at the open, EIO at the read), which the next two commit"):
            self.assertIn(title, test, title)
        self.assertNotIn("then EBUSY at the open or at the read (another process holds the file", test)
        for form in ("const vaultStates = (committed: boolean): VaultState[] => [false, true].flatMap(engine =>",
                     "  [[true, false], [false, true], [true, true]].map(([tombstoned, orphan]) => ({ committed, tombstoned: tombstoned!, engine, orphan: orphan! })));",
                     "        const phase = PHASES[(n + index) % 3]!; const code = UNREAD_CODES[index]!;",
                     "const UNREAD_CODES = ['EACCES', 'EBUSY', 'EIO'];",
                     "    deletesInEveryState(false));", "    deletesInEveryState(true));",
                     # review loop 11 RL11-P1, RL11-P3
                     "      for (const code of ['EACCES', 'EBUSY', 'EIO', 'EPERM', 'EMFILE', 'EINVAL', 'UNKNOWN']) for (const phase of [...PHASES, 'dir'] as Phase[]) {",
                     "        cpSync(crash, dir, { recursive: true });\n        const unread = await start(dir, { unread: code, at: phase, engine: [engineRef] });",
                     "const keepStates = (committed: boolean): VaultState[] => [false, true].flatMap(engine => [false, true].flatMap(tombstoned =>",
                     "  session.hooks.beforeCommit = () => { dir ??= session.snapshot(); };",
                     "        expect(pair.map(ref => entries(dir)[ref]?.state), step).toEqual(['staged', 'staged']);",
                     "      await expectAlone(dir, await start(dir, { engine }), pair, engine);",
                     "    keepsInEveryState(false));", "    keepsInEveryState(true));",
                     # review loop 12 RL12-P1, RL12-P2
                     "      for (const code of ['EACCES', 'EBUSY', 'EIO', 'EPERM', 'EMFILE', 'EINVAL', 'UNKNOWN']) for (const phase of [...PHASES, 'dir'] as Phase[]) {\n"
                     "        const dir = `${crash}-${code}-${phase}`;\n        cpSync(crash, dir, { recursive: true });\n"
                     "        for (const index of [0, 1]) {                                          // the same failure twice, ten years apart\n"
                     "          const step = `${kind}, crash before commit ${at}, ${code} at the ${phase}, start ${index + 1}`;",
                     "          const unread = await start(dir, { unread: code, at: phase });\n          expect(unread.store.current(), step).toBeNull();",
                     # review loop 13 RL13-P1, RL13-P2
                     "      const dir = `${crash!}-${code}-${phase}`;\n      cpSync(crash!, dir, { recursive: true });\n      const step = `${code} at the ${phase}`;\n"
                     "      for (const index of [0, 1]) {                                            // the same failure twice, ten years apart",
                     "        expect((await start(dir, { unread: code, at: phase })).store.current(), step).toBeNull();",
                     "function keepsAtEachPoint(crashes: Array<[Kind, number, string[]]>) {",
                     "    keepsAtEachPoint([['first sign-in', 1, ['staged', 'staged']], ['sign-in', 3, ['staged', 'staged']]]));",
                     "    keepsAtEachPoint([['refresh', 3, ['staged', 'staged']], ['refresh', 4, ['committed', 'staged']]]));",
                     "          const vault = new (await load()).Vault(join(dir, 'vault'), cryptor); await vault.initialize('epoch-2');",
                     "          engine = [await vault.saveStaged(`x2-engine-${randomBytes(16).toString('hex')}`)];",
                     "        } else expect(engine.map(ref => entries(dir)[ref]?.state), step).toEqual(['committed']);",
                     # review loop 14 RL14-P1, RL14-P2
                     "        if (index === 0 && state.orphan) {",
                     "          const late = [await vault.saveStaged(`x2-orphan-${randomBytes(16).toString('hex')}`), await vault.saveStaged(`x2-orphan-${randomBytes(16).toString('hex')}`)];",
                     "const POINT_ORDER: Phase[] = ['stat', 'stat', 'open', 'stat', 'read', 'stat', 'dir', 'open', 'open', 'read', 'open', 'dir', 'read', 'read', 'dir', 'dir', 'stat'];",
                     "  expect(new Set(POINT_ORDER.slice(1).map((phase, index) => `${POINT_ORDER[index]} then ${phase}`)).size).toBe(16);",
                     "    const code = EVERY_CODE[index % EVERY_CODE.length]!;",
                     "    vi.useRealTimers(); later(365 * (index + 1));\n    expect((await start(dir, { unread: code, at: phase })).store.current(), step).toBeNull();",
                     # review loop 15 RL15-P1: the generated order and its sessions
                     "const SEQUENCE = deBruijn(EVENTS, 3);",
                     "    expect(SEQUENCE).toHaveLength(127);",
                     "    expect(new Set(SEQUENCE.slice(2).map((_, index) => SEQUENCE.slice(index, index + 3).join(' then '))).size).toBe(125);",
                     "  await store.open();\n  const live = store.current();",
                     "        const code = EVERY_CODE[unreadable % EVERY_CODE.length]!; const phase = EVERY_POINT[unreadable % EVERY_POINT.length]!; unreadable++;",
                     "        expect(pair.map(ref => entries(dir)[ref]?.state), where).toEqual(held);",
                     "        await expectAlone(dir, await start(dir), pair);",
                     "    startSequence('first sign-in', 1, ['staged', 'staged']));",
                     "    startSequence('refresh', 4, ['committed', 'staged']));"):
            self.assertIn(form, test, form)
        for form in ("['first sign-in', 1, ['staged', 'staged'], 'EACCES', 'dir'],", "if (PHASE === 'dir') faultDir = identity(dirname(job.file));",
                     # the orphan-codes row's loop: every code at every point since review loop 13 RL13-P1
                     "    for (const code of ['EACCES', 'EBUSY', 'EIO', 'EPERM', 'EMFILE', 'EINVAL', 'UNKNOWN']) for (const phase of [...PHASES, 'dir'] as Phase[]) {\n"
                     "      const dir = `${crash!}-${code}-${phase}`;",
                     "const store = new subject.store.GitHubAccountStore(job.file, vault, job.clientId);",
                     "Object.defineProperty(RealDate.prototype, 'constructor', { value: MovedDate, writable: true, configurable: true, enumerable: false });"):
            self.assertIn(form, test, form)
        # re-review 1 R1, R4: a readable start after a sign-out deletes a crashed sign-in's orphan pair, and the startup lines
        # are anchored on code lines (the engine call and the supervisor call), never on a comment that mentions them
        self.assertIn("test('a sign-out, then a sign-in that crashed after staging, before the file write: the next readable start deletes", test)
        # review loop 1 RL1-1: a file that is read and refused (spec 4.4: invalid, oversized, extra key) reads as no account, so
        # the start deletes the orphan pair beside it; the row writes each of the three refusals, and the pin has X21_PIN_ROWS rows
        self.assertIn("test('a sign-out, a sign-in that crashed after staging, then a refused file (invalid JSON, over 64 KiB, an extra key, "
                      "version 2): the start deletes the orphan pair and rewrites the file (a refused file is read)'", test)
        for form in ("['invalid JSON', valid.slice(0, valid.lastIndexOf('}'))]", "['over 64 KiB', valid + ' '.repeat(64 * 1024)]",
                     "['an extra key', JSON.stringify({ ...signedOut, extra: true })]", "['version 2', JSON.stringify({ ...signedOut, version: 2 })]"):
            self.assertIn(form, test, form)
        # review loop 2 RL2-1: a refused file that still names the staged pair reads as no account all the same (W-o3 keeps on
        # it); the named refused-file row refuses that file in the same four ways, and both rows refuse a version 2 (W-o4)
        # review loop 3 RL3-1: the named refused-file row refuses the file beside a committed account too (after a sign-in's or a
        # refresh's crash), so a keep that holds while the vault has a committed entry beside a refused file fails (W-o5)
        self.assertIn("test('a first sign-in that crashed before commit 1, a sign-in or a refresh before commit 3 and a refresh before commit "
                      "4, then the file naming the new pair is refused (invalid JSON, over 64 KiB, an extra key, version 2): the start "
                      "deletes the staged entries and rewrites the file (a refused file names no reference, beside a committed account too)'", test)
        named_row = test[test.index("the file naming the new pair is refused"):]
        named_row = named_row[:named_row.index("\n  test('")]
        for form in ("['first sign-in', 1, ['staged', 'staged']]", "['sign-in', 3, ['staged', 'staged']]",
                     "['refresh', 3, ['staged', 'staged']]", "['refresh', 4, ['committed', 'staged']]",
                     "const { dir: crash, pair, old } = await crashBeforeCommit(kind, at);"):
            self.assertIn(form, named_row, form)
        # review loop 3 RL3-2: the ENOENT row removes the file beside a committed account too (W-h3 keeps there)
        self.assertIn("test('a first sign-in that crashed after staging, before any file existed, and a sign-in that crashed after staging "
                      "or a refresh before commit 3 beside a committed account, its file then lost: a start deletes the staged entries "
                      "(a missing file is no account)'", test)
        self.assertIn("const lost: Array<[string, string]> = [['a sign-in after staging', orphan!], ['a refresh before commit 3', "
                      "(await crashBeforeCommit('refresh', 3)).dir]];", test)
        self.assertIn("fs.rmSync(fileAt(crash));", test)
        for form in ("['an extra key', JSON.stringify({ ...named, extra: true })]", "['version 2', JSON.stringify({ ...named, version: 2 })]"):
            self.assertIn(form, test, form)
        self.assertEqual(test.count("['invalid JSON', valid.slice(0, valid.lastIndexOf('}'))]"), 2)
        self.assertEqual(test.count("['over 64 KiB', valid + ' '.repeat(64 * 1024)]"), 2)
        self.assertEqual(test.count("\n    test(`${kind}, crash before commit ${at}, ${code} at the next three starts (at the stat, the open, then the read):"), 1)
        self.assertEqual(test.count("\n  test('"), X21_PIN_ROWS - 12, "12 journey rows from the loop, the rest one test each")
        journey_md = " ".join(md_section(text, "The journey").split())
        # review loop 2 RL2-1: whatever account a refused file names
        self.assertIn("A file that is read and refused (invalid JSON, over 64 KiB, a key the format does not have, or a value it does not "
                      "allow, such as version 2) reads as no account too, whatever account it names and whatever the vault holds beside "
                      "it: the start deletes the unreferenced staged entries beside it, the pair that file names among them, and "
                      "rewrites the file.", journey_md)
        # review loop 3 RL3-2: a missing file beside a committed account reads as no account all the same
        self.assertIn("A missing file reads as no account, beside a committed account too, and the start deletes its staged "
                      "entries.", journey_md)
        # review loop 2 RL2-P2: the paragraph lists four things that stay as they are, and says so
        self.assertIn("Four things stay as they are.", journey_md)
        self.assertNotIn("Three things", journey_md)
        self.assertIn("however many starts of step 2 came first", journey_md)
        # re-review 2 RR2-1, integration 3 IC-2: the startup statements are found in index.ts parsed by TypeScript, so no comment,
        # string, regex literal, line break or missing ';' moves them; the slice runs from the end of the statement that holds the
        # engine call (or of a later one that declares references) to the start of the statement that calls supervisor.attach()
        self.assertIn("import ts from 'typescript';", test)
        self.assertIn("const file = ts.createSourceFile('index.ts', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);", test)
        self.assertIn("const to = call < 0 ? -1 : statements.findIndex((s, index) => index > call && find(s, isAttach) !== undefined);", test)
        self.assertIn("const from = call >= 0 && !declaresReferences(statements[call]!) && declared >= 0 ? declared : call;", test)
        self.assertIn("const body = source.slice(statements[from]!.end, statements[to]!.getStart(file));", test)
        self.assertIn("const extra = imported(file);", test)
        for gone in ("codeOnly", "codeLines", "isCode", "matchAll"):  # no text matching of index.ts is left
            self.assertNotIn(gone, test)
        limits = md_section(text, "What the pack does not discriminate")
        for word in ("./github-account-store", "./vault", "ReferenceError", "`method: 'vault.references'`", "one block"):
            self.assertIn(word, limits, word)
        self.assertNotIn("regex literal", limits, "the parser reads regex literals: that limit is gone")
        self.assertIn("**Runs of more than seventeen unreadable starts.**", limits)  # review loop 2 RL2-P1: the limit that is left (review loop 14: seventeen)
        # review loop 14 RL14-P1, RL14-P2: what the round-14 rows leave; review loop 15 RL15-P1: what the generator does not reach
        for words in ("so a fix that keeps only the newest four or more staged entries nothing names passes",
                      "not every pair of codes, and no ordered triple of points",
                      "**Sequences of starts beyond runs of three.**",
                      "runs of four or more only as their one order happens to hold them (124 of the 625 runs of four)",
                      "each session is a new store that reads the file, never the unreadable start's own store going on",
                      "a session runs in the test's process, so what an earlier session kept there",
                      "no session puts an engine entry or a tombstone in the vault",
                      "the pair kept at an unreadable start there at most seven years old",
                      "passed every row until review loop 15; both start-sequence rows catch it, and it is in `WRONG-FIXES.md`."):
            self.assertIn(words, " ".join(limits.split()), words)
        # review loop 9 RL9-P3..P5: the limits the round-9 rows leave, and W-v, which no row catches
        for words in ("**Forms of the rows that guard what an unreadable start still deletes and keeps.**", "**The directory beyond its reads.**",
                      "`Date` value the vault stored at the crash (`createdAt`) passes (W-v)"):
            self.assertIn(words, " ".join(limits.split()), words)
        # review loop 9: the class of wrong fixes the pack is and is not expected to catch, with no claim that the list is complete
        catch = " ".join(md_section(text, "What the pack is and is not expected to catch").split())
        self.assertIn("The journey test is a sample of the journey, not a proof that a fix is right.", catch)
        # review loop 11: wrong fixes keep being found round after round; the pack is a sample, not a proof
        self.assertIn("Review has found new wrong fixes that pass the journey test round after round", catch)
        self.assertIn("fourteen of the fifteen review rounds of calibration run 4 so far found at least one", catch)   # review loop 15
        self.assertIn("the fifteenth one: W-C1, caught once the two start-sequence rows were added for it", catch)
        self.assertIn("the order of the starts and sessions before it (every run of three of the start-sequence rows' five events)", catch)
        self.assertIn("The pack is a sample of wrong fixes and of the journey's states, not a proof", catch)
        self.assertIn("are each built in every combination of the vault states the rows build beside an unreadable file (the "
                      "vault-state rows and the keep-side vault-state rows)", catch)
        self.assertIn("it is not a claim that it is complete, and a wrong fix keyed on an input it does not name may pass.", catch)
        # review loop 5 RL5-P1: the codes the rows use, and that a list holding all seven passes
        self.assertIn("**Errno codes the rows do not use.** The rows fail the reads with EACCES, EBUSY, EIO, EPERM, EMFILE, EINVAL and "
                      "UNKNOWN. The rule is the same for every errno code but ENOENT, but a fix that keeps only on a list of codes passes "
                      "when its list holds all seven", " ".join(limits.split()))
        self.assertNotIn("Errors other than EACCES, EBUSY and EIO", limits)
        # review loop 2 RL2-1: the four refusals, on a file that names no account and on one that names the pair, and what is left
        # review loop 3 RL3-1, RL3-2: the vault states beside a refused or missing file, and what is left
        self.assertIn("**Vault states beside a refused or missing file.**", limits)
        for words in ("**Refusals other than the four.**", "on the signed-out file and on a file that names the new pair",
                      "Other values the format does not allow"):
            self.assertIn(words, " ".join(limits.split()), words)
        self.assertNotIn("Refusals other than the three", limits)
        # integration 4 (D-IC3-1): the README states that both trees leave docs/orchestration/ out, and the check's limit
        why = " ".join(md_section(text, "Why there is no pin and no review case").split())
        for words in ("**MoonAliza's orchestration records are left out of both trees.**", "without the whole directory",
                      "only the objects the two filtered trees reach", "a paraphrase of the cause elsewhere in the tree is not caught"):
            self.assertIn(words, why, words)
        self.assertIn("without its `docs/orchestration/` directory", " ".join(build.split()))

    def test_wrong_fixes_lists_every_wrong_fix_the_tests_grade(self):
        rows = x21_wrong_rows()
        self.assertEqual(sorted(rows), sorted(X21_WRONG))
        for wid, (idea, row, grade_) in rows.items():
            self.assertTrue(idea and row, wid)
            self.assertTrue(grade_.startswith("FAIL"), f"{wid}: {grade_}")
            # review loop 1 RL1-1: every grade counts out of the pin's rows as they are now
            self.assertRegex(grade_, rf"^FAIL: acceptedPin \d+ of {X21_PIN_ROWS} red; candidate green, guard red, scope and lint ok$", wid)
        text = (X21 / "WRONG-FIXES.md").read_text(encoding="utf-8")
        self.assertIn(f"counts the accepted journey test's failed rows out of its {X21_PIN_ROWS}.", " ".join(text.split()))
        self.assertIn("the **refused-file row**", text)
        self.assertIn("the **unreadable-run row**", text)
        self.assertIn("the **named refused-file row**", text)  # review loop 2 RL2-1
        self.assertIn("the **other-errno row** (the same four crash points, each with EPERM, EMFILE, EINVAL and UNKNOWN at the next "
                      "three starts, as in the journey rows, then a readable start)", " ".join(text.split()))  # review loop 5 RL5-P1, 8 RL8-P1
        self.assertIn("each with EACCES, with EBUSY and with EIO at the next three starts, the first ten years after the crash and each "
                      "ten years after the one before, failing at the stat, at the open and at the read", " ".join(text.split()))
        # review loop 3 RL3-1, RL3-2: both rows run beside a committed account too
        flat = " ".join(text.split())
        self.assertIn("the **named refused-file row** (a crash after the file named the new pair: a first sign-in's before commit 1 "
                      "and, beside the old committed pair, a sign-in's or a refresh's before commit 3 and a refresh's before "
                      "commit 4; then that file replaced by one the store reads and refuses in the same four ways", flat)
        self.assertIn("the **ENOENT row** (a first sign-in that crashed before any file existed, and a sign-in that crashed after "
                      "staging and a refresh that crashed before commit 3, each with its file then removed beside the committed account)", flat)
        for letter in "abcdefgh":  # the lead's list (H1), each by its letter
            self.assertRegex(text, rf"\| W-{letter}\d? \|", letter)

    def test_without_the_clone_the_subject_tests_report_unsupported(self):
        for name in ("test_make_repo_builds_the_manifest_ids", "test_the_accepted_journey_test_is_red_at_base_and_green_at_accepted",
                     "test_every_wrong_fix_grades_fail_on_the_accepted_journey_test_alone", "test_the_accepted_and_two_alternative_fixes_grade_pass",
                     "test_the_launch_refusals_hold_with_this_manifest_and_a_fix_only_protocol", "test_make_repo_removes_its_target_when_the_ids_differ",
                     "test_the_accepted_fix_reshaped_in_index_ts_stays_green",
                     "test_a_grade_and_run_one_write_nothing_into_the_node_modules_a_checkout_links",
                     "test_base0_names_neither_the_finding_nor_its_fix_nor_its_cause",
                     "test_no_checkout_links_an_install_in_a_moonaliza_clone_or_checkout"):
            method = getattr(type(self), name)
            if x21_clone():
                self.assertFalse(getattr(method, "__unittest_skip__", False), name)
            else:  # a skip with the UNSUPPORTED reason, never a pass
                self.assertTrue(getattr(method, "__unittest_skip__", False), name)
                self.assertEqual(method.__unittest_skip_why__, X21_UNSUPPORTED, name)

    # ---- with the clone --------------------------------------------------------------------------------------------
    @classmethod
    def setUpClass(cls):
        cls.built = None
        if not x21_clone():
            return
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.env = git_env(cls.root)
        cls.env["MSYS"] = "winsymlinks:nativestrict"  # Git Bash makes a real symlink for --link, or fails, never a copy
        cls.pack = cls.root / "pack"
        shutil.copytree(X21, cls.pack)
        cls.built = subprocess.run(["bash", str(cls.pack / "make-repo.sh"), str(x21_clone()), str(cls.pack / "repo")],
                                   env=cls.env, capture_output=True, text=True, timeout=600)
        cls.ids = dict(line.split() for line in cls.built.stdout.splitlines() if len(line.split()) == 2)
        cls.modules = (x21_install(x21_clone(), cls.pack / "repo", cls.root / "install", cls.env)  # integration 5 (IC4-1): the README's step 2
                       if cls.built.returncode == 0 else None)
        cls.n = 0
        cls.seal = cls.seal_of(cls.modules) if cls.modules else None  # review loop 8 RL8-K2: the README's step 3, before any candidate
        # integration 3 (F5): the clone is read only; every test of this class together leaves it as it was
        cls.clone_before = x21_clone_state(x21_clone(), cls.env)

    @classmethod
    def tearDownClass(cls):
        if not getattr(cls, "tmp", None):
            return
        try:
            after = x21_clone_state(x21_clone(), cls.env)
            if after != cls.clone_before:
                status, vite, tree = after
                changed = sorted(k for k in set(tree) | set(cls.clone_before[2]) if tree.get(k) != cls.clone_before[2].get(k))
                raise AssertionError(f"F5: this class changed the MoonAliza clone: status {status!r}, node_modules/.vite* {vite}, entries {changed[:20]}")
            left = sorted(p.name for p in cls.modules.glob(".vite*")) if cls.modules else []
            if left:
                raise AssertionError(f"F5: a run wrote {left} into the node_modules the checkouts link")
        finally:
            cls.tmp.cleanup()

    def at(self, name: str, modules: Path | None = None) -> Path:
        """A fresh history-less checkout of the pack commit <name>0, outside the pack, node_modules linked."""
        self.assertEqual(self.built.returncode, 0, self.built.stdout + self.built.stderr)
        type(self).n += 1
        target = self.root / "checkouts" / f"{name}-{self.n}"
        # a MoonAliza tree takes over a minute to check out on the lead's host, more while grades run beside it
        p = checkout(self.pack / "repo", self.ids[f"{name}0"], target, self.env, "--pack", str(self.pack),
                     "--link", f"node_modules={modules or self.modules}", timeout=900)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        # integration 5 (IC4-1): node_modules/.. of every checkout, made the README's way, reaches no history and no records
        self.assertEqual(x21_reaches_no_records(target), [], "a checkout's node_modules/.. reaches a .git or docs/orchestration/")
        return target

    @classmethod
    def seal_of(cls, modules: Path) -> Path:
        """Review loop 8 RL8-K2: the host's seal of the trees a checkout links (the README's step 3), made right after the
        install and before any candidate runs, kept outside the pack and every checkout: node_modules, and for .build, which
        this host does not have, an empty directory, so a candidate that puts a tree at that name is caught."""
        empty = cls.root / "no-build"
        empty.mkdir(exist_ok=True)
        cls.n += 1
        seal = cls.root / f"seal-{cls.n}.json"
        p = subprocess.run(["bash", str(KIT / "grade.sh"), "--seal", f"node_modules={modules}", f".build={empty}"], env=cls.env,
                           capture_output=True, text=True, timeout=3600)
        if p.returncode != 0:
            raise AssertionError(f"grade.sh --seal failed: {p.stdout}{p.stderr}")
        seal.write_text(p.stdout, encoding="utf-8")
        return seal

    def grade_run(self, cand: Path, seal: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(KIT / "grade.sh"), "--links", str(seal or self.seal), str(self.pack / "manifest.json"), "fix",
                               str(cand)], env=self.env, capture_output=True, text=True, timeout=3600)

    def grade_fix(self, cand: Path, seal: Path | None = None) -> dict:
        p = self.grade_run(cand, seal)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads(p.stdout)

    def vitest(self, cand: Path, *files: str) -> dict:
        """The manifest's own test command (F5: the one that writes nothing into node_modules), run on files of a checkout."""
        report = cand.parent / f"{cand.name}-report.json"
        cmd = x21_manifest()["commands"]["test"].replace("{files}", " ".join(shlex.quote(f) for f in files)).replace("{report}", shlex.quote(report.as_posix()))
        subprocess.run(["bash", "-c", cmd + " >/dev/null 2>&1"], cwd=cand, env=self.env, timeout=900)
        return json.loads(report.read_text(encoding="utf-8"))

    @NEEDS_X21
    def test_make_repo_builds_the_manifest_ids(self):
        self.assertEqual(self.built.returncode, 0, self.built.stdout + self.built.stderr)
        m = x21_manifest()
        self.assertEqual(self.ids, {"base0": m["cases"]["fix"]["base"], "accepted0": m["accepted_fix"]})
        self.assertIn("the ids equal manifest.json's", self.built.stderr)
        g = lambda *a: sh(["git", *a], self.pack / "repo", self.env).stdout.strip()
        for tag in ("base0", "accepted0"):
            self.assertEqual(g("rev-list", "--count", tag), "1", f"{tag} is a root commit")
        # integration 4 (D-IC3-1): base0 is MoonAliza 16f637f's tree minus docs/orchestration/, and accepted0 is 01a8604's tree
        # minus docs/orchestration/ plus the journey test: every other file is there, with its mode and its blob
        self.assertIn("make-repo: base0..accepted0 is 16f637f..01a8604 outside docs/orchestration/", self.built.stderr)
        repo, forbidden, reached = self.pack / "repo", set(), set()
        for tag, rev in (("base0", X21_BASE_SRC), ("accepted0", X21_ACCEPTED_SRC)):
            full = x21_ls_tree(x21_clone(), rev, self.env)
            want = {p: e for p, e in full.items() if not p.startswith(X21_EXCLUDED)}
            self.assertGreater(len(full) - len(want), 100, f"MoonAliza {rev} has its docs/orchestration/ records")
            have = x21_ls_tree(repo, tag, self.env)
            if tag == "accepted0":
                self.assertEqual(have.pop("tests/zz_accepted_x2_1.test.ts")[0], "100644")
            self.assertEqual(have, want, f"{tag} is MoonAliza {rev}'s tree minus docs/orchestration/")
            reached |= {line.split()[2] for line in g("ls-tree", "-r", "-t", tag).splitlines()}
            listing = sh(["git", "ls-tree", "-r", "-t", rev, "--", "docs/orchestration"], x21_clone(), self.env).stdout.split("\n")
            forbidden |= {line.split()[2] for line in listing if line} | {sh(["git", "rev-parse", f"{rev}^{{tree}}", f"{rev}:docs"], x21_clone(), self.env).stdout.split()[i] for i in (0, 1)}
        # only what the filtered trees reach is copied: no blob, tree or the old root and docs trees of the excluded records is
        # in the pack repository, and every blob in it is a file of base0 or accepted0
        objects = dict(line.split() for line in g("cat-file", "--batch-all-objects", "--batch-check=%(objectname) %(objecttype)").splitlines())
        brief = sh(["git", "rev-parse", f"{X21_BASE_SRC}:{X21_EXCLUDED}2026-10-13-github-sign-in/briefs/fix-x2-1.md"], x21_clone(), self.env).stdout.strip()
        self.assertIn(brief, forbidden - reached, "MoonAliza's brief of the fix is among the excluded objects")
        self.assertEqual(sorted((forbidden - reached) & set(objects)), [], "an excluded object is in the pack repository")
        self.assertEqual(sorted(o for o, kind in objects.items() if kind == "blob" and o not in reached), [], "a blob the two trees do not reach")
        self.assertEqual(g("diff", "--name-status", "base0", "accepted0", "--", "tests/zz_accepted_x2_1.test.ts"), "A\ttests/zz_accepted_x2_1.test.ts")
        self.assertEqual(subprocess.run(["git", "-C", str(self.pack / "repo"), "show", "accepted0:tests/zz_accepted_x2_1.test.ts"],
                                        capture_output=True, check=True).stdout, (X21 / "zz_accepted_x2_1.test.ts").read_bytes())
        again = subprocess.run(["bash", str(self.pack / "make-repo.sh"), str(x21_clone()), str(self.root / "elsewhere" / "repo")],
                               env=self.env, capture_output=True, text=True, timeout=600)
        self.assertEqual(again.stdout, self.built.stdout, "a second build elsewhere gives the same ids")
        p = subprocess.run(["bash", str(self.pack / "make-repo.sh"), str(x21_clone()), str(self.pack / "repo")], env=self.env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 2, "an existing target is refused")

    @NEEDS_X21
    def test_base0_names_neither_the_finding_nor_its_fix_nor_its_cause(self):
        # integration 4 (IC3-1, D-IC3-1): a candidate's checkout is base0's tree, and the prompt lets it read anything there,
        # so no file and no path name of base0 may hold X2-1 (either spelling), the accepted fix's names or a phrase of the
        # cause, and base0 has no docs/orchestration/ path. The same scan of MoonAliza 16f637f finds hints, all of them under
        # docs/orchestration/ (the scan is not vacuous, and the directory is the whole of the leak)
        self.assertEqual(self.built.returncode, 0, self.built.stdout + self.built.stderr)
        self.assertEqual([h for h in X21_HINTS if h != h.lower()], [], "the scan lower-cases what it reads")
        repo = self.pack / "repo"
        self.assertEqual([p for p in x21_ls_tree(repo, "base0", self.env) if p.startswith(X21_EXCLUDED)], [], "base0 has no docs/orchestration/ path")
        self.assertEqual(x21_hint_hits(repo, "base0", self.env), [], "base0 holds a hint of X2-1, its fix or its cause")
        in_clone = x21_hint_hits(x21_clone(), X21_BASE_SRC, self.env)
        self.assertEqual([p for p in in_clone if not p.startswith(X21_EXCLUDED)], [], "MoonAliza 16f637f holds a hint outside docs/orchestration/")
        # integration 5 (IC4-2): the non-vacuity check needs the content scan. Three of the six hits match by their path name
        # alone; RUN.md, calibration-2-extra-findings.md and ledger.jsonl name no hint in their paths, so only their bytes can
        # put them here, and the whole list is pinned
        self.assertEqual(sorted(in_clone), sorted(X21_EXCLUDED + p for p in X21_CLONE_HINT_PATHS), "the scan of MoonAliza 16f637f")
        by_name = [p for p in in_clone if any(h in p.lower() for h in X21_HINTS)]
        self.assertEqual(sorted(set(in_clone) - set(by_name)), sorted(X21_EXCLUDED + p for p in X21_CLONE_HINT_PATHS[3:]),
                         "the hits only the content scan finds")

    @NEEDS_X21
    def test_make_repo_removes_its_target_when_the_ids_differ(self):
        # review 1 F8: a failed build leaves nothing behind, so a rerun is not refused for an existing target
        bad = self.root / "bad-pack"
        shutil.copytree(X21, bad)
        m = x21_manifest()
        m["accepted_fix"] = "0" * 40
        (bad / "manifest.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
        target = self.root / "bad" / "repo"
        p = subprocess.run(["bash", str(bad / "make-repo.sh"), str(x21_clone()), str(target)], env=self.env, capture_output=True, text=True, timeout=600)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("accepted_fix: manifest " + "0" * 40, p.stderr)
        self.assertFalse(target.exists(), "the built target is removed when the ids differ")

    @NEEDS_X21
    def test_the_accepted_journey_test_is_red_at_base_and_green_at_accepted(self):
        test = (X21 / "zz_accepted_x2_1.test.ts").read_bytes()
        base = self.at("base")
        (base / "tests" / "zz_accepted_x2_1.test.ts").write_bytes(test)
        at_base = self.vitest(base, "tests/zz_accepted_x2_1.test.ts")
        results = {a["title"]: a["status"] for r in at_base["testResults"] for a in r["assertionResults"]}
        journey = {t: s for t, s in results.items() if "crash before commit" in t}
        self.assertEqual(len(journey), 12, results)
        self.assertEqual(set(journey.values()), {"failed"}, "every journey row is red at the base")
        # review loop 2 RL2-P1: the unreadable-run row is the journey with four unreadable starts, so X2-1 makes it red too
        run_row = [t for t in results if t.startswith("first sign-in before commit 1 and refresh before commit 4, then EACCES")]
        self.assertEqual([results[t] for t in run_row], ["failed"], "the unreadable-run row is red at the base")
        # review loop 5 RL5-P1: the other-errno row is the journey with the other codes, so X2-1 makes it red too
        errno_row = [t for t in results if t.endswith("then EPERM, EMFILE, EINVAL or UNKNOWN at the next three starts (at the stat, "
                                                      "the open, then the read): the pair survives all three and is live and "
                                                      "committed after the next")]  # review loop 8 RL8-P1: three starts
        self.assertEqual([results[t] for t in errno_row], ["failed"], "the other-errno row is red at the base")
        # review loop 9 RL9-P1, RL9-P2: the lasting row and the engine row are journeys through unreadable starts, so X2-1
        # makes them red too; the tombstone row at each point and the orphan-codes row hold at the base (review loop 10: and
        # so do the two vault-state rows, whose states the base's reconcile already handles)
        lasting_row = [t for t in results if t.startswith("first sign-in before commit 1, sign-in before commit 3 and refresh before "
                                                           "commit 4, then the same failure at four starts in a row")]
        self.assertEqual([results[t] for t in lasting_row], ["failed"], "the lasting row is red at the base")
        engine_row = [t for t in results if t.startswith("first sign-in before commit 1 and refresh before commit 4, each beside a "
                                                          "staged entry the engine names")]
        self.assertEqual([results[t] for t in engine_row], ["failed"], "the engine row is red at the base")
        # review loop 11 RL11-P3: the keep-side vault-state rows keep a staged pair through unreadable starts, so X2-1 makes them
        # red too
        keep_rows = [t for t in results if t.startswith("a pair to keep beside ")]
        self.assertEqual([results[t] for t in keep_rows], ["failed", "failed"], "the keep-side vault-state rows are red at the base")
        # review loop 12 RL12-P1, RL12-P2: the keep at every code and every point (two rows since review loop 13 RL13-P2) and the
        # engine's key stored during an unreadable session keep a staged pair through unreadable starts, so X2-1 makes them red too
        round12_rows = [t for t in results if t.startswith(("the pair to keep at every code and every point", "first sign-in before "
                                                            "commit 1 and refresh before commit 4, the engine storing a key"))]
        self.assertEqual([results[t] for t in round12_rows], ["failed", "failed", "failed"], "the round-12 rows are red at the base")
        # review loop 14 RL14-P2: the point-pair row of the pair to keep keeps a staged pair through unreadable starts, so X2-1 makes
        # it red too; its orphan row holds at the base
        pair_rows = [t for t in results if "then seventeen unreadable starts in a row" in t]
        self.assertEqual(sorted(results[t] for t in pair_rows), ["failed", "passed"], "the point-pair rows: the keep red at the base")
        pair_rows = [t for t in pair_rows if results[t] == "failed"]
        self.assertTrue(pair_rows[0].startswith("first sign-in before commit 1 and refresh before commit 4, then seventeen"), pair_rows)
        # review loop 15 RL15-P1: the start-sequence rows keep a staged pair through unreadable starts, so X2-1 makes both red
        sequence_rows = [t for t in results if "then 127 events a year apart in a de Bruijn order" in t]
        self.assertEqual([results[t] for t in sequence_rows], ["failed", "failed"], "the start-sequence rows are red at the base")
        red_rows = (set(journey) | set(run_row) | set(errno_row) | set(lasting_row) | set(engine_row) | set(keep_rows) | set(round12_rows)
                    | set(pair_rows) | set(sequence_rows))
        self.assertEqual(len(red_rows), 24, "the rows red at the base")
        self.assertEqual({t: s for t, s in results.items() if t not in red_rows and s != "passed"}, {}, "the other rows hold at the base")
        self.assertEqual(len(results), X21_PIN_ROWS, results)
        at_accepted = self.vitest(self.at("accepted"), "tests/zz_accepted_x2_1.test.ts")
        self.assertEqual((at_accepted["numFailedTests"], at_accepted["numPassedTests"]), (0, len(results)))

    @NEEDS_X21
    def test_the_accepted_fix_reshaped_in_index_ts_stays_green(self):
        # re-review 2 RR2-1: a correct fix whose engine call is wrapped, or whose index.ts carries a comment naming an anchor,
        # is still correct; the journey test's slice of the startup lines must not turn it red
        # integration 3: every probe is checked eslint-clean (as the grade requires), and the files it touched are reset between probes
        cand = self.at("accepted")
        (cand / "tests" / "zz_accepted_x2_1.test.ts").write_bytes((X21 / "zz_accepted_x2_1.test.ts").read_bytes())
        lint = x21_manifest()["commands"]["lint"]
        for name, edits in X21_SLICE_PROBES.items():
            with self.subTest(name):
                touched = sorted({path for path, _, _ in edits})
                for path in touched:
                    (cand / path).write_bytes(subprocess.run(["git", "-C", str(self.pack / "repo"), "show", f"accepted0:{path}"],
                                                             capture_output=True, check=True).stdout)
                for path, old, new in edits:
                    x21_edit(cand, path, old, new)
                p = subprocess.run(["bash", "-c", lint.replace("{files}", " ".join(touched))], cwd=cand, env=self.env, capture_output=True,
                                   text=True, timeout=900)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                run = self.vitest(cand, "tests/zz_accepted_x2_1.test.ts")
                failed = [a["title"] for r in run["testResults"] for a in r["assertionResults"] if a["status"] != "passed"]
                self.assertEqual((run["numFailedTests"], run["numTotalTests"]), (0, X21_PIN_ROWS), failed)

    @NEEDS_X21
    def test_every_wrong_fix_grades_fail_on_the_accepted_journey_test_alone(self):
        rows = x21_wrong_rows()

        def graded(wid: str) -> subprocess.CompletedProcess:
            cand = self.at("base")
            x21_candidate(cand, X21_WRONG[wid], self.env, f"fix: X2-1 - {rows[wid][0]}")
            return self.grade_run(cand)

        # one grade at a time: the subject's own tests have a 15 s testTimeout, and on a loaded host (grades side by side)
        # some of its long tests time out, which turns a candidate's green run red for a reason that is not its change
        runs = {wid: graded(wid) for wid in X21_WRONG}
        for wid, p in runs.items():
            with self.subTest(wid):
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                g = json.loads(p.stdout)
                self.assertEqual((g["candidateGreen"], g["guardRed"], g["scopeOk"], g["lint"]), (True, True, True, "ok"), json.dumps(g, indent=1))
                self.assertFalse(g["acceptedPinGreen"], json.dumps(g, indent=1))
                self.assertFalse(g["PASS"])
                self.assertEqual(g["restored"], True)
                self.assertEqual(g["linksIntact"], {"node_modules": True, ".build": True}, wid)  # the pin, not the links, fails it
                self.assertEqual(g["setAside"], [], wid)  # review loop 9 RL9-K1: the candidate left nothing the grade sets aside
                # the grade column of WRONG-FIXES.md states the count the grade returns
                want = re.match(rf"FAIL: acceptedPin (\d+) of {X21_PIN_ROWS} red;", rows[wid][2])
                self.assertIsNotNone(want, rows[wid][2])
                pin = g["acceptedPin"]
                self.assertEqual((pin["failed"], pin["total"]), (int(want[1]), X21_PIN_ROWS), json.dumps(g, indent=1))

    @NEEDS_X21
    def test_the_accepted_and_two_alternative_fixes_grade_pass(self):
        accepted = self.at("base")
        for f in (*x21_manifest()["paths"]["source"], "tests/github-account-store.test.ts", "tests/vault.test.ts",
                  "tests/github-main-wiring.test.ts", "docs/ARCHITECTURE.md"):
            data = subprocess.run(["git", "-C", str(self.pack / "repo"), "show", f"accepted0:{f}"], capture_output=True, check=True).stdout
            (accepted / f).write_bytes(data)
        sh(["git", "add", "-A"], accepted, self.env)
        sh(["git", "commit", "-q", "--no-verify", "-m", "fix: X2-1 - the accepted change"], accepted, self.env)
        alternative = self.at("base")
        x21_candidate(alternative, X21_ALTERNATIVE, self.env, "fix: X2-1 - an unread start keeps unreferenced staged entries (another correct fix)")
        helper = self.at("base")
        x21_candidate(helper, X21_ALTERNATIVE_HELPER, self.env, "fix: X2-1 - the startup reconcile's options come from the store's module")
        for name, cand in (("accepted", accepted), ("alternative", alternative), ("helper", helper)):
            with self.subTest(name):
                g = self.grade_fix(cand)
                self.assertTrue(g["PASS"], json.dumps(g, indent=1))
                self.assertTrue(g["acceptedPinGreen"] and g["guardRed"] and g["candidateGreen"] and g["scopeOk"], name)
                self.assertEqual(g["linksIntact"], {"node_modules": True, ".build": True}, name)  # review loop 8 RL8-K2
                self.assertEqual(g["setAside"], [], name)  # review loop 9 RL9-K1

    @NEEDS_X21
    def test_a_grade_and_run_one_write_nothing_into_the_node_modules_a_checkout_links(self):
        # integration 3 (F5): a host links each checkout's node_modules to an install it does not own (the README's build step;
        # the builder's first runs linked the read-only clone's own). Vite writes its cache dir (node_modules/.vite, where vitest
        # keeps its results cache) and its bundled config (node_modules/.vite-temp) through that link unless the commands say
        # --no-cache and --configLoader runner. A grade of the accepted change, the candidate's run_one and the manifest's test
        # command, run on a checkout whose node_modules is a fresh install (integration 5: made as the README's step 2 says,
        # every file of it recorded), leave that install and the clone unchanged.
        modules = x21_install(x21_clone(), self.pack / "repo", self.root / f"f5-{self.n}", self.env)
        seal = self.seal_of(modules)  # review loop 8 RL8-K2: sealed right after the install, as the README's step 3 says
        clone_before, links_before = x21_clone_state(x21_clone(), self.env), x21_tree(modules)
        cand = self.at("base", modules)
        for f in (*x21_manifest()["paths"]["source"], "tests/github-account-store.test.ts", "tests/vault.test.ts",
                  "tests/github-main-wiring.test.ts", "docs/ARCHITECTURE.md"):
            (cand / f).write_bytes(subprocess.run(["git", "-C", str(self.pack / "repo"), "show", f"accepted0:{f}"], capture_output=True, check=True).stdout)
        sh(["git", "add", "-A"], cand, self.env)
        sh(["git", "commit", "-q", "--no-verify", "-m", "fix: X2-1 - the accepted change"], cand, self.env)
        self.assertTrue(self.grade_fix(cand, seal)["PASS"])
        one = subprocess.run(["bash", "-c", x21_manifest()["commands"]["run_one"].replace("{file}", "tests/vault.test.ts")], cwd=cand,
                             env=self.env, capture_output=True, text=True, timeout=900)
        self.assertEqual(one.returncode, 0, one.stdout + one.stderr)
        self.assertEqual(self.vitest(cand, "tests/vault.test.ts")["numFailedTests"], 0)
        links_after = x21_tree(modules)
        self.assertEqual(sorted(set(links_after) ^ set(links_before)), [], "nothing is added to or removed from the linked node_modules")
        self.assertEqual(links_after, links_before)
        self.assertEqual(x21_clone_state(x21_clone(), self.env), clone_before, "the clone is unchanged")

    @NEEDS_X21
    def test_no_checkout_links_an_install_in_a_moonaliza_clone_or_checkout(self):
        # integration 5 (IC4-1, S3 of check 4): a checkout reaches the directory around its node_modules through
        # node_modules/.. (Git Bash, and every tool on a POSIX host, resolve it through the link), so an install inside a
        # MoonAliza clone handed the candidate the clone's docs/orchestration/ and its history, which holds the accepted fix.
        # The README's step 2 now forbids that, and the kit's --link refuses each such route: the clone's own node_modules,
        # a folder of links to its entries (round 4's harness), and a history-less checkout of base0 (it has a .git, so it is
        # no install site either). A checkout of the README's install reaches neither a .git nor docs/orchestration/.
        import os
        self.assertEqual(self.built.returncode, 0, self.built.stdout + self.built.stderr)
        clone = x21_clone()
        self.assertTrue((clone / X21_EXCLUDED).is_dir() and (clone / ".git").exists(), "the clone holds what a link into it reaches")
        entries = self.root / "entries" / "node_modules"
        entries.mkdir(parents=True)
        first = sorted(p for p in (clone / "node_modules").iterdir() if p.is_dir() and not p.name.startswith("."))[0]
        (entries / first.name).symlink_to(first, target_is_directory=True)
        base = self.root / "base-checkout"
        p = checkout(self.pack / "repo", self.ids["base0"], base, self.env, "--pack", str(self.pack), timeout=900)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        (base / "node_modules").mkdir()
        for i, d in enumerate((clone / "node_modules", entries, base / "node_modules")):
            target = self.root / "refused" / f"cand-{i}"
            p = checkout(self.pack / "repo", self.ids["base0"], target, self.env, "--pack", str(self.pack), "--link", f"node_modules={d}", timeout=900)
            self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
            self.assertIn("is inside the git repository", p.stderr, d)
            self.assertFalse(target.exists(), d)
        cand = self.at("base")  # at() asserts that node_modules/.. reaches no .git and no docs/orchestration/
        up = Path(os.path.realpath(cand / "node_modules", strict=True)).parent
        self.assertEqual(sorted(e.name for e in up.iterdir()), ["node_modules", "package-lock.json", "package.json"])
        self.assertEqual(x21_reaches_no_records(cand), [])

    @NEEDS_X21
    @NEEDS_NODE
    def test_the_launch_refusals_hold_with_this_manifest_and_a_fix_only_protocol(self):
        m = x21_manifest()
        co = self.root / "launch" / "checkouts"
        cfg = lambda **host: x21_launch_config(self.root, m, self.pack, **host)

        out = execute_template(cfg(), self.root)
        self.assertIsNone(out["error"])
        self.assertEqual(sorted(c["label"] for c in out["calls"]), ["fix:alpha-low"])
        prompt = out["calls"][0]["prompt"]
        f = m["findings"][0]
        for text in (f["summary"], f["required_behaviour"], m["cases"]["fix"]["instructions"], "npx vitest run <file> --no-cache --configLoader runner",
                     "npx eslint src/main/github-account-store.ts src/main/vault.ts src/main/index.ts tests/github-account-store.test.ts"):
            self.assertIn(text, prompt)
        self.assertNotIn("Cause:", prompt)  # integration 3: cases.fix.cause_in_prompt false keeps the cause out
        for secret in (str(self.pack), "make-repo", "zz_accepted", "WRONG-FIXES", self.ids["accepted0"], self.ids["base0"]):
            self.assertNotIn(secret, prompt)  # Item 2: the prompt names only the checkout
        for host in ({"checkout_root": str(self.pack / "checkouts")}, {"adjudication_checkout": str(self.pack / "repo" / "adj")},
                     {"pack_dir": str(co / "pack")}):
            out = execute_template(cfg(**host), self.root)
            self.assertIn("shares a filesystem path with the pack directory", out["error"] or "", host)
            self.assertEqual(out["calls"], [], host)
        frozen = cfg()
        frozen["protocol"]["frozen_at"] = "{{ISO-8601 UTC time of the freeze commit}}"
        out = execute_template(frozen, self.root)
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
            if f.is_file() and "__pycache__" not in f.parts and f != KIT / "README.md" and not in_shared_pack(f) and not in_host_pack(f):
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
        names = ("- **Calibration kit**", "- **Shared synthetic subject pack**", "- **Host subject pack moonaliza-x2-1**")
        self.assertEqual(sorted(next((n for n in names if ln.startswith(n)), ln) for ln in lines), sorted(names))
        kit = [ln for ln in lines if ln.startswith("- **Calibration kit**")]
        self.assertEqual(len(kit), 1)
        self.assertIn("calibration-first-onboarding", kit[0])
        pack = [ln for ln in lines if ln.startswith("- **Shared synthetic subject pack**")]
        self.assertEqual(len(pack), 1)
        self.assertIn("tools/calibration/subject-pack/shared/", pack[0])
        host = [ln for ln in lines if ln.startswith("- **Host subject pack moonaliza-x2-1**")]
        self.assertIn("tools/calibration/subject-pack/host/moonaliza-x2-1/", host[0])
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


def make_gate_pack(root: Path, env: dict, case: dict | None = None, files: dict | None = None) -> tuple[Path, dict]:
    """A gate-only pack: a ledger and captures the candidate must not change, a checker (the gate) and nothing else
    (files: more {path: text} in the base)."""
    pack, repo = root / "gpack", root / "gpack" / "repo"
    (repo / "data").mkdir(parents=True)
    (repo / "captures" / "deep").mkdir(parents=True)
    (repo / "data" / "ledger.txt").write_text("row 1\nrow 2\n")
    (repo / "captures" / "a.txt").write_text("capture a\n")
    (repo / "captures" / "deep" / "b.txt").write_text("capture b\n")
    (repo / "notes.txt").write_text("todo\n")
    for name, text in (files or {}).items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_bytes(text.encode("utf-8"))
    (repo / "check.py").write_text("import sys\nsys.exit(0 if open('notes.txt').read().strip() == 'ok' else 1)\n")
    sh(["git", "init", "-q"], repo, env)
    base = commit_all(repo, env, "base")
    gate = copy.deepcopy(case or GATE_CASE)
    gate["base"] = base
    manifest = {"pack": "gate-pack", "pack_version": "1", "kind": "host", "repository": "repo", "cases": {"gate": gate}, "checkout": {"links": []}}
    (pack / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return pack, {"base": base, "repo": repo}


def fsmonitor_hook(cand: Path, env: dict, temp: Path, poison: str) -> tuple[Path, dict]:
    """Review loop RL3-K1: set the candidate's core.fsmonitor to a hook that runs `poison` (sh, with $v naming a git
    directory and $here the checkout) on every git directory of every grade view under temp and logs each run to
    .git/hook.log. Returns the log and the environment to grade with: its temporary directory is temp alone, so the
    hook can reach no other grade's view."""
    hook = cand / ".git" / "fsm.sh"
    hook.write_bytes((f"#!/bin/sh\nhere='{cand.as_posix()}'\necho \"ran $*\" >> \"$here/.git/hook.log\"\n"
                      f"for v in '{temp.as_posix()}'/grade-view-*/*/; do\n  [ -f \"$v/HEAD\" ] || continue\n  {poison}\ndone\nexit 1\n").encode())
    hook.chmod(0o755)
    sh(["git", "config", "core.fsmonitor", hook.as_posix()], cand, env)
    (cand / ".git" / "hook.log").unlink(missing_ok=True)
    return cand / ".git" / "hook.log", dict(env, TMPDIR=str(temp), TEMP=str(temp), TMP=str(temp))


def replace_root(cand: Path, env: dict, form: str, top=None) -> None:
    """Review loop RL4-K1: commit what the checkout holds into a root commit of the candidate's own instead of one on
    top of the base root. "amend": `git add -A && git commit --amend` of the single root commit; "amend-gc": the same,
    then the old root expired and pruned, so the candidate's objects no longer hold the base tree; "orphan": a new
    orphan root holding everything, then top() writes more files, committed on top of it."""
    sh(["git", "add", "-A"], cand, env)
    if form.startswith("amend"):
        sh(["git", "commit", "-q", "--amend", "-m", "work"], cand, env)
        if form == "amend-gc":
            sh(["git", "reflog", "expire", "--expire=now", "--all"], cand, env)
            sh(["git", "gc", "-q", "--prune=now"], cand, env)
    else:
        sh(["git", "checkout", "-q", "--orphan", "cal/orphan"], cand, env)
        sh(["git", "commit", "-q", "-m", "root"], cand, env)
        if top:
            top()
        commit_all(cand, env, "on top")


def cut_parent_in_commit_graph(cand: Path, env: dict) -> None:
    """Write the candidate's commit-graph and cut HEAD's first parent in it (GRAPH_PARENT_NONE), as a candidate can: git
    reads a commit-graph from an alternate's objects/info, so the forged graph made HEAD its own root."""
    import struct
    sh(["git", "commit-graph", "write", "--reachable"], cand, env)
    head = sh(["git", "rev-parse", "HEAD"], cand, env).stdout.strip()
    path = cand / ".git" / "objects" / "info" / "commit-graph"
    path.chmod(0o644)
    b = bytearray(path.read_bytes())
    width = {1: 20, 2: 32}[b[5]]
    chunks = {bytes(b[8 + 12 * i: 12 + 12 * i]): struct.unpack(">Q", b[12 + 12 * i: 20 + 12 * i])[0] for i in range(b[6])}
    count = struct.unpack(">I", b[chunks[b"OIDF"] + 255 * 4: chunks[b"OIDF"] + 256 * 4])[0]
    ids = [bytes(b[chunks[b"OIDL"] + width * i: chunks[b"OIDL"] + width * (i + 1)]).hex() for i in range(count)]
    entry = chunks[b"CDAT"] + (width + 16) * ids.index(head) + width
    b[entry: entry + 4] = struct.pack(">I", 0x70000000)
    path.write_bytes(bytes(b))


def forge_object(cand: Path, env: dict, target: str, tree: str, form: str) -> None:
    """Review loop RL8-K1: file the candidate's tree object `tree` under the id `target` in its .git/objects, as a loose
    object ("loose") or in a one-object pack with its own index ("packed"): the content does not hash to the id, and git
    reads it by the id it is filed under."""
    import hashlib
    import struct
    import zlib
    body = subprocess.run(["git", "cat-file", "tree", tree], cwd=cand, env=env, capture_output=True, check=True).stdout
    objects = cand / ".git" / "objects"
    if form == "loose":
        path = objects / target[:2] / target[2:]
        path.parent.mkdir(exist_ok=True)
        if path.exists():
            path.chmod(0o644)
            path.unlink()
        path.write_bytes(zlib.compress(b"tree %d\0" % len(body) + body))
        return
    n, head = len(body), bytearray([2 << 4 | len(body) & 0x0F])
    n >>= 4
    while n:
        head[-1] |= 0x80
        head.append(n & 0x7F)
        n >>= 7
    entry = bytes(head) + zlib.compress(body)
    pack = b"PACK" + struct.pack(">II", 2, 1) + entry
    pack += hashlib.sha1(pack).digest()
    oid = bytes.fromhex(target)
    idx = b"\377tOc" + struct.pack(">I", 2) + b"".join(struct.pack(">I", int(i >= oid[0])) for i in range(256)) + oid
    idx += struct.pack(">II", zlib.crc32(entry), 12) + pack[-20:]
    idx += hashlib.sha1(idx).digest()
    (objects / "pack").mkdir(exist_ok=True)
    (objects / "pack" / f"pack-{pack[-20:].hex()}.pack").write_bytes(pack)
    (objects / "pack" / f"pack-{pack[-20:].hex()}.idx").write_bytes(idx)


def forge_base_tree(cand: Path, env: dict, base_tree: str, form: str, keep: tuple[str, ...]) -> None:
    """Commit what the checkout holds, then file under the base tree's id a tree that holds the base's entries with
    HEAD's in place of the top-level names in keep, so the base reads as already holding them; then HEAD becomes an
    orphan root holding the same tree (no peel of the base tree's id runs: the history starts elsewhere), and the files
    in keep go from disk (the index keeps them)."""
    commit_all(cand, env, "work")
    lines = [ln for ln in sh(["git", "ls-tree", base_tree], cand, env).stdout.splitlines() if ln.split("\t", 1)[1] not in keep]
    lines += sh(["git", "ls-tree", "HEAD", "--", *keep], cand, env).stdout.splitlines()
    forged = subprocess.run(["git", "mktree"], cwd=cand, env=env, input=("\n".join(lines) + "\n").encode(), capture_output=True,
                            check=True).stdout.decode().strip()
    forge_object(cand, env, base_tree, forged, form)
    root = sh(["git", "commit-tree", "HEAD^{tree}", "-m", "work"], cand, env).stdout.strip()
    sh(["git", "update-ref", "refs/heads/cal/test", root], cand, env)


def splice_cache_tree(index: Path, matching: Path) -> None:
    """Review loop RL8-K1, same class: replace the extensions of the index file `index` (version 2, as git add writes
    it) with those of `matching`, an index of the same entries' count read from HEAD: its cache tree (TREE) claims each
    directory still holds HEAD's tree, and diff-index --cached skips such a directory without reading its entries."""
    import hashlib
    import struct

    def split(b):
        off = 12
        for _ in range(struct.unpack(">I", b[8:12])[0]):
            off += (62 + (struct.unpack(">H", b[off + 60: off + 62])[0] & 0xFFF) + 8) // 8 * 8
        return b[:off], b[off:-20]
    entries, _ = split(index.read_bytes())
    _, ext = split(matching.read_bytes())
    out = entries + ext
    index.write_bytes(out + hashlib.sha1(out).digest())


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
        self.assertEqual(list(d), ["task", "head", "baseRoot", "commits", "changed", "staged", "untracked", "setAside", "srcTouched", "testFiles", "atHead",
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

    def test_k3_the_gate_command_runs_no_file_the_grade_does_not_count(self):
        # review loop RL9-K1, gate form: an untracked unittest.py at the top stood in for the runner the gate command
        # names (python -m puts the working directory first), so a gate that fails passed; it is set aside for the
        # command, and a required path the candidate left untracked stays
        case = copy.deepcopy(GATE_CASE)
        case["commands"] = {"gate": "python3 -m unittest check_notes", "timeout_seconds": 60}
        pack, c = make_gate_pack(self.root, self.env, case=case, files={"check_notes.py": (
            "import unittest\n\n\nclass N(unittest.TestCase):\n    def test_ok(self):\n"
            "        self.assertEqual(open('notes.txt').read().strip(), 'ok')\n        open('out/summary.md').close()\n")})
        for name, notes, shadow in (("gate-shadow", "not ok\n", True), ("gate-shadow-control", "ok\n", False)):
            cand = self.gate_cell(c, name, notes=notes, summary=False)
            (cand / "out").mkdir()
            (cand / "out" / "summary.md").write_text("summary, never added\n")
            if shadow:
                (cand / "unittest.py").write_text("raise SystemExit(0)\n")
            code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
            self.assertEqual(code, 0, out)
            self.assertEqual(d["requiredPresent"], {"out/summary.md": True}, out)
            self.assertEqual(d["setAside"], ["unittest.py"] if shadow else [], out)
            self.assertEqual((d["gateExit"] == 0, d["PASS"], d["restored"]), (not shadow, not shadow, True), out)
            if shadow:
                self.assertEqual((cand / "unittest.py").read_text(), "raise SystemExit(0)\n")

    def test_k3_a_linked_directory_above_a_required_path_is_set_aside_as_the_link(self):
        # review loop RL10-K3, gate form: out/ (the directory above the required out/summary.md) is a junction to a host
        # directory; the set-aside read it as a directory of the checkout and moved the host directory's other files
        # into the checkout's .git, where the put-back refused to return them. The link itself is set aside and put back
        pack, c = make_gate_pack(self.root, self.env)
        host = self.root / "host-out"
        host.mkdir()
        for n in ("summary.md", "precious.txt"):
            (host / n).write_text(n + "\n")
        cand = self.gate_cell(c, "gate-link", summary=False)
        dir_link(cand / "out", host)
        code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(p.name for p in host.iterdir()), ["precious.txt", "summary.md"], out)
        self.assertEqual((d["requiredPresent"], d["setAside"], d["restored"], d["PASS"]), ({"out/summary.md": True}, ["out"], True, True), out)
        self.assertTrue(is_dir_link(cand / "out"))
        self.assertEqual([p.name for p in (cand / ".git").glob("grade-aside-*")], [], out)

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

    def test_k3_nothing_in_the_candidates_git_hides_a_changed_invariant(self):
        # review loop RL2-K1: the grade once hashed the invariants with the candidate's own git, so a clean filter in its
        # .git/config and .git/info/attributes (both untracked) made an edited file read as the base's, and a file added
        # under an invariant hid behind the candidate's .git/info/exclude or a .gitignore that ignores itself. The view
        # reads nothing in the candidate's .git (config, attributes, excludes, index flags) and only the base's
        # .gitignore rules
        pack, c = make_gate_pack(self.root, self.env, files={"captures/stamp.txt": "$Id$"})

        def filtered(d):
            (d / "data" / "ledger.txt").write_text("row 1\nrow 2\nrow 3\n")
            (d / "keep.sh").write_text('git cat-file blob "$(git rev-list --max-parents=0 HEAD)":"$1"\n')
            sh(["git", "config", "filter.keep.clean", "sh keep.sh %f"], d, self.env)
            (d / ".git" / "info").mkdir(exist_ok=True)
            with (d / ".git" / "info" / "attributes").open("a") as f:
                f.write("data/** filter=keep\n")

        def excluded(d):
            (d / "captures" / "c.txt").write_text("new\n")
            (d / ".git" / "info").mkdir(exist_ok=True)
            with (d / ".git" / "info" / "exclude").open("a") as f:
                f.write("captures/c.txt\n")

        def self_ignored(d):
            (d / "captures" / "c.txt").write_text("new\n")
            (d / "captures" / ".gitignore").write_text("c.txt\n.gitignore\n")

        def attributed(d):  # a work tree .gitattributes: ident collapses "$Id: ... $" to the base's "$Id$"
            (d / "captures" / "stamp.txt").write_text("$Id: edited $")  # no newline: on Windows a CR would change the collapse
            (d / ".gitattributes").write_text("captures/stamp.txt ident\n")

        for name, change, broken in (("filter", filtered, "data/ledger.txt"), ("exclude", excluded, "captures"),
                                     ("selfignore", self_ignored, "captures"), ("ident", attributed, "captures")):
            cand = self.gate_cell(c, f"gate-hide-{name}", also=change)
            if name == "filter":  # the commit stores the base's text: the filter decided what git read
                self.assertEqual(sh(["git", "show", "HEAD:data/ledger.txt"], cand, self.env).stdout, "row 1\nrow 2\n")
                self.assertEqual((cand / "data" / "ledger.txt").read_text(), "row 1\nrow 2\nrow 3\n")
            self.assertEqual(sh(["git", "status", "--porcelain", "--", broken], cand, self.env).stdout, "", name)  # its own git sees nothing
            code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
            self.assertEqual(code, 0, out)
            self.assertEqual(d["gateExit"], 0, out)
            self.assertIs(d["invariantsIntact"][broken], False, f"{name}: {out}")
            self.assertIs(d["PASS"], False, name)

        def honest_filter(d):  # control: a filter that changes nothing, on an honest candidate
            sh(["git", "config", "filter.keep.clean", "cat"], d, self.env)
            (d / ".git" / "info").mkdir(exist_ok=True)
            (d / ".git" / "info" / "attributes").write_text("data/** filter=keep\n")

        cand = self.gate_cell(c, "gate-honest-filter", also=honest_filter)
        code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
        self.assertEqual(d["invariantsIntact"], {"data/ledger.txt": True, "captures": True}, out)
        self.assertIs(d["PASS"], True, out)

    def test_k3_an_ignored_file_the_candidate_committed_under_an_invariant_counts(self):
        # review loop RL5-K1: the invariant's files were the base's, the candidate's index and the others the base's
        # rules do not ignore, never HEAD's. So an ignored file committed under an invariant and then dropped from the
        # index (git rm --cached, the removal never committed) was in HEAD and on disk and in no list: intact, PASS. A
        # file HEAD adds under the path counts now, as one in the index does, on disk or not
        pack, c = make_gate_pack(self.root, self.env, files={".gitignore": "*.log\n"})

        def force_add(d):
            (d / "captures" / "x.log").write_text("committed though ignored\n")
            sh(["git", "add", "-f", "captures/x.log"], d, self.env)

        cand = self.gate_cell(c, "gate-ignored-loose", also=lambda d: (d / "captures" / "x.log").write_text("ignored, never added\n"))
        code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)  # control: an ignored file nobody added is not counted
        self.assertEqual((code, d["invariantsIntact"], d["PASS"]), (0, {"data/ledger.txt": True, "captures": True}, True), out)
        def unstage(d):  # out of the index, still in HEAD and on disk
            sh(["git", "rm", "-q", "--cached", "captures/x.log"], d, self.env)

        def remove(d):  # out of the index and off the disk, still in HEAD
            sh(["git", "rm", "-q", "captures/x.log"], d, self.env)

        for name, before, after in (("committed", force_add, None), ("unstaged", force_add, unstage),
                                    ("removed", force_add, remove), ("staged", None, force_add)):
            cand = self.gate_cell(c, f"gate-ignored-{name}", also=before)
            if after:
                after(cand)
            held = sh(["git", "ls-tree", "--name-only", "HEAD", "captures/x.log"], cand, self.env).stdout.strip()
            self.assertEqual(held, "" if name == "staged" else "captures/x.log", name)  # HEAD holds it, but for "staged"
            self.assertEqual((cand / "captures" / "x.log").exists(), name != "removed", name)
            code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
            self.assertEqual(code, 0, f"{name}: {out}")
            self.assertEqual((d["gateExit"], d["commits"]), (0, 1), f"{name}: {out}")
            self.assertEqual(d["invariantsIntact"], {"data/ledger.txt": True, "captures": False}, f"{name}: {out}")
            self.assertIs(d["PASS"], False, name)

    def test_k3_a_program_the_candidates_git_config_names_never_runs_in_the_grade(self):
        # review loop RL3-K1: the grade still ran git on the candidate's own repository (rev-list, diff, ls-files) after
        # it had made the view, so a core.fsmonitor hook in the candidate's .git/config ran inside the grade and gave the
        # view a clean filter (its config and info/attributes): an edited invariant hashed as the base's. Now no git
        # runs on the candidate's .git as a repository, so the hook never runs
        pack, c = make_gate_pack(self.root, self.env)
        temp = self.root / "grade-temp"
        temp.mkdir()

        def edited(d):
            (d / ".git" / "orig" / "data").mkdir(parents=True)
            (d / ".git" / "orig" / "data" / "ledger.txt").write_bytes((d / "data" / "ledger.txt").read_bytes())
            (d / "data" / "ledger.txt").write_text("row 1\nrow 2\nrow 3\n")

        cand = self.gate_cell(c, "gate-fsmonitor", also=edited)
        orig = (cand / ".git" / "orig").as_posix()
        log, env = fsmonitor_hook(cand, self.env, temp, "mkdir -p \"$v/info\"; echo 'data/** filter=keep' >> \"$v/info/attributes\"; "
                                  f"printf '[filter \"keep\"]\\n\\tclean = cat {orig}/%%f\\n' >> \"$v/config\"")
        code, d, out = grade(pack / "manifest.json", "gate", cand, env)
        self.assertEqual(code, 0, out)
        self.assertEqual(d["gateExit"], 0, out)
        self.assertIs(d["invariantsIntact"]["data/ledger.txt"], False, out)
        self.assertIs(d["PASS"], False, out)
        self.assertFalse(log.exists(), f"the candidate's fsmonitor hook ran in the grade: {log.read_text() if log.exists() else ''}")
        sh(["git", "config", "--unset", "core.fsmonitor"], cand, self.env)  # control: the same cell, ledger restored, passes
        (cand / "data" / "ledger.txt").write_bytes((cand / ".git" / "orig" / "data" / "ledger.txt").read_bytes())
        code, d, out = grade(pack / "manifest.json", "gate", cand, env)
        self.assertEqual(d["invariantsIntact"], {"data/ledger.txt": True, "captures": True}, out)
        self.assertIs(d["PASS"], True, out)

    def test_k3_a_large_invariant_directory_is_graded(self):
        # review loop RL2-K2: every file under an invariant went to one hash-object command line, past Windows' 32,767
        # characters for 1,200 capture files, and the grade crashed with no JSON; the paths now go on stdin
        bulk = {f"captures/research-collect-sources/capture-file-number-{i:04d}.json": f'{{"n": {i}}}\n' for i in range(1200)}
        pack, c = make_gate_pack(self.root, self.env, files=bulk)
        cand = self.gate_cell(c, "gate-bulk")
        code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual(d["invariantsIntact"], {"data/ledger.txt": True, "captures": True}, out)
        self.assertIs(d["PASS"], True, out)
        (cand / "captures" / "research-collect-sources" / "capture-file-number-0999.json").write_text('{"n": -1}\n')
        code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertIs(d["invariantsIntact"]["captures"], False, out)
        self.assertIs(d["PASS"], False, out)

    def test_k3_unusual_names_under_an_invariant_are_hashed_one_by_one(self):
        # the paths go to hash-object one per line, C-quoted where git would unquote them (a leading quote, a
        # backslash, a tab); each still hashes as its own file, so an edit to one of them is caught
        names = ["captures/caf\u00e9.txt", "captures/ two  spaces.txt"]
        if sys.platform != "win32":  # Windows takes none of these in a file name
            names += ['captures/"quoted".txt', "captures/tab\there.txt", "captures/back\\slash.txt"]
        pack, c = make_gate_pack(self.root, self.env, files={n: f"{n}\n" for n in names})
        cand = self.gate_cell(c, "gate-names")
        code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual(d["invariantsIntact"], {"data/ledger.txt": True, "captures": True}, out)
        for n in names:
            (cand / n).write_text("edited\n")
            code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
            self.assertIs(d["invariantsIntact"]["captures"], False, f"{n}: {out}")
            (cand / n).write_text(f"{n}\n")

    def test_k3_a_missing_required_path_fails(self):
        pack, c = make_gate_pack(self.root, self.env)
        cand = self.gate_cell(c, "gate-nosummary", summary=False)
        code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual((d["gateExit"], d["requiredPresent"]), (0, {"out/summary.md": False}), out)
        self.assertIs(d["PASS"], False)

    @unittest.skipUnless(sys.platform == "win32", "a reparse point of a third party's tag is a Windows (NTFS) object")
    def test_k3_an_invariant_file_that_is_a_reparse_point_is_no_plain_file(self):
        # review loop RL15-J1, the same class: the invariant read took a file for a plain one by is_file() and
        # is_symlink(), which count no reparse point but a symlink; a reparse point of a third party's tag (no filter
        # driver here: any read of it fails) now reads as no longer a plain file, as a link does: not intact, no PASS
        pack, c = make_gate_pack(self.root, self.env)
        cand = self.gate_cell(c, "gate-reparse")
        foreign_reparse(cand / "data" / "ledger.txt")
        code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
        self.assertNotIn("Traceback", out)
        self.assertEqual(code, 0, out)
        self.assertEqual(d["invariantsIntact"], {"data/ledger.txt": False, "captures": True}, out)
        self.assertIs(d["PASS"], False, out)

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

    def test_k3_a_history_that_does_not_start_at_the_base_has_no_commit_on_it(self):
        # review loop RL4-K1: commits were counted from the candidate's own root, so an orphan root holding the work and
        # one commit on top of it read as a commit on the base. Only commits on top of the base root count now
        pack, c = make_gate_pack(self.root, self.env)
        cand = self.gate_cell(c, "gate-on-base")
        code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
        self.assertEqual((code, d["commits"], d["PASS"]), (0, 1, True), out)
        on_base = d.get("baseRoot")
        for form in ("orphan", "amend"):
            cand = self.gate_cell(c, f"gate-root-{form}", summary=form == "amend", commit=False)
            replace_root(cand, self.env, form, top=lambda: ((cand / "out").mkdir(), (cand / "out" / "summary.md").write_text("summary\n")))
            code, d, out = grade(pack / "manifest.json", "gate", cand, self.env)
            self.assertEqual(code, 0, f"{form}: {out}")
            self.assertEqual((d["gateExit"], d["requiredPresent"]), (0, {"out/summary.md": True}), f"{form}: {out}")
            self.assertEqual((d["committed"], d["PASS"]), (False, False), f"{form}: {out}")
            self.assertEqual((d.get("baseRoot"), d["commits"]), (False, 0), f"{form}: {out}")
        self.assertIs(on_base, True)

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
