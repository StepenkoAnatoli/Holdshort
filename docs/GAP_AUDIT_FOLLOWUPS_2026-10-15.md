# SmartRouter gap audit follow-ups — 15 October 2026

## 1. Current State Summary

SmartRouter routes bounded tasks through qualified profiles and records dispatch,
verification, cost, and evaluation evidence. Its outputs must preserve unknown
usage, enforce the declared local budget authority, refuse invalid evidence, and
keep measured observations tied to their sources.

This report records **three additional applications of the Gap Audit skill**:
6, 6, and 8 sequential comparison passes. The same lead auditor ran the
comparisons in order. Helper agents inspected bounded code areas, implemented
authorized corrections, and checked regressions; these were not independent
audits. Audit phases were read-only. Implementation and documentation were
separate steps authorized by the owner's request for a pull request after the
initial concrete findings.

The starting Git revision was
`591a549a3661334da9ee0d336be7224e03b300fd`, the merged durable-budget correction.
Inspection covered adapter transport, pricing and dispatch boundaries, budget
persistence, watchdog execution and restart state, Brief/NestedBrief/Outcome/
LedgerRecord conformance, report aggregation, sheet generation/import/tally,
session close, regression wiring, and the documents defining the evaluation
protocol. Tests used synthetic providers, offline fixtures, and local child
processes. **No paid provider trial, billing receipt qualification, or new
comparative model-performance experiment was run.** Coding-agent usage does
not establish a project-level provider bill.

The skill's Research-Kit readiness check did not finish READY. Official fetch
and search tools were used as its documented fallback. No Research-Kit runtime
or corpus is included in this change. Project code and reproduced local
behaviors are **VERIFIED**. External comparison claims are unledgered and graded
at most **WELL-SUPPORTED**. Cost estimates below are **INFERRED**.

## 2. Gap List

These material gaps remain after the implemented corrections. A known limitation
stays visible even when surrounding code passes tests.

| Rank | Gap | Affects | Impact | Project evidence | Confidence |
| --- | --- | --- | --- | --- | --- |
| 1 | G2: a strict live billable-cost upper bound remains unqualified | Accuracy, reliability | High for a claim that a provider bill cannot exceed a task or pilot cap | `tools/live_dispatcher.py` uses a provider token estimate with a 5% input margin and an output ceiling; `tools/dispatch_adapter.py` returns selected usage fields; `tools/pricing.py` models configured token rates. `docs/DISPATCH_ACCOUNTING.md` discloses that unexpected known overruns are recorded and stop dispatch. No evidence here establishes that this model bounds every supported billable component. | VERIFIED implementation and disclosed limitation; strict provider bound UNKNOWN |
| 2 | G10: the concrete evaluation pool cannot meet its sample minimum | Completeness, reliability | Material blocker for claiming that the ratified live evaluation is complete | `docs/PHASE3_PREREGISTRATION.md` §3 specifies at least 20 observations per arm, two repeats per task, five concrete tasks, and distinct tasks rather than duplicated fixtures. Five multiplied by two is 10. The new sheet has capacity for 20 per arm but does not supply or qualify additional tasks. | VERIFIED document facts and arithmetic |

### Corrected findings included in the pull request

The original audit identified eight reproduced code defects in addition to G2.
The first follow-up found nine further defects or refinements. Related findings
are grouped below so their resulting behavior can be reviewed together.

