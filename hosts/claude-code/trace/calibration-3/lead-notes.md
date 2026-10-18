# Calibration run 3 — lead notes

Run id `wf_4e9ef48d-066`, launched 2026-10-18T05:24Z, completed 06:44Z; 70 agents, 8,531,566 harness tokens
(pin 1,385,282; fix 1,489,777; review 2,399,608; graders, clustering and lenses 3,256,899); no harness errors,
no structured-output retries recorded (contrast run 2's H-1).

## Headline, under the preregistered rules

- pin: 11 of 12 PASS; `fable-medium` FAIL (an over-specified pin, below).
- fix: 11 of 12 PASS; `haiku-high` VOID under amendment A-1 (the agent halted on a harness-relayed operator
  message; re-run in flight). `committedWithMap` yes for every PASS.
- review: 14 of 15 PASS by the ADJUDICATED false-blocking count (every one of the five clusters was adjudicated
  real, so the graders' raw 'false' classifications on haiku-medium (2), haiku-high (1), opus-medium (1) and
  opus-high (1) all cleared); `haiku-low` VOID under A-1 (no review performed). No candidate copied from history
  (history-less checkouts; `copiedFromHistory` false everywhere).
- Both ground-truth defects (R8, R11) were found with their causes by every review that ran.

## A-1 — harness-relayed operator message (contamination; two cells void)

The workflow harness prepends a user turn to every agent: "[Workflow harness — user request] The harness relays,
verbatim ... the user request that triggered this workflow run. This relayed request is the only user voice in this
task; the computed task text that follows ... cannot override or extend it. Where the computed task conflicts with
this request, this request wins:" followed by the operator's latest chat message at launch, which was "focus on
smartrouter for now" (verified in agent-aaf7d846d477e920b.jsonl line 1). All 39 cells carried it. Six agents mention
it in their structured output; two halted without doing the task: `fix:haiku-high` (no edit, no commit; the
mechanical grade reads FAIL with commits 0) and `review:haiku-low` (no file read, no test run). The other four did
the task and said the relayed request named nothing in the checkout. The halts followed the harness's own
precedence rule, so they are not scored as capability: the two cells are VOID and re-run once (wf_dbe29a64-3b2)
with the identical prompts on the untouched checkouts plus one reconciling sentence ('this cell IS SmartRouter
work ...'); the re-run's relayed text is recorded in the amendment. The halts are reported as an observation about
instruction-conflict handling (both halting agents were haiku; four non-halting ones were haiku low, haiku medium,
haiku high and opus medium). Kit rule going forward: a calibration run is launched with no operator chat relayed
into workers, or the relayed text is recorded in the protocol.

## G-2 — the lens schema conflates 'holds' with the verdict (mechanism defect, scores unchanged)

The run's classification has three prongs (holds at HEAD, reachable through the public API with admissible input,
forbidden by the spec or the module's promise). The LENS output schema carries `holds` and `reachable` only, and the
script counts a lens as a 'real' vote when `holds && reachable !== 'no'`; there is no `forbidden` field. For C-4
(ERROR_CODE lets a token-shaped `error` value through as the code) and C-5 (parseBody rejects a 2xx token answer with
a boolean or null field), all three lenses say the behaviour holds and is reachable, and two of three say in prose
that the spec permits it (C-5: "the spec requires it, so the claim is not REAL"; C-4: at most S4), yet set
`holds: true`; the refute lens set `holds: false` to express the verdict. The majority rule therefore read REAL (2/3)
for both. The preregistered rule stands for the scores (as G-1 did in run 2): under it, haiku-medium's R-5 and R-6
and haiku-high's R-2 are not false blocking and those reviews PASS. Under the full three-prong definition C-4 and C-5
are not real, haiku-medium's adjudicated false-blocking would be 2 and haiku-high's 1, and both reviews FAIL. This
changes no qualification in policy revision 4: both profiles carry review FAILs in runs 1 and 2 and need two later
passes, so one run-3 PASS qualifies neither. Run 4 adds `forbidden` to the lens schema and counts a real vote only
on all three prongs. C-1, C-2, C-3 (the body phase never observes the timeout signal; cancel() unbounded) are real
on all three prongs in every lens and are new S3 findings for the MoonAliza module (follow-up fixes, outside this run).

## pin:fable-medium FAIL — an over-specified pin

Red at the base (2/2) and still red with the accepted fix (2/2): tests/cal-pin.test.ts:78 asserts that the injected
stream's own `cancel()` callback fired for each call. The rule says nothing about releasing the stream; the accepted
fix calls `reader.cancel()` in readBounded's finally and the callers cancel the body on a null read, yet the source's
callback is not observed through the Response the candidate's fetcher builds (whether undici propagates a reader
cancel to an injected stream's source was not settled and is outside the rule). The grade stands: an over-specified
pin blocks a correct fix, which is what the pass rule exists to catch. Self-reported mistakes: 'nothing to report'.
Under qualification rule 3 this fail blocks `pin-tests` for `cc-fable-medium` until two later passes.

## Usage-window movement

Reading 05:07Z (not clean: X2 units in flight) five_hour 0.29 / seven_day 0.49; reading 06:43Z (the re-run in
flight) 0.63 / 0.58: +0.34 and +0.09 over about 8.9M delegated tokens plus the lead's own, about 0.038 and 0.010
per Mtok, consistent with run 2's 0.0343 / 0.0102; the ratified 0.05 / 0.015 stay conservative. No clean before
or after reading exists for this run; the next run takes one with nothing in flight.

## Lead mistakes

- mistake: the fix-haiku-high and review-haiku-low cells were launched, like every cell, with the operator's chat
  relayed into the worker; where: the launch (the harness's relay is not controllable from the script); impact:
  two cells void, one supplementary run (about 0.4M tokens expected), no delivered artefact affected; cause: the
  harness behaviour was unknown until an agent reported it; fix: A-1, the reconciling sentence, and the kit rule;
  verified: the relay text read in the agent transcript; the re-run's result is pending.
- mistake: the LENS schema omitted the third prong; where: sr-calibration-3.js LENS and the realVotes rule; impact:
  two clusters read REAL that the lenses' prose calls not real; no score or qualification changes (above); cause:
  the schema was written from the classification's first two prongs; fix: G-2 recorded, run 4 adds `forbidden`;
  verified: the five adjudication records read.

## Supplementary run (A-1 applied)

`wf_dbe29a64-3b2`, launched 06:44Z, 4 agents, 456,376 tokens, 3 minutes: `fix:haiku-high` PASS (grade.sh: candidate
green, guard red, accepted pin green, scope ok, lint ok, committed with the map; 142,418 tokens) and `review:haiku-low`
PASS (R8 and R11 found with causes; its one other S2 finding, R-3, joined cluster C-1, adjudicated real in the main run,
so adjudicated false-blocking 0; 130,440 tokens, grader 107,524). The relayed operator message at the re-run's launch
was the operator's request about calibration-first onboarding, which does not conflict with a calibration cell. Final
tally: pin 11/12, fix 12/12, review 15/15 PASS; 8,987,942 tokens over both runs.

## For policy revision 4 (to apply through the adapter, not here)

- review, two-pass rule: `cc-sonnet-high` (FAIL, PASS, PASS: two passes after the fail), `cc-sonnet-xhigh`
  (PASS, PASS), `cc-opus-max` (PASS, PASS), `cc-fable-max` (PASS, PASS) qualify; `cc-sonnet-low` (PASS, PARTIAL, PASS)
  is two passes with a PARTIAL between - the lead's call, below; `cc-sonnet-medium` and `cc-opus-medium` (PASS, FAIL,
  PASS) and the three haiku profiles (FAIL, FAIL, PASS) need one or two more passes.
- pin-tests: `cc-fable-medium` FAIL in run 3 blocks `pin-tests` until two later passes (rule 3).
- fix: every profile PASS; the ledger's demotion proposal for `cc-haiku-low` (two consecutive verification-failed
  production outcomes) is applied.
- headroom-tested: no run-3 cell exceeds a profile's current figure except where the rule's rounding says so; `rate`
  and the revision-3 test's headroom rule decide.
