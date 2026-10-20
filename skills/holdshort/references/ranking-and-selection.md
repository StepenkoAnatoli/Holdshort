# Ranking-and-selection companion (non-normative)

How a host turns Holdshort's ordered gates into a candidate ranking without
inventing qualification. Binding rules: the plan (§5) and spec-v2.md §§11–12.
Upstream behaviors are summarized from pinned revisions; nothing is vendored.

## 1. Decision-only selection, host-owned effects

Router-core (BlockRunAI/router-core @ `a5452c5`) is the structural model to
imitate: it classifies and ranks *locally*, with no inference call or network
access on the decision path, and returns a model plus ranked candidates plus
decision metadata — then the **host** walks the list on timeout/5xx, performs
recovery calls, and owns billing. A Holdshort route recommendation is the
same kind of object: a decision with reasons, not an execution. Consequences:

- Generating a recommendation may itself infer/transmit/spend and must be
  separately authorized and accounted (plan finding F5); displaying an
  already-computed recommendation is inference-free and needs no new call.
- The winner is chosen once per decision; re-walking the list after a failure
  is a new decision through all five gates with fresh evidence, not a pointer
  increment (plan §5: recheck before every send; changed/expired/unknown
  evidence invalidates the route).

## 2. Eligibility precedes ranking, absolutely

Filter first by Gates 1–4 (permissions/privacy, capabilities, verification
prerequisites, affordability); rank only survivors on Gate 5 economics. Direct
is preferred only after eligibility (plan finding F3). Surveyed mechanisms
worth imitating, independently authored:

- **Active-capability detection** (kani `test_capability_routing.py`, tumf/kani
  @ `d823cc4`): distinguish active tool requirements from decorative
  schemas and completed history; required tools must never be silently
  stripped to fit a model (spec §12 prohibition).
- **Minimal transparent baseline first** (BJFinancial/Smart-router @ `65efa68`
  `engine.py`): small explicit rules with stated heuristics beat an opaque
  classifier; fixed confidence constants (.8/.5-style) are *not* calibrated
  success probabilities and must never gate qualification.
- **Compare eligible alternatives only, all-in.** D01's arithmetic is the
  template: direct $0.20 vs worker $0.02 + review $0.03 = $0.05, overhead
  included, review never excluded to win the comparison. pi-smart-router's
  `expected-cost.ts (L534-L536)` computes success-weighted direct/escalation
  cost — before reuse, define whether escalation includes the failed first
  attempt's sunk cost; the Holdshort ledger sums every billed attempt and
  keeps estimates separate from accounting.

## 3. Fail-open restorations that must stay rejected

Several surveyed codebases restore rejected candidates "for availability".
Every one of these is a §12 empty-set-resurrection violation here:

| Upstream pattern | Why it stays rejected |
|---|---|
| router-core filters (`selector.ts`, `portfolio.ts`) restore the original list when filtering empties it; unknown capacities pass; all-dead tiers preserved | An empty eligible set is an explicit `blocked`, not a license to restore |
| Unknown model eligibility treated permissively (`portfolio.ts` L946–L958) | Unknown qualification is not suitability (plan §5) |
| xrouter-llm fallback below the quality floor within a "margin" (test_policy.py) | A hard verification floor never becomes a soft margin |
| agora-oracle empty provider list disabling filtering; rate confidence as quality (`smart-route.js`) | Empty lists disable nothing; rate facts are not task qualification |
| Price-missing defaults zero in selection (router-core `selector.ts`) | Unknown price is not free (plan finding F2); unknown/unbounded fees block a strict cap |

## 4. Estimates are not accounting

- Missing prices default to *unknown*, never zero; flagship-anchored "savings"
  and virtual cache/quota credits are not observed cash savings.
- Cost basis, price revision, and freshness limit are bound into the decision
  trace; a stale quote (B02a) or expired qualification (D02) invalidates the
  route even when the ranking is unchanged.
- Report completion/blocking, severe defects, uncertainty, latency and
  operator effort alongside cost (plan §1). A ranking that only minimizes token
  price is not a Gate-5 comparison.

Pinned sources: docs/ROUTER_SURVEY.md §§3, 5, 7, 9–11; plan §§1, 5 and
findings F2/F3; deep-dive reports for router-core (`a5452c5`) / ClawRouter
(`b758e03`).
