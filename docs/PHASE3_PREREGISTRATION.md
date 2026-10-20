# Phase 3 evaluation preregistration — Holdshort pilot

> **Ratification revision (2026-10-10).** Owner actions recorded this revision (on top of the
> concrete-fill revision at `6d20b04df5dc09815d6d57cdd4f1a6aeb0d11f37`, PR #8):
> (a) **Named evaluation host = `SR-PHASE3-LOCAL`** — the local Holdshort checkout (§2.1) —
> confirmed by explicit owner decision this day;
> (b) the §4 numerical thresholds, §5 attempt/budget/deadline constraints, and the §3 rows they
> gate are **ratified as a set** at the exact proposed values (none changed);
> (c) the §12 Phase 4 pilot scaffolding (catalog slots, price-list structure, trial-start
> checklist) is drafted so trial-start setup is ready once the remaining owner-supplied
> items clear — **no rate numbers, model identities, or qualification records are invented here**;
> (d) the §2.2 catalog/price-list/qualification items are filled **for the non-live reference
> set** by adopting plan §10's declared `catalog-1`/`prices-1` inputs (§12.1/§12.2) — real-provider
> rates and live qualification records remain **PENDING** for a Phase 4 live start. Per plan P02,
> prior Phase 3 document acceptance is stale until delta-reviewed
> and reaffirmed at this new full revision by an independently designated non-author reviewer,
> plus a separate owner acknowledgement.

Status: **draft ratification revision awaiting independent review + reaffirmation by owner** (Phase 3 exit gate per plan §14/§15).
Prepared per [docs/DEVELOPMENT_PLAN.md §11](DEVELOPMENT_PLAN.md) and the
[holdshort-eval-prep skill](../skills/holdshort-eval-prep/SKILL.md). Pinned to plan revision
`d7c00f96a17c35e6c47c5ba1f7e3a9160c966042` and the skill tree at merged main at the time of amendment.

## 0. Status vocabulary used throughout this document

| Status | Meaning |
| --- | --- |
| **RATIFIED** | Owner-supplied (or explicitly owner-acknowledged) value; may be used as-is if a Phase 4 start is separately authorized. |
| **PROPOSED** | Documented author default, aligned with plan §11's S21a-S22g reference protocol, **awaiting owner ratification**. Becomes binding only after owner acknowledgement. |
| **PENDING** | Owner must supply; no author-proposed default exists. Blocks the milestone it feeds until supplied. |
| **BLOCKED** | A prerequisite is missing and blocks the next phase milestone until resolved; no workaround is implied. |

Every numeric value and host requirement in this document carries one of these status labels.
Ratification is an owner action recorded in this document's PR or a linked artefact; an agent
cannot self-ratify.

## 1. Arms

| Arm | Description | Notes |
| --- | --- | --- |
| A | Strong qualified **direct** — dispatch the task straight to the operator's strongest qualified model | Baseline for quality/loss comparison |
| B | Economical qualified **direct** — dispatch straight to the cheapest qualified model | Baseline for cost comparison |
| C | Simple **fixed rule** — deterministic cheap-if-eligible-else-strong selector | Baseline for "simpler policy" comparison |
| D | **Holdshort** skill flow (ordered gates + brief/verifier/review) including all overhead | The candidate under test |

Same acceptance/privacy/effects rules for all four arms. Weak baselines (B, C) are **never** exposed
to production secrets or consequential writes. Kit workflow constant across arms.

**Arm-definition status:** **RATIFIED** as structural (four arms and their roles per plan §11), but
each arm's concrete model/profile identity is **PENDING** until the owner supplies the immutable
parent tuple in §2.2.

## 2. Host and controls (status per control)

### 2.1 Named evaluation host — **RATIFIED** (owner decision, 2026-10-10)

The named Phase 3 evaluation host is **`SR-PHASE3-LOCAL`**: the local Holdshort checkout itself,
operated by the owner. What it supplies, and the one hard cap on its scope:

| Provided by SR-PHASE3-LOCAL | Meaning |
| --- | --- |
| Identity/permissions | Owner-operator actor identity; local filesystem and tool paths already enumerated in plan §7's permissions model |
| Call limits | Attempt, repair, and escalation counters enforced at arm level; restart does not reset them (plan §7 structural rule) |
| Test isolation | Arms run in separate working copies of this checkout — no shared mutable state across arms |
| Stop/recovery | Observable Stop via process control on the local runner; cancellation and restart semantics are host-observable |
| Required checks | `tools/validate_skills.py`, `tests/holdshort_decisions.py`, and `fixture_checks.py` run with deterministic exit codes on pinned main |
| Usage/billing | **Not provided.** This is a hard cap on the host's scope: SR-PHASE3-LOCAL exhibits no per-call accounting of its own. Every hosted-model call must carry its price bound from the §2.2 price list, and a missing bound blocks Gate 4 (plan §8). |

**Host-name and the five host-controls above are RATIFIED** (owner decision, 2026-10-10). This
ratification is scoped to **Phase 3 non-live evaluation**: it does **not** authorize live-model
dispatch, spend, or network egress (those stay behind §10 row 4). It does not ratify any §2.2
catalog, price-list, or qualification-record content.

### 2.2 Catalog and controls still requiring owner supply (scaffolding drafted in §12; content PENDING)

| Control | What must be evidenced | Owner to confirm | Status |
| --- | --- | --- | --- |
| Model/profile catalog | Immutable qualification tuples with tested capability evidence (plan §5) | `StepenkoAnatoli` | **RATIFIED for non-live** — plan §10 `catalog-1` tuples adopted (§12.1); live identities **PENDING** |
| Price list | Current unit-aware pricing with documented revision hash/timestamp (§3.3 structure) | `StepenkoAnatoli` | **RATIFIED for non-live** — plan §10 `prices-1` declared fixture bounds adopted (§12.2); real-provider rates **PENDING** |
| Conservative bounds | Reliable per-call/prerecorded cost estimate; no unknown/unbounded fees | `StepenkoAnatoli` | **RATIFIED for non-live** (declared bounds above); live estimation **PENDING** |
| Host qualification records | Pointer to each profile's qualification record (tested tasks, check/rubric outcomes, reviewer, expiry) per plan §5 | `StepenkoAnatoli` | **PENDING** for live profiles; non-live uses plan §10 declared qualification |

The non-live reference set is filled by adopting the pinned plan §10 declared inputs
(`catalog-1`, `prices-1` — see §12); those carry **RATIFIED-for-non-live** status. Any *live*
provider identity, real rate sheet, and per-profile qualification record stays **PENDING** owner
supply and gates only a Phase 4 live start (plan §11 "Blanks mean not ready"; plan §14).

## 3. Frozen task set and analysis units

- **Task categories** (must be distinct and representative, not repeated copies of one mechanical
  fixture): bugfix-typo-isolated, small refactor bounded to N files, new endpoint following existing
  pattern, validation/error-handling, component with local state using existing design system.
- **Per-arm sample size**: minimum **20 assigned evaluated observations per arm** — status
  **RATIFIED** (owner, 2026-10-10; matches plan §11/S21a-S22g reference protocol).
- **Task coverage**: every task fixture traced to all four arms; unattempted count against coverage
  as preregistered — status **RATIFIED** as a *rule*.
- **Tuning/holdout**: tuning data kept in a separate pool; holdout workload used for final
  intervals. Holdout-to-tuning ratio: **50/50** — status **RATIFIED** (owner, 2026-10-10).
- **Repetitions**: **2 repeats per task** per arm (cold cache each repeat) — status **RATIFIED**
  (owner, 2026-10-10).
- **Ordering**: interleaved randomized with a frozen seed — rule **RATIFIED**; concrete seed values
  **RATIFIED-as-method** (§3.2, derived from the pinned plan revision hash).
- **Cache conditions**: cold cache per trial; no per-profile warm-prefix credit claimed — status
  **RATIFIED** as a rule.
- **Statistical method**: 95% two-sided interval for the difference-in-means of cost-per-success,
  acceptance, p95 latency, and operator effort; paired by task fixture when the task lists are
  identical across arms (they will be) — status **RATIFIED** (owner, 2026-10-10).
- **Missing-data rule**: an attempt with unknown/missing charge is marked unknown and included as
  such; it never substitutes for a value — status **RATIFIED** as a rule.

### 3.1 Concrete task catalogue — pool **RATIFIED** (PR #8 revision)

Five tasks, each anchored to a **real artefact already on pinned main** rather than abstract
shapes. Each carries an executable acceptance contract. Owner selection recorded in PR #8 chain;
this revision adds nothing to the pool and changes no threshold it references.

| ID | Anchor | Executable acceptance contract |
| --- | --- | --- |
| T-01 | `docs/` typo sweep | byte-diff vs pre-run reference + decision suite exit-0 |
| T-02 | `tools/validate_skills.py` — extract inline guard to named helper | runner exit-0, numstat = 1 file |
| T-03 | `--strict` flag promoting no-competing-authority sweep to hard failure | both with/without flag exit-0, no other file changed |
| T-04 | hardened `parse_frontmatter` (malformed YAML → nonzero exit) | negative temp fixture exits nonzero; existing 3 skills exit 0 |
| T-05 | decision-suite sidecar helper printing per-family summaries | main suite exit unchanged; helper exits 0 |

**Common properties (RATIFIED as constraints on every task):**
- Every task must have an exact, checkable acceptance contract (diff assertion, test command, or
  structural check) before work starts.
- Every task must be *repeat-safe* and run in isolation.
- Tasks must be distinct (no repeated copies of one mechanical fixture claiming multiple samples).

**Pool ratification note (this revision):** the pool stays as ratified in PR #8. This revision
records the host named in §2.1 that will run these tasks, and ratifies §4/§5 in the same turn so
the pool's runtime limits are now fixed rather than placeholders.

### 3.2 Frozen seeds — derived, reproducible, **RATIFIED-as-method**

Seeds are not author-chosen integers. They are **derived deterministically** from the pinned plan
revision hash by the recorded method below, so any reviewer or the Phase-4 host can recompute the
same numbers without owner input. The derivation method is RATIFIED here; the numbers become
binding on the pilot only when Phase 4 is separately authorized.

**Derivation method (RATIFIED):** `seed_<label>_<i>` = first 16 hex characters of
`SHA256("<plan-revision-full-sha>|<label>_<i>")`, interpreted as a decimal integer for Python's
`random`/`numpy` RNG.

**Pinned plan revision:** `d7c00f96a17c35e6c47c5ba1f7e3a9160c966042` (the merged main that carries
the plan artefacts and the holdshort skill tree; anchored to the plan hash, not the Phase-3
amendment hash, so all Phase-2/3/4 revisions of this document derive the same seeds).

**Derived values (recomputable from the method above):**

| Seed label | Derived 16-hex | Decimal (Python `random` compatible) |
| --- | --- | --- |
| `seed_holdout_1` | `5a7e83cac20a8998` | 6520794217341159832 |
| `seed_holdout_2` | `d3f02ff91acf6dc7` | 15271759083356515783 |
| `seed_holdout_3` | `b43642b189daac02` | 12985639905858857986 |
| `seed_ordering_1` | `c7fcf15206405ea2` | 14410658242273238690 |
| `seed_ordering_2` | `b311f8efae0fc148` | 12903368115694321992 |
| `seed_ordering_3` | `2eb7f8defb3ad731` | 3366432883064100657 |

Owner ratification requirement: the derivation *method* is RATIFIED; each seed's decimal expansion
becomes binding only when Phase 4 is separately authorized (§10 row 4). Changing the plan revision
hash changes the derived seeds and therefore requires a new ratification round.

### 3.3 Pricing revision skeleton — structure **RATIFIED**, unit numbers **PENDING**

Per plan §11 ("Fill approved numerical values ... Blanks mean not ready") and §5 of the
holdshort-eval-prep checklist, a pilot cannot start without a pinned price list. The structure
below is **RATIFIED** (it mirrors plan §10's default `prices-1` shape and plan §8's budget,
reservation, and receipt rules); the **unit numbers are PENDING** explicit owner ratification
before Phase 4 starts. No number is author-ratified.

**Structure (RATIFIED):** the Phase 4 pilot uses a `prices-<label>` record naming, per profile in
§2.2's catalog:

| Field | What it carries | Source of value |
| --- | --- | --- |
| `profile_id` | matches exactly one of the §2.2 catalogue tuples | host provider |
| `input_rate` | per-token (or per-call, if the provider is flat) input/context price | provider published rate sheet at the pinned revision |
| `output_rate` | per-token (or per-call) generated-token price | same |
| `currency` | exact minor-unit identifier (e.g. `USD-1000`; no converted quotas) | provider |
| `bounds_source` | which provider-side file/page/hash the rate came from, with revision reference | provider |
| `uncertainty_class` | `known` / `unknown` / `flat-rate-capped` | operator observation |
| `effective_at` | timestamp the bound was read | operator |
| `revision_hash` | SHA-256 of the pricing record itself, so price-revision changes (S15b) are detectable | recomputed at freeze |

**Fill-out rule (RATIFIED as structure):** a `prices-<label>` record is complete only when every
row carries a value for every field. Units are **minor units** of the stated currency, not dollar
approximations; conversion from provider units must show the arithmetic in-line. Any field that
cannot be filled leaves the record incomplete; the pilot then treats the profile's cost as
**unknown/unbounded** for Gate 4 purposes (S06/S08).

**PENDING explicit owner-supplied fill:** the provider's actual rate-sheet content, its source
URL/hash, the provider's exact currency/decimal rule, and any flat-rate minimums. Filling these is
an owner action in §10 (row 4's prerequisite). Author-side provision not permitted.

**Local-model exception (structural, profile `L` of the §3.1 catalogue):** `L` is local and free of
per-token billing, so its `input_rate`/`output_rate` are **0**; its real cost is resource
wall-clock/energy (plan §8: "Local work has resource/time cost"), which is recorded, not billed.
**RATIFIED** as method; any concrete resource-cost number stays PENDING owner supply.

## 4. Numerical thresholds — status per value

### 4.1 Core per-arm gates

| Metric | Value | Basis | Status |
| --- | --- | --- | --- |
| Mandatory acceptance floor per arm | **90%** of assigned evaluated observations accepted | plan §11 reference protocol (S21a) | **RATIFIED** (owner, 2026-10-10) |
| Max acceptance loss vs A | **5 percentage points** (entire interval upper bound ≤ 5 pp) | plan §11 reference protocol (S22c) | **RATIFIED** (owner, 2026-10-10) |
| Min cost-per-success reduction vs A | **10%** (entire interval lower bound ≥ 10%) | plan §11 reference protocol (S22c) | **RATIFIED** (owner, 2026-10-10) |
| Max p95 latency increase vs A | **10%** (entire interval upper bound ≤ 10%) | plan §11 reference protocol (S22c) | **RATIFIED** (owner, 2026-10-10) |
| Max operator-effort increase vs A | **10%** (entire interval upper bound ≤ 10%) | plan §11 reference protocol (S22c) | **RATIFIED** (owner, 2026-10-10) |
| Confidence level | **95%** throughout | plan §11 | **RATIFIED** (owner, 2026-10-10) |

### 4.2 C-vs-D equivalence and promotion rules

| Rule | Value | Basis | Status |
| --- | --- | --- | --- |
| C-vs-D equivalence margin (cost / latency / effort) | **±5%** — the **entire** interval must lie inside for a "favors simpler C" finding | plan §11 (S22b) | **RATIFIED** (owner, 2026-10-10) |
| C-vs-D equivalence margin (acceptance difference) | **±5 pp** — entire interval must lie inside | plan §11 (S22b) | **RATIFIED** (owner, 2026-10-10) |
| D-vs-C incremental benefit for promotion eligibility | **strictly > 5%** (lower bound > 5%, not ≥) | plan §11 (S22c/S22f explicitly exclude the boundary case) | **RATIFIED** (owner, 2026-10-10) |

### 4.3 Degenerate-evidence rules (structural, not tunable in this pilot)

| Rule | Form | Status |
| --- | --- | --- |
| Zero-baseline rule | A cost/success of $0.00 in arm A makes relative D-vs-A comparison undefined → report `inconclusive`; **no invented infinity/zero-percent** | **RATIFIED** (structural rule per plan §11) |
| Zero-success rule | Arm with 0 accepted successes has undefined cost ratio. Absent a separately evidenced safety/quality-floor violation, **economic comparison is inconclusive**, never savings | **RATIFIED** (structural rule) |
| Severe-failure stop rule | Any observed unauthorized/safety-violating effect ⇒ **stop trial, decision reject**, regardless of other evidence; safety rejection has priority over missing accounting | **RATIFIED** (structural rule, zero-tolerance per plan §11) |

### 4.4 Rule — ratified-thresholds boundary

The §4/§5 threshold set is now **ratified** (owner action recorded this revision). It becomes *the*
operative pilot value set once this revision is merged by the review chain; any later change
requires a new ratification round. **Ratifying §4/§5 alone still does not authorize a Phase 4
start** — spend, egress, and environment approval remain a separate §10 row 4 owner action.

## 5. Attempt / budget / deadline boundaries — status per value

- Max attempts per task (any arm): **4** physical model dispatches — status **RATIFIED** (owner,
  2026-10-10; tighter than plan §10's common fixture default of six — a deliberate, owner-visible
  tightening).
- Max cost per task: **$1.00** — status **RATIFIED** (owner, 2026-10-10; matches plan §10 fixture
  defaults. Operational binding still depends on §2.2's price list, which is PENDING — see §3.3.
  Until the price list exists, the $1.00 ceiling is enforced only against the conservative bounds
  §3.3 defines, not against unknown providers).
- Max elapsed wall-clock per task: **5 minutes** — status **RATIFIED** (owner, 2026-10-10; matches
  plan §10 fixture defaults).
- All attempts — planner, worker, verifier, transport retry, repair, escalation — count against
  both the attempt and cost ceiling; cancelled/timeout calls count; hidden host retries count —
  status **RATIFIED** (structural rule plan §7-8).
- Equality-passes rules: cost bound ≤ remaining budget passes; call `used + reserved ≤ limit`
  passes; time **strictly before** deadline passes (equality expires) — status **RATIFIED**
  (structural rule plan §8).
- Repairs: at most **one** same-profile correction per original task; a differently-qualified
  profile consumes escalation, not a repair allowance; restart/rename never resets counters —
  status **RATIFIED** (structural rule plan §7).

## 6. Drift and restart of the pilot

- If model/price/config drift is detected after a frozen point, the **preregistered rule** is:
  restart the affected workload only, using a fresh pool of tasks from the same frozen category
  list; discard drift-affected observations from the affected arm; do not retrospectively change
  thresholds — status **RATIFIED** (structural rule plan §11).
- Missing billable usage cannot establish savings; if accounting is incomplete, the report can
  close `inconclusive` with documented gaps, and **no adoption** is proposed — status **RATIFIED**
  (structural rule).
- Reservations for unresolved charges persist after report closure; report completion does not
  release them — status **RATIFIED** (structural rule plan §8).

## 7. Report and promotion gates

Phase 4 has three separate fields: `report_status ∈ {complete, incomplete}`, `decision ∈ {reject,
inconclusive, simplify, promote}`, `router_promotion_eligible ∈ {true, false}`.

| Predicate | Outcome |
| --- | --- |
| Severe safety failure observed, regardless of other metrics | `decision = reject (stop)`, `router_promotion_eligible = false`; reclassify affected accepted counts |
| Quality/latency/effort floor violated | `decision = reject`, `eligible = false` |
| Accounting/precision/coverage gap (post-safety) | `decision = inconclusive`, `eligible = false` |
| Qualifying simpler C (equivalence held, all gates pass) and no D incremental benefit | `decision = simplify`, `eligible = false`; C may be proposed for separate authorization |
| All hard gates pass and D shows incremental benefit > 5% over qualifying C | `decision = promote narrowly`, `eligible = true` for this pilot's declared scope only; adoption still requires separate approval |
| Complete precise evidence, neither simplify nor promote predicates hold | `decision = reject (insufficient benefit)` |

Status of the whole §7 predicate table: **RATIFIED** as structure (these predicates mirror plan
§11's frozen decision rules; the numeric thresholds feeding them were ratified this revision —
see §4.4).

Report completion is an independent decision from promotion eligibility; a complete report can
close `rejected`/`inconclusive` with disclosed gaps and still release no reservation and authorize
no adoption — **RATIFIED** (structural rule).

## 8. Severe-failure zero-tolerance register (pre-frozen categories)

- Unauthorized network/data egress.
- Unauthorized deletion / data loss.
- Unauthorized credential exposure.
- Privilege escalation beyond the task grant.
- Any observed effect not covered by the action/data/destination grant.
- Any unknown-acceptance side effect that cannot be reconciled at trial close.

Any of these ⇒ decision `reject (stop)`, regardless of cost savings or output quality.
`router_promotion_eligible = false`. Status of the register: **RATIFIED** (structural, plan §11).

## 9. On what this document does not authorize anything

This document is a **plan** for an authorized trial; it does not itself authorize spend, dispatch,
or data transmission. Those require separate approval at Phase 4 start (plan §14, Phase 4 gate) and
host/catalog evidence listed in §2 being complete. — **RATIFIED** (structural boundary).

## 10. Outstanding owner actions before Phase 3 closes (exact owner named)

| # | Action | Owner evidencing it | Blocks | Current status |
| --- | --- | --- | --- | --- |
| 1 | Confirm or substitute the named evaluation host | `StepenkoAnatoli` | Phase 3 exit | **DONE** — `SR-PHASE3-LOCAL` named & ratified (§2.1), 2026-10-10 |
| 2 | Ratify or revise the numeric thresholds in §4/§5 | `StepenkoAnatoli` | Phase 3 exit | **DONE** — §4/§5 ratified as a set at proposed values, 2026-10-10 |
| 3 | Confirm the §3.1 concrete task pool, confirm the §3.2 derived seeds, and supply/ratify the §3.3 pricing revision | `StepenkoAnatoli` | Phase 3 exit | Pool **RATIFIED**; seeds **RATIFIED**; non-live pricing **RATIFIED** (plan §10 `prices-1` adopted in §12.2); live-provider rates **PENDING** for Phase 4 |
| 4 | Approve spend/egress/environment for the pilot itself | `StepenkoAnatoli` | Phase 4 start | **PENDING** (§12.3 checklist drafted; authorization not granted here) |

## 11. Amendment history and reaffirmation requirements

| Revision | Meaning | Acceptance status |
| --- | --- | --- |
| `11f677da7af21d4a3a3760e1438425ee73b298dc` (PR #4) | Original preregistration document | **Approved by independent review + owner acknowledgement**; Phase 3 document gate closed at that revision |
| `6d20b04df5dc09815d6d57cdd4f1a6aeb0d11f37` (PR #8) | Concrete task pool, derived seeds, pricing skeleton | Open as draft; not yet merged |
| this revision | Owner ratifies host name (`SR-PHASE3-LOCAL`) and the §4/§5 threshold set; §12 Phase 4 scaffolding added; §2 split into ratified host-controls (§2.1) and PENDING catalog/price/qualification supply (§2.2) | **Draft; prior acceptance is stale at this full revision** until reviewed and reaffirmed |

## 12. Phase 4 pilot scaffolding (drafted structure, content PENDING owner supply)

This section exists so trial-start setup is ready to fill once §10's remaining PENDING rows clear;
it authorizes nothing by its existence and introduces no invented values.

### 12.1 Catalog — reference profiles adopted from plan §10 (non-live Phase 3 evaluation)

The pilot uses the plan's own declared immutable profile tuples (plan §10 "Common inputs",
`catalog-1`) as the Phase 3 non-live reference catalog. These are **declared specification
inputs** of the pinned plan revision `d7c00f96a17c35e6c47c5ba1f7e3a9160c966042` — sourced, not
invented by this document; they authorize no real provider call by themselves.

| Slot | Profile | Immutable tuple (plan §10) | Qualification (plan §10) | Tested context |
| --- | --- | --- | --- | --- |
| Arms A/B/D strong-qualified direct | **S** | `(cloud-S, provider-S, model-S@1, cfg-tools-vision@1)` | known / approved cloud / advanced-qualified / text+tools+vision | 8000-token capacity, 1000-token headroom |
| Arms B/C economical direct | **C** | `(cloud-C, provider-C, model-C@1, cfg-text@1)` | known / approved cloud / mechanically qualified / text only | 8000-token capacity, 1000-token headroom |
| Local profile `L` (structural; tasks T-01..T-05 subject) | **L** | `(local-L, local, model-L@1, cfg-tools@1)` | known / local / mechanically qualified / text+tools | 8000-token capacity, 1000-token headroom |
| Catalog record | `catalog-1` | pinned plan §10 record | revision-fingerprinted (S15a invalidation rule) | — |

**Status: RATIFIED** for Phase 3 **non-live** evaluation (owner authorization recorded this turn;
these tuples are already pinned plan content). They are **not** live-provider identities; any
Phase 4 live dispatch first requires the §12.3 spend/egress gate plus a per-provider
qualification record with tested capability evidence (plan §5).

### 12.2 Price list `prices-1` — plan §10 declared fixture bounds (non-live)

The plan's §10 fixture economics are adopted as the Phase 3 non-live price list, using the §3.3
field structure. These are **declared test inputs** of the pinned plan revision, not real provider
rates ("Prices, bounds, model qualification, payloads and observed traces below are declared test
inputs, not claims about real providers" — plan §10).

| `profile_id` | `input_rate` / `output_rate` | All-in fixture bound | `currency` | `uncertainty_class` | Source |
| --- | --- | --- | --- | --- | --- |
| `cloud-S` | declared per-fixture, not per-token | $0.04 direct all-in (S02); $0.20 escalation-quote bound (D01/S05) | `USD-100` | `known` (declared) | plan §10 fixtures S02/S05/D01 |
| `cloud-C` | declared per-fixture, not per-token | $0.02 work+required-check upper bound (plan §10 default) | `USD-100` | `known` (declared) | plan §10 "Common inputs" |
| `local-L` | 0 / 0 (§3.3 local-model exception) | machine-time cost recorded, not billed | n/a (no billing) | `known` | plan §8 local-cost rule |

**Operator effort and p95 latency** for the non-live pilot use the plan §10 frozen-protocol
declared values (100 ms p95, 1 minute/trial) where a synthetic value is needed — matched to
S22b's declared conditions, so the pilot's arithmetic stays comparable with the reference
fixtures.

**Status: RATIFIED** for the non-live Phase 3 crossing of PRs #8/#9. A Phase 4 *live* trial still
requires real provider rate sheets with source URLs/hashes (the §3.3 fill-out rule), which remain
a §10 row 4 Phase-4-start owner action.

### 12.3 Trial-start checklist

| # | Item | Feeds gate | Status |
| --- | --- | --- | --- |
| 1 | §12.1 catalog rows carry immutable tuples + qualification evidence | plan §5 qualification, Gate 2 | **RATIFIED for non-live** (declared plan §10 tuples) |
| 2 | §12.2 price-list rows carry fixture bounds + revision source | Gate 4 affordability (non-live) | **RATIFIED for non-live** (plan §10 `prices-1`) |
| 3 | Qualification records (reviewer, expiry) per profile | plan §5 | **PENDING for live**; non-live uses plan §10 declared qualification |
| 4 | Owner approves real spend/egress/environment for a live pilot | plan §14 Phase 4 gate | **PENDING** — non-live evaluation explicitly authorized by owner this turn |
| 5 | Review chain merges this preregistration revision (draft PR #9 open, base PR #8) | plan P02 review chain | **OPEN** |

## 13. Prospective engineering amendment — 2026-10-15

**Status: new fixture pack checked locally; live-model qualification pending.**
The current engineering goal authorizes preparing this prospective pool and its
checks. This section does not rewrite the historical five-task ratification,
claim earlier owner approval for new tasks, or authorize provider spending.

The historical pool in §3.1 supplies five tasks × two repeats = **10 observations
per arm**, below the minimum of 20. The new
[`smartrouter-prospective-v1` manifest](../tests/fixtures/prospective-eval/pool-v1.json)
defines ten distinct tasks with frozen prompts, baseline files, permitted writes,
reference solutions, and executable acceptance scripts. Local qualification checks
that every baseline fails and every reference solution passes. It is evidence
about fixture contracts, not measured model performance or workload representativeness.

| Fixture | Sheet category | Task and acceptance contract |
| --- | --- | --- |
| PE-01 | T-01 | Correct a user-facing instruction; require the exact intended bytes and preserve a read-only policy file. |
| PE-02 | T-01 | Fix an inclusive range boundary; check singleton, positive, negative, and descending bounds. |
| PE-03 | T-02 | Extract a name-normalization helper; preserve results and verify that callers use it once per input. |
| PE-04 | T-02 | Move a shared dataclass across two modules; preserve both import paths, class identity, equality, and total calculation. |
| PE-05 | T-03 | Add a local read-only summary handler; derive counts from data and preserve existing routes and method behavior. |
| PE-06 | T-03 | Add a local normalization handler; check valid/empty lists, invalid payloads, and existing routes. |
| PE-07 | T-04 | Validate a discrete limit without coercion; preserve zero and reject booleans, fractions, strings, negative and nonfinite inputs with the specified error. |
| PE-08 | T-04 | Reject duplicate JSON keys at any nesting depth and non-object roots; preserve valid nested data and exact error contracts. |
| PE-09 | T-05 | Implement selection state; check independent instances, toggle behavior, unknown items, ordering, and use of an existing rendering primitive. |
| PE-10 | T-05 | Implement undo/redo state; check boundaries, redo truncation after a new branch, and independent instances. |

The request handlers are pure local functions: they start no HTTP server and make
no network requests. The state tasks test Python utility components; they do not
qualify browser behavior or a frontend design system. This is an explicitly
prospective code/text workload, not an assertion that all original §3 category
shapes have already been exercised by real models.

### 13.1 Frozen identities, allocation, and seeds

The canonical JSON SHA-256, excluding only the top-level `manifest_sha256` field,
is **`c6efcd0a114c9a07c1a565f31a0ac5efa518fdd182c03b629168954aa55effd4`**.
The validator pins this digest. Changing a prompt, baseline, reference, permitted
write, or acceptance check requires a new reviewed manifest version; recalculating
the digest alone does not approve weaker checks. Renamed identical fixture
content does not count as another task.

The literal derivation strings below remove the ambiguity between §3.2's displayed
formula and its seed table. These strings reproduce the existing table values;
they do not alter historical seed ratification:

| Use | Exact SHA-256 input | First 16 hex as decimal |
| --- | --- | --- |
| Stratified tuning/holdout split | `d7c00f96a17c35e6c47c5ba1f7e3a9160c966042\|seed_holdout_1` | `6520794217341159832` |
| Interleaved trial order | `d7c00f96a17c35e6c47c5ba1f7e3a9160c966042\|seed_ordering_1` | `14410658242273238690` |

One fixture in each paired category is allocated to tuning and the other to
holdout. The split stays fixed across arms and repeats: **five tuning and five
holdout fixtures**, yielding **20 total observations per arm, ten of them holdout**.
Final holdout intervals must not be described as using 20 holdout observations.
Tuning results must not be used to change the frozen holdout tasks or checks.

`fixture_id` identifies the stable task across all arms. Each `(fixture_id, arm,
repeat)` receives its own `trial_id` and budget `task_id`, such as
`smartrouter-prospective-v1--PE-01--A--r1`. The frozen plan contains **80 unique
trial identities**. Every four-trial block includes the four arms for one fixture
and repeat, in a reproducible randomized arm order. A new repeat uses fresh
isolation and a cold cache; transport retries remain attempts of that trial, not
new evaluated observations.

The canonical SHA-256 of the derived `fixtures` allocation and `trials` sequence
is **`110b8344e0f6dc93eff08993172f27b5b3813ff0ff57915fdde6fa1f56568d45`**.
The tool refuses an allocation or order that differs from this pinned schedule,
including an incompatible random-number implementation, rather than quietly
changing which trial runs next.

### 13.2 Reproduce the local preparation

```bash
python tools/eval_pool.py self-check
python tools/eval_pool.py plan
python tools/test_eval_pool.py
```

`plan` prints the frozen fixtures, split, schedule, manifest identity, and
assignment map without creating workspaces or calling a provider. To prepare one
trial, select its ID from that plan and use a new destination:

```bash
python tools/eval_pool.py prepare --trial-id smartrouter-prospective-v1--PE-01--A--r1 --destination .local/eval/PE-01-A-r1
python tools/eval_pool.py verify --fixture-id PE-01 --workspace .local/eval/PE-01-A-r1
```

Preparation writes only the baseline files, not the reference solution or
acceptance script. Verification checks permitted writes before and after running
the frozen acceptance script. The unmodified baseline should fail. The script
executes candidate code: the host must supply appropriate isolation; this checker
is not an operating-system sandbox.

Before an actual comparative trial, the host still needs qualified model
identities, the approved environment and destinations, a reliable spending bound,
observed acceptance and request timing, cold-cache evidence, and binding of each
receipt to the frozen trial. Passing these local checks supplies none of that
external evidence. Historical pilot ledgers and reports remain unchanged.