| Findings | Before | Corrected behavior and evidence |
| --- | --- | --- |
| G1, G8, F9: adapter transport | Default urllib redirects could forward a credential-bearing request; a caller timeout was ignored; HTTP failures could leave a response open and expose a remote reason. | A private opener refuses all five redirect statuses for count and send, including same-origin redirects. Finite positive timeouts reach both default transports. HTTP error responses close and fixed exceptions omit remote details. `tools/test_dispatch_adapter.py` exercises the real urllib handler path using synthetic responses. |
| G3, F1: report evidence and reservation transitions | Nonfinite money and fractional counts could enter aggregation. A repeated reservation ID could supersede another task's charge. Contradictory nonphysical usage or pending records could obscure incomplete accounting. | Shared validation checks types, finite ranges, event semantics, reservation identity, order, and known-charge floors before choosing effective entries. Invalid lines prevent intact/complete reporting; uncertain usage stays unknown. `tools/pilot_report.py`, `tools/test_pilot_report.py`. Final regression review also covers complete measured reconciliation receipts and direct pending-to-reconciled crash recovery supported by the dispatcher. |
| G4, F2–F4: observation validity | Filled/accounting flags could admit absent usage, inconsistent rates, duplicate evidence, wrong fixed-arm profiles, or incorrect repeat labels after interleaved imports. | Observations require measured integer usage, finite cost matching configured rates, consistent source metadata, unique source lines, the fixed profile where applicable, and consistent task/repeat assignments. Validation does not mutate the sheet. `tools/live_fill_tally.py`, `tools/test_live_fill_tally.py`. Fingerprints check consistency, not receipt authenticity. |
| G5: structural sheet capacity | The 40-slot skeleton could hold only 10 observations per arm. | Version 2 has 20 cells and 80 slots: two task positions per column, each with two repeats. CSV separates the planned column ID from the actual task ID. This closes capacity; G10 remains open. `tools/gen_live_fill_sheet.py`. |
| G6, F5: conformance | NestedBrief and Outcome lacked important type, range, inheritance, and time checks. LedgerRecord admitted fractional counters and could raise TypeError for null counters. | Brief/NestedBrief validation checks budgets, acceptance records, aware deadlines, nesting permission/depth, remaining resources, and inherited non-goals. Outcome and LedgerRecord reject malformed fields before use. `tools/conform_spec.py`, `tools/outcome_ledger.py`, and their tests. Empty Outcome checks remain allowed; host acceptance authentication is a separate duty. |
| G7, G9, F6–F7: watchdog | Invalid limits/state could be accepted; removing every argument separator changed a target command; inconsistent pending-repair history admitted another attempt; invalid UTF-8 could lose diagnostics under a UTF-8 supervisor. | Validate limits and persisted history before execution, preserve invalid state bytes, remove only the wrapper's first separator, require a consistent repair grant, and capture decoding errors with replacement. `tools/host_watchdog.py`, `tools/test_host_watchdog.py`. On Windows the decoder probe verified lost diagnostics, not a lost persisted attempt; the stronger candidate was retracted. |
| F8: session-close refresh | An existing sheet was not filled from newly appended ledger lines; caller rendering and exit behavior could hide findings. | Existing observations are preserved and checked against current source evidence; appended evidence imports once. Changed or absent sources become findings. Prices flow through the caller, integrity messages render, and unplaced evidence makes closure fail. `tools/pilot_close.py`, `tools/test_pilot_close.py`. |

## 3. Error-Reduction Recommendations

1. **G2 — qualify the supported billing surface before making a strict live-cap
   claim.** Pin supported provider/model/configuration identities and rates;
   document all supported billable usage components; obtain authoritative bounds
   or constrain unsupported configurations. Verify failure and timeout receipts
   as well as successful responses. Retain uncertain reservations until complete
   evidence permits reconciliation. Estimated effort: **1–3 engineering days
   plus provider evidence lead time** (INFERRED). An authoritative existing
   qualification record proving the supported all-in bound would change this
   recommendation. An arbitrary larger margin alone would not supply that proof.

2. **G10 — reconcile the task pool prospectively.** Qualify enough distinct tasks
   to meet the minimum at two repeats per task, with acceptance checks and the
   same assignments across arms; freeze tuning/holdout allocation and ordering
   before collection. Alternatively, explicitly revise the protocol and its
   acceptance conditions through the project's approval process. Do not count
   renamed copies as distinct tasks or revise the plan to fit observed results.
   Estimated effort: **1–2 engineering days plus task qualification time**
   (INFERRED). A later approved, accessible sufficient pool or revised protocol
   could make this unnecessary. This PR does not rewrite the ratified
   preregistration or fabricate approval.

