# Contributing to Holdshort

Thank you for helping improve Holdshort. Documentation, reproducible bug reports,
tests, and focused code changes are all welcome. You do not need to be an expert in
model routing to contribute.

## Choose a starting point

- [Good first issues](https://github.com/StepenkoAnatoli/Holdshort/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22good%20first%20issue%22)
  describe small tasks with clear acceptance checks.
- [Help wanted](https://github.com/StepenkoAnatoli/Holdshort/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22help%20wanted%22)
  identifies work where community contributions would help.
- [LLM testing issues](https://github.com/StepenkoAnatoli/Holdshort/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22llm%20evaluation%22)
  cover unseen fixtures, repeated GPT comparisons, Claude, offline Gemini adapters,
  local models, and usage capture. Each issue defines its acceptance criteria.
- For a substantial change, open an issue describing the problem and proposed scope
  before investing in the implementation. Avoid duplicating an existing issue.

Read the [README](README.md) first. The [canonical skill](skills/holdshort/SKILL.md)
and [host contract](skills/holdshort/references/spec-v2.md) define behavior;
the [engineering review](docs/HOLDSHORT_USAGE_REVIEW_2026-10-13.md) records known gaps.

## Set up a fresh clone

You need Git, Bash, and Python. GitHub CI uses Python 3.12. On Windows, install
Git for Windows and make Git Bash available on `PATH`. Use `python3` in place of
`python` below if that is your interpreter's command name.

Fork the repository on GitHub, then clone your fork and create a branch:

```bash
git clone https://github.com/YOUR-USERNAME/Holdshort.git
cd Holdshort
git remote add upstream https://github.com/StepenkoAnatoli/Holdshort.git
git switch -c docs-improve-example
python tools/install_hooks.py
python tools/validate_skills.py --strict
python tests/holdshort_decisions.py
```

Set your intended Git author name and email in the clone before committing.
The hook installer changes this clone's hook configuration, not your global
configuration. The longer `setup_machine.sh` onboarding proof also changes the
clone's author identity, so use that proof only in a clean, disposable clone.

## Make a focused change

Define how you will verify the result before changing behavior. Keep unrelated
refactors, generated machine state, and other projects out of the pull request.
Use a separate branch or worktree when work could overlap with another task.

For documentation, check that examples run, relative links exist, and the text
agrees with the canonical policy. For code, add or update a meaningful test for
the behavior you changed, including a relevant failure or boundary case. A test
that repeats the implementation without checking observable behavior adds little.

Preserve the project's core rules:

- Apply eligibility checks before comparing models or sending work.
- Keep verification and the cost of verification in the task's contract.
- Preserve counters and terminal stops across restarts.
- Enable human checkpoints only from an explicit user request.
- Use synthetic data in tests. Keep API keys, private logs, account identifiers,
  and consumer credentials out of commits and public reports.
- Report missing accounting as unknown, rather than zero or a savings claim.

Keep evaluation ledgers append-only. Disclose corrupt or incomplete records;
do not edit them to manufacture a passing result. Preserve decision status labels
(such as RATIFIED, PENDING, and PROPOSED) and signing provenance when changing an
evaluation contract. Use the task cross-check to surface disagreements between
persisted counters and the ledger.

Live provider calls require a separately authorized protocol and spend allowance.
An ordinary contribution or passing CI is not authorization to run them.
The current live adapter permits only the approved Anthropic endpoint
(`https://api.anthropic.com`). Its key belongs in the local, gitignored `.env`;
provider and destination changes require the evaluation protocol's authorization.

## Verify and commit

Run the full gate from the repository root:

```bash
python tools/run_regression.py
git diff --check
git add README.md
git commit -m "docs: clarify the local supervisor example"
git push -u origin docs-improve-example
```

Replace the example filename and branch with those for your change. Stage only
intended files. The enabled pre-commit hook runs the full gate again against the
staged content. Resolve failures before committing; do not bypass the hook.
Some gate steps inspect local credential or application stores. Use synthetic
fixtures for tests and review genuine findings without exposing their values.

Write commit subjects that explain the result in the imperative. A short optional
prefix helps readers scan the history:

| Example | Appropriate change |
| --- | --- |
| `docs: add a blocked supervisor example` | User-facing instructions or examples |
| `fix: reserve task budget before dispatch` | A behavior correction |
| `test: cover restart with corrupt task state` | Verification coverage |
| `ci: verify routing fixtures in the regression gate` | Contributor or CI checks |

For a complex change, use the commit body to explain the original problem, the
chosen behavior, and any important tradeoff. Avoid subjects such as "update",
"stuff", or "fix bugs" that leave reviewers guessing.

## Open a pull request

Target `main` in the upstream repository. Describe the problem, the resulting
behavior, and the checks you ran. Link the issue with `Fixes #NUMBER` only when
the change actually completes that issue. For partial work, use `Related to #NUMBER`.

GitHub runs the regression gate and watcher proof. Required checks must pass
against the current base before merge. If `main` moves, update your branch and
let CI verify the new result. Maintainers may request a focused revision.

Be clear about limitations. A local fixture pass does not establish live-model
qualification, provider billing accuracy, or production adoption.

## Understand issue labels

| Label | Meaning |
| --- | --- |
| `good first issue` | A small task suitable for a newcomer, with explicit acceptance checks |
| `help wanted` | Community contributions are welcome |
| `bug` | Reproduced or reported incorrect behavior |
| `documentation` | Instructions, examples, or explanations need improvement |
| `enhancement` | A proposed capability or usability improvement |
| `tests` | Test coverage, fixtures, or verification |
| `ci` | GitHub Actions or contributor checks |
| `priority: high` | An important correctness or accounting problem |
| `maintainer decision` | A scope or policy decision needs an explicit maintainer answer |

Maintainers assign labels after triage. Complex budget and recovery bugs should
not be marked as beginner tasks merely because they need help.

## Report a bug

Use the [bug report form](https://github.com/StepenkoAnatoli/Holdshort/issues/new?template=bug_report.yml).
Include the commit, operating system, Python version, exact steps, expected result,
and observed result. Prefer a minimal reproduction using synthetic data.

If the issue concerns credential leakage, do not paste the credential or a raw
session export. Describe the affected writer or surface and show a synthetic
reproduction. A value-free digest or count can help identify a finding safely.

## Collaboration and license

Keep feedback specific, respectful, and focused on the work. Credit useful prior
work and explain disagreements with evidence.

Read [LICENSE](LICENSE) for the existing grant and its stated scope. It currently
names planning documents; skill metadata separately declares a license. Do not
assume that this settles licensing for every tool file, historical version, or
third-party dependency. Changes to license scope need a maintainer decision.
