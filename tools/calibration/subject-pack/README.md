<!-- Lineage: generalises the subject sections of calibration runs 1-3's protocols (run 3: subject, known_defects, cases, the isolation line) and what their grading scripts hard-coded, into one manifest a pack carries. -->

# Subject pack format

A subject pack is what a calibration run grades against: a module with known, accepted defects, its tests, its
accepted fix, and the ground truth a review is graded by. A pack is a directory holding `manifest.json` and the pack's
git repository (the base trees and the accepted fix are commits in it). Two kinds (proposal Item 2):

- **Shared pack**: small, synthetic, self-contained, the same on every host, so its cells compare across hosts. It is
  rewritten when it leaks into training data, so the protocol records its version. Onboarding requires it.
- **Host pack**: a real accepted defect pair from the host's own repository, as runs 1-3 used. Its cells qualify the
  profile for the host's own categories and do not compare across hosts.

## The shared pack

The kit ships one shared pack, `shared/` (version 1, its README says what it holds and how a host runs it). It carries
its base and accepted trees as directories, not as a nested repository, and `shared/make-repo.sh` builds them into the
pack's git repository with fixed identity, dates and messages, so the commit ids are the ones its `manifest.json`
names on every host. The host builds that repository outside the kit's tree and copies `manifest.json` beside it, so
`repository` (`repo`) resolves and the manifest's hash is the same on every host.

## Isolation

A candidate's checkout is a history-less tree of its case's base only (`historyless-checkout.sh`). The accepted fix, the
ground truth, the manifest and the grader material live outside every candidate's permitted paths: the candidate prompt
names only the checkout, never the pack; `historyless-checkout.sh --pack`, `grade.sh` and the launch step of
`run.template.js` refuse a checkout that shares a filesystem path with the pack directory, and
`historyless-checkout.sh --link` refuses a dependency directory inside the pack or its repository (installed
dependencies live outside the pack). The fix case gives the
candidate the finding (its summary, cause and required behaviour; without the cause when `cases.fix.cause_in_prompt` is
false), never the accepted change. A shared pack is small by
construction: it discriminates the bounded T1 shape only, and a host that needs more runs its own pack.

## manifest.json

Paths inside the pack's repository are relative to its root, with `/`. Text fields are written for the candidate or the
grader to read, so they say what the module must do, never how the accepted fix does it.

- `pack`: the pack's name.
- `pack_version`: its version; the protocol records it (`subject_pack.pack_version`), and a rewritten pack is a new version.
- `kind`: `shared` or `host`.
- `repository`: the pack's git repository, relative to the manifest's directory (or absolute on the host machine; a
  host path never enters this repository).
- `subject`: what is under test.
  - `subject.name`: a short description the candidate prompt uses ("the base tree of <name>").
  - `subject.module`: the module's path, which the review and the judging prompts name.
  - `subject.promise`: the module's stated promise, which decides prong 3 of the classification.
  - `subject.reference`: the reference material in the checkout (the specification sections, the test harness), as the
    candidates and the lenses are told it.
- `commit_rule`: optional; the subject repository's own commit rule, told to the candidates (e.g. a map that must be
  staged with a source change).
- `accepted_fix`: the commit holding the accepted fix of the pin and fix cases' finding; grade.sh swaps its source in.
- `findings`: the ground truth, one entry per accepted finding.
  - `findings[].id`: its id, as the grader reports it.
  - `findings[].severity`: S1-S4.
  - `findings[].present_at`: the base commits it is present at.
  - `findings[].summary`: the problem, stated without the fix.
  - `findings[].cause`: where it comes from (the condition, the location). Required: the grader and the lenses read it,
    and the fix prompt prints it unless `cases.fix.cause_in_prompt` is false.
  - `findings[].required_behaviour`: what the module must do instead, stated without the fix; the pin case's rule.
  - `findings[].found_rule`: what a review finding must say for `found`.
  - `findings[].cause_rule`: what it must locate for `causeNamed`.
  - `findings[].accepted_fix`: the commit that fixed it.
