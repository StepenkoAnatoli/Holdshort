#!/usr/bin/env bash
# Lineage: generalises the mechanical grader of calibration runs 1-3 (pin and fix cells graded against the pack's base
# and accepted trees). Everything run 3 hard-coded - the source and accepted revisions, the source and test paths, the
# scope rule, the test and lint commands, the output location - now comes from the subject-pack manifest; the grade
# goes to stdout. The grading logic is the Python program below (a quoted heredoc: no shell value is spliced into it).
#
# usage: grade.sh [--links SEAL] MANIFEST pin|fix|gate CHECKOUT > GRADES_DIR/<case>-<profile>.json
#        grade.sh --seal NAME=DIR... > SEAL
#
#   MANIFEST      the subject pack's manifest.json (format: tools/calibration/subject-pack/README.md)
#   pin|fix|gate  the case; a review is graded by the grader agent, not here
#   CHECKOUT      the candidate's history-less checkout (historyless-checkout.sh), graded in place: the grade swaps the
#                 manifest's source files for the accepted, base or mutant versions while it runs the tests and restores
#                 them; each swap gives the files a fresh mtime two seconds past the last, so a cache keyed on mtime and
#                 size (Python's __pycache__) never runs a previous version, and the original mtimes go back at the end.
#                 Each command runs with every path the base tree lacks set aside (moved into the checkout's .git),
#                 ignored or not, unless the grade counts it as the candidate's (changed, a new test, a path the case
#                 names) or it is a linked name: the commands see only what the grade lists (setAside; review loop RL9-K1)
#   --links SEAL  needed when the manifest has checkout.links: the seal the host made of each linked directory with
#                 --seal right after installing it, before any candidate ran, and kept outside every checkout and linked
#                 directory. The test, lint and gate commands run from those trees, and a candidate can write them
#                 (through the link, or by putting a directory of its own at the name), so each name in the checkout is
#                 read by content before the first command and after the last: a name the checkout holds must hold the
#                 sealed content (linksIntact: {name: bool}; PASS needs every one true), and only an intact name is left
#                 out of `changed` and `untracked` (review loop RL8-K2)
#   --seal        print the seal of each NAME=DIR: a SHA-256 over every entry under DIR (DIR followed, nothing below it:
#                 each entry's path and kind, a file's bytes and executable bits, a link's target as text)
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
# index entries, its HEAD and refs read as files: no git ever runs on the candidate's .git as a repository, so nothing
# in its config, attributes, excludes or hooks (the candidate's to write) is applied or run.
# That second git holds only objects filed under the id git computed from their content (the base tree's from the pack
# repository, the candidate's copied), so no object the candidate stores under another object's id is read (review
# loop RL8-K1). What the candidate committed is read against the case's base tree, never against a root commit the
# candidate can replace (an amend of the checkout's single commit, an orphan root), and every file on disk that the
# base lacks and the candidate's index holds counts as changed.
#
# Exit 0 with the grade (PASS true or false) as one JSON object; 2 on a bad argument, an unusable manifest or seal, or
# a checkout that shares a path with the pack; 3 with {"error": ...} when the checkout is missing, has no commit, or
# its history or index cannot be read.
set -u
[ $# -ge 1 ] || { echo "usage: grade.sh [--links SEAL] MANIFEST pin|fix|gate CHECKOUT | grade.sh --seal NAME=DIR..." >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "grade.sh: python3 not found" >&2; exit 2; }
# none of git's repository variables (GIT_DIR, GIT_INDEX_FILE, ...) nor GIT_ATTR_SOURCE reaches the grade's git: each
# git it runs names its repository itself (the pack, the checkout or the view below)
unset GIT_ATTR_SOURCE $(git rev-parse --local-env-vars 2>/dev/null)
exec python3 -I - "$@" <<'PY'
import hashlib, json, os, re, shlex, shutil, signal, stat, struct, subprocess, sys, tempfile, time, zlib
from pathlib import Path

def refuse(msg, code=2):
    print(f"grade.sh: refused: {msg}", file=sys.stderr)
    sys.exit(code)

USAGE = "usage: grade.sh [--links SEAL] MANIFEST pin|fix|gate CHECKOUT | grade.sh --seal NAME=DIR..."

def is_link(path, st):
    """A symlink, a junction or any other reparse point (Windows): a link of any kind, never followed below the top."""
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)

