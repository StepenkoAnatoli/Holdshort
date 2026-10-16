# Pilot readiness review — 16 October 2026

The known local accounting, recovery, reporting, and evaluation defects have
targeted fixes and regression controls. **Live provider operation is still
unqualified.** The checked-in billing record deliberately refuses real dispatch
before key lookup or network access. No paid provider requests were made during
this review; no final bill, model ranking, or savings claim is inferred.

This review continues the [15 October audit](GAP_AUDIT_FOLLOWUPS_2026-10-15.md)
without rewriting its historical conclusions. The integration base is
`b764c67092023255b2214513c810f512b5669545`, which includes PRs #74, #84, #85,
and #87. The inert task-state owner is retained. The Appendix-B reshape in #86
is a separate migration assigned to another contributor.

## Findings and resulting behavior

| Finding | Correction | Evidence and practical limit |
| --- | --- | --- |
| G2: no established billing bound | The default real adapter requires a fresh local qualification record matching endpoint, model, request mode, exact price bytes, enforceable token ceilings, and captured evidence. Revalidate before counting and sending; pin supported request scope and reject unsupported response usage. | `test_billing_qualification.py`, `test_dispatch_adapter.py`, and a real CLI refusal. This closes unsafe admission; hashes do not authenticate provider claims, and the final provider bill is not guaranteed. |
| G10: five tasks could not supply 20 observations per arm | Add ten distinct executable fixtures with failing baselines and passing reference fixes, plus a pinned 80-trial schedule. Each execution gets a unique budget task ID. | `test_eval_pool.py` and standalone `eval_pool.py self-check`. There are 20 total observations per arm, including ten holdout observations; live model qualification and comparative performance remain pending. |
| #75: a committed send could look refused after mirror failure | Separate authority commit from derived JSONL synchronization. Return the committed physical outcome, usage, cost, reservation identity, and pending mirror status. | Real SQLite and injected post-commit mirror failures in the budget suite. Hosts must recover the reservation rather than treating mirror lag as permission to resend. |
| #76: observed usage could disappear when settlement failed | Flush safe reservation-bound recovery receipts before settlement; replay them idempotently before new admission. Kernel leases distinguish live concurrent transports from orphaned reservations. | Process crashes, simultaneous owners, authority lock failure, receipt-write failure, and recovery racing original settlement. No multi-machine or network-filesystem guarantee is established. |
| #77: failed verification could consume its only owed slot | Preserve physical attempt charges and restore the owed verification slot when the attempt cap permits it. Refusals retain verification purpose. | Known/unknown failure, reconciliation, and exhausted-cap controls. No attempt or repair allowance is renewed. |
| #78: failed work could retain review allowance forever | Add explicit terminal abandonment that releases unused review allowance while preserving spend and attempts. A no-send task uses the `<not-dispatched>` event profile. | Abandonment of expired, untouched, and preflight-blocked tasks; later attempts refuse. Unsettled work cannot release its reservation, and abandonment never means acceptance. |
| #79: later refusals could hide stronger accounting outcomes | Preserve unknown usage, verification, abandonment and awaiting-verification states; record the last refusal separately. Disclose incomplete per-task spend and unknown caps; detect reservation overruns. | Report/close controls include unknown verification followed by known work and false completion attempts. A known subtotal is not a complete charge. |
| #80: sheet counts and latency could misrepresent observations | Exclude verification and terminal bookkeeping; bind exact trial assignments and order; preserve execution timing through reconciliation; separate transport duration from inter-observation spacing. | Idempotent partial/full imports, complete synthetic 80-trial control, changed evidence, duplicated work, malformed metadata and exact numeric-type controls. Fingerprints prove consistency, not authenticity. |
| #81: close/crosscheck could miss the authority | Read a validated SQLite snapshot without recovery or writes. Report mirror lag, divergence, corruption, retained reservations, and counter disagreement. Keep raw JSONL separate for sheet evidence. | Report, close and crosscheck tests preserve original bytes and cover absent optional mirrors. Legacy ledgers disclose their weaker evidence source. |
| #82: working-directory changes could break pilot identity | Resolve CLI relative paths from the repository root and preserve an established optional task-store binding when omitted. | Actual CLI calls from different directories. Explicitly changed bindings, caps, or pilot paths still refuse; this is not a portable pilot-identity migration. |
| #83: repeated warmups reused expired state | Use a fresh temporary ledger directory for every warmup. | Three separate CLI warmups produce the expected synthetic `$0.0015` result. Reusing a ledger intentionally resumes its counters and deadline. |

