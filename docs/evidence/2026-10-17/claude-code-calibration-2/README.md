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

## Results (added 2026-10-18 after the run; the sections above are the frozen protocol)

Run `wf_fe91e1d6-d78` finished 2026-10-18T01:24Z: 54 agents (39 items + 15 graders), 7,872,276 reported tokens,
three agents at a time, 119 minutes. Scores in [scores.json](scores.json), the full observations in
[observations.json](observations.json), the table in [results-table.md](results-table.md).

- **pin 12/12 PASS, fix 12/12 PASS** (lint now part of the pin pass; every fix committed through the subject's
  commit gate with the map staged). The harder fix did not separate the profiles either; what keeps small profiles
  off large units in the host policy is the headroom guard, not these cells.
- **review**: PASS sonnet-high, sonnet-xhigh, opus-high, opus-xhigh, opus-max, fable-medium, fable-high,
  fable-xhigh, fable-max; PARTIAL sonnet-low; FAIL haiku-low, haiku-medium, haiku-high, sonnet-medium,
  opus-medium. Every profile found U2-R13; U2-R11 (the rollback's un-named refs) is what the small and low-effort
  profiles missed. The three review-only profiles (sonnet-xhigh, opus-max, fable-max) cost 1.3-2.0x the tokens and
  2-6x the wall time of the high profiles for the same PASS.
- **One harness error**: fix:haiku-low's structured return was rejected five times (missing `mistakes`); its worktree
  grades PASS (protocol amendment).
- **Grader inconsistency (G-1)**: the same other finding ("clear() after an unreadable open answers durable without
  writing") was classified true by five candidates' graders and false by two on reachability; a post-hoc
  cross-candidate adjudication (three independent lenses per distinct claim) found two of the six recurring claims real
  and the contested one unreachable through the spec's flows; the split traces to the grader instruction, which did
  not say whether reachability is part of a finding holding. Recorded as an amendment with every lens's verdict; the
  preregistered scores stand, and run 3 must define the question and preregister the adjudication.
- **Usage windows**: 0.0343 (five_hour) and 0.0102 (seven_day) per Mtok of reported sub-agent tokens, upper bounds;
  lead-only work moved five_hour by 0.10 in 15 minutes with no agent running. The host policy's declared 0.24 / 0.06
  were 6-7x too high, and its lead reserve covered about eight minutes of the lead's own work (host adapter README,
  "Usage windows", revision 3).
