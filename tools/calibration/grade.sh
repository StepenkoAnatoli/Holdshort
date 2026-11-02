#!/usr/bin/env bash
# Lineage: generalises the mechanical grader of calibration runs 1-3 (pin and fix cells graded against the pack's base
# and accepted trees). Everything run 3 hard-coded - the source and accepted revisions, the source and test paths, the
# scope rule, the test and lint commands, the output location - now comes from the subject-pack manifest; the grade
# goes to stdout. The grading logic is the Python program below (a quoted heredoc: no shell value is spliced into it).
#
# usage: grade.sh MANIFEST pin|fix|gate CHECKOUT > GRADES_DIR/<case>-<profile>.json
#
#   MANIFEST      the subject pack's manifest.json (format: tools/calibration/subject-pack/README.md)
#   pin|fix|gate  the case; a review is graded by the grader agent, not here
#   CHECKOUT      the candidate's history-less checkout (historyless-checkout.sh), graded in place: the grade swaps the
#                 manifest's source files for the accepted, base or mutant versions while it runs the tests and restores
#                 them; each swap gives the files a fresh mtime two seconds past the last, so a cache keyed on mtime and
#                 size (Python's __pycache__) never runs a previous version, and the original mtimes go back at the end
#
# A pin case with `mutants` ([{id, commit}]) also needs the candidate's new tests red with each mutant commit's source
# swapped in (redAtMutants: {id: bool}); without mutants the pin grade is what it always was. A gate case is graded by
# its own command (cases.gate.commands.gate, exit 0), its invariants (each path's files hash as at the base, read as the
# checkout stands, and no file that HEAD or the index adds is there, ignored or not), its required paths (each exists)
# and a commit; the invariants and the required paths are read before the command runs, so they grade the candidate's
# work and not the command's side effects, which stay. A mutant whose source files equal the base's or the accepted
# fix's is refused; a command that overruns its timeout (a test, lint or gate command) has its whole process tree
# killed and reads as exit 124. What the checkout holds (the
# invariants, `changed`, `untracked`, the source diff) is read by a git of the grade's own over the base tree, and what
# the candidate committed and staged by a second git of the grade's own over the candidate's objects and a copy of its
# index, its HEAD and refs read as files: no git ever runs on the candidate's .git as a repository, so nothing in its
# config, attributes, excludes, hooks or index flags (the candidate's to write) is applied or run. What the candidate
# committed is read against the case's base tree, never against a root commit the candidate can replace (an amend of
# the checkout's single commit, an orphan root), and every file on disk that the base lacks and the candidate's index
# holds counts as changed.
#
# Exit 0 with the grade (PASS true or false) as one JSON object; 2 on a bad argument, an unusable manifest or a
# checkout that shares a path with the pack; 3 with {"error": ...} when the checkout is missing or has no commit.
set -u
[ $# -eq 3 ] || { echo "usage: grade.sh MANIFEST pin|fix|gate CHECKOUT" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "grade.sh: python3 not found" >&2; exit 2; }
# none of git's repository variables (GIT_DIR, GIT_INDEX_FILE, ...) nor GIT_ATTR_SOURCE reaches the grade's git: each
# git it runs names its repository itself (the pack, the checkout or the view below)
unset GIT_ATTR_SOURCE $(git rev-parse --local-env-vars 2>/dev/null)
exec python3 -I - "$@" <<'PY'
import json, os, re, shlex, shutil, signal, subprocess, sys, tempfile, time
from pathlib import Path

def refuse(msg, code=2):
    print(f"grade.sh: refused: {msg}", file=sys.stderr)
    sys.exit(code)

manifest_path, task, checkout = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
if task not in ("pin", "fix", "gate"):
    refuse(f"case must be pin, fix or gate, not {task!r} (a review is graded by the grader agent)")

def inside(path):
    """A path the manifest names inside the checkout: relative (not rooted with '/' or '\\', no drive letter), no '..'
    segment."""
    return isinstance(path, str) and path != "" and not path.startswith(("/", "\\")) and ":" not in path and ".." not in path.replace("\\", "/").split("/")

mutants = []
try:
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    pack_dir = manifest_path.resolve().parent
    repo = Path(m["repository"])
    repo = repo if repo.is_absolute() else pack_dir / repo
    if task not in (m.get("cases") or {}):
        refuse(f"the manifest has no {task} case")
    case = m["cases"][task]
    base = case["base"]
    links = list((m.get("checkout") or {}).get("links") or [])
    if task == "gate":
        gate_cmd = (case.get("commands") or {}).get("gate") if isinstance(case.get("commands"), dict) else None
        if not isinstance(gate_cmd, str) or not gate_cmd.strip():
            refuse("cases.gate.commands.gate is not set (the command whose exit 0 passes the cell)")
        timeout = int(case["commands"].get("timeout_seconds", 900))
        invariants, required = case.get("invariants", []), case.get("required_paths", [])
        for key, v in (("invariants", invariants), ("required_paths", required)):
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                refuse(f"cases.gate.{key} must be a list of paths")
            for x in v:
                if not inside(x):
                    refuse(f"cases.gate.{key} names {x!r}, which is not a relative path inside the checkout")
        revs = (base,)
    else:
        accepted = m["accepted_fix"]
        paths, commands = m["paths"], m["commands"]
        sources = list(paths["source"])
        src_dir = paths["source_dir"].rstrip("/") + "/"
        new_test = re.compile(paths["new_test_pattern"])
        test_cmd, mode = commands["test"], commands.get("test_report", "exit-code")
        lint_cmd, timeout = commands.get("lint"), int(commands.get("timeout_seconds", 900))
        if task == "fix":
            test_file, acc_from, acc_to = paths["test_file"], paths["accepted_test"]["from"], paths["accepted_test"]["to"]
            allowed_extra, map_file = list(paths.get("allowed_extra") or []), paths.get("map_file")
        else:
            mutants = case.get("mutants", [])
            if not isinstance(mutants, list) or not all(isinstance(x, dict) and isinstance(x.get("id"), str) and x["id"] and isinstance(x.get("commit"), str)
                                                        for x in mutants):
                refuse("cases.pin.mutants must be a list of {id, commit}")
            ids = [x["id"] for x in mutants]
            twice = sorted({i for i in ids if ids.count(i) > 1})
            if twice:
                refuse(f"cases.pin.mutants names {', '.join(twice)} twice")
        revs = (accepted, base, *(x["commit"] for x in mutants))
except (OSError, ValueError, KeyError, TypeError) as e:
    refuse(f"manifest {manifest_path} unusable: {type(e).__name__} {e}")
if task != "gate" and mode not in ("exit-code", "vitest-json"):
    refuse(f"commands.test_report must be exit-code or vitest-json, not {mode!r}")
for rev in revs:
    if subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"], capture_output=True).returncode:
        refuse(f"{rev} is not a commit in the pack repository {repo}")

def show(rev, path):
    p = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True)
    return p.stdout if p.returncode == 0 else None

