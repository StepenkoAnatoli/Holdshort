# Lead restart report, run 4, sr-pack-4a (2026-10-25 to 2026-11-01)

Result: sr-pack-4a ACCEPTED (check 5, 2f73c9f, draft PR #122, stacked on #120). The kit change it depends on, lead
integrations 2-8 on build/sr-kit-cases (#120, head 3ed05d4), is ACCEPTED by check 8. Nothing merged; merges are yours.

## What you should hear
1. D-IC3-1: round 3 found (IC3-1) that the pack's answer key was reachable; the fix kept the cause out of the fix prompt and
   base0 (kit option `cause_in_prompt: false`, K5, on #120). A paraphrase of the cause in the summary or instructions
   still passes the textual check (LIMIT-1, disclosed since round 3).
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

## Next (yours)
Review and merge #120, then #122, then #119. Plan step 5 (sr-policy-7, sr-packs-t1) waits for you; follow-ups FU-1..FU-5
on #120 are still open.
