# Claude Code calibration run `wf_052c5f34-973` — preregistered protocol

Status: **preregistered; run in progress.** This folder holds the protocol
frozen at 2026-10-17T19:05:00Z, before any result was recorded. Results will
be added later as `observations.json` and `scores.json`; nothing here is a
result, and no number in this folder describes a model's performance.

## What is measured

Twelve profiles (model × effort) on a Claude Code subscription host:

| Model (host alias) | Efforts |
| --- | --- |
| Claude Haiku 5.5 (`haiku`) | low, medium, high |
| Claude Sonnet 5.5 (`sonnet`) | low, medium, high |
| Claude Opus 5.5 (`opus`) | medium, high, xhigh |
| Claude Fable 5.1 (`fable`) | medium, high, xhigh |

Each profile runs three tasks once, each in its own git worktree at MoonAliza
`d87f796`, a state of the GitHub sign-in unit (U5) with one known accepted
defect: review finding U5-R16 (S2), fixed by commit `4151a25`.

- `pin` (build-tests): a red-first pin test for the rule, in a new file, no
  source change. Graded mechanically.
- `fix` (fix): fix the finding from its accepted text, red-first, lint,
  commit. Graded mechanically.
- `review` (review): a refute-first review of the refresh path, graded by an
  Opus 5.5 high-effort grader agent against the ground truth (U5-R16 and the
  S4 finding U5-R17).

The exact pass rules, grader fields, metrics, accounting and limits are in
[protocol.json](protocol.json). Two points a reader should not miss: the
pin task's scored pass excludes lint (its instructions never asked for it;
lint is reported separately as hygiene), and `review` has no composite pass,
only the grader's fields.

## Files

- `protocol.json` — the frozen protocol. `sources` records SHA-256 hashes
  (UTF-8, CRLF/CR normalized to LF) of the ground truth, the workflow script
  holding the prompts, the fix task's finding text and the grader script, by
  their host paths. The ground truth, prompts and finding text are kept off
  this repository on purpose; only their hashes are here.
- `grade.sh` — byte-identical copy of the host's `cal-grade.sh`, so the
  mechanical grading of `pin` and `fix` can be read and re-run. Its paths
  (the scratchpad, `/home/user/task5-handoff/wt/cal-<task>-<profile>`
  worktrees, `/home/user/moonaliza`, the Node install) are host-local; to
  re-run it elsewhere, point them at a MoonAliza clone holding `d87f796` and
  `4151a25` and at the candidate worktrees.

## Accounting

The host is a subscription: there is no per-call price or bill. Tokens and
wall time come from the workflow journal as the harness reports them, not
from a provider bill. An estimated cash column will apply the rows of
`tools/prices-2.json` (revision `prices-2`) to those tokens and is labelled
estimate-only; it supports no savings claim. Unknown values are recorded as
null, never zero.