if mutants:  # a mutant only swaps paths.source: one whose files equal the base's adds nothing, one equal to the accepted fix's fails every pin
    src_base, src_acc = ({f: show(rev, f) for f in sources} for rev in (base, accepted))
    for mu in mutants:
        src = {f: show(mu["commit"], f) for f in sources}
        if src == src_base:
            refuse(f"cases.pin.mutants {mu['id']}: its paths.source files equal the base's, so it adds nothing to the base's red")
        if src == src_acc:
            refuse(f"cases.pin.mutants {mu['id']}: its paths.source files equal the accepted fix's, so no candidate's pin can be red at it")

def base_entries(*pathspec):
    """[(mode, type, blob id, file)] of the files at or under the pathspec in the case's base commit."""
    out = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "-z", "--full-tree", base, "--", *pathspec], capture_output=True,
                         encoding="utf-8", errors="surrogateescape").stdout
    return [(*e.split("\t", 1)[0].split(), e.split("\t", 1)[1]) for e in out.split("\0") if "\t" in e]

def base_blobs(path):
    """{file: blob id} of the files at or under path in the case's base commit."""
    return {f: oid for _, _, oid, f in base_entries(path)}

if task == "gate":
    base_inv = {x: base_blobs(x) for x in invariants}
    absent = [x for x, files in base_inv.items() if not files]
    if absent:
        refuse(f"cases.gate.invariants names {', '.join(absent)}, which the base {base} does not hold")

if not checkout.is_dir():
    print(json.dumps({"task": task, "error": "no checkout", "checkout": str(checkout)}))
    sys.exit(3)
cand = checkout.resolve()
if cand == pack_dir or pack_dir in cand.parents or cand in pack_dir.parents:
    refuse(f"the checkout {cand} shares a path with the pack {pack_dir} (proposal Item 2: the answer stays outside every candidate's paths)")

