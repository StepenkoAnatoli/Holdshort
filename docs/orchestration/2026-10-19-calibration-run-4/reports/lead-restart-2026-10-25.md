# Lead restart report, run 4, sr-pack-4a (2026-10-25 to 2026-11-01)

Result: sr-pack-4a ACCEPTED (check 5, 2f73c9f, draft PR #122, stacked on #120). The kit change it depends on, lead
integrations 2-8 on build/sr-kit-cases (#120, head 3ed05d4), is ACCEPTED by check 8. Nothing merged; merges are yours.

After those verdicts a review loop (six rounds of fresh reviewers) found more, so the heads to review moved; see RUN.md,
entry "review loop after the ACCEPTs":
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
- heads now: kit 2937b2c, pack a6d12b8, docs the RUN.md commit after 8fcf32c. Outcome seq 3 ("accepted", check 5's
  head) is append-only and stays.

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

## Next (yours)
Once the loop's heads are pushed (kit 2937b2c to #120, pack a6d12b8 to #122, this branch to #119), review and merge
#120, then #122, then #119. Plan step 5 (sr-policy-7, sr-packs-t1) waits for you; follow-ups FU-1..FU-5
on #120 are still open.
