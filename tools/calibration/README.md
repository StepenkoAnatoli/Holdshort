<!-- Lineage: generalises the method calibration runs 1-3 rebuilt by hand (run 3's evidence README: the freeze, the run id, the amendments, the results layout) into one kit, as docs/proposals/calibration-first-onboarding.md Items 2-4.2 ask. -->

# Calibration kit

The files every calibration run so far rebuilt by hand, under one path. A host uses them to calibrate a model and
effort (a profile) before the profile enters its policy (proposal Item 1). They grade pin, fix and review cells against
a subject pack, build the results the adapter's `rate` reads, and print the pull request that takes the results
upstream. The kit is files, not a package: Python 3.12 and bash like the rest of `tools/`, and one JavaScript workflow
template for the Claude Code workflow harness (the only harness with a run).

The kit contains **no provider calls, no keys and no host paths**. The host's harness runs the agents; the kit supplies
the prompts, the checkouts, the graders and the builders. Nothing here reads an environment variable for a credential,
and the kit's own test fails on a host path, a session id or a run id anywhere under this directory.

## Files

| File | What it is | Lineage (run 3 artefact it generalises) |
|------|------------|-----------------------------------------|
| `protocol.template.json` | the preregistration form, values blank: subject pack, profiles, cases with pass rules and `tier`, sources with the hash convention, metrics, accounting, timing, privacy, limits, `classification.prongs`, `judging_profile`, `relayed_operator_text`, `run_id` null until the launch, `amendments` [] | `protocol.json` |
| `classification.md` | the three-prong definition of a true other finding, the S4 rule, the rules G-1 and G-2 | the CLASSIFICATION text of the workflow script |
| `grader.prompt.md` | the grader prompt (one per review cell) and its output schema | the grader prompt and GRADE schema |
| `lens.prompt.md` | the adjudication lens prompt (three per cluster) and its schema, which carries `forbidden`; a lens votes real only on all three prongs | the lens prompt and LENS schema, with G-2 applied |
| `cluster.prompt.md` | the clustering prompt and the supplementary run's assignment variant, with their schema | the clustering step of both run-3 scripts |
| `historyless-checkout.sh` | one root commit holding a case's base tree, so the accepted fix is unreachable | the history-less checkout script |
| `grade.sh` | mechanical grading of a pin, fix or gate cell, every value from the pack manifest (a pin case's mutants included) | the pin and fix grading script |
| `observations.py` | builds `observations.json`, `scores.json`, the tables, `adjudication.json` and `void-cells.json` from the harness journal and run file; the journal format is documented at its top | the observations builder |
| `run.template.js` | the workflow: cells per profile and case, the preamble that reconciles a relayed operator request, pipelined grading, clustering, three lenses per cluster, majority; harness-specific lines marked `// HARNESS:` | the main and supplementary workflow scripts |
| `request.py` | prints the branch, the files and the pull-request body in this repository's template, and asks the operator to open it | the results pull request of run 3 |
| `subject-pack/README.md` | the format of a subject pack (`manifest.json`) | the subject sections of runs 1-3's protocols |
| `subject-pack/shared/README.md` | the shared synthetic pack (version 1): its README lists the pack's files (`manifest.json`, `make-repo.sh`, the trees) | proposal Item 2 |

## How a host onboards a profile

The folder `docs/evidence/<date>/<host>-calibration-<n>/` is the run's evidence folder (proposal Item 4.1). The pack,
the checkouts, the grades and the harness files stay outside it and outside every candidate's paths.

1. **Pack.** Choose the subject pack: the shared synthetic pack (Item 2; `subject-pack/shared/`, built by its
   `make-repo.sh` as its README says) and, if the host wants its own categories qualified on its own code, a host pack.
   Each is a directory holding `manifest.json` in the format of `subject-pack/README.md` and the pack's git repository.
2. **Protocol freeze.** Copy `protocol.template.json` to the evidence folder as `protocol.json`, fill every
   `{{placeholder}}` and delete `_lineage`; write the folder's `README.md` with the frozen sections (what the run is,
   what changed from the last run, the files). Decide the relayed operator text (run protocol rule 2), the judging
   profile (rule 3) and take the before reading (rule 5). Hash every source under the protocol's convention:
   `python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], encoding="utf-8", newline="").read().replace("\r\n", "\n").replace("\r", "\n").encode()).hexdigest())' FILE`.
3. **Checkouts.** One history-less checkout per cell, named `<checkout root>/<run tag>-<case>-<profile>` on branch
   `<run tag>/<case>-<profile>`, plus one checkout of the review base for the lenses:
   `bash tools/calibration/historyless-checkout.sh --pack <pack dir> [--link <name>=<dependency dir>] <pack dir>/<repository> <case base> <checkout> <branch>`.
   `--pack` refuses a checkout that shares a path with the pack; `--link` makes an installed dependency tree available
   without letting a candidate commit it. A candidate can still write that tree, through the link or by putting a tree
   of its own at the name, and the test, lint and gate commands run from it: right after the install, before any
   candidate runs, seal each linked directory with
   `bash tools/calibration/grade.sh --seal <name>=<dependency dir>... > <seal file>` and keep the seal outside the pack,
   every checkout and every linked directory; the grade reads each link against it (step 6). Install the dependencies outside the pack and outside every git repository:
   `--link` refuses a directory whose real path is inside the pack or its repository, or holds either, since a link
   there is a path to the accepted fix; and it refuses a directory inside any git repository (it or one of its real
   ancestors holds a `.git` entry of any type, or may be a git directory: it holds an entry named `HEAD`, `commondir`
   or `gitdir`, or both an `objects` and a `refs` entry, a rule wider than git's own repository test, so that every
   directory git would take for a repository, a bare one or a linked worktree's admin directory too, is refused),
   since through `..` the checkout reaches that repository's files and history: a subject clone's `node_modules` would hand the
   candidate the clone's accepted fix and orchestration records. So run the install in a directory that is no
   repository, such as a history-less checkout of the case base made outside the pack. Each symlink among the
   directory's own entries is checked the same way where it resolves (a linked directory is followed before a `..`
   after it, as a POSIX kernel does), and one that does not resolve is refused. Paths are compared by identity, not
   spelling (another case on a case-insensitive filesystem names the same directory). A UNC path (`//host/share/...`)
   is refused wherever a check needs it (the directory, a symlink's target, the pack, its repository, the checkout's
   parent), since its parents cannot be checked reliably: install on a local drive. The checkout itself must not be
   inside any git repository either (it would reach that repository through `..` the same way), and a refused
   checkout makes nothing, not even its parent directories (a refusal after the checkout is made, by the link rule
   below, removes it again, each link in it as an entry, never followed). Every check runs twice. The shell layer uses the path Git
   Bash resolves and the parents it walks, plus the Windows parents of that path (a mount such as Git Bash's `/` or
   `/tmp` has Windows parents of its own). On Windows, the native layer then resolves each path the way native
   programs (git, node, Python) resolve it, through a Windows Python's `os.path.realpath`, and checks that path and its
   parents again. Git Bash cannot see some links native programs follow, such as one whose target is a volume-GUID or
   `GLOBALROOT` path, so only the native layer catches those. The native layer also checks every path the shell layer
   resolves, as native programs resolve that path: Git Bash follows MSYS's own symlinks too (a system file or a `.lnk`
   shortcut, made under `MSYS=winsymlinks:sys` or `:lnk`), which native programs take for plain files, so where such a
   link at the linked directory's top leads by Git Bash's reading (a volume-GUID link, a `subst` drive) is checked
   where native programs find it. The native layer fails closed: a path it cannot resolve,
   or one that resolves to anything but a drive-letter path, is refused, and so is every checkout when no Windows
   Python 3.10+ (the version whose `os.path.realpath` takes `strict`) is on `PATH` as `python3` or `python`. The
   script ignores the host's `GIT_DIR`, `GIT_WORK_TREE` and git's other repository variables, and copies no git template (so `GIT_TEMPLATE_DIR` or `init.templateDir` cannot
   give the checkout another repository's objects through `objects/info/alternates`). Its final proof counts every
   object the checkout's git can read. Every path string the checks read, or hand on to the native layer and to git,
   is proved by file identity (`[ a -ef b ]` in the shell, the same file by `os.stat` natively) to name the file it
   came from, and the path is refused ("is not proved to name the file it came from") when that fails or cannot be
   proved: a shell command substitution drops a trailing newline, and Windows drops a trailing space or dot from a
   name, so `x/repo` followed by a newline or a space was checked, read or written as its twin `x/repo`. The
   checkout's own name, which does not exist yet, is kept exactly as spelled, and its last segment may not be `.` or
   `..`. Git for Windows takes no path with a segment that ends in a space or dot, so such a checkout is refused too.
   No part of a path is taken through a command substitution between the path and its proof: each directory and
   name a link at the linked directory's top resolves through, and each link target read, is kept exactly as
   spelled, since an identity check holds through a hard link (a file reached through `x/hl` followed by a newline
   may also be the file in a twin `x/hl`, so a check made at the twin would pass the proof).
   Git is given the source and the checkout only by those proved Windows spellings, so a host that turns off MSYS's
   argument conversion (`MSYS_NO_PATHCONV=1`) does not make it read `/c/x` as `\c\x` on its current drive.
   Nothing deeper is checked: a symlink or a repository further down the dependency tree is not followed, and keeping
   those out is the host's duty. A `--link` name is a plain relative path of letters, digits and `.`, `_`, `-`, `+`,
   `@`, in `/`-separated parts that are not empty and do not end in a dot: git reads the name as a pattern in the
   checkout's `.git/info/exclude`, where `[`, `?`, `*`, a space or a newline would leave the link unignored (a
   candidate's `git add -A` would commit it, a symlink holding the host's path) or hide other files. None of its
   parts may name `.git` in any spelling Windows resolves to it (any case, trailing dots or spaces, `GIT~1`). Each link is made only where its
   name does not exist yet in the checkout and its real parent lies inside the checkout and outside its `.git`, in both
   layers: the base tree may track a symlink (checked out as one with `core.symlinks=true`, such as `g -> .git`), and
   an earlier `--link` is one too. Once a name is listed in `.git/info/exclude`, `git check-ignore` must show that
   git ignores the link, or the checkout is refused (the base tree's `.gitignore` can re-include the name with `!`). The script sets the globbing its checks rely on itself, so a `SHELLOPTS` or
   `BASHOPTS` the host exports (`noglob`, `nullglob`, `failglob`) does not change what they see.
   **What the guard covers, and what is the host's duty.** It covers every path the checkout gets from the script:
   no parent of the checkout, no linked directory or its parents, and no link at a linked directory's top level or the
   parents of where it leads reaches a git repository, the pack or its repository, by any spelling native programs
   resolve. It knows a repository only by its markers, and the pack only by the paths given, so it cannot see the
   subject's files outside a repository. These are the host's to keep away from the linked directories and the
   checkout: a plain copy or export (`git archive`) of the subject, a work tree whose git directory lies elsewhere
   (`core.worktree` leaves no `.git` in it), a link or a repository deeper in a dependency tree, and anything else
   known only by its content. A refusal never means "remove the `.git` and retry": a clone stripped of its `.git`
   still hands over the subject's files, its orchestration records and briefs among them. Install where no subject
   file is, as above: a history-less checkout of the case base made outside the pack.
4. **Fill.** Write `run-config.json` = `{"manifest": <manifest.json>, "protocol": <protocol.json without its sources>,
   "host": {...}}` (the host keys are listed in the header of `run.template.js`; the protocol goes in without `sources`
   because the sources record the filled script's hash). Every host path in it (`checkout_root`, `adjudication_checkout`, `pack_dir`) is absolute and already resolved: the launch step compares the strings and follows no symlink and no `..`, so a relative path, or one that resolves elsewhere after the launch, is outside its guard (the checkout script resolves real paths where the checkouts are made). Fill the template, hash `run.js` into the protocol's
   `sources`, and commit the evidence folder: that commit is the freeze.

   ```bash
   python3 -c 'import json, pathlib, sys
   k = pathlib.Path(sys.argv[1]); t = (k / "run.template.js").read_text()
   p = {n: (k / f"{n}.prompt.md").read_text() for n in ("grader", "lens", "cluster")}
   p["classification"] = (k / "classification.md").read_text()
   c = json.loads(pathlib.Path(sys.argv[2]).read_text())
   sys.stdout.write(t.replace("null // {{RUN}}", json.dumps(c)).replace("null // {{PROMPTS}}", json.dumps(p)))' tools/calibration run-config.json > run.js
   ```
5. **Launch.** Launch `run.js` in the harness (Claude Code: the workflow tool, with the script path). The script's launch
   step refuses, before any agent starts, a protocol that is not frozen, an unrecorded relayed text or statement, prongs
   other than the three, a judging profile with neither its qualification nor the bootstrap line (a `{{placeholder}}`
   qualification counts as none, and the limitation must begin with that line), any `{{placeholder}}` left in the
   protocol, and a checkout that shares a path with the pack. Record the run id the harness assigns in `protocol.json` (`run_id`) and in the folder's README at the
   launch, with the time.
6. **Grade.** For each pin and fix cell, after it finishes:
   `bash tools/calibration/grade.sh [--links <seal file>] <pack dir>/manifest.json <case> <checkout> > <grades dir>/<case>-<profile>.json`.
   A manifest with `checkout.links` needs `--links` with the seal of step 3 (a grade without it, or with a seal of
   other names, is refused): each linked name in the checkout is read by content before the first command and after
   the last, `linksIntact` records whether it still held the sealed content, and PASS needs every one intact.
   Each command runs with every path the base tree lacks set aside, ignored or not, other than the paths the grade
   counts as the candidate's and the linked names, found by a walk of the checkout on disk that sets a link aside as
   itself (`setAside`, see the limits); the checkout's own `.git` stays and holds what is set aside, so the pack's
   runner must exclude `.git`, and a cell whose own `.git` is spelled any other way fails. A fix cell runs the accepted pin first, on the base tree, the candidate's
   sources and the accepted test only, then the candidate's tests, the guard and the lint.
   The review cells are graded by the run itself (grader, clustering, lenses).
7. **Build.** `python3 tools/calibration/observations.py <journal> <run file> <pack dir>/manifest.json <grades dir>
   <evidence folder> --protocol <evidence folder>/protocol.json`. A cell void under rule 2 is re-run once: launch the
   template again with `host.supplementary` set to the void cells and the main run's clusters and adjudications, grade
   it, and add `--void <case>:<profile>` (each) and `--supplementary <journal> <run file>` to the build.
8. **Results.** The evidence folder now holds the layout runs 2 and 3 used (Item 4.1): `protocol.json` (frozen, then
   amended), `observations.json`, `void-cells.json`, `adjudication.json`, `scores.json`, `results-table.md`,
   `clusters.md`, `tokens-and-estimates.md`, plus copies of `grade.sh` and `historyless-checkout.sh` as run and the
   README with the frozen sections above a `## Results` section. Take the after reading (rule 5); append amendments.
9. **Request.** `python3 tools/calibration/request.py <evidence folder> [--issue <n>]` prints the branch, the files, the
   title and the body in `.github/pull_request_template.md`'s four sections, and ends by asking the operator to open the
   pull request. The kit never pushes and never opens it: the operator's push is the operator's consent that the
   evidence may be shared (Item 4.2). Qualification stays the host's: the policy edit that grants a category names the
   runs, under the host's own rules.

**The check a results pull request must pass.** Before the request, run `python3 tools/check_calibration_evidence.py
<evidence folder>` and `python3 tools/qualification_table.py`, then commit the regenerated
`docs/evidence/qualification-table.md` with the folder. The regression gate runs the check over every calibration
evidence folder and the table as `--check` on every commit, so the pull request merges only when the folder passes the
eight rules of proposal Item 4.3: protocol-frozen, prongs-declared, scores-derivable, fewer-prong-pass-flagged,
pin-category-mapping, judging-profile-named, relayed-chat-statement and no-secrets-or-bodies. A folder this kit builds
is a kit run, so every rule applies in full; `docs/evidence/README.md` says what each rule asks for and what the table
supports.

## The shared pack

`subject-pack/shared/` is the shared synthetic subject pack every host runs (proposal Item 2), version 1: a
standard-library Python module, `src/bounded.py`, whose `read_bounded` promises never to raise on bytes-like or str
chunks and never to return more than `limit` bytes, with two seeded S3 defects: D-1, a rejection of a memoryview chunk
(review case only), and D-2, a bound skipped on str chunks (the pin, fix and review cases). The pack ships its three
trees as directories; `make-repo.sh` builds them into the pack repository with the commit ids `manifest.json` carries,
outside the kit's tree, and the host copies the manifest beside it. It discriminates the T1 shape only, and it is
rewritten as a new version when it leaks; its README says how a host builds and runs it.

## The run protocol

The kit enforces these where a file can (the launch step of `run.template.js`, `observations.py`); the rest are the
host's duty and the protocol records them.

1. **Preregistration before launch** (Item 3.1). The protocol is frozen, with source hashes, before any agent starts;
   the run id is recorded at the launch. A cell whose prompt or checkout differs from the frozen hash is void.
2. **No operator chat in the workers** (Item 3.2). A harness that relays operator chat into workers either suppresses it
   for the run or the relayed text is recorded verbatim in `relayed_operator_text` before the launch; the candidate
   preamble reconciles a relayed request (run 3 amendment A-1). A cell that halts on relayed text is void and re-run
   once in a supplementary run, never graded as capability.
3. **Judging by a qualified reviewer** (Item 3.3). The grader, the clustering agent and the lenses run on a profile the
   host policy qualifies for `review`. A host onboarding its first model has none: the protocol says so with the line
   "judging profile not independently qualified" and names who declared the judge, and the results carry the line.
4. **One run per profile and case** (Item 3.4). Retry limit 0; a harness retry is recorded as such (the run file's
   `attempt`), never as a model retry. The host's two-pass rule needs two runs, or one run and accepted outcomes.
5. **Readings with nothing in flight** (Item 3.5), before and after the run, in `usage_window_readings`, so the run also
   measures the host's usage-window coefficients; when no clean reading exists the protocol says why.

## Run ids and amendments

The run id is the one value written after the freeze without an amendment: in `protocol.json` and the folder's README,
with the launch time. Everything else that changes after the freeze is an amendment appended to `amendments`, never an
edit of a frozen field: `{"id", "at", "case", "change", "reason"}` and, when the change is one the next run should carry,
`"kit_rule"`. Run 3's ids: `A-<n>` for the run's conduct (a void cell, a category mapping), `G-<n>` for the grading
rules, `N-<n>` for a note that changes no score. The frozen sections of the folder's README are never edited; results go
below them under `## Results`.

## observations.json: the flat profile map

One object per profile key (`<model alias>-<effort>`); hosts/claude-code/route.mjs `rate` reads it from
`<trace>/calibration-<n>/observations.json`. Keys of one observation:

- `profile`: the key. The adapter takes the effort from its last `-` part.
- `review-only`: true for a profile run on the review case only.
- `pin`, `fix`: the mechanical grade, or null when the cell was not run. `score` (true, false, or null when the cell ran
  but has no grade: the adapter counts it ungraded, never as a pass), `tier`, `category` (only when the manifest names
  the case's category), and grade.sh's fields (pin: `redAtHead`, `greenWithFix`, `srcClean`, `lint`, `committed`,
  `atHead`, `withAcceptedFix`, and `redAtMutants` when the pin case has mutants; fix: `candidateGreen`, `guardRed`,
  `acceptedPinGreen`, `scopeOk`, `lint`, `committedWithMap`, `commits`, `srcDiffLines`, `candidateTests`,
  `guardRemoved`, `acceptedPin`).
- `gate`: present only when the manifest has a gate case; the gate grade (null when the cell was not run): `score`,
  `tier`, `category`, `gateExit`, `invariantsIntact`, `requiredPresent`, `committed`, `commits`.
- `review`: the candidate's verdict, its findings as `[id, severity, problem]` and the count of `checked`.
- `review-grade`: `result` (`PASS` | `PARTIAL` | `FAIL` under the run's preregistered rule; null when ungraded), `tier`,
  `category` (when the manifest names one), `truth` (per ground-truth finding: found, causeNamed, severity), `rawFalseBlocking`, `adjudicatedFalseBlocking`,
  `threeProngFalseBlocking`, `threeProngResult`, `copiedFromHistory`, `others` (each with its cluster and verdicts),
  `notes`.
- `self-reported-mistakes`: per case (`gate` too when the manifest has one), the candidate's `mistakes` verbatim.
- `harness-retries`: per case, the harness retries recorded for the cell.
- `usage`: per case and `grade`, the run file's record: `label`, `model` (the resolved model id; the adapter maps it to
  a policy profile, and never reads the grader's), `effort`, `state`, `tokens`, `ms` and `run` (the run id, which names
  the supplementary run for a cell that replaced a void one).

## scores.json

`profiles` (per profile and case: `pass` or `result`, `tier`, the estimate, and for a review `would_fail_under_three_prong`
with `three_prong_false_blocking` when it is true), `totals` (`cells` per case, `tokens` per run with items, graders,
clustering, lenses and other summing to the run's agents, `non_pass`; a gate cell counts as an item and under `cells.gate`), `category_mapping` (case to host category: the pin
case is `pin-tests`; `gate` too when the manifest has a gate case), `adjudication_schema` (the prongs the classification declares, the prongs the lens records carried,
the missing ones, the vote rule, the clusters where the run's verdict and the declared rule disagree), `void_cells`,
`pass_rules`, `accounting_note`, `run_id`, `supplementary_run_id`, `pack`.

## Run 4's case keys: category, mutants, gate

Three manifest keys, added for calibration run 4 (its plan, R4-4), let a pack carry cells for categories other than
`pin-tests`, `fix` and `review`. Each is optional: a manifest without them grades and builds byte for byte as before
(the kit's test rebuilds the fixture folder against a golden copy).

**`category`** (`cases.<case>.category`). `observations.py` writes it into each `pin`, `fix` and `gate` task object and
into `review-grade`, and `scores.json` carries it in `category_mapping`. When the manifest names none, the task object
carries no `category` key and a reader applies the fixed mapping (pin to `pin-tests`, fix to `fix`, review to
`review`) as it always has. For the adapter: the task object's `category` is what `rate` will read under
host-policy-7, in place of the position mapping; the review's category sits on `review-grade`, beside its `tier`.

**`mutants`** (`cases.pin.mutants`, a list of `{id, commit}`). `grade.sh pin` then also swaps each mutant commit's
source in turn (each swap with its own mtime step, as for the base and the accepted source) and requires the
candidate's new tests red at every one, as well as red at the base and green with the accepted source. The grade
carries `atMutants` (the test run per mutant) and `redAtMutants: {id: bool}`, and `observations.py` copies
`redAtMutants` into the pin task object. Without mutants the pin grade carries neither key. A mutant whose
`paths.source` files equal the base's (it adds nothing) or the accepted fix's (no pin could be red at it) is refused. A
pin case is red at its base by rule, so a pack whose rules hold at the base needs a base where they fail.

**`gate`** (`cases.gate`). A case kind graded by a command: the candidate's prompt is the case's `instructions` after
the common preamble (the relayed-text reconciliation, the checkout, the commit command), and `run.template.js` runs a
gate item per profile like a pin or fix item, with no grader agent. `grade.sh gate` passes the cell when
`commands.gate` exits 0 in the candidate's checkout, every `invariants` path holds the files and content it holds at
the base, every `required_paths` path exists, and the candidate committed on top of the base commit; the grade carries
`gateExit`, `invariantsIntact` and `requiredPresent` (each a `{path: bool}` map) and `committed`. An invariant is compared file by
file with the base tree: every base file under the path must be there as a plain file that hashes as at the base, and
no other file may be there that the base's `.gitignore` rules do not ignore (one that HEAD or the candidate's index
holds counts even when ignored, and even when it is no longer on disk: HEAD is read against the base tree, so an
ignored file committed and then unstaged still counts). The checkout is read as files by a git of the grade's own, not the candidate's: a fresh repository
outside the checkout whose objects are the pack repository's, whose index is the base tree, whose attributes are the
base tree's (`--attr-source`, so git 2.40+ is needed) and whose config is the host's. What the candidate committed and
staged is read by a second git of the grade's own, with no alternates: its objects are the base tree's trees and
blobs from the pack repository, then a copy of the candidate's loose objects and packs (never what its
`objects/info/alternates` names), each filed by `git index-pack` under the id git computes from its content, so an
object the candidate stores under another object's id (a forged base tree, which made the candidate's files read as
the base's: review loop RL8-K1) is read under its own id or not at all, and a commit the candidate does not hold (the
pack's accepted fix) is not there. Its index holds the entries of a copy of the candidate's index, each written
again, so no cache tree the candidate wrote is read (one claiming a directory still matched HEAD hid a staged
file), and its commit is the candidate's HEAD read from the files `.git/HEAD`, `.git/refs` and `.git/packed-refs`; a
history or index git cannot read is exit 3. HEAD is compared with the case's base tree, never with the history's own root: the candidate
writes that history, and an amend of the checkout's single commit or an orphan root put its new files in a root, where
a comparison with the root did not see them (review loop RL4-K1). Every grade carries `baseRoot` (the history has one
root and it holds the base tree), and `commits` counts the commits on top of that root, 0 when `baseRoot` is false. No
git of the grade reads a commit-graph file, which the candidate can write into its objects (a forged one made HEAD its
own root). No git runs on the candidate's `.git` as a repository, so nothing in its `.git/config` is applied
or run: a clean filter there and in `.git/info/attributes`, a line in its `.git/info/exclude` or a `.gitignore` it adds
does not hide a change (review loop RL2-K1), and a program that `core.fsmonitor` names does not run inside the grade,
where it could rewrite the grade's own repositories (RL3-K1). A checkout whose `.git` is not a directory, or is a link
of any kind (a symlink, a junction or any other reparse point; Python's `is_symlink()` counts only a symlink), is
graded as having no commit (exit 3) before any command runs (review loop RL15-J1: a `.git` junction was graded, and
the set-aside made its directory and moved the candidate's entries through the junction into its target, outside the
checkout, in a base directory or in the pack repository's `.git`). What the grade reads from the candidate's `.git`
(HEAD, the refs, `packed-refs`, the object directories and files, the index) and a gate's invariant files are read
the same way: a link of any kind is not followed and reads as no file, so HEAD, a ref or an object behind one is no
commit (exit 3), an index behind one is no index, and an invariant file behind one is not intact. Line endings are compared as the host's git
would store them, so a conversion the host makes reads as the same content. The same view gives every grade's
`changed` (with the candidate's committed and staged files, and every file on disk the base lacks that the candidate's
index holds) and `untracked` (such a file the index does not hold), so a tracked file marked skip-worktree or
assume-unchanged and then edited still counts as changed in a fix's scope check and a pin's source check. The view
hashes the paths on stdin, so a directory of any size is graded. `observations.py` counts gate cells
in `scores.json` (`cells.gate`, `category_mapping.gate`). The invariants and the required paths are read before the
command runs, so a command that writes files neither passes a candidate nor fails one. The gate command runs with
every path the base lacks set aside except the required paths and what the grade lists as changed, and the gate grade
carries `setAside` and `restored` as a fix or pin grade does (review loop RL9-K1). A command (gate, test or lint)
that overruns its timeout has its whole process tree killed and reads as exit 124. One case per kind per pack stays the
rule. A gate-only pack needs no `subject`, `paths`, `commands` or `accepted_fix`.

**`cause_in_prompt`** (`cases.fix.cause_in_prompt`, true or false). A fourth key, added when run 4's lead integrated
these: with `false` the fix prompt leaves out the finding's cause (the whole "Cause: ..." clause) and keeps its summary
and required behaviour, for a tier whose cause the candidate must find itself. True or absent prints the cause, so the
prompt is byte for byte what it was (the kit's test compares it with the prompt the earlier template renders). The
finding's `cause` stays required in the manifest and stays in the ground truth the grader and the lenses read. The
launch step refuses a value that is not a boolean, and refuses the key on any other case or on a finding (only the fix
prompt prints a cause, so a misplaced key would be ignored while the cause stayed in).

**A null `judging_profile`.** A run whose manifest has no review case judges nothing (pin, fix and gate are graded
mechanically), so its protocol may record `judging_profile: null`; the launch step refuses null when the manifest has a
review case, and refuses an absent key either way. The evidence check's rule f (`judging-profile-named`)
still requires a named judging profile, so until it changes such a run names one with the note that no cell uses it.

## Limits of this kit

- `run.template.js` has been executed under a stub harness in the kit's test (every launch refusal, the cells, the
  prompts, the vote), not yet in the real workflow harness; the first real run is its test, and the filled script's hash
  in the protocol makes any change to it visible.
- `grade.sh` reads two test-report modes: `exit-code` (green is exit 0; a crash reads red, so a counting report is
  better) and `vitest-json` (run 3's). Another runner writes vitest's three counters or uses `exit-code`.
- The evidence check in the regression gate and the qualification table (proposal Items 4.3 and 4.4) are separate
  units; this kit defines the pack format and the results layout they rely on. The shared pack (Item 2) is
  `subject-pack/shared/`, version 1, and qualifies the T1 shape only.
- Python 3.12 is the repository's CI version; the kit uses nothing newer than 3.11. `grade.sh` needs git 2.40+
  (`--attr-source`) and refuses to grade without it.
- The linked trees (`checkout.links`) are read against the host's seal before the first command and after the last,
  not between commands, and only as files: every command runs the candidate's code (its tests, its source), which can
  change what a command reports while it runs and undo a change to a linked tree before the last read. The seal grades
  what the candidate left on disk. Each read is a full content read of the tree: X21's `node_modules` (about 15,000
  files) took minutes on a first read under an on-access virus scanner and seconds once cached. A link deeper inside a
  linked tree is read as its target's text, not followed; what it leads to is the host's to keep out of reach.
- The grade runs while no candidate runs: a candidate process left running after its cell can change the checkout or a
  linked tree between the grade's reads.
- A file the base's `.gitignore` ignores is in `changed` and `untracked` only when HEAD or the candidate's index holds
  it. No command runs it, though: the commands find modules, configs and runners on disk, not in the grade's lists
  (review loop RL9-K1: on the X21 pack an ignored nested `tests/node_modules/esbuild` beat the sealed install for the
  accepted test and a wrong fix graded PASS). So before each command every path the base tree lacks, ignored or not and
  at any depth, is moved into a directory inside the checkout's `.git`, unless the grade counts it as the candidate's
  (changed, a new test, the case's source paths, test file and `allowed_extra`, a gate's `required_paths`) or it is a
  linked name. What goes is found by one walk of the checkout on disk compared with the base tree, not by git's listing,
  which missed three kinds of entry a runner reads, each of which ran a candidate's test inside the accepted pin while a
  wrong fix graded PASS with every list empty: git never lists an entry named `.git` in any case below the top, nor
  anything below it (its directory walk skips the name, case-insensitively where `core.ignorecase` is set, as on
  Windows), while vitest reads it (its default exclude `**/.git/**` is case-sensitive; review loop RL12-K1:
  `tests/.GIT/tests/zz_accepted_x2_1.test.ts`); git reads through a junction as a directory, so a junction put where the
  base has a directory, leading to a copy of the base's files and a `.GIT` forge, showed no change (RL13-K1); and a name
  that ends in a dot or a space (`tests/x.`, `tests/x `), which Win32 paths trim, was listed by git but renamed by its
  trimmed path, not found and skipped as gone, while node reads it by its extended path (RL13-K2; `tests/x ` and
  `tests/x..` crashed the grade, RL13-K3). The walk reads and moves every entry by its extended-length path on Windows
  (`\\?\`), so no name is trimmed, and never enters a link: a link (a symlink, a junction) goes aside as the link
  itself, unless it is the base's own link, unchanged, or a counted path that leads to a file (RL10-K3: moving the
  entries below a junction took a host directory's files into the checkout's `.git`). A directory the base has, or one
  that holds a counted path, is entered and only its entries the base lacks go; any other directory goes whole; an entry
  named `.git` in any case, other than the checkout's own, goes like any other path the base lacks (git checks out no
  path with such a name). The checkout's own `.git` is the one path the base lacks that stays, and what goes aside goes
  into it, so a runner sees neither only by its own exclude of the name `.git` (vitest's default `**/.git/**`, which is
  case-sensitive; pytest's default `norecursedirs`, `.*`): a pack's runner must exclude it. The checkout's own `.git`
  spelled any other way fails the cell (`notSetAside`; review loop RL14-K1: a case-only rename to `.GIT`, which git and
  the grade still read on a case-insensitive disk, put a forge at `.GIT/tests/zz_accepted_x2_1.test.ts` in the view of
  vitest's default include, where it ran inside the accepted pin and a wrong fix graded PASS with every list empty).
  What the candidate left that way is listed in `setAside` and put back after the last command,
  in place of anything a command wrote at its path; what one command writes at a path the base lacks is set aside before
  the next and removed. A path the grade cannot move, a path the rename does not find that is still there when the grade
  reads the disk again (never "gone"), and a directory the grade cannot read are listed in `notSetAside` and fail the
  cell; `restored` is false when a path did not go back, and that fails the cell. Not covered: a directory above the
  checkout (node's `node_modules` lookup and a config search walk past the checkout's top into the host's directories,
  which are the host's to keep out of the candidate's reach); and a file the grade counts as the candidate's, which runs
  as it is: a changed source or new test that patches the runner or the test framework while it runs, or a committed
  file that shadows a module or the runner (a top-level `unittest.py` beside a gate command `python3 -m unittest ...`),
  is listed in `changed` and is in the diff the review reads; a fix cell refuses such a file only outside its scope
  (`scopeOk`), so the case's test file or a new test that patches the runner runs as it is in the candidate's runs and
  the guard (not in the accepted pin, below), and no grade check refuses one in a pin or gate cell. The walk compares
  names only: an NTFS alternate data stream or an extended attribute on a base path stays (only code that names it reads
  it, and that code is the candidate's or the pack's); a base directory the candidate renamed in case on disk (`Tests`
  for `tests`) and, on macOS, a name in another Unicode normalization than the base tree's read as paths the base lacks
  and go aside whole, which fails a cell rather than passing one. On a case-sensitive directory (NTFS's per-directory
  flag, or a case-sensitive disk) an entry `.GIT` beside the checkout's own `.git` is a path of its own and goes aside
  (a test covers it, review loop RL15). An NTFS 8.3 short name, which a candidate can set (`fsutil file setshortname`,
  probed in RL15 without elevation), is listed by no walk and no runner: one on a path the base lacks goes aside with
  it, and one on the checkout's own `.git`, a base path or a counted path stays, reached only by code that opens that
  name (a module lookup that tries names such as `index.js`); the grade neither reads nor resets short names. A gate's
  required path stays as the candidate left it, a link too, and counts as present when what it leads to exists. What the last command writes stays in the checkout.
- The commands of one cell are not independent runs. The set-aside resets only the paths the base lacks: a command can
  rewrite a base file the grade does not swap (the pack's runner, a config), leave a process running (a detached child;
  only a command that overruns its timeout has its process tree killed) or keep state outside the checkout (a file in
  the temp directory or the home directory), and the next command runs with it. So a fix cell runs the accepted pin
  first, before any of the candidate's tests (review loop RL10-K1: a test that rewrote `tests/run.py`, or that left a
  child overwriting the accepted test, made the pin read green for a wrong fix), and on the base tree, the candidate's
  sources and the accepted test only: while it runs, every other path the base lacks (the candidate's new tests,
  anything it added) is set aside, every other base file the candidate changed (the case's test file, `allowed_extra`,
  an out-of-scope edit) holds the base's content with an mtime of its own, and both go back right after it (RL11-K1:
  vitest takes a file argument as a filter and runs every included test whose path contains it, so the pin's own command
  ran a candidate's in-scope new test at `tests/xtests/zz_accepted_x2_1.test.ts`, which rewrote the accepted test before
  vitest read it, and a wrong fix graded PASS). So whatever a runner selects from its arguments, no test of the
  candidate's exists to select (one below an entry named `.git` in any case, below a junction or under a name Win32
  paths trim included: RL12-K1, RL13-K1, RL13-K2, above), outside the checkout's own `.git`, which the runner must
  exclude and which fails the cell when it is not spelled `.git` (RL14-K1, above); a base file that cannot hold the base's content there (a link
  above it) leaves the pin unrun, an error and not green. Still not covered for the pin: the candidate's sources run
  inside it and can patch the runner, the assertion library or the accepted test while it runs (a source is code the pin
  must run; only the diff the review reads shows it), and state outside the checkout that the candidate's work left
  before the grade (a process started before the grade, a file in the temp directory) reaches it as it reaches every
  command. Everything else a grade reads from the candidate's own tests can be forged across commands, as it can by a
  test that reads the source it runs against: `candidateGreen`, `guardRed` and the lint in a fix cell, and `redAtHead`,
  `redAtMutants` and `greenWithFix` in a pin cell (RL10-K2: a row that counted its runs in a temp file and failed the
  second, the guard run, made `guardRed` true for a weak fix). Only the diff the review reads shows it.