# No git runs on the candidate's .git as a repository. Any git that does reads the candidate's .git/config, which the
# candidate writes: a clean filter, .git/info/attributes, .git/info/exclude and its index's flags (skip-worktree,
# assume-unchanged) made a changed file read as the base's (review loop RL2-K1), and core.fsmonitor names a program git
# runs, as the grader, on any read of the index: it ran inside the grade after the view below was made and rewrote the
# view's config, attributes and index flags (RL3-K1). So the grade reads the checkout through two repositories of its
# own in a temporary directory, each with the host's config only (global and system) and none of git's repository
# variables (the wrapper unsets them):
# - the view (`vgit`): what the checkout's files are. Its work tree is the checkout, its objects are the pack
#   repository's (alternates), its index is the case's base tree, its attributes come from the base tree
#   (--attr-source, git 2.40+) and its ignore rules are the base tree's .gitignore files.
# - the history (`hgit`): what the candidate committed and staged. Its objects are the candidate's (alternates to
#   .git/objects, which git only reads), its index a copy of the candidate's .git/index (with any split-index file
#   beside it), and the commit it reads is the candidate's HEAD resolved from the files .git/HEAD, .git/refs and
#   .git/packed-refs. It has no work tree, so an index flag changes nothing it reports. The candidate's objects never
#   reach the view: a pack of the candidate's could otherwise stand in for the base tree the view's index is read from.
#   The history also reads the pack repository's objects, so it holds the base tree even when the candidate's history
#   no longer does (an amended root, then gc): its commits are compared with the base tree, not with its own root
#   (review loop RL4-K1: a replaced root commit that held a new file left the file out of every list).
# Every git of the grade runs with core.fsmonitor off, without replace refs and without commit-graph files, so no
# program, no object substitution and no history a commit-graph claims (git reads one from an alternate's
# objects/info: a forged one cut HEAD's parent, so HEAD read as its own root) comes from the host's config or the
# candidate's objects.
VIEW = tempfile.TemporaryDirectory(prefix="grade-view-", ignore_cleanup_errors=True)
view_dir, hist_dir = Path(VIEW.name) / "git", Path(VIEW.name) / "history"
SAFE = ["--no-replace-objects", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "-c", "core.commitGraph=false",
        "-c", "core.quotepath=off"]

def run_git(what, repo_args, args, cwd, stdin=None):
    p = subprocess.run(["git", *SAFE, *repo_args, *args], cwd=cwd, capture_output=True, input=stdin if stdin is not None else b"")
    if p.returncode:
        raise RuntimeError(f"git ({what}) {' '.join(args)}: {p.stderr.decode('utf-8', 'replace').strip()}")
    return p.stdout.decode("utf-8", "surrogateescape")

def vgit(*args, stdin=None):
    return run_git("view", [f"--git-dir={view_dir}", f"--work-tree={cand}", f"--attr-source={base}", "-c", "core.bare=false"], args, cand, stdin)

def hgit(*args):
    return run_git("history", [f"--git-dir={hist_dir}"], args, VIEW.name)

def vnames(*args):
    return [x for x in vgit(*args).split("\0") if x]

def hnames(*args):
    return [x for x in hgit(*args).split("\0") if x]

OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
REF = re.compile(r"refs/(?:[^/\x00-\x20\x7f~^:?*\[\\]+/)*[^/\x00-\x20\x7f~^:?*\[\\]+")

def plain_text(path):
    """The text of a regular file (not a link), None for anything else."""
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() and not path.is_symlink() else None

def cand_head():
    """(the candidate's HEAD commit id, None) read as files from its .git, or (None, why): HEAD holds an id or
    `ref: <name>`, and a name resolves through its loose ref file or its packed-refs line, up to five names deep."""
    gd = cand / ".git"
    if gd.is_symlink() or not gd.is_dir():
        return None, "the checkout's .git is not a directory"
    text = plain_text(gd / "HEAD")
    packed = None
    for _ in range(6):
        if text is None:
            return None, "HEAD names no commit (an unborn branch, or refs in a format other than files)"
        text = text.strip()
        if OID.fullmatch(text):
            return text, None
        if not text.startswith("ref: "):
            return None, f"HEAD is neither a commit id nor a ref: {text[:80]!r}"
        name = text[len("ref: "):].strip()
        if not REF.fullmatch(name) or ".." in name or "@{" in name or name.endswith((".lock", ".")):
            return None, f"HEAD names {name[:80]!r}, which is not a ref name"
        text = plain_text(gd / name)
        if text is None:
            if packed is None:
                packed = {}
                for ln in (plain_text(gd / "packed-refs") or "").splitlines():
                    if ln[:1] not in ("#", "^") and " " in ln:
                        oid, _, ref = ln.partition(" ")
                        packed.setdefault(ref.strip(), oid.strip())
            text = packed.get(name)
    return None, "HEAD's refs name each other more than five deep"

