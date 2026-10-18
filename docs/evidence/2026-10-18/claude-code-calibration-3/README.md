# Claude Code calibration run 3 — preregistered protocol

Status: **preregistered; launched after this file was committed.** The host assigned run id `wf_4e9ef48d-066`, launched
2026-10-18T05:24Z from the script whose hash the protocol records, after the protocol commit `0013451`.
Results come later as `observations.json`, `scores.json` and `results-table.md`; nothing here is a result.

Run 3 keeps the method of runs 1 and 2 and changes what their limits named:

1. **History-less checkouts.** Each candidate works in a fresh repository whose single root commit is the tree of the
   base revision (`historyless-checkout.sh`), so the accepted fix is not an object the candidate's git could reach.
2. **A defined classification.** The grader's "true" for an other finding needs three things: the behaviour holds at
   HEAD, it is reachable through the module's public API with input its contract admits, and the spec or the module's
   promise forbids it. A contract hole no admissible input reaches is at most S4.
3. **A preregistered adjudication.** The other S1-S3 findings of every review are clustered by mechanism, each cluster
   is judged by three independent lenses (reproduce, reachability, refute), and the adjudicated verdict is the scored
   one for false blocking findings. Run 2 did this post hoc; here it is part of the protocol.

Subject: the GitHub OAuth wire module of MoonAliza, whose contract (nothing rejects; no result carries GitHub's text) and
API (an injected fetcher may hand back any Response) make reachability well defined. Review at `0e7a7f3` (U1-R8 and
U1-R11 present); pin and fix at `e68583c` against the accepted fix `348aa2d`.

Files: `protocol.json` (the frozen protocol with source hashes), `grade.sh` and `historyless-checkout.sh` (byte-identical
copies of the host's scripts; host-local paths inside).

## Results (added 2026-10-18 after the run; the sections above are the frozen protocol)

Run `wf_4e9ef48d-066` finished 2026-10-18T06:44Z: 70 agents (39 items, 15 graders, 1 clustering agent, 15 lenses),
8,531,566 reported tokens, three agents at a time, 80 minutes; plus the supplementary run `wf_dbe29a64-3b2`
(amendment A-1: 4 agents, 456,376 tokens, 3 minutes). Scores in [scores.json](scores.json), the full observations in
[observations.json](observations.json) (the flat profile map the host adapter's `rate` reads, as in runs 1-2), the void
cells in [void-cells.json](void-cells.json), the table in [results-table.md](results-table.md), the clusters and their
lens verdicts in [clusters.md](clusters.md) and [adjudication.json](adjudication.json).

- **pin 11/12 PASS**: `fable-medium` FAIL on an over-specified pin that asserts the injected stream's cancel callback,
  which the rule does not state, so it stays red with the accepted fix (amendment N-1). **fix 12/12 PASS**, every one
  committed with the map through the subject's commit gate.
- **review 15/15 PASS** under the preregistered rules; **13/15 under the full three-prong definition** (G-2 below:
  `haiku-medium` and `haiku-high` carry `would_fail_under_three_prong: true` in `scores.json`). Every review found U1-R8 and U1-R11 with their causes
  (history-less checkouts: nothing to copy). Five clusters of other S1-S3 findings, all adjudicated REAL by the
  three-lens majority, so every grader `false` cleared. C-1, C-2 and C-3 (the body read and cancel never observe
  the bounded signal) are real on all three prongs in every lens: new S3 findings for the subject module. C-4 and
  C-5 read REAL on two prongs only (amendment G-2): the lens schema had no forbidden-by-spec field; the prose of the
  lenses says the specification permits both behaviours. The preregistered rule stands; it changes no qualification.
- **Contamination (A-1)**: the workflow harness relays the operator's latest chat message to every agent as the
  request that "wins" over the computed task. Two of 39 cells halted on it and were void, then re-run once; both PASS.
  The halts are an observation about instruction-conflict handling (both haiku; four other agents that mentioned the
  message did the task), not a capability grade.
- **Tokens, reconciled run by run** (`scores.json` `totals.tokens`):

  | run | items (cells) | graders | clustering | lenses | total |
  |-----|---------------|---------|------------|--------|-------|
  | main `wf_4e9ef48d-066` | 5,274,667 (39 cells, of which the two void cells 166,266) | 1,597,164 (15, of which the void review's grader 88,760) | 81,285 (1) | 1,578,450 (15) | 8,531,566 |
  | supplementary `wf_dbe29a64-3b2` | 272,858 (2 cells) | 107,524 (1) | 75,994 (1, the cluster-assignment agent) | 0 | 456,376 |
  | both | 5,547,525 | 1,704,688 | 157,279 | 1,578,450 | 8,987,942 |

  Scored cells (main items minus the void cells, plus the supplementary cells): 5,381,259, of which pin 1,385,282,
  fix 1,541,115, review 2,454,862. Judging (graders, clustering, lenses): 3,440,417 over both runs, about 38-39% of
  the total (38.2% of the main run alone). The review-only profiles cost, per model, 1.4x (sonnet-xhigh 227,264 vs
  sonnet-high 159,276), 1.9x (opus-max 266,339 vs opus-high 141,662) and 1.3x (fable-max 189,364 vs fable-high
  147,254) the high profile's review tokens for the same PASS.
- **Usage windows**: about 0.038 (five_hour) and 0.010 (seven_day) per Mtok over the run, lead included; consistent
  with run 2; no clean before or after reading exists for this run (units in flight at both).
- **Main, void and supplementary**: 39 cells ran in the main run; two (fix:haiku-high, review:haiku-low) are void
  under A-1 and are kept in `void-cells.json` with their main-run tokens; the two supplementary cells replace them in
  `observations.json` and `scores.json`, marked with `supplementary_run`. `void-cells.json` also lists the six agents
  whose structured output mentions the relayed message (the workflow journal itself is host-local and not committed).
- **Qualification consequences, under the host's rules (hosts/claude-code/README.md, rules 1-4), applied by the host
  in its policy revision 4, not by this evidence folder.** Negative: `fable-medium`'s pin FAIL blocks `pin-tests` for
  that profile until two later passes (rule 3, with the pin case read as `pin-tests` per rule 4 and amendment A-2).
  Positive: this run is the second review pass for `sonnet-high` (after a fail and a pass), `sonnet-xhigh`,
  `opus-max` and `fable-max` (two passes each), and the second pass for `sonnet-low` with a PARTIAL between (the
  host's call); `sonnet-medium` and `opus-medium` have one pass after a fail and need another; the three haiku
  profiles' run-3 review PASSes are one of the two later passes rule 3 needs after their two fails, and two of them are
  two-prong PASSes (G-2), so no haiku profile gains `review`. Every fix PASS is a further pass for already-qualified
  profiles. Nothing in this folder changes a policy.
- **What run 4 changes**: the `forbidden` prong in the lens schema (G-2); no operator chat relayed into workers, or
  the relayed text recorded before the launch (A-1); and, if the difficulty-tiers proposal is accepted, one T3 cell
  per category for the profiles qualified at T1.