The implemented class-level controls validate before aggregation and
supersession, bind settlement to reservation identity, recompute costs, preserve
incomplete evidence, and test negative controls alongside legitimate recovery.
They do not turn schema conformance into acceptance authentication or synthetic
data into evaluated model quality.

## 4. What Is Already Solid

- **Durable local budget authority — VERIFIED.** The existing SQLite authority
  reserves cash and attempt capacity before transport and coordinates local
  processes. The 18 budget tests cover restart, independent-instance,
  reservation, review-budget, and uncertainty behavior. The previously merged
  #47/#48 correction is not reopened as an unfixed defect.
- **Unknown usage remains unknown — VERIFIED.** Missing or partial physical
  usage retains an uncertain reservation. Report/import negative controls
  reject attempts to present it as a completed zero-cost measurement.
- **Bounded autonomous execution — VERIFIED.** The watchdog and dispatch APIs
  keep machine-enforced limits and terminal states. These fixes add no human
  approval step. Distributed coordination and descendant-process cleanup remain
  host responsibilities.
- **Traceable observation handling — VERIFIED locally.** Appended imports are
  idempotent, changed evidence is disclosed, and existing measured records are
  preserved for reconciliation. A complete synthetic 80-observation control
  validates with 20 per arm; it is a structural test only.
- **Interface boundaries retained — VERIFIED by inspection/tests.** Injected
  three-argument transports remain usable, count failures do not create model
  sends, additive record fields remain supported, and empty Outcome checks do
  not prove that the host ran acceptance. No intended capability was found
  accidentally dropped in the inspected paths. Historical Research-Kit removal
  remains deliberate.

Final staged-tree validation is recorded in the pull request and CI checks.
The local full gate is `python tools/run_regression.py`; the new live-fill suite
is included. Windows verification requires Git Bash on PATH for shell-based
hook fixtures and consistent UTF-8 mode for Python subprocess fixtures. Initial
environment failures were not hidden by weakening assertions.

## 5. Iteration Log

Passes are successive comparisons by one auditor, not independent reviews.
Corrections were made between audit stages. Each run rotates the comparison
pair per pass. Run 1's passes 5–6 added no new high-impact gap (F9 was moderate).
Run 2's final two passes were also empty. Run 3 was extended after G10 until
passes 7–8 met the same stopping rule. Delta includes candidates and moderate
findings; confirmations do not increment it.

