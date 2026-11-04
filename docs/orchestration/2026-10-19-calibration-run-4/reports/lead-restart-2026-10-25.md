# Lead restart report, run 4, sr-pack-4a (2026-10-25 to 2026-11-01)

Result: sr-pack-4a ACCEPTED (check 5, 2f73c9f, draft PR #122, stacked on #120). The kit change it depends on, lead
integrations 2-8 on build/sr-kit-cases (#120, head 3ed05d4), is ACCEPTED by check 8. Nothing merged; merges are yours.

After those verdicts a review loop (eleven rounds of fresh reviewers) found more, so the heads to review moved; see RUN.md,
entry "review loop after the ACCEPTs" and the entries after it. The ids below are the ones each round committed; later
rebases of the pack branch replaced the pack's, so the ids on the branches now are in the table under "heads now".
- round 1: RL1-1 (S3, pack) a wrong fix that keeps the staged pair when the account file was read and refused graded
  PASS, fixed in 045ee89, f16f10f after the rebase (refused-file row, W-o2); RL1-2 (S4) item 1 below misdescribed
  D-IC3-1, fixed in b93c808.
- round 2: RL2-K1 (S3, kit) a candidate's own `.git` config, attributes or excludes could hide an edited invariant file
  from the gate grade, and RL2-K2 (S4, kit) the gate grade crashed on a large invariant directory, both fixed in
  dead160; RL2-P1 (S3, pack) a keep through one unreadable start only graded PASS, and RL2-P2 (S4) a miscount in the
  pack README, both fixed in f25b52c (20 rows, W-p, W-q); RL2-D1 (S4) this report and RUN.md stopped before the loop;
  RL2-1 (S3, pack) the refused-file row refused only the signed-out file, so a keep while a refused file still names an
  account (or names another format version) graded PASS, fixed in 556b166 (named refused-file row, version-2 forms, 21
  rows, W-o3, W-o4).
- round 3: RL3-K1 (S3, kit) the grade still ran the candidate's own git, so a `core.fsmonitor` hook in its `.git/config`
  ran inside the grade and could poison the view, fixed in d73511f (a history repo of the grade's own; no git runs on
  the candidate's `.git`); RL3-1 (S3, pack) no row refused a file beside a committed account, and RL3-2 (S4, pack) the
  ENOENT row had only an empty vault, so keeps beside a committed entry graded PASS, both fixed in 00df498 (crash points
  beside a committed account in both rows, still 21 rows, W-o5, W-h3, accepted0 a106f3bc). The pack branch was rebased
  onto d73511f (556b166 is now 12ebdb8; id map in RUN.md).
- round 4: RL4-K1 (S3, kit) the grade read the commits against the candidate's own root, so an amended or orphan root
  that held a new file hid it from the scope and source checks, fixed in 7ac8143 (commits read against the base tree,
  `baseRoot`, no commit-graph read). No pack finding: the pack branch was rebased onto 7ac8143 (00df498 is now
  0ec45ca; id map in RUN.md).
- round 5: RL5-K1 (S4, kit) an ignored file committed under a gate invariant and then unstaged was missed, because the
  grade never read HEAD for invariants, fixed in 2937b2c (every file HEAD adds under the path against the base tree
  counts); RL5-P1 (S4, pack) a wrong fix that keeps only on a list of errno codes holding EACCES, EBUSY and EIO graded
  PASS, fixed in 7595509 (the other-errno row with EPERM, EMFILE, EINVAL and UNKNOWN, 22 rows, W-l2, accepted0
  a53755b9). The pack branch was rebased onto 2937b2c first (0ec45ca is now 9ee7222; id map in RUN.md).
- round 6: RL6-P1 (S3, pack) the unreadable start failed only eight fs/promises and sync reads, so a wrong fix that
  re-reads the file by a stream (W-r) graded PASS, fixed in a6d12b8 (every node:fs read of the account file fails, by
  string, Buffer or file: URL; each session and start loads the subject's modules afresh; W-r, W-r2, W-r3; accepted0
  d8af1fd4). No kit finding and no rebase.
- round 7: RL7-P1 (S3, pack) every start ran in the one test process, so a wrong fix that keeps the refs on `globalThis`
  (W-r4) graded PASS, and RL7-P2 (S3, pack) the fault matched the path string, so a second read through a hard link
  (W-r5) graded PASS, both fixed in cfe982c (each later start runs in a new process of its own with an empty
  environment; the fault knows the file by its identity and fails the module loader too; accepted0 1c516672). No kit
  finding and no rebase.
- round 8: RL8-K1 (S3, kit) an object the candidate filed under the base tree's id hid a committed file from the grade,
  and RL8-K2 (S3, kit) nothing read `checkout.links`, so a fix that wrote through the linked `node_modules` graded
  PASS, both fixed in ad9e4b0 (the history git has no alternates and `git index-pack` files each object under its
  content's id; the history index holds the candidate's entries written again; `grade.sh --seal`/`--links` and
  `linksIntact`). RL8-P1 (S3, pack) a path as a `Uint8Array` or a URL-shaped object escaped the fault, RL8-P2 (S3) an
  age by `performance`'s clock passed, RL8-P3 (S3) a keep decided by the failing syscall passed, all fixed in
  1feb090 after a rebase onto ad9e4b0 (the fault reads every path form through the real `stat`, fails at the stat, the
  open or the read with a real error's shape; a start moves every clock it reads and the data directory's file times
  move back; W-t, W-t2, W-u, W-u2, W-u3, W-u4, W-l3, W-l4; accepted0 970e5e47). RL8-D1 and RL8-D2 (S4, docs): the PR
  bodies were refreshed and this report given the table below.
- round 9: RL9-K1 (S3, kit) a path the base lacks (a nested `tests/node_modules`, a cached `.pyc`, a top-level
  `unittest.py`, a file one command writes for the next) shadowed the sealed install or the runner, fixed in 817c6be
  (before each command the grade sets aside every path the base tree lacks but the candidate's counted files and the
  linked names; `setAside`, `notSetAside`, `restored`). RL9-P1..P3 (S3, pack) W-p2 (same failure twice in a row), W-b4
  (engine refs), W-b3 and W-j2 passed; RL9-P4 and RL9-P5 (S4) two clocks a start did not move (W-u5, W-u6; W-v
  disclosed) and the stat cause wording (W-s); all fixed in 822f701 after a rebase onto 817c6be (four new rows, 26:
  the lasting row with a `dir` phase, the engine row, the tombstone row at the open and the read, the orphan-codes row;
  the store's default clock and the date constructor moved; README section "What the pack is and is not expected to
  catch"; forty-four wrong fixes; accepted0 fe4fdc2f). RL9-D1 (S4, docs): #122 named check 5 by an id on an older head;
  now 5fab5c3 on 822f701.
- round 10: RL10-K1 (S3, kit) the accepted pin of a fix cell ran after the candidate's tests, so a test that rewrote a
  base-tracked runner or left a detached process forged it; RL10-K2 (S4, kit) a counter in the temp directory forged
  `guardRed`; RL10-K3 (S3, kit) the set-aside moved entries below a junction into the checkout's `.git` and the cell
  still passed; all fixed in 042ac43 (the pin runs first; nothing below a link is moved; PASS needs `restored`; the
  README names what the candidate's own tests can still forge). RL10-P1, RL10-P2 (S3, pack) W-j3 and W-b5 (a hold or
  a sparing keyed on whether a committed entry exists) passed; RL10-P3 (S3) W-x (`existsSync`, outside the fault)
  passed; RL10-P4 (S4) W-u7 (`process.report`'s clock) passes, disclosed; all fixed in 2694883 after a rebase onto
  042ac43 (the two vault-state rows, 28: every combination of the states the rows build beside an unreadable file; the
  fault fails every path-taking `node:fs` function by default; "every clock it reads" narrowed to the clocks named;
  forty-seven wrong fixes; accepted0 a6f7896a). RL10-D1, RL10-D2 (S4, docs): two wrong facts in the round-9 RUN.md
  entry, and stale PR body files in the notes folder; corrected.
- round 11: RL11-K1 (S3, kit) the accepted pin ran first, but the candidate's in-scope new tests stayed on disk, and
  vitest takes a file argument as a filter, so the pin's own command ran a candidate test that rewrote the accepted
  test; fixed in b12d6a8 (the pin runs on the base, the candidate's sources and the accepted test only; the README says
  what the sources can still do inside it). RL11-P1 (S3, pack) W-b6 (W-b on EIO alone), RL11-P2 (S3) W-l5 (a re-read
  through a FileHandle's `fd`, which the fault did not know) and RL11-P3 (S3) W-b7 (the keep dropped beside a
  tombstone) passed; RL11-P4 (S4) `process.loadEnvFile` reads the faulted file, disclosed; all fixed in 2876cc6 after a
  rebase onto b12d6a8 (every code at every point on a fresh tombstone; descriptors known by the file's identity; two
  keep-side vault-state rows, 30; the README says plainly that review keeps finding wrong fixes and the pack is a
  sample, not a proof; fifty wrong fixes; accepted0 fe7bf927). Docs and PR bodies: nothing new.
- heads now: kit b12d6a8 (pushed, #120), pack 2876cc6 (committed, not pushed: see Next), docs the RUN.md commit
  after 287489a (pushed, #119). Outcome seq 3 ("accepted", check 5's head) is append-only and stays.
- ids on the branches (round-by-round id -> id on the branch now, matched by subject):

  | what | as committed | on the branch now |
  |---|---|---|
  | kit, rounds 2-5 and 8-11 | dead160, d73511f, 7ac8143, 2937b2c, ad9e4b0, 817c6be, 042ac43, b12d6a8 | the same (the kit branch is never rebased) |
  | pack RL1-1 | 045ee89, f16f10f | 7fde450 |
  | pack RL2-P1 | f25b52c | a4eb9ea |
  | pack RL2-1 | 556b166, 12ebdb8 | 3f35c7b |
  | pack RL3-1, RL3-2 | 00df498, 0ec45ca | 40f1dbd |
  | pack RL5-P1 | 7595509 | acf68f9 |
  | pack RL6-P1 | a6d12b8 | 8643b42 |
  | pack RL7-P1, RL7-P2 | cfe982c | d319100 |
  | pack RL8-P1..P3 | 1feb090 | 87610f6 |
  | pack RL9-P1..P5 | 822f701 | c1ed7ef |
  | pack RL10-P1..P4 | 2694883 | d4cf773 |
  | pack RL11-P1..P4 | 2876cc6 | 2876cc6 |
  | check 5 report (ACCEPT) | 2f73c9f | 5c2a386 |

## What you should hear
1. D-IC3-1 (lead decision, departs from the brief's literal wording): check 3 found (IC3-1, S2) that base0 itself held
   the answer key. MoonAliza 16f637f's `docs/orchestration/` records name X2-1, state its cause and give the accepted
   fix (`briefs/fix-x2-1.md` among them), and the kit option `cause_in_prompt: false` (the owner's earlier F2 decision,
   K5 on #120) keeps the cause only out of the prompt text, so it did not stop the leak. The decision: `make-repo.sh`
   exports both trees (base0 and accepted0) without MoonAliza's `docs/orchestration/`, and the pack repository holds
   none of its objects. This departs from the brief's "export the base tree 16f637f": the brief's intent ("the
   candidate never sees it") was put above its wording (integration 4, ffa8b45). A test checks that no file or path
   name of base0 holds the finding's id, the fix's names or a phrase of the cause; a paraphrase elsewhere still passes
   that textual check (LIMIT-1, disclosed since round 3).
2. Kit guard changes on #120 (all in `historyless-checkout.sh --link`, each found by a refute-first check, tooling fixed
   at the root rather than the README worked around):
   - integrations 2-6: `--link` refuses a directory inside any git repository, native path resolution, fail closed.
   - integration 7 (3f23728): LC6-1 closed as a class by file identity (`-ef`, samestat), fail closed.
   - integration 8 (f06353f): LC7-1 (S3) resolve spells every path part exactly (hard-link bypass closed); LC7-2 (S4)
     NAME whitelist plus `git check-ignore` proof per link.
   - Open S4s on the kit, not blocking: LC8-1 (`MSYS=winsymlinks:lnk` stages `NAME.lnk`; verified fix: require
     `git ls-files --others --exclude-standard --directory` to print nothing), LC8-2 (wrong line in the integration 8
     report), LC8-3 (test gap, mutant Y6). Kit README step 3 recommends a history-less checkout `--link` refuses (KR5-1).
3. OBS-1 stays out of scope, untouched. New observation OBS-8a: the grade.sh gate-timeout test
   (`test_k3_a_gate_that_overruns_its_timeout_leaves_no_child_writing`) failed once under heavy load; passes alone and in
   the gate. Suspected cause untested (taskkill tree snapshot). Worth its own unit. OBS-8b: a checkout path ending in a
   newline with `--link` is refused (fails closed).

## Run facts
- Workflow wf_ba5994fb-daf, 4 agents, 688,179 subagent tokens, about 11.4 h. Weekly usage 0.00 at start.
- Kit 8: tests red at d4c2c8f (3/3), green now; suite 140 OK; prompts 0/60 differ vs 09b476d; mutants old 70/70, new 7/7.
- Pack 5: kit suite 158 OK (11 skipped), HostPackX21 with the clone 18 OK, clone unchanged, evidence 0 failures.
- Outcome: sr-pack-4a seq 3 accepted; route tests 142 pass.
- Pack S4s: IC5-1, IC5-3 (see integration-check-5 report), IC5-2 = KR5-1.
- Review loop, pack at f25b52c: the journey test has 20 rows; HostPackX21 with the clone 17 of 18 OK in 5354 s, every
  wrong fix FAIL with its stated count of 20; the one failure was the base-red test expecting only the 12 journey rows
  red at base0 (the unreadable-run row is red there too), fixed in the same commit and passing alone with the clone;
  accepted0 577f52b4.
- Review loop, pack at 556b166 (RL2-1): the journey test has 21 rows; HostPackX21 with the clone all 18 OK in 7566 s,
  every wrong fix FAIL with its stated count of 21 (W-o3 1, W-o4 2); its tearDownClass F5 check saw the clone's `.git`
  mtime change at 15:32:49Z, attributed to a read outside the class (no file in `.git` changed), and the six tests that run the
  clone pass with F5 on a rerun; the clone is unchanged (status empty, HEAD 1ac226d); kit suite 163 OK (11 skipped) in
  the gate; accepted0 1f7aa3bf.
- Review loop round 3, pack at 00df498 (RL3-1, RL3-2): still 21 rows; HostPackX21 with the clone 18 of 18 OK in 4947 s,
  every wrong fix FAIL with its stated count of 21 (W-o5 1, W-h3 1); the clone is unchanged (status empty, HEAD
  1ac226d); make-repo builds base0 4eaf584a and accepted0 a106f3bc; gate PASS on d73511f and on 00df498.
- Review loop round 4, pack rebased to 0ec45ca (no pack change): HostPackX21 with the clone 18 of 18 OK in 4012 s; the
  clone is unchanged (status empty, HEAD 1ac226d); gate PASS on 7ac8143 and on a gate run of 0ec45ca.
- Review loop round 5, pack at 7595509 (RL5-P1): 22 rows; HostPackX21 with the clone 17 of 18 OK in 4346 s, every wrong
  fix FAIL with its stated count of 22 (W-l2 1), the red-at-base test then fixed to expect the new row red at the base
  and 1 of 1 OK with the clone; the clone is unchanged (status empty, HEAD 1ac226d); make-repo builds base0 4eaf584a
  and accepted0 a53755b9; gate PASS on 2937b2c and on 7595509.
- Review loop round 6, pack at a6d12b8 (RL6-P1): still 22 rows; HostPackX21 with the clone 18 of 18 OK in 4895 s, every
  wrong fix FAIL with its stated count of 22 (W-r, W-r2 and W-r3 14); nine more second-read routes from the class hunt
  each fail 14 of 22; the clone is unchanged (status empty, HEAD 1ac226d); make-repo builds base0 4eaf584a and
  accepted0 d8af1fd4; gate PASS on a6d12b8.
- Review loop round 7, pack at cfe982c (RL7-P1, RL7-P2): still 22 rows; HostPackX21 with the clone 18 of 18 OK in
  6511 s, every wrong fix FAIL with its stated count of 22 (W-r4 14, W-r5 15); fourteen more routes from the class hunt
  (eleven of them pass the a6d12b8 test) each fail 14 or 15 of 22; the clone is unchanged (status empty, HEAD 1ac226d);
  make-repo builds base0 4eaf584a and accepted0 1c516672; gate PASS on cfe982c.
- Review loop round 8: kit at ad9e4b0, full kit suite with no early stop 155 passed, 1 skipped, exit 0; gate PASS on
  ad9e4b0. Pack at 1feb090: still 22 rows; HostPackX21 with the read-only clone 18 passed and 53 subtests, exit 0
  (every wrong fix FAIL with its WRONG-FIXES.md count, accepted and both alternatives PASS, linksIntact true; W-p's
  row corrected to 14 of 22, as the three unreadable starts of each journey row now catch it); every new wrong fix
  fails 14 of 22 on a scratch tree, and the
  cfe982c test passes all but W-u4 22 of 22 (red first); the clone is unchanged; make-repo builds base0 4eaf584a and
  accepted0 970e5e47; gate PASS on 1feb090.
- Review loop round 9: kit at 817c6be, red first on ad9e4b0 (every shadow cell PASS true), ten guard-removal mutants
  each red, full kit suite with no early stop 157 passed, 1 skipped, exit 0; gate PASS on 817c6be. Pack at 822f701
  (rebased onto 817c6be; `git diff 1feb090 31e8738` equals the kit's diff): 26 rows; accepted 26 of 26, base 16 red;
  each of the seven new wrong fixes passes the 1feb090 test 22 of 22 and fails its new row (red first); HostPackX21
  with the read-only clone 17 of 18 OK in 10957 s, every wrong fix FAIL with its stated count of 26; the red-at-base test then fixed to expect the lasting and engine rows red at the base (16) and 1 of 1 OK with the clone; the clone is unchanged; make-repo builds base0 4eaf584a and accepted0
  fe4fdc2f; gate PASS on 822f701.
- Review loop round 10: kit at 042ac43, the four new tests red on 817c6be, guard-removal mutants each red (one
  redundant check's mutant green, stated), full kit suite 161 passed, 1 skipped, exit 0; gate PASS on 042ac43. Pack
  at 2694883 (rebased onto 042ac43; the changed lines of `git diff 822f701 e582d5a` equal the kit's): 28 rows; accepted
  28 of 28, base the same 16 red; W-j3, W-b5, W-x and W-u7 pass the 822f701 test 26 of 26 (red first) and W-j3, W-b5
  and W-x fail the new one (1, 1, 16 of 28; W-u7 green, disclosed); HostPackX21 with the read-only clone 18 passed; the
  clone is unchanged; make-repo builds base0 4eaf584a and accepted0 a6f7896a; gate PASS on 2694883.
- Review loop round 11: kit at b12d6a8, the reviewer's probe5 PASS on 042ac43 and PASS false after, the new test red on
  042ac43, seven guard-removal mutants each red, full kit suite 162 passed, 1 skipped, exit 0; gate PASS on b12d6a8. Pack
  at 2876cc6 (rebased onto b12d6a8; the changed lines of `git diff 2694883 d4cf773` equal the kit's): 30 rows; accepted 30
  of 30, base 18 red; W-b6, W-l5 and W-b7 pass the 2694883 test 28 of 28 (red first) and fail the new one (1, 18, 2 of
  30; W-u7 green, disclosed); HostPackX21 with the read-only clone 18 passed; the clone is unchanged; make-repo builds
  base0 4eaf584a and accepted0 fe7bf927; gate PASS on 2876cc6.

## Next (yours)
Kit b12d6a8 (#120) and this branch (#119) are pushed. The pack branch was rebased onto b12d6a8, so it needs a
force-push with lease, which is yours: `git push --force-with-lease=build/sr-pack-4a:1feb090ac40b46474999995ddc921fc16cdc4126 origin build/sr-pack-4a`
(from the pack worktree, which holds 2876cc6; it refuses if origin's pack is no longer 1feb090, which it still was
when round 11 ended; 822f701 and 2694883 were never pushed). Then review and
merge #120, then #122, then #119. Plan step 5 (sr-policy-7, sr-packs-t1) waits for you; follow-ups FU-1..FU-5
on #120 are still open.