## Bugs caught while reviewing the fixes

The final review found and corrected problems in the new work as well as the
original findings:

- Frozen numeric metadata accepted `true` or `1.0` where an exact integer was
  required because Python equality coerces these values. Assignment maps,
  recorded trial metadata, slots, and sheet repeat counts now enforce types.
- Malformed fixture metadata could crash tallying; a malformed observations
  collection could mutate a sheet before failing. Both produce findings while
  preserving source records.
- An unknown verification charge followed by known work could produce false
  completion. Completion now also requires complete spend evidence.
- Legacy crosscheck could suppress malformed numeric accounting. Invalid state
  and ledger accounting remain explicit findings.
- Zero-attempt abandonment emitted an empty profile. It now emits the documented
  non-dispatch sentinel, with zero attempts and valid accounting.
- An invalid dispatch purpose could enter the journal through its own refusal.
  It is now refused before task creation or durable writes; malformed string,
  list, object, and null values have negative controls.
- `dispatch-unsettled` had ambiguous journal semantics. It is now explicitly
  return-only, rejected by canonical journal validation, and documented as
  reservation-bound recovery evidence. The dispatcher owns canonical appends.
- A synthetic adapter-check placeholder triggered the existing secret guard.
  The placeholder was corrected; the guard and assertions were preserved.