def exclude_line(gitignore_dir, line):
    """One line of the base's .gitignore in gitignore_dir ('' or 'a/b/') as a line of one exclude file read at the top:
    a pattern with a '/' before its end is relative to its own directory, any other may match at any depth below it,
    and a deeper file's lines come later, so they win as they do in git."""
    while line.endswith(" ") and not line.endswith("\\ "):  # git drops unescaped trailing spaces
        line = line[:-1]
    if not gitignore_dir or line in ("", "!") or line.startswith("#"):
        return line
    neg, body = (True, line[1:]) if line.startswith("!") else (False, line)
    core = body[:-1] if body.endswith("/") else body
    prefix = "/" + re.sub(r"([*?\[\\])", r"\\\1", gitignore_dir)
    return ("!" if neg else "") + prefix + (body[1:] if body.startswith("/") else body if "/" in core else "**/" + body)

def make_view():
    git_dir = subprocess.run(["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True,
                             encoding="utf-8", stdin=subprocess.DEVNULL).stdout.strip()
    for d in (view_dir, hist_dir):
        if subprocess.run(["git", "init", "-q", "--bare", "--template=", str(d)], cwd=VIEW.name, capture_output=True, stdin=subprocess.DEVNULL).returncode or not git_dir:
            refuse(f"no view repository could be made for the pack repository {repo}")
        (d / "objects" / "info").mkdir(parents=True, exist_ok=True)
    (view_dir / "objects" / "info" / "alternates").write_bytes((Path(git_dir) / "objects").as_posix().encode("utf-8") + b"\n")
    # the history: the candidate's objects and the pack repository's (both read only) and a copy of the candidate's
    # index; git treats a missing index as empty, as the candidate's own git did
    (hist_dir / "objects" / "info" / "alternates").write_bytes(b"".join(p.as_posix().encode("utf-8") + b"\n"
                                                                         for p in (cand / ".git" / "objects", Path(git_dir) / "objects")))
    for f in [cand / ".git" / "index", *sorted((cand / ".git").glob("sharedindex.*"))]:
        if f.is_file() and not f.is_symlink():
            shutil.copyfile(f, hist_dir / f.name)
    lines = []
    ignores = [(mode, oid, f) for mode, kind, oid, f in base_entries() if kind == "blob" and mode != "120000" and f.rsplit("/", 1)[-1] == ".gitignore"]
    for mode, oid, f in sorted(ignores, key=lambda e: (e[2].count("/"), e[2])):
        text = subprocess.run(["git", "-C", str(repo), "cat-file", "blob", oid], capture_output=True).stdout.decode("utf-8", "surrogateescape")
        lines += [exclude_line(f[: -len(".gitignore")], ln.rstrip("\r")) for ln in text.removeprefix("﻿").split("\n")]
    (view_dir / "info").mkdir(exist_ok=True)
    (view_dir / "info" / "base-excludes").write_bytes("\n".join(lines).encode("utf-8", "surrogateescape") + b"\n")
    try:
        vgit("read-tree", base)
        vgit("update-index", "-q", "--refresh")
    except RuntimeError as e:
        refuse(f"no view of the checkout (it needs git 2.40+, for --attr-source): {e}")

def view_others(*pathspec):
    """The checkout's files that are not in the base tree and that the base tree's .gitignore rules do not ignore."""
    return vnames("ls-files", "--others", "-z", f"--exclude-from={view_dir / 'info' / 'base-excludes'}", "--", *pathspec)

C_ESCAPES = {0x5C: b"\\\\", 0x22: b'\\"', 0x0A: b"\\n", 0x09: b"\\t", 0x0D: b"\\r"}

def c_quoted(f):
    """f as hash-object --stdin-paths reads it: C-quoted when it starts with a quote or holds a backslash or a control
    character, as is otherwise."""
    raw = f.encode("utf-8", "surrogateescape")
    if not (raw.startswith(b'"') or any(b == 0x5C or b < 0x20 or b == 0x7F for b in raw)):
        return raw
    return b'"' + b"".join(C_ESCAPES.get(b) or (b"\\%03o" % b if b < 0x20 or b == 0x7F else bytes([b])) for b in raw) + b'"'

def hash_paths(files):
    """The view's blob id of each file, as git would store it at the base: one hash-object reading the paths on stdin (a
    Windows command line holds at most 32,767 characters, so a list of arguments failed on a large directory, RL2-K2)."""
    if not files:
        return []
    ids = vgit("hash-object", "--stdin-paths", stdin=b"".join(c_quoted(f) + b"\n" for f in files)).split()
    if len(ids) != len(files):
        raise RuntimeError(f"git (view) hash-object returned {len(ids)} ids for {len(files)} files")
    return ids

def run_bash(cmd):
    """The exit code of `bash -c cmd` in the checkout, 124 when it overruns the timeout. A timeout kills the command's
    whole process tree (taskkill /T on Windows, the process group elsewhere): killing bash alone would leave a node or
    python child writing into the checkout after the grade."""
    p = subprocess.Popen(["bash", "-c", cmd], cwd=cand, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=os.name != "nt")
    try:
        return p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
            else:
                os.killpg(p.pid, signal.SIGKILL)
        except (OSError, subprocess.SubprocessError):
            pass
        p.kill()
        p.wait()
        return 124

head_id, why = cand_head()
if head_id is None:
    print(json.dumps({"task": task, "error": f"no commit in the checkout: {why}"}))
    sys.exit(3)
make_view()
try:
    hgit("rev-parse", "--verify", "--quiet", f"{head_id}^{{commit}}")
    roots = hgit("rev-list", "--max-parents=0", head_id).split()
    head = hgit("rev-parse", "--short", head_id).strip()
except RuntimeError as e:
    print(json.dumps({"task": task, "error": f"no commit in the checkout: HEAD {head_id} is not a commit in its objects: {e}"}))
    sys.exit(3)
# The checkout's history is one root commit holding the base tree (historyless-checkout.sh), but the candidate writes
# that history: an amend of the root, or an orphan root, puts its own files in a root. So nothing is read against a
# root: committed and added compare HEAD with the base tree, baseRoot says whether the history still starts at the base
# (exactly one root, holding the base tree), and commits counts the commits on top of that root (0 when there is none).
base_tree = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", f"{base}^{{tree}}"], capture_output=True,
                           encoding="utf-8", stdin=subprocess.DEVNULL).stdout.strip()