def tree_seal(top):
    """The seal of the tree at top (top followed when it is a link, nothing below it): a SHA-256 over each entry in
    name order - its path below top, its kind, a file's bytes (and executable bits off Windows), a link's target as
    text - so a file edited, added, removed or renamed, or a link led elsewhere, changes it (review loop RL8-K2)."""
    h = hashlib.sha256()

    def walk(d, rel):
        with os.scandir(d) as it:
            entries = sorted(it, key=lambda e: e.name)
        for e in entries:
            r = rel + os.fsencode(e.name)
            st = e.stat(follow_symlinks=False)
            if is_link(e.path, st):
                h.update(b"L\0" + r + b"\0" + os.fsencode(os.readlink(e.path)) + b"\0")
            elif stat.S_ISDIR(st.st_mode):
                h.update(b"D\0" + r + b"\0")
                walk(e.path, r + b"/")
            elif stat.S_ISREG(st.st_mode):
                fh = hashlib.sha256()
                with open(e.path, "rb") as f:
                    if st.st_size <= 1 << 24:
                        fh.update(f.read())
                    else:
                        for chunk in iter(lambda: f.read(1 << 24), b""):
                            fh.update(chunk)
                x = b"%o" % (st.st_mode & 0o111) if os.name != "nt" else b""
                h.update(b"F\0" + r + b"\0" + x + b"\0" + fh.digest())
            else:
                h.update(b"O\0" + r + b"\0")
    walk(top, b"")
    return h.hexdigest()

args = sys.argv[1:]
if args[:1] == ["--seal"]:
    seal = {}
    for spec in args[1:]:
        name, eq, d = spec.partition("=")
        if not eq or not name or not d or name in seal:
            refuse(f"--seal takes NAME=DIR, each NAME once, not {spec!r}")
        if not os.path.isdir(d):
            refuse(f"--seal {spec}: {d} is not a directory")
        try:
            seal[name] = tree_seal(d)
        except OSError as e:
            refuse(f"--seal {spec}: {d} cannot be read: {e}")
    if not seal:
        refuse(USAGE)
    print(json.dumps({"seal": 1, "links": seal}, indent=1))
    sys.exit(0)
seal_path = None
if args[:1] == ["--links"]:
    if len(args) < 2:
        refuse(USAGE)
    seal_path, args = Path(args[1]), args[2:]
if len(args) != 3:
    refuse(USAGE)
manifest_path, task, checkout = Path(args[0]), args[1], Path(args[2])
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
# checkout.links: the commands run from those trees and the candidate can write them, so each is graded against the
# host's seal (RL8-K2); a grade without one would trust whatever the candidate left there
sealed = {}
if links and seal_path is None:
    refuse(f"the manifest has checkout.links ({', '.join(links)}): the grade needs --links SEAL, the seal grade.sh --seal made of "
           "each linked directory before any candidate ran")