The [host compatibility amendment](DISPATCH_ACCOUNTING.md#host-compatibility-amendment--2026-10-16)
and ADR-0001 record the intentional additive terminal events and optional
metadata. Matching tools and host instructions must be deployed together.
Unknown canonical events stop old readers; they must not become completion,
zero spend, or an automatic retry. These corrections introduce no human approval
checkpoint.

## Verification and exact pilot inputs

The pre-integration 49-entry regression gate passed. The integration adds the
task-state-owner check from merged main, making **50 gate entries**; one legacy
redaction suite is registered twice, so this is not a claim of 50 distinct
suites. The staged-tree pre-commit gate and hosted PR check must both pass before
merge. The PR records the final exact-head result.

Focused controls include 32 budget tests, 33 adapter tests, nine qualification
tests, 12 prospective-pool tests, 28 tally tests, and report/close/crosscheck
coverage. The full gate also checks policy fixtures, host lifecycle, schemas,
hooks, credential hygiene and documentation drift. Test counts describe their
respective runs; they are not measurements of provider performance.

Actual command entry points were exercised independently of unit-level helpers:
fresh dispatcher warmups, the default real-adapter refusal, authority-backed
reporting, and all ten fixture baseline/reference acceptance controls. The
evidence manifest at [pilot-readiness.json](evidence/2026-10-16/pilot-readiness.json)
records source fingerprints, command results, and the frozen evaluation identity.
Local logs containing machine-specific hygiene diagnostics remain untracked.

The prospective pool is `smartrouter-prospective-v1`:

- Manifest SHA-256: `c6efcd0a114c9a07c1a565f31a0ac5efa518fdd182c03b629168954aa55effd4`.
- Schedule SHA-256: `110b8344e0f6dc93eff08993172f27b5b3813ff0ff57915fdde6fa1f56568d45`.
- Ten fixtures; four arms; two repeats; 80 distinct execution IDs. Five fixtures
  are tuning and five holdout; each arm has ten observations in each split.
- Baseline/reference checks qualify local task contracts only. Candidate code
  runs in local Python processes; this verifier is not a security sandbox.

The reviewed price configuration is `tools/prices-2.json`; the qualification
record binds exact raw price-file bytes. Source-review fingerprints normalize
line endings to LF and disclose that convention. A source fingerprint does not
ratify prices, authenticate a receipt, or replace the qualification record.

## Post-fix gap audit

One sequential follow-up audit compared the corrected paths against six rotated
primary-source pairs. These are successive passes by one auditor, not six
independent reviews. Research-Kit was unavailable; official-source fetches were
used without a Research-Kit ledger. External comparisons are at most
**WELL-SUPPORTED**. Project defects and controls were established from code and
local execution, rather than differences in product feature lists.

| Pass | Comparison | Result |
| --- | --- | --- |
| 1 | LiteLLM / OpenRouter | Confirmed qualification scope and admission/accounting separation; no final-bill proof inferred. |
| 2 | Promptfoo / Inspect AI | Confirmed executable fixture contracts, unique trials, and explicit pending live qualification. |
| 3 | Pydantic / JSON Schema | Inspected strict numeric and malformed-input handling. The later equality-coercion reproduction led to the exact-type correction above. |
| 4 | Temporal / LangGraph | Traced receipts, leases, restart recovery and idempotent settlement with local process controls. |
| 5 | OpenTelemetry GenAI / Langfuse | Confirmed requested/resolved identity distinctions, unknown usage, timing, and unsupported bill modifiers. No new high-impact finding. |
| 6 | CPython / SQLite | Traced resource lifetime, authority commits versus derived mirrors, and read-only snapshots. No new high-impact finding. |

The last two comparison passes introduced no new high-impact findings. The
subsequent bounded integration review found the abandonment, invalid-purpose,
and return-only-contract issues listed above; each received a targeted correction.
The stopping rule is a review limit, not proof that undiscovered defects cannot
exist.

Primary comparisons: [LiteLLM budgets](https://docs.litellm.ai/docs/proxy/users),
[OpenRouter routing](https://openrouter.ai/docs/guides/routing/routers/auto-router),
[Promptfoo assertions](https://www.promptfoo.dev/docs/configuration/expected-outputs/),
[Inspect logs](https://inspect.aisi.org.uk/eval-logs.html),
[Pydantic strict validation](https://pydantic.dev/docs/validation/latest/concepts/strict_mode/),
[JSON Schema numbers](https://json-schema.org/understanding-json-schema/reference/numeric),
[Temporal execution](https://docs.temporal.io/workflow-execution),
[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence),
[OpenTelemetry GenAI](https://github.com/open-telemetry/semantic-conventions-genai),
[Langfuse usage/cost](https://langfuse.com/docs/observability/features/token-and-cost-tracking),
[CPython context managers](https://docs.python.org/3/library/contextlib.html),
and [SQLite transactions](https://www.sqlite.org/lang_transaction.html).
Provider-scope references are the official
[Messages contract](https://platform.claude.com/docs/en/api/messages/create),
[token-counting guide](https://platform.claude.com/docs/en/build-with-claude/token-counting),
and [pricing documentation](https://platform.claude.com/docs/en/about-claude/pricing).

## Architecture review and complementary pass

The supplied architecture review skill and complementary architecture-pass
skill were applied after the initial closure controls. The focused sample
covered ten runtime modules with matching tests, immediate persistence/pricing/
watchdog seams, co-change history, and ADR-0001. It did not re-audit the entire
repository. The visual HTML report was written to the OS temporary directory,
outside the repository.

No additional deepening candidate was strong enough to recommend. The accepted
task-state read consolidation already addresses the observed scattering.
`TaskStateOwner.read()` is inert outside tests and still uses the mutating
transaction path; Appendix B already directs #86 toward `read_authority()`.
That limitation was recorded without implementing a competing migration.

The complementary pass treated the uncommitted pilot-readiness diff as its
scope. Its design note is:

1. `BudgetStore` owns authority transactions, leases and receipt storage;
   `LiveDispatcher` owns admission and settlement policy.
2. Qualification validates local evidence; the adapter owns exact HTTP scope.
3. The pool owns frozen contracts; tally owns imported observations; reports
   consume validated accounting snapshots and preserve raw evidence separately.
4. Data flows into derived reports; reporting never sends or recovers requests.
5. Keep the read-owner migration in #86, against the landed runtime fixes.

No extra structural move was justified. Correctness changes remain labeled as
behavior changes. Removing the inert owner would discard the accepted migration;
merging qualification into HTTP or evaluation contracts into measurement import
would move complexity into unrelated callers. A general provider interface with
only one real adapter would be speculative.

## Remaining pilot prerequisites

- A trusted host must establish current, applicable provider/rate/request-scope
  evidence and enforceable ceilings before enabling real requests. The checked-in
  record does not satisfy this requirement. Final provider-bill accuracy remains
  unknown.
- Run the prospectively frozen trials with qualified models, isolated workspaces,
  authentic usage and acceptance evidence before claiming quality or savings.
  The engineering amendment is not retrospective ratification of old results.
- Complete the separately assigned Appendix-B reshape before treating the inert
  owner as the shared production read path. Review its integration against this
  branch rather than merging its previous implementation unchanged.
- Distributed coordination, descendant-process cleanup, real external-host file
  samples, receipt authenticity, and untrusted-code containment remain host
  responsibilities or unverified assumptions.

These limits do not authorize a fallback, counter reset, fabricated measurement,
or per-send approval workflow. An unmet prerequisite produces an automatic stop
with preserved evidence.