if not OID.fullmatch(base_tree):
    refuse(f"no tree for the base {base} in the pack repository {repo}")
base_root = len(roots) == 1 and hgit("rev-parse", "--verify", f"{roots[0]}^{{tree}}").strip() == base_tree
commits = int(hgit("rev-list", "--count", f"{roots[0]}..{head_id}")) if base_root else 0
# committed: HEAD's files that differ from the base tree, renames as both names; staged: the copied index against HEAD;
# changed adds the view's diff-files (the checkout against the base tree), which holds every base file the work tree
# changes, so nothing is read against the candidate's index flags, and every file on disk the base does not hold that
# the candidate's index does (it is not untracked, so it must be changed: RL4-K1)
committed = hnames("diff-tree", "-r", "-z", "--name-only", "--no-renames", base_tree, head_id)
staged = hnames("diff-index", "--cached", "-z", "--name-only", "--no-renames", head_id)
indexed = set(hnames("ls-files", "-z"))
others = [f for f in view_others() if not any(f == ln or f.startswith(ln + "/") for ln in links)]
changed = sorted(set(committed + staged + vnames("diff-files", "--name-only", "-z") + [f for f in others if f in indexed]))
untracked = sorted(f for f in others if f not in indexed)

if task == "gate":
    def cand_blobs(path):
        """{file: blob id or None} of the checkout's files at or under path as it stands: the base's (None when deleted
        or no longer a plain file), the ones the candidate committed (HEAD against the base tree) or holds in its index,
        ignored or not, and the others the base's ignore rules do not ignore; each hashed by the view as git would store
        it at the base, so a host's line-ending conversion reads as the same content and nothing in the candidate's .git
        changes what is read. A committed or indexed file the base does not hold counts on disk or not (None): reading
        only the index missed an ignored file committed and then unstaged, still in HEAD and on disk (RL5-K1)."""
        files = sorted(set(base_inv[path]) | set(hnames("diff-tree", "-r", "-z", "--name-only", "--no-renames", base_tree, head_id, "--", path))
                       | set(hnames("ls-files", "-z", "--", path)) | set(view_others(path)))
        present = [f for f in files if (cand / f).is_file() and not (cand / f).is_symlink()]
        blobs = dict(zip(present, hash_paths(present)))
        return {f: blobs.get(f) for f in files}

    intact = {x: cand_blobs(x) == base_inv[x] for x in invariants}
    present = {x: (cand / x).exists() for x in required}
    gate_exit = run_bash(gate_cmd)
    result = {"task": task, "head": head, "baseRoot": base_root, "commits": commits, "changed": changed, "staged": staged,
              "untracked": untracked, "gateExit": gate_exit, "invariantsIntact": intact, "requiredPresent": present, "committed": commits > 0,
              "PASS": gate_exit == 0 and all(intact.values()) and all(present.values()) and commits > 0}
    print(json.dumps(result, indent=1))
    sys.exit(0)