if seal_path is not None:
    try:
        s = json.loads(seal_path.read_text(encoding="utf-8"))
        sealed = s["links"] if s.get("seal") == 1 and isinstance(s.get("links"), dict) else None
    except (OSError, ValueError, AttributeError) as e:
        refuse(f"--links {seal_path} unusable: {type(e).__name__} {e}")
    if sealed is None or not all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) for v in sealed.values()):
        refuse(f"--links {seal_path} is not a seal grade.sh --seal made")
    if sorted(sealed) != sorted(links):
        refuse(f"--links {seal_path} seals {', '.join(sorted(sealed)) or 'nothing'}, the manifest's checkout.links are "
               f"{', '.join(sorted(links)) or 'none'}")

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
# - the history (`hgit`): what the candidate committed and staged. It holds objects of its own only, no alternates,
#   each filed by git index-pack under the id it computes from the object's content: git reads an object by the id a
#   store files it under and never checks that id on most reads (diff-tree, ls-tree), so a forged object under the base
#   tree's id, in the candidate's store ahead of the pack repository's, made committed and added read the candidate's
#   files as the base's (review loop RL8-K1). The base tree's trees and blobs come from the pack repository, first, so
#   it holds the base tree even when the candidate's history no longer does (an amended root, then gc): its commits are
#   compared with the base tree, not with its own root (RL4-K1: a replaced root commit that held a new file left the
#   file out of every list). Then every object of the candidate's (a copy of .git/objects' loose objects and packs,
#   nothing its info/alternates names) filed under an id the base's objects do not hold; one filed under another
#   object's id lands under its own. A commit the candidate does not hold is not there, though the pack repository
#   holds it. Its index holds the
#   entries of a copy of the candidate's .git/index (with any split-index file beside it), each written again, so no
#   cache tree the candidate wrote is read (a TREE extension claiming a directory still matches HEAD hid a staged file
#   from diff-index --cached). The commit it reads is the candidate's HEAD resolved from the files
#   .git/HEAD, .git/refs and .git/packed-refs. It has no work tree. The candidate's objects never reach the view.
# Every git of the grade runs with core.fsmonitor off, without replace refs and without commit-graph files, so no
# program, no object substitution and no history a commit-graph claims (git reads one from an alternate's
# objects/info: a forged one cut HEAD's parent, so HEAD read as its own root) comes from the host's config or the
# candidate's objects.
VIEW = tempfile.TemporaryDirectory(prefix="grade-view-", ignore_cleanup_errors=True)
view_dir, hist_dir = Path(VIEW.name) / "git", Path(VIEW.name) / "history"
SAFE = ["--no-replace-objects", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "-c", "core.commitGraph=false",
        "-c", "core.quotepath=off"]
OBJECT_FORMAT = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-object-format"], capture_output=True, encoding="utf-8",
                               stdin=subprocess.DEVNULL).stdout.strip() or "sha1"
if OBJECT_FORMAT not in ("sha1", "sha256"):
    refuse(f"the pack repository {repo} stores objects as {OBJECT_FORMAT}, which the grade does not read")

def run_git(what, repo_args, args, cwd, stdin=None):
    p = subprocess.run(["git", *SAFE, *repo_args, *args], cwd=cwd, capture_output=True, input=stdin if stdin is not None else b"")
    if p.returncode:
        raise RuntimeError(f"git ({what}) {' '.join(args)}: {p.stderr.decode('utf-8', 'replace').strip()}")
    return p.stdout.decode("utf-8", "surrogateescape")

def vgit(*args, stdin=None):
    return run_git("view", [f"--git-dir={view_dir}", f"--work-tree={cand}", f"--attr-source={base}", "-c", "core.bare=false"], args, cand, stdin)

def unreadable(what):
    """Exit 3: the candidate's history or index, which it writes, cannot be read (no grade, no traceback)."""
    print(json.dumps({"task": task, "error": f"the checkout's history cannot be read: {what}"}))
    sys.exit(3)

def hgit(*args, stdin=None):
    try:
        return run_git("history", [f"--git-dir={hist_dir}"], args, VIEW.name, stdin)
    except RuntimeError as e:
        unreadable(e)

PACK_TYPES = {b"commit": 1, b"tree": 2, b"blob": 3, b"tag": 4}

