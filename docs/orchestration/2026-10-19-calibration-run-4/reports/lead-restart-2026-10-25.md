# Lead restart report, run 4, sr-pack-4a (2026-10-25 to 2026-11-01)

Result: sr-pack-4a ACCEPTED (check 5, 2f73c9f, draft PR #122, stacked on #120). The kit change it depends on, lead
integrations 2-8 on build/sr-kit-cases (#120, head 3ed05d4), is ACCEPTED by check 8. Nothing merged; merges are yours.

After those verdicts a review loop (two rounds of fresh reviewers) found more, so the heads to review moved; see RUN.md,
entry "review loop after the ACCEPTs":
- round 1: RL1-1 (S3, pack) a wrong fix that keeps the staged pair when the account file was read and refused graded
  PASS, fixed in 045ee89, f16f10f after the rebase (refused-file row, W-o2); RL1-2 (S4) item 1 below misdescribed
  D-IC3-1, fixed in b93c808.
- round 2: RL2-K1 (S3, kit) a candidate's own `.git` config, attributes or excludes could hide an edited invariant file
  from the gate grade, and RL2-K2 (S4, kit) the gate grade crashed on a large invariant directory, both fixed in
  dead160; RL2-P1 (S3, pack) a keep through one unreadable start only graded PASS, and RL2-P2 (S4) a miscount in the
  pack README, both fixed in f25b52c (20 rows, W-p, W-q); RL2-D1 (S4) this report and RUN.md stopped before the loop.
- heads now: kit dead160, pack f25b52c, docs the RUN.md commit after b93c808. Outcome seq 3 ("accepted", check 5's
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

## Next (yours)
Once the loop's heads are pushed (kit dead160 to #120, pack f25b52c to #122, this branch to #119), review and merge
#120, then #122, then #119. Plan step 5 (sr-policy-7, sr-packs-t1) waits for you; follow-ups FU-1..FU-5
on #120 are still open.
