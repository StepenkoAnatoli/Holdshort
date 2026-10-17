# Calibration run 1 (wf_052c5f34-973) - lead's notes and the lead's own mistakes

## Lead mistake L-1 (prompt defect, fix task)
The fix prompt said "Do not touch any other file" and "Commit test and fix together", while the repository's
commit gate (standing protocol rule 1, research/kit.json declared code paths) refuses a commit that touches
src/main/github-signin.ts without docs/ARCHITECTURE.md staged. The real build briefs (common.md) say so; the
calibration prompt did not. Impact: 7 candidates stopped at the gate and left the work staged (haiku low/
medium/high, sonnet low/medium/high, opus-medium), 3 deviated deliberately and committed with a one-clause
map update (opus-high, opus-xhigh, fable-medium); fable-high/xhigh pending. Both behaviours are defensible;
neither is a model failure. Grading: the mechanical checks run on the working tree (staged or committed);
a "committedWithMap" column records the deviation; docs/ARCHITECTURE.md is an allowed file.
Cause: the lead wrote the calibration prompt without re-reading the commit gate's rule. Fix: this note and
the script change; the next calibration prompt names the map rule. Verified: grades re-run (see cal-grades/).

## Lead mistake L-2 (grading script)
cal-grade.sh computed `changed` and `srcDiffLines` from `d87f796..HEAD` only, so staged-but-uncommitted
candidates showed "commits 0, srcDiff 0" while their tests passed. It also restored src with
`git checkout -- file`, which restores from the index: a staged candidate change survived (verified by
`git status` after grading: still `M  src/main/github-signin.ts`); an unstaged one would have been lost.
Fix: `changed` is the union of committed, staged and unstaged; srcDiff is working tree vs base.

## Pin task: lint not requested
The pin prompt did not ask for eslint; 4 of 12 left unused imports from copying the harness (sonnet x3,
opus-medium). Reported as a hygiene column, not a task failure.