def batch_objects(cmd, stdin):
    """(the id it is filed under, type, bytes) of each object `git cat-file --batch` prints."""
    p = subprocess.Popen(cmd, cwd=VIEW.name, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while line := p.stdout.readline():
            head = line.split()
            if len(head) != 3 or not head[2].isdigit():
                continue  # "<id> missing", or a line git could not read as an object
            oid, kind, size = head[0].decode("ascii", "replace"), head[1], int(head[2])
            data = p.stdout.read(size)
            p.stdout.read(1)
            if kind in PACK_TYPES and len(data) == size:
                yield oid, kind, data
    finally:
        p.stdout.close()
        p.wait()

def copy_store(src, dst):
    """The loose objects and the packs (.pack with its .idx) of the object directory src, copied to dst: regular files
    only, no link followed, nothing else (no info/alternates, commit-graph, multi-pack-index or bitmap)."""
    (dst / "pack").mkdir(parents=True, exist_ok=True)
    if src.is_symlink() or not src.is_dir():
        return
    for d in sorted(src.iterdir()):
        if d.is_symlink() or not d.is_dir():
            continue
        if re.fullmatch(r"[0-9a-f]{2}", d.name):
            for f in d.iterdir():
                if re.fullmatch(r"[0-9a-f]{38}|[0-9a-f]{62}", f.name) and f.is_file() and not f.is_symlink():
                    (dst / d.name).mkdir(exist_ok=True)
                    shutil.copyfile(f, dst / d.name / f.name)
        elif d.name == "pack":
            for f in d.glob("pack-*.pack"):
                idx = f.with_suffix(".idx")
                if all(x.is_file() and not x.is_symlink() for x in (f, idx)):
                    shutil.copyfile(f, dst / "pack" / f.name)
                    shutil.copyfile(idx, dst / "pack" / idx.name)

def make_history():
    """The history's objects - the base tree's trees and blobs from the pack repository, then every object of the
    candidate's whose id none of those holds - written as one pack that git index-pack files, each object under the id
    it computes from the object's type and bytes; and its index: the candidate's entries, each written again."""
    raw = Path(VIEW.name) / "candidate-objects"
    copy_store(cand / ".git" / "objects", raw / "objects")
    for sub in ("refs", "info"):
        (raw / sub).mkdir(parents=True, exist_ok=True)
    (raw / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (raw / "config").write_text(f"[core]\n\trepositoryformatversion = {1 if OBJECT_FORMAT != 'sha1' else 0}\n\tbare = true\n"
                                + (f"[extensions]\n\tobjectformat = {OBJECT_FORMAT}\n" if OBJECT_FORMAT != "sha1" else ""), encoding="utf-8")
    base_ids = Path(VIEW.name) / "base-ids"
    ls = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "-t", "-z", base_tree], capture_output=True, stdin=subprocess.DEVNULL)
    if ls.returncode:
        refuse(f"the base tree {base_tree} cannot be read from the pack repository {repo}")
    ids = [base_tree] + [e.split(b"\t", 1)[0].split()[2].decode("ascii") for e in ls.stdout.split(b"\0")
                         if b"\t" in e and e.split(b"\t", 1)[0].split()[1] in (b"tree", b"blob")]
    base_ids.write_text("".join(i + "\n" for i in ids), encoding="ascii")
    body, seen = Path(VIEW.name) / "objects.body", set()
    with open(body, "wb") as out, open(base_ids, "rb") as base_in:
        for source in (batch_objects(["git", *SAFE, "-C", str(repo), "cat-file", "--batch"], base_in),
                       batch_objects(["git", *SAFE, f"--git-dir={raw}", "cat-file", "--batch-all-objects", "--batch", "--unordered"],
                                     subprocess.DEVNULL)):
            for oid, kind, data in source:
                if oid in seen:
                    continue
                seen.add(oid)
                n, header = len(data), bytearray([PACK_TYPES[kind] << 4 | len(data) & 0x0F])
                n >>= 4
                while n:
                    header[-1] |= 0x80
                    header.append(n & 0x7F)
                    n >>= 7
                out.write(bytes(header) + zlib.compress(data, 1))
    if base_tree not in seen:
        refuse(f"the base tree {base_tree} cannot be read from the pack repository {repo}")
    pack = Path(VIEW.name) / "objects.pack"
    h = hashlib.new(OBJECT_FORMAT)
    with open(pack, "wb") as out, open(body, "rb") as src:
        for chunk in [b"PACK" + struct.pack(">II", 2, len(seen))]:
            h.update(chunk)
            out.write(chunk)
        while chunk := src.read(1 << 20):
            h.update(chunk)
            out.write(chunk)
        out.write(h.digest())
    body.unlink()
    with open(pack, "rb") as f:
        p = subprocess.run(["git", *SAFE, f"--git-dir={hist_dir}", "index-pack", "--stdin"], cwd=VIEW.name, stdin=f, capture_output=True)
    if p.returncode:
        unreadable(f"its objects could not be indexed: {p.stderr.decode('utf-8', 'replace').strip()}")
    shutil.rmtree(raw, ignore_errors=True)
    pack.unlink()
    # the index: its entries (mode, id, stage, path) read from a copy, then written into a new one; git treats a
    # missing index as empty, as the candidate's own git did. The copy sits where the history's git looks for its
    # index by default, so no variable names it (the grade's environment is passed on unchanged, review loop RL8 K3);
    # it and its shared parts are removed before the new index is written in the same place
    copied = hist_dir / "index"
    parts = []
    for f in [cand / ".git" / "index", *sorted((cand / ".git").glob("sharedindex.*"))]:
        if f.is_file() and not f.is_symlink():
            parts.append(copied if f.name == "index" else hist_dir / f.name)
            shutil.copyfile(f, parts[-1])
    if copied.is_file():
        try:
            entries = run_git("history", [f"--git-dir={hist_dir}"], ["ls-files", "-s", "-z"], VIEW.name)
        except RuntimeError as e:
            unreadable(f"its index: {e}")
        for f in parts:
            f.unlink()
        hgit("update-index", "-z", "--index-info", stdin=entries.encode("utf-8", "surrogateescape"))

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
        if subprocess.run(["git", "init", "-q", "--bare", "--template=", f"--object-format={OBJECT_FORMAT}", str(d)], cwd=VIEW.name,
                          capture_output=True, stdin=subprocess.DEVNULL).returncode or not git_dir:
            refuse(f"no view repository could be made for the pack repository {repo}")
        (d / "objects" / "info").mkdir(parents=True, exist_ok=True)
    (view_dir / "objects" / "info" / "alternates").write_bytes((Path(git_dir) / "objects").as_posix().encode("utf-8") + b"\n")
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