- `cases`: one entry per case the pack supports, keyed `pin`, `fix`, `review` or `gate`, one case per kind.
  - `cases.pin.base`, `cases.fix.base`, `cases.review.base`: the commit the case's checkouts hold.
  - `cases.pin.category`, `cases.fix.category`, `cases.review.category`: the host category the case represents
    (`pin-tests`, `fix`, `review`, or another category of the host's policy, e.g. `build-tests` for a pin case or
    `build-core` for a fix case); `observations.py` writes it into the case's task object and `scores.json` carries it
    as `category_mapping`. Optional: without it the task object carries no category and a reader applies the fixed
    mapping (`pin-tests`, `fix`, `review`).
  - `cases.pin.tier`, `cases.fix.tier`, `cases.review.tier`: the difficulty tier (`T1` for a shared pack).
  - `cases.pin.pass_rule`, `cases.fix.pass_rule`, `cases.review.pass_rule`: the pass rule in words, copied verbatim
    into the protocol; grade.sh and observations.py apply it.
  - `cases.pin.finding`, `cases.fix.finding`: the finding whose rule the pin expresses and the fix repairs.
  - `cases.pin.test_file`: the new test file the pin case asks for.
  - `cases.pin.instructions`, `cases.fix.instructions`: optional; one more sentence of task shape (e.g. how many rows).
  - `cases.fix.commit_prefix`: optional; the commit message prefix the fix case asks for.
  - `cases.fix.cause_in_prompt`: optional, `true` or `false` (default `true`). `false` leaves the finding's cause out of
    the fix prompt (the summary and the required behaviour stay), for a tier whose cause is unnamed; `true` or absent
    renders the prompt as before. The launch step of `run.template.js` refuses a value that is not a boolean, and the
    key on any other case or on a finding.
  - `cases.review.findings`: the ground-truth findings a review is graded on.
  - `cases.review.scope`: optional; the functions or sections the review covers.
  - `cases.pin.mutants`: optional; a list of single-rule mutants of the accepted source, each `{id, commit}`. With it,
    `grade.sh pin` also requires the candidate's new tests red with each mutant's source swapped in (`redAtMutants`).
    - `cases.pin.mutants[].id`: the mutant's id, as the grade reports it (each id once).
    - `cases.pin.mutants[].commit`: a commit in the pack's repository holding the mutant's `paths.source` files; they
      must differ from both the base's and the accepted fix's (grade.sh refuses a mutant that equals either).
  - `cases.gate`: optional; a task graded by a command rather than by tests against an accepted fix. A pack with only a
    gate case needs no `subject`, `findings`, `paths`, `commands` or `accepted_fix`.
    - `cases.gate.base`: the commit the case's checkouts hold.
    - `cases.gate.category`: the host category the cell represents (e.g. `research-collect`, `docs-mechanical`).
    - `cases.gate.tier`: the difficulty tier.
    - `cases.gate.pass_rule`: the pass rule in words, copied verbatim into the protocol.
    - `cases.gate.instructions`: the task, as the candidate reads it after the common preamble; it states what to
      produce, never the grading command.
    - `cases.gate.commands.gate`: run with bash in the candidate's checkout after the candidate finishes; exit 0 is
      one condition of a pass. Its side effects stay in the checkout.
    - `cases.gate.commands.timeout_seconds`: the limit on the command (a timeout reads as exit 124, never a pass).
    - `cases.gate.invariants`: paths (files or directories) whose files must hash as at the base, read as the
      checkout stands before the command runs (committed or not); a file added or removed under a directory breaks it.
      Each must exist at the base.
    - `cases.gate.required_paths`: paths that must exist in the checkout before the command runs. Every invariant and
      required path is relative: one rooted with `/` or `\`, with a drive letter or with a `..` segment is refused.
- `paths`: what grade.sh reads in a candidate's checkout.
  - `paths.source`: the source files the accepted fix changes; swapped for the accepted or base version while grading.
  - `paths.source_dir`: a pin cell may change nothing under it.
  - `paths.test_file`: the existing test file the fix case extends.
  - `paths.new_test_pattern`: a regular expression matching a new test file's path.
  - `paths.allowed_extra`: further files a fix may change (a map, a changelog).
  - `paths.map_file`: optional; the file whose change makes `committedWithMap` true.
  - `paths.accepted_test`: `{"from": <path in accepted_fix>, "to": <a free path in the checkout>}`; the accepted test
    is placed there and run against the candidate's source.
  - `paths.scratch_test`: a path pattern with `{name}` for the uncommitted scratch tests of reviews and lenses.
- `commands`: run in the checkout with bash.
  - `commands.test`: runs test files; `{files}` becomes the shell-quoted files and `{report}` a report path.
  - `commands.test_report`: `exit-code` (green is exit 0, red any other exit but a timeout or a missing command) or
    `vitest-json` (the report holds `numPassedTests`, `numFailedTests`, `numTotalTests`).
  - `commands.run_one`: optional; how a candidate runs one test file, with `{file}` (defaults to `commands.test`).
  - `commands.lint`: optional; lints `{files}`, clean on exit 0; null when the pack has no linter.
  - `commands.timeout_seconds`: the limit on each test or lint command.
- `checkout`: how checkouts are made.
  - `checkout.links`: the names under which dependency trees are symlinked into each checkout
    (`historyless-checkout.sh --link NAME=DIR`); grade.sh ignores them. The trees are installed outside the pack, never
    in its repository: a link into the pack is a path to the accepted fix, and the script refuses it.
- `source_hashes`: SHA-256 of every pack file the protocol records, under the protocol's hash convention.
- `isolation`: the pack's isolation statement, copied into the protocol's privacy line.
