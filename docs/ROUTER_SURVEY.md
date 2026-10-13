# Pinned routing-repository survey

Reviewed 2026-10-07 through public repository metadata, READMEs, complete recursive trees and selected source/test/license files. No clones, installs, upstream execution, provider calls or paid inference. Counts are approximate tree/path-discovered test counts, **not tests run**. Benchmark and savings figures in upstream READMEs remain publisher claims. Source behavior observations are not deployment/exploitation claims.

This is a source-review appendix, not a live ledger-backed evidence corpus. Revalidate blocking facts through the applicable consumer research workflow before adoption. No upstream code/assets are vendored; this plan-only PR delivers no usable skills. Proposed future skills must be independently authored or use material only with suitable permission. Links pin the surveyed commit, not mutable main.

## 1. yenanjing/awesome-model-routing

Revision: [`de2d17e41f8031b6f9c41495cd339c02235b657a`](https://github.com/yenanjing/awesome-model-routing/tree/de2d17e41f8031b6f9c41495cd339c02235b657a). Approximately 5 files; no discovered tests.

[README](https://github.com/yenanjing/awesome-model-routing/blob/de2d17e41f8031b6f9c41495cd339c02235b657a/README.md) is a discovery list, not a selector or vetted evaluation. It includes unrelated NAT, vehicle routing, political and UI material, so inclusion cannot endorse relevance, safety or licenses. Reviewed license is CC0; linked projects retain their own terms.

**Use:** leads for separate primary-source checks. **Avoid:** claiming a curated evidence base or copying recommendations without inspecting each project. No runtime dependency.

## 2. BlockRunAI/ClawRouter

Revision: [`b758e036bbd1290c0997ad14c9812a106ef8d72b`](https://github.com/BlockRunAI/ClawRouter/tree/b758e036bbd1290c0997ad14c9812a106ef8d72b). Approximately 364 files / 146 discovered test paths. Reviewed standard MIT license; copying still requires notices and exact provenance.

[retry.ts](https://github.com/BlockRunAI/ClawRouter/blob/b758e036bbd1290c0997ad14c9812a106ef8d72b/src/retry.ts) retries 429/502/503/504 and caught network errors with exponential sleeps; numeric Retry-After is handled, although documentation mentions a date form. This helper alone does not establish replay/idempotency/cancellation safety. Do not extrapolate helper behavior to every deployment.

[proxy.spend-policy.test.ts](https://github.com/BlockRunAI/ClawRouter/blob/b758e036bbd1290c0997ad14c9812a106ef8d72b/src/proxy.spend-policy.test.ts) drives the actual proxy against a local 402 server and asserts blocked payees cause no signature/payment attachment. This is materially stronger static test evidence than a recreated score function, but was **not run here**.

**Use:** actual-callsite no-side-effect tests, transparent local decisions/explanations. **Avoid:** generic transport retries as permission to replay, x402 wallets/payments/provider gateway in skills V1, marketing savings as measured SmartRouter outcomes.

## 3. BJFinancial/Smart-router

Revision: [`65efa68d97004021cfdc3571d6974315a61d8865`](https://github.com/BJFinancial/Smart-router/tree/65efa68d97004021cfdc3571d6974315a61d8865). Approximately 30 files / 2 discovered tests.

[engine.py](https://github.com/BJFinancial/Smart-router/blob/65efa68d97004021cfdc3571d6974315a61d8865/src/smart_router/router/engine.py) demonstrates small regex/rule routing. Confidence values such as .8/.5 are fixed heuristics, not calibrated success probabilities. The inspected optimizer reduces summaries to a few topics/characters; such transformations do not establish semantic preservation or exact token-budget compliance. Simple priority/default tests do not prove verified task quality.

[LICENSE](https://github.com/BJFinancial/Smart-router/blob/65efa68d97004021cfdc3571d6974315a61d8865/LICENSE) is labeled MIT but the inspected custom text is not the standard MIT permission grant. Treat redistribution permission as unresolved; do not assume SPDX/README labels cure it.

**Use:** anatomy of a minimal transparent rule baseline, independently reauthored. **Avoid:** arbitrary confidence thresholds, lossy code summaries and copying under an assumed MIT grant.

## 4. NadirRouter/NadirClaw

Revision: [`fa6ca992d32d3639d2a3be1fcfa8ed8b2b7208c1`](https://github.com/NadirRouter/NadirClaw/tree/fa6ca992d32d3639d2a3be1fcfa8ed8b2b7208c1). Approximately 149 files / 50 discovered test paths.

[cascade.py](https://github.com/NadirRouter/NadirClaw/blob/fa6ca992d32d3639d2a3be1fcfa8ed8b2b7208c1/nadirclaw/cascade.py) accepts on verifier error, has a cheap-only kill-switch acceptance path after repeated failures, and force-cheap avoids verification. Fallback is not verified within this component. These are unsuitable fail-open patterns for a verification-first SmartRouter; no assertion is made that all callers lack additional controls. Pro-trained .80 calibration claims do not qualify the OSS heuristic for this workload.

[test_code_safety.py](https://github.com/NadirRouter/NadirClaw/blob/fa6ca992d32d3639d2a3be1fcfa8ed8b2b7208c1/tests/test_code_safety.py) checks unfenced Python indentation via parsing and fenced-code byte preservation while allowing prose normalization. Static tests inform exact-content requirements; not executed here.

[LICENSE](https://github.com/NadirRouter/NadirClaw/blob/fa6ca992d32d3639d2a3be1fcfa8ed8b2b7208c1/LICENSE) is PolyForm Noncommercial: commercial reuse needs separate permission, not an MIT assumption.

**Use:** exact code-preservation test ideas and explicit failure classification. **Avoid:** accepting verifier errors, cheap-only circuit-breaker success, transplanted calibration, unlicensed commercial copying.

## 5. xorbitsai/xrouter-llm

Revision: [`a0b29f9199e1601af5c5a967fa607530ad539ad9`](https://github.com/xorbitsai/xrouter-llm/tree/a0b29f9199e1601af5c5a967fa607530ad539ad9). Approximately 107 files / 17 discovered tests.

[test_policy.py](https://github.com/xorbitsai/xrouter-llm/blob/a0b29f9199e1601af5c5a967fa607530ad539ad9/tests/test_policy.py) inspects predicted-quality/cost selection, fusion and fallback. A fallback may pick a model below the requested quality threshold within a margin of the best (e.g. .56/.58 with .70 floor). Fusion uses an any-success independence-style expression; it is not measured semantic correctness or engine verification. A hard task verification floor cannot become a soft margin in SmartRouter.

[LICENSE](https://github.com/xorbitsai/xrouter-llm/blob/a0b29f9199e1601af5c5a967fa607530ad539ad9/LICENSE) is Xagent source-available with restrictions including competing/hosted use and branding/single-tenant conditions. Review exact terms for intended use; not interchangeable with permissive open-source grants.

**Use:** separate predicted task quality from capability and cost, conceptually. **Avoid:** below-floor fallback, unverified fusion assumptions, adopting predictor/engine infrastructure or code without suitable authorization.

## 6. Izzetee/PiPiMink

Revision: [`63f820cebb4569c028326ec1e25333020b09854b`](https://github.com/Izzetee/PiPiMink/tree/63f820cebb4569c028326ec1e25333020b09854b). Approximately 213 files / 38 discovered tests. Reviewed Apache-2.0; retain applicable license/NOTICE and separately review branding rights.

[decision_cache.go](https://github.com/Izzetee/PiPiMink/blob/63f820cebb4569c028326ec1e25333020b09854b/internal/llm/decision_cache.go) has bounded LRU/TTL defaults (1000 entries/2 minutes), locks/statistics and SHA256 keys including sorted model properties. Catalog-aware caching is useful, but whitespace-normalized prompts can conflate code indentation and the key lacks relevant policy/permission/verifier/price revisions. Hashing does not automatically make sensitive inputs safe.

Inspected selector behavior depends on meta-LLM tags and logs prompt snippets/raw replies; generated membership does not alone establish enabled, permitted and qualified models. A paid classifier and prompt logging are not defaults for skills V1.

**Use:** bounded caches with catalog/version awareness, independently specified exact-input invalidation. **Avoid:** whitespace conflation, sensitive logs, meta-LLM recommendations as permission or qualification authority.

## 7. tumf/kani

Revision: [`d823cc4c9dd9a00aaafd814c1758b30c67d963c7`](https://github.com/tumf/kani/tree/d823cc4c9dd9a00aaafd814c1758b30c67d963c7). Approximately 203 files / 19 discovered tests.

[test_capability_routing.py](https://github.com/tumf/kani/blob/d823cc4c9dd9a00aaafd814c1758b30c67d963c7/tests/test_capability_routing.py) distinguishes active tool requirements from decorative schemas/old completed history. It covers forced choice, tools, vision, JSON and multiple capabilities; stripping decorative fields works on a copy. Required tools must never be silently stripped to fit a model.

Inspected routing has explicit capability/input-limit errors, but classifier errors can default MEDIUM; all-cooldown paths may disregard cooldown; escalation metadata can diverge from selected candidate. Internal RoutingDecision includes resolved credential material; without serializer proof, this is **not a finding of a public leak**. SmartRouter receipts simply prohibit credentials.

No LICENSE was found in the complete tree despite README MIT wording; inspected project metadata did not establish a license grant. Redistribution remains blocked pending permission.

**Use:** active-capability detection and typed no-candidate errors. **Avoid:** unknown/error defaults as qualification, ignoring all-unavailable vetoes, public receipts carrying credentials, copying on README label alone.

## 8. Cohorte-ai/context-router

Revision: [`5e3cf74f6b0b600316b17dd0b429844b4e1a11d9`](https://github.com/Cohorte-ai/context-router/tree/5e3cf74f6b0b600316b17dd0b429844b4e1a11d9). Approximately 81 files / 16 discovered tests. Reviewed Apache-2.0.

[permissions.py](https://github.com/Cohorte-ai/context-router/blob/5e3cf74f6b0b600316b17dd0b429844b4e1a11d9/src/theaios/context_router/permissions.py) defaults allow for no matching rule; wildcard/exact rules merge with deny wins and restrictive defaults, rather than the documented exact-only precedence. [test_permissions.py](https://github.com/Cohorte-ai/context-router/blob/5e3cf74f6b0b600316b17dd0b429844b4e1a11d9/tests/test_permissions.py) includes a misleading default-deny-named test that actually asserts allow, and empty-path chunks can pass denied-path filtering.

Inspected context pipeline fetches/caches sources before path denial; optional remote embeddings occur later. Source exceptions can be silently skipped; cache source/query keys lack some authorization metadata. These warrant design review, **not an asserted exploit**. SmartRouter must authorize before external fetching/embedding, fail closed for unknown identities/paths and make missing evidence explicit.

**Use:** provenance-rich bounded context and minimum necessary snippets. **Avoid:** default-allow identity/path, post-fetch permission checks, silent missing-evidence acceptance or building a new context engine now.

## 9. cylonmolting-creator/agora-oracle

Revision: [`7224ddff5a9d5dd03974429d6a34e1df292b2161`](https://github.com/cylonmolting-creator/agora-oracle/tree/7224ddff5a9d5dd03974429d6a34e1df292b2161). Approximately 114 files / 11 discovered test paths.

[smart-route.js](https://github.com/cylonmolting-creator/agora-oracle/blob/7224ddff5a9d5dd03974429d6a34e1df292b2161/src/api/smart-route.js) combines rates/latency/confidence; rate confidence is not task-quality qualification. Estimated cost uses a price value without sufficient token/input-output unit weighting. Empty available-provider lists can disable filtering and deduplication is provider-oriented, not necessarily model-oriented.

[smart-route.test.js](https://github.com/cylonmolting-creator/agora-oracle/blob/7224ddff5a9d5dd03974429d6a34e1df292b2161/tests/smart-route.test.js) recreates/mocks sorting/scoring rather than proving production selection behavior; existence of this test is not integration proof. No tests were executed.

No LICENSE in the inspected complete tree despite package MIT claim: do not infer redistribution permission.

**Use:** timestamp/unit/source discipline for rate facts. **Avoid:** confidence conflation, empty-list bypass, recreated logic as callsite proof, aggregator/network infrastructure in skills V1.

## 10. beettlle/pi-smart-router

Revision: [`c3395c82c89d2e13c97552347a453c7ec122e33d`](https://github.com/beettlle/pi-smart-router/tree/c3395c82c89d2e13c97552347a453c7ec122e33d). Approximately 1892 files / 182 discovered tests.

[expected-cost.ts](https://github.com/beettlle/pi-smart-router/blob/c3395c82c89d2e13c97552347a453c7ec122e33d/src/domain/routing/expected-cost.ts#L534-L536) calculates bounded-success-weighted direct/escalation cost and assumes frontier success in that model. Before reuse define whether escalation includes the failed first attempt's sunk cost; actual SmartRouter ledger sums every billed attempt and keeps estimates separate. Risk penalties and virtual cache/quota credits are not observed cash savings.

[session-pinner.ts](https://github.com/beettlle/pi-smart-router/blob/c3395c82c89d2e13c97552347a453c7ec122e33d/src/domain/pinning/session-pinner.ts) illustrates stickiness broken by context overflow/compaction, eligible overrides and qualified escalation/economics. Force-model checks reject out-of-fleet/unhealthy choices with reason; no silent provider remap. Context headroom constants are implementation choices, not universal qualification.

[assert-release-gates.test.ts](https://github.com/beettlle/pi-smart-router/blob/c3395c82c89d2e13c97552347a453c7ec122e33d/tests/eval/assert-release-gates.test.ts) inspects fixture/config quality retention/capability/overrouting/pin gates. Static harness thresholds are not reproduced live task success; not executed here.

No LICENSE found in inspected tree despite package MIT declaration. Permission must be clarified before copying.

**Use:** explicit pin break reasons, context headroom, estimates separate from accounting, calibration sample/freshness discipline and declared release gates. **Avoid:** frontier-success certainty, borrowed coefficients, virtual credits as cash, oversized architecture for a skill preview.

## 11. BlockRunAI/router-core

Revision: [`a5452c544d8e5e12b87460eab18428fbe60f3ffa`](https://github.com/BlockRunAI/router-core/tree/a5452c544d8e5e12b87460eab18428fbe60f3ffa). Approximately 35 files / 6 discovered tests. Reviewed standard MIT.

[selector.ts](https://github.com/BlockRunAI/router-core/blob/a5452c544d8e5e12b87460eab18428fbe60f3ffa/selector.ts) includes decision-only selection, cost estimates, a fixed flagship savings anchor, x402 margin/minimum floor and flat-price override. Missing prices default zero in selection. Several tool/vision/exclusion/fallback filters restore the original list if filtering empties it; unknown capacities can pass. Such estimates are not actual per-success savings.

[portfolio.ts](https://github.com/BlockRunAI/router-core/blob/a5452c544d8e5e12b87460eab18428fbe60f3ffa/portfolio.ts#L946-L958) treats unknown model eligibility permissively; structured support is tied to tools there. [Fallback construction](https://github.com/BlockRunAI/router-core/blob/a5452c544d8e5e12b87460eab18428fbe60f3ffa/portfolio.ts#L1045-L1049) can restore original chains/base when eligible candidates disappear. [unavailable-models.test.ts](https://github.com/BlockRunAI/router-core/blob/a5452c544d8e5e12b87460eab18428fbe60f3ffa/unavailable-models.test.ts) explicitly preserves all-dead tiers, despite tests for individual removal. Those paths cannot be imported while advertising fail-closed constraint-first routing.

[README scorecard](https://github.com/BlockRunAI/router-core/blob/a5452c544d8e5e12b87460eab18428fbe60f3ffa/README.md) candidly labels release eligibility false and uncertainty/quality/latency tradeoffs; these remain publisher results, not replicated evidence.

**Use:** separate decision-only policy from host effects, pinned revisions/parity/snapshot tests and honest scorecards as later design references. **Avoid:** direct dependency for skills V1, fail-open restoration, unknown-price=free, flagship anchors as real savings. Correct/test veto paths before considering future integration.

## 12. Magma-Devs/smart-router

Revision: [`a2d90c470170acec1a468d066a685b9d14b83a60`](https://github.com/Magma-Devs/smart-router/tree/a2d90c470170acec1a468d066a685b9d14b83a60). Approximately 904 files / 462 discovered tests. This is blockchain RPC routing, not an LLM skill router. Inspected license combines PolyForm Noncommercial and Enterprise terms; commercial reuse requires appropriate authorization.

[attempt_budget_callsite_test.go](https://github.com/Magma-Devs/smart-router/blob/a2d90c470170acec1a468d066a685b9d14b83a60/protocol/rpcsmartrouter/attempt_budget_callsite_test.go) exercises a real dispatcher with an upstream slower than an internal window but inside the total budget, asserting the caller passes the correct budget. A direct callee test could miss that regression. [eligibility.go](https://github.com/Magma-Devs/smart-router/blob/a2d90c470170acec1a468d066a685b9d14b83a60/protocol/relaypolicy/eligibility.go) is a wrapper around common eligibility, not proof of an LLM semantic selector.

**Use:** callsite budget/deadline tests with controlled clocks and adverse timing. **Avoid:** blockchain relay hedging/quorum/transaction fanout as LLM replay policy, irrelevant infrastructure, noncommercial code copying for commercial use.

## 13. ginsonko/newapi-smart-router

Revision: [`034daabaac5038bfc5f0a5c54a30df59baaffb3a`](https://github.com/ginsonko/newapi-smart-router/tree/034daabaac5038bfc5f0a5c54a30df59baaffb3a). Approximately 814 files / 38 discovered tests. Reviewed AGPL-3.0: copying/integration needs network/copyleft compatibility and notice review, **not a categorical prohibition**. No code/schema copied here.

[Retry design](https://github.com/ginsonko/newapi-smart-router/blob/034daabaac5038bfc5f0a5c54a30df59baaffb3a/parts/algorithms/retry/README.md) separates transport/protocol/business contracts, committed semantic streams, acceptance ambiguity, replay class, deadlines and attempts. [Outcome golden vectors](https://github.com/ginsonko/newapi-smart-router/blob/034daabaac5038bfc5f0a5c54a30df59baaffb3a/parts/conformance/golden-vectors/outcome-v1.json) cover valid tool calls, pseudo-200 errors, committed streams, unknown video acceptance, capacity 429 and side-effecting unknown dispatch. Static vectors are not live success claims.

[planner.go](https://github.com/ginsonko/newapi-smart-router/blob/034daabaac5038bfc5f0a5c54a30df59baaffb3a/core/smartrouter/planner.go) exposes no-price/no-candidate/attempt-budget outcomes, capability/replay fingerprints and snapshot/commit rules. [cache_economy.go](https://github.com/ginsonko/newapi-smart-router/blob/034daabaac5038bfc5f0a5c54a30df59baaffb3a/core/smartrouter/cache_economy.go) scores only after eligibility with bounded snapshot/horizon/sample/confidence/drift guards; specific namespace/session warm evidence matters, not generic hit-rate optimism. Numeric defaults are not transferable SmartRouter tolerances.

[Route receipt schema](https://github.com/ginsonko/newapi-smart-router/blob/034daabaac5038bfc5f0a5c54a30df59baaffb3a/parts/spec/route-receipt.schema.json) describes versions/attempt/reservation/settlement/reconciliation/operator review. Borrow the conceptual need for a small secret-free receipt, not the gateway or whole schema.

**Use:** independently authored contract-specific verification/replay handling, conservative price/eligibility outcomes, immutable snapshots and accounting/recovery discipline. **Avoid:** heavyweight gateway/cache horizon framework, transplanted thresholds and AGPL source reuse without compatibility review.

## Consolidated recommendation

1. **Plan a later three-skill package with one authority**, not a router service. This PR delivers planning documents only; usable skills require separate authorization. The proposed policy prefers eligible direct work with no automatic paid classifier; review/eval-prep would be procedures, not additional selectors.
2. **Fail closed at every stage and fallback.** Unknown actor/path/required capability/pricing under strict caps and empty candidate sets are explicit blockers. Verify zero sends at real callsites in later hosts.
3. **Preserve task contracts and exact context.** Tool/refusal/media/structured outcomes are contract-specific; verifier failures do not accept. Cache keys include relevant authority/price/check revisions and exact meaningful content.
4. **Bound and account every attempt.** Capability escalation is not a price ladder. No replay after ambiguous effects/committed output; cancellation/restart reconcile first. Count router/review/sunk costs without double counting.
5. **Measure before growth.** Four fair arms, approved preregistration, actual cost per verified success, complete accounting, hard severe-failure stops and explicit promote/simplify/reject/inconclusive outcomes.
6. **Prefer original policy over copied implementations.** No runtime dependency now. MIT/Apache ideas do not establish correctness; noncommercial/source-available/no-grant/AGPL materials need appropriate permission/compatibility checks before any future copy. SmartRouter's chosen MIT grant covers only the newly authored planning documents listed in LICENSE, not upstream or historical content.