def run_bash(cmd, keep_also=()):
    """The exit code of `bash -c cmd` in the checkout, 124 when it overruns the timeout, run with every path the grade
    does not count set aside (RL9-K1; keep_also: more paths it runs, the accepted test). A timeout kills the command's
    whole process tree (taskkill /T on Windows, the process group elsewhere): killing bash alone would leave a node or
    python child writing into the checkout after the grade."""
    set_aside(KEEP | set(keep_also))
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
base_tree = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", f"{base}^{{tree}}"], capture_output=True,
                           encoding="utf-8", stdin=subprocess.DEVNULL).stdout.strip()
if not OID.fullmatch(base_tree):
    refuse(f"no tree for the base {base} in the pack repository {repo}")
make_view()
make_history()
try:
    run_git("history", [f"--git-dir={hist_dir}"], ["rev-parse", "--verify", "--quiet", f"{head_id}^{{commit}}"], VIEW.name)
except RuntimeError as e:
    print(json.dumps({"task": task, "error": f"no commit in the checkout: HEAD {head_id} is not a commit in its objects: {e}"}))
    sys.exit(3)
roots = hgit("rev-list", "--max-parents=0", head_id).split()
head = hgit("rev-parse", "--short", head_id).strip()
# The checkout's history is one root commit holding the base tree (historyless-checkout.sh), but the candidate writes
# that history: an amend of the root, or an orphan root, puts its own files in a root. So nothing is read against a
# root: committed and added compare HEAD with the base tree, baseRoot says whether the history still starts at the base
# (exactly one root, holding the base tree), and commits counts the commits on top of that root (0 when there is none).
base_root = len(roots) == 1 and hgit("rev-parse", "--verify", f"{roots[0]}^{{tree}}").strip() == base_tree
commits = int(hgit("rev-list", "--count", f"{roots[0]}..{head_id}")) if base_root else 0
# committed: HEAD's files that differ from the base tree, renames as both names; staged: the copied index against HEAD;
# changed adds the view's diff-files (the checkout against the base tree), which holds every base file the work tree
# changes, so nothing is read against the candidate's index flags, and every file on disk the base does not hold that
# the candidate's index does (it is not untracked, so it must be changed: RL4-K1)
committed = hnames("diff-tree", "-r", "-z", "--name-only", "--no-renames", base_tree, head_id)
staged = hnames("diff-index", "--cached", "-z", "--name-only", "--no-renames", head_id)
indexed = set(hnames("ls-files", "-z"))

