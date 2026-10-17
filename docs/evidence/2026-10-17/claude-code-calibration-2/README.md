# Claude Code calibration run 2 — preregistered protocol

Status: **preregistered; launched after this file was committed.** This
folder holds the protocol frozen before the run was launched. The host
assigned run id `wf_fe91e1d6-d78`, launched 2026-10-17T23:26Z from the
script whose hash the protocol records, after the protocol commit `9cf7079`. Results are added later as
`observations.json`, `scores.json` and `results-table.md`; nothing here is a
result, and no number in this folder describes a model's performance.

Run 1 is `../claude-code-calibration/` (`wf_052c5f34-973`). Run 2 keeps its
method and changes three things, each for a reason run 1 recorded:

1. **Harder tasks.** Run 1's defect (U5-R16) was a one-line order regression
   in a path the prompt pointed at, and every profile fixed and pinned it;
   only review separated profiles. Run 2 uses two accepted S3 durability
   findings of the GitHub account store (U2-R11, U2-R13): the review runs at
   `d3aaf21` where both are present; pin and fix run at `d0bb208` where only
   U2-R13 remains, against its accepted fix `587d445`.
2. **Two more efforts on review.** `sonnet-xhigh`, `opus-max` and
   `fable-max` run on review only, where the profiles separated least.
3. **Prompt defects of run 1 corrected.** The fix prompt states the subject
   repository's commit-gate rule (the architecture map staged with any
   `src/` change; run 1's lead mistake L-1) and asks for typecheck, lint and
   the five-part commit message; the pin prompt asks for lint, so lint is
   part of its pass rule this time.

The review pass rule is three-valued (PASS both found, PARTIAL one found,
FAIL) with no false blocking finding and no copying from history in either
of the first two; only PASS counts toward the host policy's two-pass
qualification rule. See [protocol.json](protocol.json) for the exact rules,
fields, metrics, accounting and limits.

A fourth measurement rides on the run: the platform's two usage windows are
read with nothing in flight before the launch and after the last agent, so
the run's total reported tokens give one clean observation of the adapter's
`utilization-per-mtok` coefficients (the host's usage-windows gate declares
them from two coarse observations; see the adapter README, "Usage windows").

## Files

- `protocol.json` — the frozen protocol, with SHA-256 hashes (UTF-8,
  CRLF/CR normalized to LF) of the ground truth, the workflow script (the
  run is launched from that file by path, so its hash predates the launch),
  the finding text and the grader script, by their host paths. The ground
  truth, prompts and finding text stay off this repository on purpose.
- `grade.sh` — byte-identical copy of the host's `cal-grade-2.sh`. Its
  paths (the scratchpad, `/home/user/task5-handoff/wt/cal2-<task>-<profile>`
  worktrees, `/home/user/moonaliza`, the Node install) are host-local; to
  re-run it elsewhere, point them at a MoonAliza clone holding `d0bb208` and
  `587d445` and at the candidate worktrees.

## Accounting

As in run 1: a subscription host, no per-call price; tokens and wall time
from the workflow journal; an estimate-only cash column from
`tools/prices-2.json` that supports no savings claim; unknown values null.
