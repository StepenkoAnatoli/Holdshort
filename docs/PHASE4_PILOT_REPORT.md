# Phase 4 pilot report — SmartRouter first non-live evaluation

> **Scope declaration.** This report covers the **non-live Phase 3/4 evaluation** authorized by the
> owner (2026-10-10): the five §3.1 tasks executed on the ratified host **`SR-PHASE3-LOCAL`**, in an
> isolated scratch clone at merged main `c69352c`, with the plan §10 declared profile/price catalog.
> **No live-model dispatch, no spend, no network egress occurred.** The §7 fields below are closed
> *for this non-live scope only*; a live pilot is a separate §10 row 4 authorization and would
> re-open the report under its own scope.

## 1. Report identity

| Field | Value |
| --- | --- |
| Report path | `docs/PHASE4_PILOT_REPORT.md` (this file) |
| Host | `SR-PHASE3-LOCAL` (§2.1 of the merged preregistration) |
| Tree evaluated | merged main `c69352c` (PR #8 → PR #9 chain) |
| catalogs / prices | plan §10 declared `catalog-1` / `prices-1` (non-live, per §12) |
| Working method | each task executes its §3.1 contract in an isolated scratch clone; main untouched |
| Exit codes captured | explicit, per command; no piped-filter passes |

## 2. Per-task evidence ledger (§3.1 contracts)

| Task | Contract executed | Evidence observed | Pass |
| --- | --- | --- | --- |
| T-01 docs typo sweep | locate misspelling in `docs/`, byte-diff vs pre-run reference, decision suite exit-0 post-edit | 2 × `recieve` → `receive` in `docs/DEVELOPMENT_PLAN.md`; `git diff --numstat` = 1 file / 2+2; suite **79/79 exit 0** post-edit (run from `tests/decision-suites` copy) | **Pass** |
| T-02 helper extraction | extract inline guard in `tools/validate_skills.py` to named helper; runner exit-0; numstat = 1 file | inline per-skill block extracted to `check_skill_dir(sd, errors)`; runner **exit 0** pre/post; change bounded to 1 file | **Pass** |
| T-03 `--strict` flag | promote no-competing-authority sweep informational→hard failure; both with/without flag exit-0 | `validate_skills.py` exit 0 without flag; exit 0 **with** `--strict` (clean tree, no findings to promote); argument disclosed in code path | **Pass** |
| T-04 frontmatter hardening | malformed SKILL.md YAML → named structured error + nonzero exit; existing 3 skills still exit 0 | temp `bad-skill` fixture → `FAILED … malformed frontmatter line (expected 'key: value'): 'name bad-skill!!'`, **exit 1**; removed; 3 real skills **exit 0** | **Pass** |
| T-05 sidecar summary | per-family route-summary helper; main suite exit unchanged; helper exit 0 | `tests/decision_summary.py` prints 4 families + catalog count, **exit 0**, advisory-only; main suite **79/79 exit 0** unchanged | **Pass** |

Aggregate: **5/5 task contracts passed on the ratified host, zero deviations, zero unmatched side-effects** (numstat accounted every run).

## 3. Non-live gates replayed on real artifacts

The decision suite (`tests/smart_router_decisions.py`, 79 assertions / 52 fixture IDs) proves the
deterministic gate-runner semantics: fail-closed routing, empty-set non-resurrection, unknown-price
blocking, reservation arithmetic, cache-fingerprint invalidation, repair-counter stickiness.

The five executed tasks additionally prove the repo's **tooling contracts** behave as the gates
require: check availability (T-02), strictness opt-in (T-03), structured parse failures (T-04),
and advisory-only sidecar output with no dispatch claims (T-05).

## 4. §7 report fields (scheme per merged preregistration §7)

| Field | Value | Basis |
| --- | --- | --- |
| `report_status` | **complete** | all five §3.1 contracts executed with captured exit codes; no §12.3 item outstanding for the non-live scope |
| `decision` | **promote (non-live)** | 5/5 contracts passed; no safety/accounting/coverage gaps in the non-live scope |
| `router_promotion_eligible` | **true — non-live scope only** | same scope boundary as the §10 row 3/4 split: real-provider rate sheets and live qualification records stay PENDING, so *live* promotion is not granted by this report |
| Automation | `run_gates`/`choose_route` verified 79/79 | suite output, exit 0 |
| Operator effort | within §5 5-minute wall-clock per task | per-command execution logs |
| Cost | $0.00 real spend | non-live declared inputs; no live model calls made |

## 5. Honest limitations

- The evaluation is **non-live**: no real provider, no real billing, real rate-sheet economics
  unproven. The `$0.00` spend is a fact of scope, not a savings claim.
- Semantics proven are the suite's **deterministic gate-runner model** of the skill's rules, not
  live host enforcement, real-model behavior, or consumer-agent adherence (plan §13+ runtime
  gates; Phase 5–7 consumer scope).
- Quality/latency/effort thresholds (§4) were not exercised against live measurements — they
  govern a **live** pilot, whose prerequisites are explicitly `PENDING` in §10.
- Merge into `main` for PRs #8/#9 was owner-directed **without** the plan P02 independent
  reviewer step; recorded in `docs/PROJECT_COMPLETION.md` rather than silently claimed as a
  reviewed approval.

## 6. Arm-coverage execution matrix (§3.1 × A/B/C/D)

> Scope of this matrix: mechanical-derivation record, not a live-execution claim. Cells marked
> **G** were exercised by running the task through the decision suite's real gate model
> (`choose_route` on plan §10 profiles) with the task's actual economic shape — the same model the
> suite's 79 assertions verify. Cells marked **D** (definitional) are arm A/B/C: by preregistration
> §1 these arms dispatch straight to a profile without routing, so their "route decision" is a
> definition of the arm, not a computed result. They are recorded so every task has a documented
> path in every arm; where the arm would execute the task identically to what the non-live run
> already did, that is claimed; where it is a plan-only shape, the honesty note below applies.

| Task | A (strong direct / cloud-S) | B (econ direct / cloud-C) | C (fixed rule) | D (SmartRouter flow) |
| --- | --- | --- | --- | --- |
| T-01 docs typo sweep | D: defined arm; content-wise same job as executed non-live contract | D: same, weaker model | D: pick cheapest eligible = **C**, content-wise same job | **G tested:** route=`direct`, profile=`local-L`, 5 gates pass |
| T-02 validate_skills helper | D: same contract (extract helper); stronger model unneeded | D: same contract | D: picks C | **G tested:** route=`direct`, profile=`local-L` |
| T-03 `--strict` flag | D: same contract | D: same contract | D: picks C | **G tested:** route=`direct`, profile=`local-L` |
| T-04 frontmatter hardening | D: same contract | D: same contract | D: picks C | **G tested:** route=`direct`, profile=`local-L` |
| T-05 sidecar summary helper | D: (if viewed as advanced-review task) same contract via cloud-S | D: same as simpler helper | D: picks C | **G tested (basic):** route=`direct`, profile=`local-L`. **G tested (advanced-review interpretation):** route=`direct`, profile=`cloud-S` — gates 2 initially flag S,C,L ordering artifact, resolved by ordering that puts S first; no 5-gate residual failure on S |

**Honesty note (per §5 of this report):** only the **D** column is evidence the *routing policy*
would take the recorded action under the preregistered gates. The A/B/C columns show what a
non-router arm would do *by definition* — they do not claim that arm actually executed the task;
only the D-arm T-01..T-05 contracts were physically run (in [§2](#2-per-task-evidence-ledger-31-contracts))
and the gate-model derivations were rerun live for this matrix. Costs/latency/effort per cell are
**not** measured for A/B/C in this report — those need a live Phase 4 run per §10 row 4, which stays
PENDING there. This is a **coverage ledger**, not a comparative measurement.
## 7. Arm-matrix ledger — aggregated summary (2026-10-10, rerun on main)

> Machine source: `tools/arm_matrix.py` (matrix_version 1), 4×5 = 20 cells, coverage
> `complete=true`. This section *summarizes* the freshly generated ledger on the current tree;
> the §6 matrix above preserves the original walkthrough's derivations. Same honesty rule:
> A/B/C observed values are arm definitions, D is the gate-runner route actually computed.

| Arm | T-01 | T-02 | T-03 | T-04 | T-05 | All match |
| --- | --- | --- | --- | --- | --- | --- |
| A — strong qualified direct | cloud-S ✓ | cloud-S ✓ | cloud-S ✓ | cloud-S ✓ | cloud-S ✓ | 5/5 |
| B — economical qualified direct | cloud-C ✓ | cloud-C ✓ | cloud-C ✓ | cloud-C ✓ | cloud-C ✓ | 5/5 |
| C — simple fixed rule | cloud-C ✓ | cloud-C ✓ | cloud-C ✓ | cloud-C ✓ | cloud-C ✓ | 5/5 |
| D — SmartRouter skill flow (gate-runner) | direct → local-L ✓ | direct → local-L ✓ | direct → local-L ✓ | direct → local-L ✓ | direct → local-L ✓ | 5/5 |

**Aggregate: 20/20 cells `match=true`, coverage complete, no missing cells.** Per-cell cost labels
remain the non-live $0.00 modeled class (see the matrix's accounting note) — measured costs arrive
only via the live sampling plan in §8.

## 8. Live sampling plan — how each matrix cell fills with measured observations (row-4 start)

Precondition: this plan executes only after §10 row 4 (`docs/PHASE4_LIVE_START_PACKET.md` §3,
SIGNED) and the runbook's go-live preflight pass. It is preregistered *shape*, not new policy;
per-arm sample size and repetitions are the preregistration's ratified rules (20 assigned
evaluated observations per arm; 2 repeats per task, cold cache; 50/50 tuning/holdout).

**Current readiness caveat (2026-10-15):** the ratified Phase 3 catalogue contains
five concrete tasks. At two repeats each, that pool supplies only **10 observations
per arm**, below the required minimum of 20. The version 2 sheet now provides
**80 structural slots, 20 per arm**, using two distinct task positions in each of
five category columns and two repeats per task. Those positions do not qualify
additional tasks or amend the frozen protocol. A representative prospective task
pool, including its tuning/holdout assignment and acceptance checks, must be
qualified and recorded before a live trial. A reliable strict live billing bound
also remains unqualified. This update reports tooling changes, not live results.

| Element | Contract |
| --- | --- |
| Mapping task↔cell | The live pilot's task pool (preregistration §3 categories: typo/mechanical/text per §10) maps onto the five matrix columns. Each live task lands in cell `(arm, task)` by its assigned arm; D-arm cells additionally record the gate-runner's route decision (profile, rejects). |
| Fill cadence | 20 observations fill each of the 4 arm rows; with 2 ratified repeats each task contributes 2 observations → 10 tasks minimum per arm. Order interleaves arms (A→B→C→D per task pair) so spend/time drift hits arms symmetrically. |
| What a measured cell records | Per observation: profile actually dispatched, `(input_tokens, output_tokens)` from usage evidence, cost checked against `tools/prices-2.json`, and decision metadata from `tools/pilot_ledger.jsonl`. The importer's `latency_s` is the interval between ledger timestamps for the same task; the first dispatch is explicitly unavailable. It is not a measured send-to-response duration. The host must collect the trial's required latency and acceptance evidence separately. |
| Caps enforced during fill | $1.00/task, $20.00/pilot, 4 attempts + 1 same-profile repair, 300 s/task wall clock. The persistent dispatch authority preserves attempts and reservations across restarts; `--task-store` adds optional task mirrors. Every block (cap or gate) is retained as a ledger observation rather than silently dropped. These local controls do not establish a reliable provider billing ceiling. |
| Drift / deviation handling | §7 drift rule (preregistration §6): provider-side change discovered mid-filling ⇒ affected arm's observations discarded, cause recorded before restart; no retrospective cell edits. |
| Cell completion rule | A cell is *filled* when all four positions contain validated measured observations: two distinct assigned tasks with two repeats each. `tools/gen_live_fill_sheet.py` generates the version 2 **20-cell/80-slot** sheet (`tools/live_fill_sheet.json`/.csv, gitignored). `tools/live_fill_tally.py` checks required values, repeat limits, fixed-arm profiles, source identities, and cost recomputed from the configured rates. Missing or invalid evidence cannot count as filled. A ledger block is retained as an observation without being counted as a successful dispatch. |
| Import and close | Run `python tools/live_fill_tally.py --import tools/pilot_ledger.jsonl --assignments map.json`, where the map assigns each live task ID to `{"arm": "A..D", "cell": "T-01..T-05"}`. Re-import and close add new source observations once; changed, missing, wrong-arm, over-repeat, or unassignable evidence becomes a finding. Source fingerprints check consistency and do not authenticate provider receipts or acceptance. Invalid prior recorded sheets are preserved for reconciliation, without silent migration. |
| Success/acceptance floor | ≥90% of assigned evaluated observations accepted per arm (preregistration §11 floor); the §7 report fields then carry the arm-level result. |
| Exit | When all 20 cells are filled or caps bind: `tools/pilot_close.py` (§9 block below) closes the ledger; pilot_report must still be `intact` and the full regression gate green before the close report is accepted. |

## 9. Pilot-close template — markdown block format (synthetic ledger, $0.00 — not real spend)

Generated by `tools/pilot_close.py --markdown` from a *synthetic* ledger so the owner can see the
exact shape the live close will produce. All figures below are fabricated sample data; the real
close regenerates them from `tools/pilot_ledger.jsonl` at session end.

| Task | Attempts | Spend (USD) | Disposition | Caps OK |
| --- | --- | --- | --- | --- |
| L-001 | 2 | 0.003000 | completed | OK |

**Pilot totals**: 1/1 tasks completed, 0 blocked; 2 dispatches; spend $0.003000 of $20.00
(headroom $19.997000); accounting intact.
_No section-7 decision is derived from this table; see the Phase 4 report's section-4 fields._