# checkout.links (RL8-K2): the test, lint and gate commands run from those trees, and the candidate can write them
# (through the link, or by putting a tree of its own at the name), so each name the checkout holds is read by content
# against the host's seal before the first command and after the last; a name the checkout no longer holds runs
# nothing of the host's and counts as intact. The commands run the candidate's code, which can change what a command
# reports as it runs (and undo a change before the read after the last command): the seal grades what the candidate
# left on disk, not what its code does while the grade runs.
link_reads = []

def read_links():
    if not links:
        return
    seen = {}
    for name in links:
        top = cand / name
        if not os.path.lexists(top):
            seen[name] = True
            continue
        try:
            seen[name] = top.is_dir() and tree_seal(top) == sealed[name]
        except OSError:
            seen[name] = False
    link_reads.append(seen)

def links_intact():
    return {name: all(r[name] for r in link_reads) for name in links}

read_links()
others = [f for f in view_others() if not any((f == ln or f.startswith(ln + "/")) and link_reads[0][ln] for ln in links)]
changed = sorted(set(committed + staged + vnames("diff-files", "--name-only", "-z") + [f for f in others if f in indexed]))
untracked = sorted(f for f in others if f not in indexed)

# Set aside (review loop RL9-K1): the commands resolve modules, configs and runners from the files on disk, not from the
# grade's lists, and a file the base lacks that is in no list the grade checks decided what they ran: an ignored nested
# tests/node_modules/esbuild beat the sealed install for the accepted test (node looks in the importing file's own
# directory first), an unchecked-hash .pyc in an ignored __pycache__ stood in for the accepted test, and an untracked
# unittest.py at the top stood in for the runner (python -m puts the working directory first). So before each command
# every path the base tree lacks - ignored or not, at any depth - that is neither a file the grade counts as the
# candidate's (changed, a new test, a path the case names) nor a linked name is moved into a directory of its own
# inside the checkout's .git, where no resolution looks; the commands see the base, the counted files and the linked
# trees only. What the candidate left (setAside) is put back after the last command, in place of anything a command
# wrote there; what a command wrote and the next one would see is set aside and removed. A path that cannot be moved is
# listed in notSetAside and fails the cell.
aside = {"dir": None, "left": [], "out": [], "failed": []}

def remove_entry(p):
    """Remove the file, link or directory p, never following a link."""
    st = os.lstat(p)
    if stat.S_ISDIR(st.st_mode) and not is_link(p, st):
        shutil.rmtree(p)
    else:
        try:
            os.unlink(p)
        except OSError:
            os.rmdir(p)  # a directory link or junction on Windows

def set_aside(keep, first=False):
    """Move every path the base tree lacks, other than keep and the linked names, out of the checkout's tree."""
    keep = set(keep) | set(links)
    above = {"/".join(k.split("/")[:i]) for k in keep for i in range(1, k.count("/") + 1)}
    found = []

    def visit(name, is_dir):
        if any(name == k or name.startswith(k + "/") for k in keep):
            return
        if is_dir and name in above:  # a directory that holds a kept path: only its other entries go
            with os.scandir(cand / name) as it:
                for e in sorted(it, key=lambda e: e.name):
                    st = e.stat(follow_symlinks=False)
                    visit(f"{name}/{e.name}", stat.S_ISDIR(st.st_mode) and not is_link(e.path, st))
            return
        found.append(name)

    # no exclude file: every path the view's index (the base tree) lacks, a wholly new directory as one entry
    for e in vnames("ls-files", "--others", "--directory", "-z"):
        visit(e.rstrip("/"), e.endswith("/"))
    for name in found:
        dest = None
        try:
            if aside["dir"] is None:
                aside["dir"] = Path(tempfile.mkdtemp(prefix="grade-aside-", dir=cand / ".git"))
            dest = aside["dir"] / str(len(aside["left"]) + len(aside["out"]))
            for attempt in range(5):
                try:
                    os.rename(cand / name, dest)
                    break
                except FileNotFoundError:
                    raise
                except OSError:
                    if attempt == 4:
                        raise
                    time.sleep(0.2)
        except FileNotFoundError:
            continue
        except OSError:
            aside["failed"].append(name)
            continue
        (aside["left"] if first else aside["out"]).append((name, dest))
    return found

