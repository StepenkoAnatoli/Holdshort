# Calibration run 2 (wf_fe91e1d6-d78) - lead's notes and the lead's own mistakes

Launched 2026-10-17T23:26Z, finished 2026-10-18T01:24Z: 54 agents (39 items + 15 graders), 7,872,276 reported tokens,
three agents at a time. Preregistered upstream before the launch (SmartRouter `docs/evidence/2026-10-17/claude-code-calibration-2/`,
commit 9cf7079; run id at 98d4c8a). Results: `results-table.md`, `observations.json`, `tokens-and-estimates.md`.

## What the run showed
- **pin 12/12 PASS, fix 12/12 PASS** (every fix committed through the subject's gate with the map staged, lint and
  typecheck clean by the mechanical grade and the self-report). The harder fix (a new re-read step under a lock) did not
  separate the profiles either: the headroom guard, not the pass/fail, is what keeps small profiles off large units.
- **review** separated them: PASS sonnet-high, sonnet-xhigh, opus-high, opus-xhigh, opus-max, fable-medium, fable-high,
  fable-xhigh, fable-max; PARTIAL sonnet-low (R13 only, no false blocking); FAIL haiku-low/medium/high (R11 missed, false
  blocking findings), sonnet-medium (R11 missed, one false), opus-medium (both found, one finding the grader called false:
  see G-1). Every profile found R13; R11 (the rollback's un-named refs) is what the small and low-effort profiles missed.
- **Tokens**: the three review-only profiles cost 1.3-2.0x a high-effort review (sonnet-xhigh 328k and 38 min, opus-max
  307k and 23 min, fable-max 229k and 18 min) for the same PASS the high profiles reached; max effort bought nothing here.

## Usage-window measurement (the run's fourth result)
Readings with nothing in flight: 23:22:51 five_hour 0.12 / seven_day 0.28; 01:23:32 five_hour 0.39 / seven_day 0.36
(the last event before completion). Over 7,872,276 reported tokens: **0.0343 per Mtok five_hour, 0.0102 per Mtok seven_day**,
the lead idle but for one check-in (00:29). The policy declared 0.24 and 0.06: about 7x and 6x too high. Separately,
lead-only work moved five_hour 0.02 -> 0.12 between 23:07 and 23:22 (no sub-agent running): about 0.40 per hour of active
lead work. The lead's own turns are this host's dominant cost; `lead-reserve` 0.05 covers about eight minutes of them.
`rate` could not learn any of this: the run was not dispatched through the adapter, so every pair of readings had T=0
recorded outcome tokens (skipped), and during ordinary work every pair spans a running unit. Policy revision 3 ratifies
measured values (briefs/policy3-builder.md) and the friction log carries the learning-loop gap upstream.

## Harness finding H-1 (corrected from the 00:29 check-in note)
fix:haiku-low was not hung: the harness retried its StructuredOutput five times (cap) because the output kept omitting
the required `mistakes` field, then reported the agent as an error (journal: "StructuredOutput retry cap (5) exceeded").
Its worktree holds a complete, committed fix (8781c1f) that grades PASS mechanically. Recorded as a harness retry, not a
model retry (the protocol's retry_limit 0 is about re-running the task); its self-reported fields are null.

## Grader finding G-1: inconsistent classification of the same 'other' finding across candidates
Seven candidates reported the same defect ("clear() after an open() that could not read the file answers 'durable'
without writing, and the next start signs in"): the graders of five called it true (S2/S3), the graders of haiku-medium
and opus-medium called it false on reachability (the UI offers Sign out only while signed in). Two candidates reported
"cap() ignores a failed removal": one grader true, one false. A per-candidate grader cannot be consistent across
candidates, and opus-medium's FAIL rests on that one classification. Adjudication (workflow `wf_603131fc-773`: three
independent fable-high lenses per distinct claim - reproduce, reachability, refute - majority verdict) is recorded in
this file once it returns and in the upstream evidence as a post-hoc amendment; **the preregistered rule stands for the
scores** (opus-medium review FAIL), and run 3's protocol preregisters a cross-candidate adjudication step.

## Lead mistakes
- **L-3 (duplicate decision record).** The lead ran `route.mjs decide` twice for sr-policy-3 after the policy fix (seq 2
  and seq 3, identical routes); the dispatch (seq 4) names seq 3. Where: the lead's shell, 01:37. Impact: one redundant
  ledger line and decision file; no dispatch or budget effect (a decision reserves nothing). Cause: a second command
  meant as a dry run was a real call. Fix: none possible (the ledger is append-only); recorded here and in RUN.md.
  Verified: `route.mjs status sr-policy-3` (last seq 4, calls 1/6).
- **L-4 (stale headroom).** The accepted sr-policy-2 outcome (770,527 tokens on cc-opus-high) did not raise
  cc-opus-high's headroom-tested (514000), so the first sr-policy-3 decision was blocked (every profile failed the context
  check for a 600,000-token estimate). Impact: one blocked decision, no dispatch. Cause: the adapter proposes no headroom
  raise and the lead did not apply the policy's own definition at the outcome. Fix: policy maintenance commit 490b7ed and
  deliverable F in the policy-3 brief. Verified: decision seq 2/3 route delegate to cc-opus-high.
- The 00:29 check-in note called fix:haiku-low "hung"; see H-1.

## G-1 outcome: the adjudication (wf_603131fc-773, 18 fable-high lenses, 2,611,427 tokens, 34 min)
Six distinct claims, three independent lenses each (reproduce at HEAD with the real startup order; reachability through
the service and the spec's flows; refute). A claim is real when at least two lenses find it holds and reachable.
Verdicts: **C-B real (S3)** and **C-C real (S3 by reachability, S4 by the other two; a vault defect, unit U0)**; C-A, C-D,
C-E and C-F not real (C-A and C-D hold in code but no flow reaches the state; C-E's consequence needs a reconcile failure
survived, which startup does not do; C-F is pinned at HEAD and cleared by the service on any refresh ReplaceFailure).

What it says about the grades. No preregistered score changes. The two graders that called C-A false (haiku-medium,
opus-medium) reasoned on reachability and agree with the adjudication; the five that called it true (haiku-low,
haiku-high, opus-high, fable-medium, fable-max) followed the grader instruction's letter ('false' = the claim does not
hold, or the test does not show what it says), under which a code behaviour that reproduces is 'true'. The root cause
is the lead's grader instruction, which did not say whether reachability through the spec'd flows is part of 'holds';
two readings were defensible and the graders split. Under a reachability-strict reading, the C-A claims of opus-high,
fable-medium and fable-max (filed S2/S3) would be false blocking findings and those three reviews would FAIL; under a
code-behaviour reading opus-medium's review would PASS. Neither post-hoc reading is applied: the preregistered rule and
the grader's raw fields stand for the scores and for policy revision 3's qualifications (fable-medium's second review
pass carries this caveat in the README). Run 3's protocol must define the classification question (reachability through
the spec'd flows is part of a blocking finding; a contract hole no flow reaches is S4) and preregister the
cross-candidate adjudication step. The `true_extra_findings` counts in scores.json are the graders'; adjudicated, the
only real extras are C-B (sonnet-medium, sonnet-xhigh, opus-high, opus-xhigh, opus-max) and C-C (haiku-high, opus-max;
sonnet-high filed it S4).

### C-A: clear() after an unreadable open() answers durable without writing - **not real** (1/3 lenses hold and reachable)
- reproduce: holds True, reachable unclear, severity S4. Reproduced at HEAD with the real store and the index.ts start order, no rejection swallowed, no hand-built disk: open() :76-79 catches EBUSY (errno code is a string, so startupWrite stays false), disk and live stay null, finishStartup :111 writes nothing; then clear(() => true) :175-178 passes admit on live=null, taken=[], clearLocked :186-188 computes all=[] from disk=null and returns 'durable' with no tombstone and
- reachability: holds True, reachable no, severity S4. Holds: open() reads via boundedJson -> regularFile -> fsp.lstat (src/models/artifact-files.ts:7,41); an EBUSY rejection has a string code, so github-account-store.ts:79 sets startupWrite=false and :75/:80 leave disk=null, live=null. clear(() => true) then passes at :175, takes [] at :176-177, clearLocked sees live===null, accountRefs=[] and all=[] (:186-187) and returns 'durable' at :188 with no tombstone and no writ
- refute: holds True, reachable no, severity S4. Refutation by code failed: with the U2-R9 lstat-EBUSY open (src/main/github-account-store.ts:76-80 leaves disk=null, live=null, startupWrite=false), clear(() => true) passes admit on null (:175), takes no refs (:176), and clearLocked returns 'durable' at :188 before the step-2 write, leaving account.json byte-identical; the next start reads it and is signed in with both refs committed (scratch test). Refutation by sp

### C-B: a crash between the file write and the commit, then an unreadable start, loses the account - **REAL** (3/3 lenses hold and reachable)
- reproduce: holds True, reachable yes, severity S3. Reproduced at HEAD with the real Vault and the real store, the startup run as index.ts:181-184 runs it for a store (open; reconcile awaited with no catch; finishStartup). The crash snapshot is taken inside the first commit() of the second replace, i.e. after step 4's atomicJson rename (github-account-store.ts:141) and before any commit (:143) - the same point the suite's own crash-window test 'after the file write, b
- reachability: holds True, reachable yes, severity S3. Holds: src/main/github-account-store.ts:76-79 — boundedJson's first I/O is lstat (src/models/artifact-files.ts:7, :41); an errno error leaves disk=null, live=null, startupWrite=false, so references() (:95) is [] and vault.reconcile (src/main/vault.ts:112-116) unlinks and deletes the still-staged pair named by the untouched, valid file; the next readable start's open() tombstones retiredRefs (:87, the old pair of a re
- refute: holds True, reachable yes, severity S3. Tried to refute on three fronts; none held. (1) Code: open() on an I/O error leaves live null (github-account-store.ts:76-80,89) so references() is [] (:95); vault.reconcile (vault.ts:113-118) unlinks staged entries not in the set and deletes them from the index; finishStartup skips the write (errno code is a string, :79) so the file survives intact; the next readable start's open() tombstones retiredRefs (:81-87), t

### C-C: vault.saveStaged leaves an unindexed .bin when its persist fails - **REAL** (3/3 lenses hold and reachable)
- reproduce: holds True, reachable yes, severity S4. Holds at HEAD: vault.ts:87-91 opens and fsyncs `<ref>.bin`, sets `this.index.entries[ref]` in memory, then persist(); a persist rejection (vault.ts:73 open 'wx' or :78 rename, e.g. ENOSPC/EIO or a locked index.json on Windows) propagates with the .bin on disk and no unlink. Store replace() step 2 (github-account-store.ts:125-127) pushes the ref only after the await resolves, so `staged` lacks it and discard() cannot 
- reachability: holds True, reachable yes, severity S3. Holds by reading: src/main/vault.ts:87-89 writes and fsyncs `<ref>.bin`, :90 sets the memory entry, :91 awaits persist(); persist (:71-79) can throw at open/write/sync or the rename over index.json, and saveStaged has no catch, so the .bin stays and the ref never returns. The store's replace step 2 (src/main/github-account-store.ts:125-127) discards only refs that were pushed, exactly as spec 4.3 step 2 orders, so it
- refute: holds True, reachable yes, severity S4. Mechanism confirmed at HEAD: vault.ts:87-91 writes `${ref}.bin`, sets the in-memory entry, then persist() throws; nothing unlinks the file, serial() swallows the rejection (:62), and the store's step 2 (github-account-store.ts:125-127) only discards refs saveStaged returned. initialize()/reconcile() (:36-48, :108-117) walk index entries only, so a restart with that index leaves the .bin and stops redacting its token 

### C-D: cap() ignores a failed removal, leaving a dropped ref committed and unnamed - **not real** (0/3 lenses hold and reachable)
- reproduce: holds True, reachable no, severity S4. Mechanically the claim is right: cap() (src/main/github-account-store.ts:218-222) awaits drop(ref) and discards its boolean, so a dropped ref whose removal failed is in neither the kept list (:221) nor replace's step-7 `failed` (:156) nor clearLocked's `failed` (:210). My MECHANICS test shows that if index.json held such a ref as committed, the next start keeps it and vault.redact throws REDACTION_UNAVAILABLE (vault.
- reachability: holds True, reachable no, severity S4. Code reads as claimed: cap() (github-account-store.ts:218-222) awaits drop() and discards its boolean, so a dropped ref whose retire()/removeTombstoned() returned false is in neither `kept` nor any `failed` list; called from replace step 4 (:140) and clearLocked (:196). But the harmful state (dropped ref still committed in the on-disk index, .bin gone) is not reachable through the spec's flows (6.3 sign-in replace, 6
- refute: holds False, reachable no, severity none. Mechanics as stated are true: cap() (github-account-store.ts:218-222) ignores drop()'s boolean, so a dropped ref whose removal failed is named by no file. The harm, though, needs the dropped ref to still be 'committed' in the ON-DISK vault index, and no flow produces that: (1) replace's cap (:140) runs only after step 2's saveStaged, whose persist (vault.ts:91) writes the whole in-memory index, in which every previou

### C-E: a retired ref whose tombstone never reached disk is un-named by finishStartup - **not real** (0/3 lenses hold and reachable)
- reproduce: holds False, reachable no, severity none. Built the real 4.5 "commit, before retiring" crash state (file names the old pair in retiredRefs, index holds it committed), then ran the next start as src/main/index.ts:181-184 does: open(), `await vault.reconcile(set)` with no catch, finishStartup(). The barrier is vault.ts:164-167 + :106-121: tombstone() marks the entry 'tombstoned' in memory before its persist, and reconcile reads that memory, so (A) if the disk 
- reachability: holds False, reachable no, severity none. Mechanically the store does drop a retired ref R unconditionally: open() ignores tombstoneNow's boolean (src/main/github-account-store.ts:87) and finishStartup() writes retiredRefs = orphans, which only covers the live-ref path (:108, :111). But the claim's consequence ("the on-disk index keeps it committed, so later starts never delete it") cannot arise with the real vault: vault.tombstone marks the in-memory entry 
- refute: holds False, reachable no, severity none. The mechanism the claim names is real in isolation (open() ignores tombstoneNow's boolean at github-account-store.ts:87; finishStartup writes orphans only at :108-111), but no flow at HEAD reaches it. The tombstone persist fails only when Vault.persist (vault.ts:71-79) fails, and the reconcile that spec 4.4 / index.ts:183 runs next ends with the same `await this.persist()` (vault.ts:119) and throws on a non-ENOENT un

### C-F: setLogin is dropped after a refresh whose commit failed - **not real** (1/3 lenses hold and reachable)
- reproduce: holds True, reachable yes, severity none. Literal behaviour reproduced at HEAD d3aaf21: after a refresh whose 1st commit fails, replace throws ReplaceFailure(true), the file names the new pair, live is still the old account, and setLogin(a.signInId) returns at src/main/github-account-store.ts:167 (account.accessRef !== live.accessRef) writing nothing; the login lands neither in the file nor in live. This is already pinned as intended at tests/github-account-
- reachability: holds True, reachable no, severity none. Store reading (holds): src/main/github-account-store.ts:145 throws ReplaceFailure(true) before :152 updates live, so disk names the new pair and live the old; setLogin :167 then returns on `account.accessRef !== live.accessRef` without writing. That is what the claim says, independent of any caller. Barrier (reachability): at HEAD src/main/github-signin.ts does not exist and src/main/index.ts:181-184 never constructs
- refute: holds False, reachable no, severity none. The store-level mechanics the claim describes are accurate: after ReplaceFailure(true) (github-account-store.ts:145) live still names the old pair and the file the new one, so setLogin returns at :167 on `account.accessRef !== live.accessRef` — and HEAD already pins exactly that as intended at tests/github-account-store.test.ts:862-872, whose comment says "The service clears the account next (X-9) (U2-R10)". The spec

## Lead mistake L-5 (a false "verified" claim, and a red suite committed over)
- **mistake**: commit 490b7ed's report says "node --test route.test.mjs 80 pass, 0 fail with the edited policy (verified)". The
  suite was red at that commit: 78 pass, 2 fail ('host-policy-2: the pin-tests category ...' expected 514000 for cc-opus-high;
  'README: the host-policy-2 qualification table ...' expected '771k'). The lead's shell printed no suite summary (the grep
  pattern did not match the reporter's output) and the lead wrote "verified" without seeing a result.
- **where**: the lead's policy-maintenance turn, 2026-10-18 01:36 UTC; commit 490b7ed and the two commits on top of it.
- **impact**: build/github-sign-in carried a red adapter suite for about 30 minutes (490b7ed..f2036bd); the policy-3 builder
  found it at the start of its unit and fixed it first (ca102ea: the README row and the test's headroom basis widened to
  accepted outcomes). Nothing delivered elsewhere is affected; the policy value itself was right.
- **cause**: a verification claim written from the expectation of the command, not its observed output; standing rule 5
  (a red suite stops work) was not applied because the red was not seen.
- **fix**: ca102ea cherry-picked onto build/github-sign-in ahead of the rest of the unit; from now on the lead captures the
  suite's output to a file and quotes its summary line.
- **verified**: before the cherry-pick `node --test` exit 1 (78 pass, 2 fail); after it exit 0 (80 pass, 0 fail) - both runs
  captured to files and their summary lines read (this entry's commit report quotes them).