| Pass | Comparison set | New gaps | Confirmed | Retracted or limited | Delta |
| --- | --- | --- | --- | --- | --- |
| 1.1 | LiteLLM / OpenRouter | F1: cross-task reservation ID can hide a charge | G1/G8 controls; G2 unresolved | No provider-bill bound inferred | 1 |
| 1.2 | Promptfoo / Inspect AI | F2: duplicated evidence; F3: interleaved repeat labels; F4: wrong fixed-arm profile | G3 numeric validation; G5 capacity | More slots do not qualify a task pool | 3 |
| 1.3 | Pydantic / JSON Schema | F5: fractional LedgerRecord counts; null-counter crash | G6 NestedBrief/Outcome checks | Empty Outcome checks alone do not prove acceptance | 1 |
| 1.4 | Temporal / LangGraph | F6: inconsistent pending repair; F7: decoder candidate; F8: existing-sheet refresh | Durable dispatch boundaries | Zero repair allowance remains a policy question | 3 |
| 1.5 | OpenTelemetry GenAI / Langfuse | None | F1: contradictory usage/pending records; F7 UTF-8 diagnostic loss | Windows attempt still persisted; no inferred per-model bill | 0 |
| 1.6 | CPython / SQLite | F9: HTTP response lifetime and remote reason (moderate) | Adapter/budget controls; F8 caller propagation | Default Windows byte-FF decoding is valid; host cleanup duties retained | 1; zero high-impact |
| 2.1 | LiteLLM / OpenRouter | None | Identity-bound settlement; uncertainty retained | Existing budget-authority fixes not reopened | 0 |
| 2.2 | Promptfoo / Inspect AI | None | Duplicate rejection, interleaved labels, fixed profiles, malformed summaries | Extra capacity does not ratify extra tasks | 0 |
| 2.3 | Pydantic / JSON Schema | None | Exact counters, controlled shape violations, conformance suite | One record cannot prove history monotonicity or receipt authenticity | 0 |
| 2.4 | Temporal / LangGraph | None | F6 state refusal; appended imports and idempotent close | Repair-allowance policy unchanged | 0 |
| 2.5 | OpenTelemetry GenAI / Langfuse | None | Unknown usage remains null; usage tests | Source hashes are consistency metadata | 0 |
| 2.6 | CPython / SQLite | None | HTTP cleanup/privacy; redirect and timeout controls | Synthetic tests do not qualify billing | 0 |
| 3.1 | LiteLLM / OpenRouter | None | Identity changes and lower-charge reconciliation refused | Local accounting is not a provider-bill guarantee | 0 |
| 3.2 | Promptfoo / Inspect AI | None | Synthetic 80-slot control; weakened plans rejected; missing sources preserved/disclosed | No claim of a qualified frozen pool | 0 |
| 3.3 | Pydantic / JSON Schema | None | Outcome/conformance validation | Additive evidence is not authenticated by shape checks | 0 |
| 3.4 | Temporal / LangGraph | None | Restart/repair and source-refresh inspection | No multi-process watchdog or descendant-cleanup guarantee added | 0 |
| 3.5 | OpenTelemetry GenAI / Langfuse | None | Contradictory events fail; null and overlapping usage handled honestly | No receipt, bill, or savings inferred | 0 |
| 3.6 | CPython / SQLite | G10: five tasks × two repeats cannot meet 20/arm | 29 watchdog and 18 budget tests; transport controls | Decoder failure was diagnostic loss on Windows | 1 high-impact |
| 3.7 | MLflow / Hugging Face Evaluate | None | G10 arithmetic, dataset identity, expectations/types | Renamed copies do not establish task diversity | 0 |
| 3.8 | scikit-learn / Ray Tune | None | Tuning/holdout requirement; close-report regressions | Synthetic fills cannot establish intervals or promotion | 0 |

For traceability, SHA-256 source digests were recorded at the **start** of each
run. They are not final Git commit IDs, independent attestations, or hashes of
the entire repository:

| Run | Start-of-run digest | Included source paths |
| --- | --- | --- |
| 1 | `6b1536544fc16a5618372e05a4721606d88f1c951833d0a4939e6f43a3fa1f25` | `tools/{dispatch_adapter,host_watchdog,conform_spec,outcome_ledger,pilot_report,live_fill_tally,gen_live_fill_sheet}.py` |
| 2 | `c8dca0c96359a3d660e925e6659a29ebb4ef94266dbdf46f6533e52478ec50fe` | The same seven files plus `tools/pilot_close.py` |
| 3 | `5f7e8975cf18a8a36bf06b16794516c6d71bd3371e58ca157575c27dcd3c9fff` | The same eight files |

Final focused regression review after these comparison passes tightened the
same F1 transition-validation class: nullable reconciliations must produce
findings without crashing, while complete reconciliation directly from a
retained pending reservation must remain legal. Those controls are included in
the PR tests. This is not presented as a fourth application of the skill.

## 6. Final Assessment

**The remaining gaps are not negligible for strict live billing or a completed
comparative evaluation.** The reproduced transport, validation, watchdog,
reporting, and observation defects have targeted corrections. This supports
local reliability under the tested contracts. G2 and G10 still prevent stronger
claims about all-in provider caps and a complete ratified live evaluation.

The audit did not inspect private billing records, authenticate host acceptance
receipts, run paid live dispatches, prove multi-machine budget coordination, or
establish comparative production savings and confidence intervals. Source and
local tests confirm the defects and protocol arithmetic; they cannot answer
those external questions. Qualified billing records and a prospectively frozen,
sufficient evaluation pool would change the readiness assessment.

