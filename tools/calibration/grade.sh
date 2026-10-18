#!/usr/bin/env bash
# Lineage: generalises the mechanical grader of calibration runs 1-3 (pin and fix cells graded against the pack's base
# and accepted trees). Everything run 3 hard-coded - the source and accepted revisions, the source and test paths, the
# scope rule, the test and lint commands, the output location - now comes from the subject-pack manifest; the grade
# goes to stdout. The grading logic is the Python program below (a quoted heredoc: no shell value is spliced into it).
#
# usage: grade.sh MANIFEST pin|fix CHECKOUT > GRADES_DIR/<case>-<profile>.json
#
#   MANIFEST  the subject pack's manifest.json (format: tools/calibration/subject-pack/README.md)
#   pin|fix   the case; a review is graded by the grader agent, not here
#   CHECKOUT  the candidate's history-less checkout (historyless-checkout.sh), graded in place: the grade swaps the
#             manifest's source files for the accepted or base versions while it runs the tests and restores them
#
# Exit 0 with the grade (PASS true or false) as one JSON object; 2 on a bad argument, an unusable manifest or a
# checkout that shares a path with the pack; 3 with {"error": ...} when the checkout is missing or has no commit.
set -u
[ $# -eq 3 ] || { echo "usage: grade.sh MANIFEST pin|fix CHECKOUT" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "grade.sh: python3 not found" >&2; exit 2; }
exec python3 -I - "$@" <<'PY'
import json, re, shlex, subprocess, sys, tempfile
from pathlib import Path

def refuse(msg, code=2):
    print(f"grade.sh: refused: {msg}", file=sys.stderr)
    sys.exit(code)

manifest_path, task, checkout = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
if task not in ("pin", "fix"):
    refuse(f"case must be pin or fix, not {task!r} (a review is graded by the grader agent)")
try:
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    pack_dir = manifest_path.resolve().parent
    repo = Path(m["repository"])
    repo = repo if repo.is_absolute() else pack_dir / repo
    accepted, base = m["accepted_fix"], m["cases"][task]["base"]
    paths, commands = m["paths"], m["commands"]
    sources = list(paths["source"])
    src_dir = paths["source_dir"].rstrip("/") + "/"
    new_test = re.compile(paths["new_test_pattern"])
    test_cmd, mode = commands["test"], commands.get("test_report", "exit-code")
    lint_cmd, timeout = commands.get("lint"), int(commands.get("timeout_seconds", 900))
    links = list((m.get("checkout") or {}).get("links") or [])
    if task == "fix":
        test_file, acc_from, acc_to = paths["test_file"], paths["accepted_test"]["from"], paths["accepted_test"]["to"]
        allowed_extra, map_file = list(paths.get("allowed_extra") or []), paths.get("map_file")
except (OSError, ValueError, KeyError, TypeError) as e:
    refuse(f"manifest {manifest_path} unusable: {type(e).__name__} {e}")
if mode not in ("exit-code", "vitest-json"):
    refuse(f"commands.test_report must be exit-code or vitest-json, not {mode!r}")
for rev in (accepted, base):
    if subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"], capture_output=True).returncode:
        refuse(f"{rev} is not a commit in the pack repository {repo}")

if not checkout.is_dir():
    print(json.dumps({"task": task, "error": "no checkout", "checkout": str(checkout)}))
    sys.exit(3)
cand = checkout.resolve()
if cand == pack_dir or pack_dir in cand.parents or cand in pack_dir.parents:
    refuse(f"the checkout {cand} shares a path with the pack {pack_dir} (proposal Item 2: the answer stays outside every candidate's paths)")

def git(*args):
    p = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=cand, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if p.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout

def names(*args):
    return [x for x in git(*args).split("\0") if x]

try:
    roots = git("rev-list", "--max-parents=0", "HEAD").split()
    head = git("rev-parse", "--short", "HEAD").strip()
except RuntimeError as e:
    print(json.dumps({"task": task, "error": f"no commit in the checkout: {e}"}))
    sys.exit(3)
root = roots[0]
commits = int(git("rev-list", "--count", f"{root}..HEAD"))
committed = names("diff", "--name-only", "-z", f"{root}..HEAD")
staged = names("diff", "--cached", "--name-only", "-z")
unstaged = names("diff", "--name-only", "-z")
changed = sorted(set(committed + staged + unstaged))
status = git("status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0")
untracked = sorted(e[3:] for e in status if e.startswith("?? ") and not any(e[3:] == ln or e[3:].startswith(ln + "/") for ln in links))
added = names("diff", "--name-only", "-z", "--diff-filter=A", f"{root}..HEAD") + names("diff", "--cached", "--name-only", "-z", "--diff-filter=A")
new_tests = sorted({f for f in added + untracked if new_test.search(f)} - ({acc_to} if task == "fix" else set()))

def run_tests(files):
    if not files:
        return {"passed": None, "failed": None, "total": None, "exit": None, "error": "no test files"}
    with tempfile.TemporaryDirectory() as td:
        report = Path(td) / "report.json"
        cmd = test_cmd.replace("{files}", " ".join(shlex.quote(f) for f in files)).replace("{report}", shlex.quote(str(report)))
        try:
            code = subprocess.run(["bash", "-c", cmd], cwd=cand, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            code = 124
        r = {"passed": None, "failed": None, "total": None, "exit": code}
        if mode == "vitest-json":
            try:
                d = json.loads(report.read_text(encoding="utf-8"))
                r.update(passed=int(d["numPassedTests"]), failed=int(d["numFailedTests"]), total=int(d.get("numTotalTests", 0)))
            except (OSError, ValueError, KeyError, TypeError):
                r["error"] = "no readable report"
        return r

def red(r):
    if mode == "vitest-json":
        return r["failed"] is not None and r["failed"] > 0
    return r["exit"] is not None and r["exit"] not in (0, 124, 125, 126, 127)  # a timeout or a missing command is not red

def green(r):
    if mode == "vitest-json":
        return r["failed"] == 0 and (r["passed"] or 0) > 0
    return r["exit"] == 0

def lint(files):
    if not lint_cmd:
        return "none"
    cmd = lint_cmd.replace("{files}", " ".join(shlex.quote(f) for f in files))
    try:
        p = subprocess.run(["bash", "-c", cmd], cwd=cand, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "fail"
    return "ok" if p.returncode == 0 else "fail"

def show(rev, path):
    p = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True)
    return p.stdout if p.returncode == 0 else None

saved = {f: ((cand / f).read_bytes() if (cand / f).is_file() else None) for f in sources}

def put(rev):
    for f in sources:
        data, path = show(rev, f), cand / f
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

def restore():
    for f, data in saved.items():
        path = cand / f
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(data)

result = {"task": task, "head": head, "commits": commits, "changed": changed, "staged": staged, "untracked": untracked}
try:
    if task == "pin":
        files = new_tests
        at_head = run_tests(files)
        put(accepted)
        with_fix = run_tests(files)
        restore()
        lint_res = lint(files) if files else "fail"
        src_touched = sorted({f for f in changed + untracked if f.startswith(src_dir)})
        r_red, r_green, clean = red(at_head), green(with_fix), not src_touched
        result.update(srcTouched=src_touched, testFiles=files, atHead=at_head, withAcceptedFix=with_fix, lint=lint_res,
                      redAtHead=r_red, greenWithFix=r_green, srcClean=clean, committed=commits > 0,
                      PASS=bool(files) and r_red and r_green and clean and lint_res in ("ok", "none"))
    else:
        files = [f for f in dict.fromkeys([test_file] + new_tests) if (cand / f).is_file()]
        at_cand = run_tests(files)
        put(base)
        guard = run_tests(files)
        restore()
        acc_path = cand / acc_to
        if acc_path.exists():
            refuse(f"{acc_to} already exists in the checkout; the accepted test needs that path")
        data = show(accepted, acc_from)
        try:
            if data is None:
                accepted_run = {"passed": None, "failed": None, "total": None, "exit": None, "error": f"{acc_from} not in {accepted}"}
            else:
                acc_path.parent.mkdir(parents=True, exist_ok=True)
                acc_path.write_bytes(data)
                accepted_run = run_tests([acc_to])
        finally:
            acc_path.unlink(missing_ok=True)
        lint_res = lint([f for f in dict.fromkeys(sources + files) if (cand / f).is_file()])
        diff = subprocess.run(["git", "diff", root, "--", *sources], cwd=cand, capture_output=True, text=True).stdout
        allowed = set(sources) | {test_file} | set(allowed_extra) | set(new_tests)
        scope_ok = set(changed) <= allowed
        c_green, g_red, a_green = green(at_cand), red(guard), green(accepted_run)
        result.update(newTests=new_tests, committedWithMap=(map_file in changed and commits > 0) if map_file else None,
                      srcDiffLines=sum(1 for ln in diff.splitlines() if ln[:1] in ("+", "-") and not ln.startswith(("+++ ", "--- "))),
                      candidateTests=at_cand, guardRemoved=guard, acceptedPin=accepted_run, lint=lint_res,
                      candidateGreen=c_green, guardRed=g_red, acceptedPinGreen=a_green, scopeOk=scope_ok,
                      outOfScope=sorted(set(changed) - allowed),
                      PASS=c_green and g_red and a_green and scope_ok and lint_res in ("ok", "none"))
finally:
    restore()
restored = all(((cand / f).read_bytes() if (cand / f).is_file() else None) == data for f, data in saved.items())
result["restored"] = restored
if not restored:
    print(f"grade.sh: WARNING: the source files in {cand} were not restored", file=sys.stderr)
print(json.dumps(result, indent=1))
PY
