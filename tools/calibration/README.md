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
   without letting a candidate commit it. Install the dependencies outside the pack and outside every git repository:
   `--link` refuses a directory whose real path is inside the pack or its repository, or holds either, since a link
   there is a path to the accepted fix; and it refuses a directory inside any git repository (it or one of its real
   ancestors holds a `.git` directory or file, or is a git directory such as a bare repository), since through `..`
   the checkout reaches that repository's files and history: a subject clone's `node_modules` would hand the
   candidate the clone's accepted fix and orchestration records. So run the install in a directory that is no
   repository, such as a history-less checkout of the case base made outside the pack. Each symlink among the
   directory's own entries is checked the same way where it resolves (a linked directory is followed before a `..`
   after it, as a POSIX kernel does), and one that does not resolve is refused.
   Nothing deeper is checked: a symlink or a repository further down the dependency tree is not followed, and keeping
   those out is the host's duty.
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
   `bash tools/calibration/grade.sh <pack dir>/manifest.json <case> <checkout> > <grades dir>/<case>-<profile>.json`.
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
the base, every `required_paths` path exists, and the candidate committed; the grade carries `gateExit`,
`invariantsIntact` and `requiredPresent` (each a `{path: bool}` map) and `committed`. `observations.py` counts gate cells
in `scores.json` (`cells.gate`, `category_mapping.gate`). The invariants and the required paths are read before the
command runs, so a command that writes files neither passes a candidate nor fails one. A command (gate, test or lint)
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
- Python 3.12 is the repository's CI version; the kit uses nothing newer than 3.11.