## 7. Source Audit

All sources below are official primary sources fetched during the comparisons.
**Every external comparison is an unledgered fetch, at most WELL-SUPPORTED;
no Research-Kit E-nn evidence rows exist for these runs.** Project defects were
established from source and probes, rather than feature differences. No
external tool is claimed to guarantee SmartRouter's correctness.

| Official source | Supported comparison claim | Source type | Confidence |
| --- | --- | --- | --- |
| [LiteLLM budgets](https://docs.litellm.ai/docs/proxy/users), [OpenRouter Auto Router](https://openrouter.ai/docs/guides/routing/routers/auto-router) | Budget authority and explicit routing constraints are distinct from a universal bill bound. Features alone establish no gap. | Vendor documentation; unledgered | WELL-SUPPORTED |
| [Anthropic token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting) | Counts are estimates and can differ from actual usage; this does not prove the 5% margin bounds an all-in bill. | Provider documentation; unledgered | WELL-SUPPORTED |
| [Promptfoo assertions](https://www.promptfoo.dev/docs/configuration/expected-outputs/), [Inspect AI logs](https://inspect.aisi.org.uk/eval-logs.html) | Expected outputs and per-sample records distinguish measurements from unvalidated filled markers. | Maintainer documentation; unledgered | WELL-SUPPORTED |
| [Pydantic strict validation](https://pydantic.dev/docs/validation/latest/concepts/strict_mode/), [standard types](https://pydantic.dev/docs/validation/latest/api/pydantic/standard_library_types/), [JSON Schema numbers](https://json-schema.org/understanding-json-schema/reference/numeric), [objects](https://json-schema.org/understanding-json-schema/reference/object) | Integer/range checks, finite values, aware datetimes, and required-versus-null distinctions inform malformed-input controls. | Maintainer/reference documentation; unledgered | WELL-SUPPORTED |
| [Temporal execution](https://docs.temporal.io/workflow-execution), [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | Durable state and checkpoint boundaries inform recovery inspection; neither supplies distributed coordination to this project. | Vendor/maintainer documentation; unledgered | WELL-SUPPORTED |
| [OpenTelemetry registry](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/), [GenAI repository](https://github.com/open-telemetry/semantic-conventions-genai), [Langfuse usage/cost](https://langfuse.com/docs/observability/features/token-and-cost-tracking) | Requested/resolved model and ingested/inferred usage distinctions matter; overlapping subtotals must not be added blindly. Moved conventions are not described as a stable new guarantee. | Standards/maintainer documentation; unledgered | WELL-SUPPORTED |
| [CPython urllib source](https://raw.githubusercontent.com/python/cpython/3.14/Lib/urllib/request.py), [urllib reference](https://docs.python.org/3/library/urllib.request.html), [subprocess reference](https://docs.python.org/3/library/subprocess.html), [SQLite transactions](https://www.sqlite.org/lang_transaction.html) | Redirect/header behavior, socket timeouts, argument/decoding behavior, and local transactions. Timeout forwarding is not a total wall-clock deadline guarantee. | Language/database primary sources; unledgered | WELL-SUPPORTED |
| [MLflow datasets](https://mlflow.org/docs/latest/genai/concepts/evaluation-datasets/), [Hugging Face Evaluate](https://huggingface.co/docs/evaluate/a_quick_tour) | Dataset identity, inputs, expectations, and metric input types distinguish a qualified task pool from empty capacity. | Maintainer documentation; unledgered | WELL-SUPPORTED |
| [scikit-learn cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html), [Ray Tune](https://docs.ray.io/en/latest/tune/index.html) | Holdout separation and explicit optimization metrics inform readiness checks. Ray is not claimed to automatically prevent holdout leakage. | Maintainer documentation; unledgered | WELL-SUPPORTED |

An initially requested Ray example URL could not be fetched; the accessible
Ray Tune overview above was used instead. Unfetched content is not evidence.