# added: a file HEAD or the index adds to the base tree (a rename is not an addition: -M, as git diff's default
# diff.renames)
added = (hnames("diff-tree", "-r", "-z", "--name-only", "-M", "--diff-filter=A", base_tree, head_id)
         + hnames("diff-index", "--cached", "-z", "--name-only", "-M", "--diff-filter=A", head_id))
new_tests = sorted({f for f in added + untracked if new_test.search(f)} - ({acc_to} if task == "fix" else set()))

def run_tests(files):
    if not files:
        return {"passed": None, "failed": None, "total": None, "exit": None, "error": "no test files"}
    with tempfile.TemporaryDirectory() as td:
        report = Path(td) / "report.json"
        cmd = test_cmd.replace("{files}", " ".join(shlex.quote(f) for f in files)).replace("{report}", shlex.quote(str(report)))
        code = run_bash(cmd)
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
    return "ok" if run_bash(cmd) == 0 else "fail"

saved = {f: ((cand / f).read_bytes() if (cand / f).is_file() else None) for f in sources}
saved_mtime = {f: (cand / f).stat().st_mtime_ns for f in sources if (cand / f).is_file()}

# Every swap gives the swapped files an mtime of their own, two seconds past the last one, so a runner that validates a
# cache by mtime and size (Python's __pycache__ keeps the mtime in whole seconds) never runs the previous version of a
# same-size file; the original mtimes go back at the end.
STEP_NS = 2_000_000_000
clock = [max([time.time_ns(), *saved_mtime.values()])]

def stamp():
    clock[0] += STEP_NS
    for f in sources:
        if (cand / f).is_file():
            os.utime(cand / f, ns=(clock[0], clock[0]))

def put(rev):
    for f in sources:
        data, path = show(rev, f), cand / f
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    stamp()

def restore(final=False):
    for f, data in saved.items():
        path = cand / f
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(data)
    if not final:
        stamp()
        return
    for f, ns in saved_mtime.items():
        os.utime(cand / f, ns=(ns, ns))

result = {"task": task, "head": head, "baseRoot": base_root, "commits": commits, "changed": changed, "staged": staged, "untracked": untracked}
try:
    if task == "pin":
        files = new_tests
        at_head = run_tests(files)
        at_mutants = {}
        for mu in mutants:  # each mutant's source swapped in turn, with its own mtime step
            put(mu["commit"])
            at_mutants[mu["id"]] = run_tests(files)
        put(accepted)
        with_fix = run_tests(files)
        restore()
        lint_res = lint(files) if files else "fail"
        src_touched = sorted({f for f in changed + untracked if f.startswith(src_dir)})
        r_red, r_green, clean = red(at_head), green(with_fix), not src_touched
        r_mut = {k: red(v) for k, v in at_mutants.items()}
        result.update(srcTouched=src_touched, testFiles=files, atHead=at_head, withAcceptedFix=with_fix, lint=lint_res,
                      redAtHead=r_red, greenWithFix=r_green, srcClean=clean, committed=commits > 0)
        if mutants:
            result.update(atMutants=at_mutants, redAtMutants=r_mut)
        result["PASS"] = bool(files) and r_red and r_green and clean and lint_res in ("ok", "none") and all(r_mut.values())
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
        diff = vgit("diff", "--no-ext-diff", "--no-textconv", "--no-color", base, "--", *sources)
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
    restore(final=True)
restored = (all(((cand / f).read_bytes() if (cand / f).is_file() else None) == data for f, data in saved.items())
            and all((cand / f).stat().st_mtime_ns == ns for f, ns in saved_mtime.items()))
result["restored"] = restored
if not restored:
    print(f"grade.sh: WARNING: the source files in {cand} were not restored", file=sys.stderr)
print(json.dumps(result, indent=1))
PY