def put_back():
    """Put back what the candidate left, in place of anything a command wrote at its path, through real directories of
    the checkout only; remove what the commands wrote. True when every path went back."""
    ok = True
    for name, dest in aside["left"]:
        target, parent = cand / name, cand
        try:
            for part in name.split("/")[:-1]:
                parent = parent / part
                if not os.path.lexists(parent):
                    parent.mkdir()
                st = os.lstat(parent)
                if not stat.S_ISDIR(st.st_mode) or is_link(parent, st):
                    raise OSError(f"{parent} is not a directory of the checkout")
            if os.path.lexists(target):
                remove_entry(target)
            os.rename(dest, target)
        except OSError as e:
            ok = False
            print(f"grade.sh: WARNING: {name} was not put back ({e}); it is in {dest}", file=sys.stderr)
    for name, dest in aside["out"]:
        try:
            remove_entry(dest)
        except OSError:
            pass
    if ok and aside["dir"] is not None:
        shutil.rmtree(aside["dir"], ignore_errors=True)
    return ok

KEEP = set(changed)

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
    KEEP |= {x.replace("\\", "/").rstrip("/") for x in required}
    set_aside(KEEP, first=True)
    try:
        gate_exit = run_bash(gate_cmd)
    finally:
        back = put_back()
    read_links()
    result = {"task": task, "head": head, "baseRoot": base_root, "commits": commits, "changed": changed, "staged": staged,
              "untracked": untracked, "setAside": sorted(n for n, _ in aside["left"]), "gateExit": gate_exit, "invariantsIntact": intact,
              "requiredPresent": present, "committed": commits > 0,
              "PASS": (gate_exit == 0 and all(intact.values()) and all(present.values()) and commits > 0 and all(links_intact().values())
                       and not aside["failed"])}
    if aside["failed"]:
        result["notSetAside"] = sorted(set(aside["failed"]))
    if links:
        result["linksIntact"] = links_intact()
    result["restored"] = back
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
        code = run_bash(cmd, keep_also=files)
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

KEEP |= set(new_tests) | set(sources) | (set(allowed_extra) | {test_file} if task == "fix" else set())
set_aside(KEEP, first=True)
result = {"task": task, "head": head, "baseRoot": base_root, "commits": commits, "changed": changed, "staged": staged, "untracked": untracked,
          "setAside": sorted(n for n, _ in aside["left"])}
back = False
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
        set_aside(KEEP)  # a file the commands wrote at the accepted test's path goes, as any other they wrote
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
    back = put_back()
read_links()
if aside["failed"]:
    result["notSetAside"] = sorted(set(aside["failed"]))
    result["PASS"] = False
if links:
    result["linksIntact"] = links_intact()
    result["PASS"] = result["PASS"] and all(result["linksIntact"].values())
restored = (back and all(((cand / f).read_bytes() if (cand / f).is_file() else None) == data for f, data in saved.items())
            and all((cand / f).stat().st_mtime_ns == ns for f, ns in saved_mtime.items()))
result["restored"] = restored
if not restored:
    print(f"grade.sh: WARNING: the source files or the paths set aside in {cand} were not restored", file=sys.stderr)
print(json.dumps(result, indent=1))
PY
