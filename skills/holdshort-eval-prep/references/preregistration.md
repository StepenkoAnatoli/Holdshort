# Preregistration and economic-comparison checklist

Companion reference for `holdshort-eval-prep`. Normative source: plan sections 11 and 10
(S21a/S21b/S22a-S22g) at merge `d7c00f96a17c35e6c47c5ba1f7e3a9160c966042`.

A preregistration is complete only when **every** item below has a numeric value, an explicit
protocol, or an explicitly named owner and evidence requirement. Blanks mean not ready.

## 1. Arms and fairness

- [ ] Four arms specified: strong qualified direct (A), economical qualified direct (B), simple fixed
      rule (C), Holdshort including all overhead (D).
- [ ] Same acceptance/privacy/effects rules for every arm.
- [ ] Weak baselines never exposed to production secrets or consequential writes.
- [ ] Kit workflow constant across arms.

## 2. Frozen revisions and pretrial controls

- [ ] Named already-existing evaluation host with evidence for identity, permissions, usage/billing,
      conservative bounds, all-call limits, test isolation, Stop/recovery and required checks.
- [ ] Pinned task/rubric/host/model/policy/catalog/prices revisions.
- [ ] Task categories, tuning/holdout split, cache conditions, ordering/randomization, repetitions
      frozen.
- [ ] Hidden checks and qualitative grading frozen.
- [ ] Failure of host qualification for any baseline is recorded, never silently remapped.

## 3. Metrics and thresholds (fill numeric values; blanks = not ready)

- [ ] Minimum sample size and task-coverage per arm (e.g. ≥20 observations/arm, all holdout task
      fixtures attempted).
- [ ] Mandatory acceptance quality floor per arm.
- [ ] Maximum acceptance loss vs strong direct (A) in percentage points, using interval's upper
      bound.
- [ ] Minimum cost-per-success reduction vs A, using interval's lower bound.
- [ ] Maximum p95 latency increase vs A, using interval's upper bound.
- [ ] Maximum operator-effort increase vs A, using interval's upper bound.
- [ ] C-vs-D equivalence margin for cost/latency/effort and acceptance difference required for a
      "favors simpler C" finding.
- [ ] Additional incremental benefit D must show over qualifying C (strict inequality; equality is
      insufficient) for narrow promotion eligibility.
- [ ] Confidence interval method and level for all the above.
- [ ] Rules for zero-baseline cost (relative percentages undefined over a $0 numerator; advertise an
      absolute comparison instead).
- [ ] Rules for zero accepted successes (ratio undefined; absence of a separate quality-floor
      violation makes the economic comparison inconclusive, not savings).

## 4. Severe-failure, accounting and drift rules

- [ ] Severe-failure stop rule (zero tolerance; observed unauthorized/unsafe effect rejects the trial
      regardless of other evidence, and reclassifies affected per-task outcomes even after the fact).
- [ ] Accounting completeness rule: known charges by attempt; unknown/bounded charges owned and kept
      reserved, never released on report closure; no savings claim when accounting is incomplete.
- [ ] Blocked/cancelled/spent-with-no-output attempts counted in numerator and spent, never
      discarded.
- [ ] Model/price/config drift rule: preregistered restart/exclusion; no retrospective threshold
      changes.
- [ ] Max attempts, max cost, max deadline per task; all counted against the arm's economics.

## 5. Before-trial dispositions

- [ ] Predicates frozen for reject / stop, inconclusive, simplify, promote (report-completion rule
      separate from promotion-eligibility rule).
- [ ] Explicit rule: report can close `rejected` or `inconclusive` with disclosed gaps, without
      releasing reservations or authorizing adoption.
- [ ] Adoption (of router or simpler policy) always requires separate authorization even after a
      clean promote.

## 6. Isolation, ownership and feedback-loop dimensions (v1.1)

What v1.1 reviewers verify must be freezable before the trial — otherwise the
evaluation cannot observe it:

- [ ] Host isolation capability frozen: worktree support, branch-naming convention
      (`sr/<task-id>/<slug>` per host-task-id), Brief-injection mechanism.
- [ ] Per-owner accounting frozen: which worker owns which brief, where ownership is
      recorded (Outcome Ledger + registry), and what counts as a silent transfer
      (any transfer without a fresh decision fails the arm).
- [ ] Feedback-loop budget frozen: at most one same-profile corrective dispatch per
      original task (plan R01/R02/R03); every verification/CI/review failure returns
      to the same owner; repair spend counts in the arm's all-in economics.
- [ ] Provenance evidence frozen: which artifacts (branch, diff file list, ledger
      entries) the trial will keep so `check_provenance`-style review is possible
      after the fact.
