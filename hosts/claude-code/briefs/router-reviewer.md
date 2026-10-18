# Reviewer brief: the SmartRouter host adapter (refute first)

Review `docs/orchestration/smartrouter/route.mjs`, its tests and README in `/home/user/task5-handoff/wt/sr-host` from base
`3f33151`. Assume the adapter is wrong until you have tried to break it. Change nothing in the worktree; scratch copies only
under your scratchpad; never commit or push.

Read first: the builder brief `docs/orchestration/smartrouter/briefs/router-builder.md`, then SmartRouter's normative files
at `/home/user/stepenkoanatoli/smartrouter` (at `fbe7bca`): `skills/smart-router/SKILL.md`, `references/gates.md`,
`references/spec-v2.md` §5-§12 and §14, and the fixture runner `tests/smart_router_decisions.py` lines 36-215. Compliance
is judged against those, not against the builder's reading of them.

Check, with evidence (commands run, outputs seen):
1. Every test is red-first: re-run the builder's red proofs yourself in a scratch copy (stub out or revert the piece the test guards) and the green on HEAD.
2. Gate order and semantics vs gates.md and the fixture runner: Gate 1 before any other work (S17a/S17b: a forbidden data class must not reach Gate 2 reasons), no resurrection of a rejected candidate, no cheaper-tier fallback to avoid `blocked`, equality rules (calls `used + reserved <= limit`, deadline strictly before), repairs at most one same-profile corrective per task, cash never blocks in this host but is always reported as uncertainty.
3. Hard prohibitions (spec §12) and host duties (§11): the adapter never claims a dispatch, never resets counters on rename or profile change, writes the dispatch record before any send, validates every §10 object it emits (Brief, Outcome, LedgerRecord) and refuses what it cannot produce.
4. Determinism: same request + same ledger → byte-identical decision file apart from timestamps supplied by the request.
5. Try to break it: a request with an unknown profile in `candidates`; a candidate list of one unqualified profile; `estimatedTokens` above every headroom; `deadline` equal to `now`; an Outcome for a task with no dispatch; two decisions for the same task (seq must continue, not restart); a Brief whose `allowance.calls` exceeds the remaining slots; a ledger line hand-corrupted (the adapter must refuse to append to an unparseable ledger rather than skip lines).
6. The golden decisions `trace/decisions/hand-*.json` reproduce exactly.
7. The README's friction log: is every claim about the spec cited to a file and section, and is anything claimed as spec behaviour that the spec does not say?

Severity: S1 a wrong route that could dispatch where SmartRouter would block, or a counter that can be reset; S2 a gate semantics divergence from gates.md or the fixture runner; S3 a missing proof or an unenforced duty the README claims; S4 wording. Report only real problems, each with the reproduction. Return the verdict schema you are given; `ACCEPT` only when 1-7 are all checked and listed under `checked`.
