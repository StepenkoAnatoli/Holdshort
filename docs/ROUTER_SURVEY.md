# Pinned routing-repository survey

Reviewed 2026-10-07 through public repository metadata, READMEs, complete recursive trees and selected source/test/license files. No clones, installs, upstream execution, provider calls or paid inference. Counts are approximate tree/path-discovered test counts, **not tests run**. Benchmark and savings figures in upstream READMEs remain publisher claims. Source behavior observations are not deployment/exploitation claims.

This is a source-review appendix, not a live ledger-backed evidence corpus. Revalidate blocking facts through the applicable consumer research workflow before adoption. No upstream code/assets are vendored; this plan-only PR delivers no usable skills. Proposed future skills must be independently authored or use material only with suitable permission. Links pin the surveyed commit, not mutable main.

Extended 2026-10-17 for entries 14–23 and the surfaced-candidates list at the end. Same static method: repository metadata, complete recursive trees, and selected source/docs/license files fetched at each pinned revision. No clones into this repository, no installs, no upstream execution, no provider calls. Counts are tree-discovered file and test-path counts, not tests run. Names, stars, licenses and push dates in the surfaced-candidates list are GitHub API metadata for that date and were not code-reviewed.

Counting rule used for the entries added 2026-10-17: "test-discovered paths" means tracked paths under a directory named `test`, `tests`, `spec`, `specs` or `__tests__`, plus files named `test_*.py`. Language-native test files that do not sit in such a directory (Go `_test.go`, JS/TS `*.test.*` and `*.spec.*`) are **excluded**, so a Go or JS/TS repository's real test-file count can be much larger than the figure given; semantic-router's entry names its Go figure separately.

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

## 14. musistudio/claude-code-router

Revision: [`057abaa1f95519ab8faf999e1ccef2b80ccdeb9e`](https://github.com/musistudio/claude-code-router/tree/057abaa1f95519ab8faf999e1ccef2b80ccdeb9e), 2026-10-10. Approximately 863 tree-discovered files; tests are organised per gateway concern under `packages/*/test/` (tool-id fidelity, stream disconnect, virtual models, cache usage, non-stream reasoning). Reviewed MIT: reuse is permitted with notice; no code copied here.

[policy-engine.ts](https://github.com/musistudio/claude-code-router/blob/057abaa1f95519ab8faf999e1ccef2b80ccdeb9e/packages/core/src/routing/policy-engine.ts) is a 24-line first-match chain: `RoutePolicyEngine.evaluate` walks the registered `RoutePolicy` objects in order, treats a falsy `decision` as a decline and continues, returns the first `{decision, policyId}` so the winning rule is identifiable, and returns `undefined` when no policy fires — there is no implicit default. [failure-classifier.ts](https://github.com/musistudio/claude-code-router/blob/057abaa1f95519ab8faf999e1ccef2b80ccdeb9e/packages/core/src/routing/failure-classifier.ts) classifies a status code into `"client" | "rate-limit" | "retryable" | "server"` and derives `shouldFallback` from the configured `RouterFallbackMode` (`"model-chain"`), i.e. fallback is a function of (failure class, mode), not of the prompt.

Neither file establishes replay or side-effect safety for a model chain: a status/mode classifier cannot tell whether the request already had effects.

**Use:** first-match policy chains that name the rule that fired, an explicit no-match outcome instead of a silent default, failure classification kept separate from fallback mode, and integration tests named after concrete wire concerns. **Avoid:** treating a model chain as a safety net without separate proof that ambiguous effects are not replayed.

## 15. decolua/9router

Revision: [`87a74e1bda3677193c6f71a7e2100c90311f0689`](https://github.com/decolua/9router/tree/87a74e1bda3677193c6f71a7e2100c90311f0689), 2026-10-15. Approximately 1,797 tree-discovered files; 403 test-discovered paths; JavaScript; MIT.

[smart-routing.md](https://github.com/decolua/9router/blob/87a74e1bda3677193c6f71a7e2100c90311f0689/gitbook/content/en/features/smart-routing.md) specifies a 3-tier fallback (subscription → cheap → free) whose stated goal is to "never stop coding due to quota limits or rate limiting" — availability, not task fit. [accountFallback.js](https://github.com/decolua/9router/blob/87a74e1bda3677193c6f71a7e2100c90311f0689/open-sse/services/accountFallback.js) computes quota cooldowns as `BACKOFF_CONFIG.base * 2^level` clamped by `BACKOFF_CONFIG.max`, and consults an imported `ERROR_RULES` table to decide whether an error switches accounts, and is documented to return `{shouldFallback, cooldownMs, newBackoffLevel?}` so the backoff level travels with the decision.

Whether the tier walk terminates in a usable provider is a runtime claim, not something these files establish; neither was executed here.

**Use:** bounded exponential cooldown with an explicit maximum, and a per-error rule table as a readable availability policy with the backoff level carried in the decision. **Avoid:** availability-driven tiering as a substitute for eligibility and cost caps, and reading "never stop coding" fallbacks as side-effect safe.

## 16. NVIDIA-NeMo/Switchyard

Revision: [`6f4e7749083a86484a0140078a42d487aed7259e`](https://github.com/NVIDIA-NeMo/Switchyard/tree/6f4e7749083a86484a0140078a42d487aed7259e), 2026-10-16. Approximately 719 tree-discovered files; 92 test-discovered paths; Rust; Apache-2.0.

[escalation_router_routing.md](https://github.com/NVIDIA-NeMo/Switchyard/blob/6f4e7749083a86484a0140078a42d487aed7259e/docs/routing_algorithms/escalation_router_routing.md) describes a weak-model-first strategy: an LLM judge reads how the run is going and latches the session to a stronger model on sustained trouble (repeated errors, loops, drift), with an optional de-escalation policy — a mid-run judgement, unlike classifier routing that predicts difficulty before running. [advisor_gate/budget.rs](https://github.com/NVIDIA-NeMo/Switchyard/blob/6f4e7749083a86484a0140078a42d487aed7259e/crates/libsy/src/algorithms/advisor_gate/budget.rs) keeps the gate's only shared mutable state behind one lock: a per-scope review budget behind a reserve/refund interface, `MAX_FAILED_CONSULTS: u32 = 3` (failures refund the budget, so the cap bounds a *down* advisor), and `MAX_TRACKED_SCOPES: usize = 1_024` bounding tracked budgets and stall keys, plus a per-conversation stall latch. By the file's own description the gate *stops consulting* after those failed consults: an advisor outage degrades toward ungated handling rather than blocking, because the cap bounds a down advisor instead of making it a veto.

**Use:** reserve/refund accounting for a verification budget, explicit bounds on tracked scopes, a stall latch to stop re-consulting a stuck conversation, and mid-run judge-driven escalation. **Avoid:** "stop consulting when the budget is exhausted" as acceptable behaviour under a strict cap — in a fail-closed design an exhausted review budget must block or downgrade explicitly rather than silently proceeding.

## 17. vllm-project/semantic-router

Revision: [`4416f76c1b991fb32d81b4b0fb3d321eae6782c3`](https://github.com/vllm-project/semantic-router/tree/4416f76c1b991fb32d81b4b0fb3d321eae6782c3), 2026-10-17. Approximately 11,613 tree-discovered files; 678 test-discovered paths by the counting rule in the header, plus roughly 2,300 further `_test.go` files that the rule excludes; Go; Apache-2.0. Classification-driven routing inside a large Kubernetes-oriented tree: 1,526 non-test Go files under `pkg/` match routing/classification/selection naming, and the API layer exposes decision tasks ([route_decision_tasks.go](https://github.com/vllm-project/semantic-router/blob/4416f76c1b991fb32d81b4b0fb3d321eae6782c3/src/semantic-router/pkg/apiserver/route_decision_tasks.go)).

[authz_fail_open.go](https://github.com/vllm-project/semantic-router/blob/4416f76c1b991fb32d81b4b0fb3d321eae6782c3/src/semantic-router/pkg/classification/authz_fail_open.go) implements the deliberate opposite of this project's stance: `applyAuthzFailOpenOnClassifyError` clears the classification error when `authz.fail_open` is true and the user ID is empty, continuing "with no matched roles (anonymous)" and emitting only a warning log. An unauthenticated caller therefore resolves to anonymous roles on the fail-open path.

**Use:** a configurable fail-open/fail-closed switch documented as a switch (so the choice is explicit rather than incidental), and a large routing tree as a reminder that classifier/service code can dwarf policy code. **Avoid:** fail-open authorisation when identity is empty — the unauthenticated caller is exactly the case strict caps must block, and a warning log is not a control.

## 18. BerriAI/litellm

Revision: [`d346d769f02811d5e325a2ac5f45ac54ff5593de`](https://github.com/BerriAI/litellm/tree/d346d769f02811d5e325a2ac5f45ac54ff5593de), 2026-10-17. Approximately 14,259 tree-discovered files; 5,643 test-discovered paths; Python. GitHub reports `NOASSERTION` for licensing — the root `LICENSE` and a separate `enterprise/LICENSE.md` exist, and the terms were **not** assessed in this pass, so terms must be read before any reuse. Included for contrast, not as a dependency.

[lowest_cost.py](https://github.com/BerriAI/litellm/blob/d346d769f02811d5e325a2ac5f45ac54ff5593de/litellm/router_strategy/lowest_cost.py) is deployment *selection within a model group*: a `cost_map:{model_group}` accumulator is updated in the success callbacks and `async_get_available_deployments` returns a deployment with the lowest recorded cost. Cost here is a load-balancing strategy across providers of one logical model, not a task-difficulty policy. [fallback_event_handlers.py](https://github.com/BerriAI/litellm/blob/d346d769f02811d5e325a2ac5f45ac54ff5593de/litellm/router_utils/fallback_event_handlers.py) is the more transferable file: `_trigger_cooldown_for_failed_deployment` exists because "in the fallback path the normal failure-callback cooldown is skipped", it deliberately skips cooldown for `is_advisor_orchestration_failure`, restricts cooldown to request-scoped status codes so one request does not cool down a whole chain, and types skipped fallbacks (`FallbackSkipReason`, `SkippedFallbackTarget`) so they are reportable rather than silent.

**Use:** the recognition that a fallback path evades the primary path's accounting, so cooldown/trigger logic must be re-established explicitly there and skips must be recorded; cost as an accumulator keyed by group. **Avoid:** assuming a major gateway's routing is difficulty-aware (it is availability/cost based), and copying from a 14,259-file monorepo whose GitHub licensing reads `NOASSERTION` without reading the terms.

## 19. Portkey-AI/gateway

Revision: [`669825cbe89ee51569918b8f78a9db486fd69dd4`](https://github.com/Portkey-AI/gateway/tree/669825cbe89ee51569918b8f78a9db486fd69dd4), 2026-05-25 — the pinned revision *is* the last push, i.e. stale relative to the rest of this extension. Approximately 766 tree-discovered files; 20 test-discovered paths; TypeScript; MIT.

[conditionalRouter.ts](https://github.com/Portkey-AI/gateway/blob/669825cbe89ee51569918b8f78a9db486fd69dd4/src/services/conditionalRouter.ts) is a compact, readable conditional-route contract: resolution refuses a strategy whose mode is not `CONDITIONAL` and refuses a conditional strategy with no conditions; it then iterates `strategy.conditions` in order and returns the first target whose query holds; if nothing matches it returns the declared `strategy.default`; with no default it throws "Query router did not resolve to any valid target". `evaluateQuery` is a small boolean language over the request context (metadata/params/url) with recursive `Operator.Or`/`Operator.And` and an operator layer (`Equal`, `NotEqual`, …) rather than ad-hoc predicates.

**Use:** as the shape of an explicit conditional contract — ordered conditions, an optional *declared* default, typed refusal when nothing resolves, and boolean composition instead of bespoke matching. **Avoid:** evaluating router conditions against caller-controlled metadata without a trust boundary, and weighing a 20-test surface as assurance for anything security relevant.

## 20. katanemo/plano

Revision: [`a031d31105d0cd9801dc75f37d7507c44b65ab1c`](https://github.com/katanemo/plano/tree/a031d31105d0cd9801dc75f37d7507c44b65ab1c), 2026-10-07. Approximately 734 tree-discovered files; 59 test-discovered paths; Rust; Apache-2.0.

[routing_service.rs](https://github.com/katanemo/plano/blob/a031d31105d0cd9801dc75f37d7507c44b65ab1c/crates/brightstaff/src/handlers/routing_service.rs) returns a `RoutingDecisionResponse` whose `models: Vec<String>` is documented as the "ranked model list — use first, fall back to next on 429/5xx", alongside `route`, `trace_id`, `session_id`, `pinned`, and `switched` ("whether the routing budget allowed a model switch this turn", `plano.switch.decision=allowed`). The handler derives `explicit_session_id` from a model-affinity header and a tenant id from the orchestrator's tenant header, then delegates to `routing_decision_inner` with `EffectivePromptCaching`, `Option<EffectiveRoutingBudget>`, `route_on_user_only` and the configured `ModelAlias` map.

**Use:** ranking the candidate list and letting per-hop 429/5xx cascade be visible to the caller; expressing a routing budget that can *forbid* a switch this turn, not just record cost; and keeping affinity (cache/warmth) as a first-class, overridable input. **Avoid:** reading affinity as a correctness policy — pinning a session to the warm model can hold it on a model that should have been escalated.

## 21. Continuum-AI-Corp/OrcaRouter-Lite

Revision: [`4cacea8538f6dc16c4c9a8364ec867a1c4c80088`](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/tree/4cacea8538f6dc16c4c9a8364ec867a1c4c80088), 2026-10-08. Approximately 187 tree-discovered files against 72 test-discovered paths (roughly two fifths of the tree); Python; MIT.

[auto_routing.py](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/4cacea8538f6dc16c4c9a8364ec867a1c4c80088/app/auto_routing.py) resolves `model="auto"` as two pure functions — `required_capabilities(body)` → `{tools, vision, json_mode}` and `choose_auto_model(needs, deployable, candidates, strategy, preferred_models)` → model ids ordered best-first and **empty when none qualify**. Capability needs are intersected with the set of *deployable* providers before strategy ordering, so the selection is a filter-then-order pipeline rather than an order-then-hope. It also de-duplicates sibling versions through `canonical_model_base` (so `gemini-2.0-flash-lite-001` does not masquerade as a cross-provider fallback), and documents `_lookup_score`'s dot→hyphen normalisation as a correctness guard: without it every dotted id scores 0, which ranks the *most expensive* model first.

**Use:** pure selection functions separated from the HTTP handler; capability ∩ deployable before ordering; empty-not-last-resort; sibling-version dedupe before claiming a fallback; and treating id normalisation as a correctness bug rather than cosmetics. **Avoid:** letting score tables decide eligibility, and reading the 72 test paths as evidence the selector met real providers — nothing here was executed against a provider.

## 22. bitrouter/bitrouter

Revision: [`54c822a34d4dbfd75d484ca35e108b497048efef`](https://github.com/bitrouter/bitrouter/tree/54c822a34d4dbfd75d484ca35e108b497048efef), 2026-10-16. Approximately 1,157 tree-discovered files; 195 test-discovered paths; Rust; Apache-2.0 (LICENSE read at the pinned revision).

The integration contract is the interesting part: the [README](https://github.com/bitrouter/bitrouter/blob/54c822a34d4dbfd75d484ca35e108b497048efef/README.md) points an existing OpenAI-compatible agent at a local `http://localhost:4356/v1` and asks it to set the model to `bitrouter/auto`, so routing is opted into by *model name* with no other agent change, and the provider credential stays with the router rather than the calling agent. It markets itself as the "minimal interpretable model router that learns & adapts to your agent workflows", and ships a `/bitrouter` skill so the agent can install, configure and migrate itself. The interpretability and learning claims were not evaluated — only the entry contract and repository shape.

**Use:** model-name opt-in as a drop-in contract; a local endpoint so the agent never holds provider credentials; naming the router in the model field rather than in a provider-setting rewrite. **Avoid:** adopting a "learning/adaptive" router on marketing without an evaluation artefact, and asking the agent to self-install router software — that is a supply-chain path, not a routing decision.

## 23. ulab-uiuc/LLMRouter

Revision: [`c65ee0122bc9e84f71d571fcdec4a948481b6e88`](https://github.com/ulab-uiuc/LLMRouter/tree/c65ee0122bc9e84f71d571fcdec4a948481b6e88), 2026-10-08. Approximately 428 tree-discovered files; 61 test-discovered paths; Python; MIT (LICENSE read at the pinned revision). A research library with an accompanying paper and the `xRouteBench` dataset; all benchmark and savings figures are publisher claims.

[custom_routers/fusion_gate/gate.py](https://github.com/ulab-uiuc/LLMRouter/blob/c65ee0122bc9e84f71d571fcdec4a948481b6e88/custom_routers/fusion_gate/gate.py) is the clearest artefact: a `RouteGate` deciding *per query* between a cheap SINGLE model and an expensive fused panel from a difficulty estimate and the gate's own confidence, with `GateDecision` declared additive-only and preset resolution centralised (`resolve_preset`, `TIER_TO_PRESET`) so the router and its evaluation harness cannot diverge on the table. Difficulty estimation follows the `ThresholdRouter` two-mode design: an embedding when one is supplied *and* an estimator is wired in, otherwise a deterministic, documented lexical heuristic — the gate therefore runs end-to-end with no embedding model at all.

**Use:** difficulty/confidence gating as an explicit, unit-testable decision; one table shared by router and eval harness; an additive-only decision schema for a gate consumed by a harness; and a documented no-model fallback path. **Avoid:** importing a published threshold without re-calibration, and treating a fusion panel's benchmark as evidence about cost per *verified* success.

## Surfaced candidates (metadata only — not code-reviewed)

Surfaced while searching for the entries above, recorded so a later pass can pick them up. Figures are GitHub API metadata returned on 2026-10-17 (stars, license, last push); no tree, source, docs or license file from these was inspected, and none was cloned, installed or executed.

- One-endpoint many-provider gateways: `diegosouzapw/OmniRoute` (77.4k★, MIT), `QuantumNous/new-api` (50.1k★, AGPL-3.0), `lidge-jun/opencodex` (17.5k★, MIT), `mnfst/awesome-free-llm-apis` (10.4k★, CC0-1.0 — list, not a router), `maximhq/bifrost` (8.9k★, Apache-2.0), `coaidev/coai` (9.3k★, Apache-2.0), `bestruirui/octopus` (2.7k★, AGPL-3.0).
- General API/AI gateways where LLM routing is a plugin or extension rather than a policy of their own: `Kong/kong` (44.3k★, Apache-2.0), `apache/apisix` (17.2k★, Apache-2.0), `TykTechnologies/tyk` (10.9k★, NOASSERTION), `higress-group/higress` (9.6k★, Apache-2.0), `agentgateway/agentgateway` (5.4k★, Apache-2.0).
- Surfaced by the same queries but not routing policies: `farion1231/cc-switch` (145.3k★, MIT) and `earendil-works/pi` (115.8k★, MIT).

Re-verify any blocking fact before adoption; none of these was cloned, installed or executed, and nothing from them is vendored here.

## Consolidated recommendation

1. **Plan a later three-skill package with one authority**, not a router service. This PR delivers planning documents only; usable skills require separate authorization. The proposed policy prefers eligible direct work with no automatic paid classifier; review/eval-prep would be procedures, not additional selectors.
2. **Fail closed at every stage and fallback.** Unknown actor/path/required capability/pricing under strict caps and empty candidate sets are explicit blockers. Verify zero sends at real callsites in later hosts.
3. **Preserve task contracts and exact context.** Tool/refusal/media/structured outcomes are contract-specific; verifier failures do not accept. Cache keys include relevant authority/price/check revisions and exact meaningful content.
4. **Bound and account every attempt.** Capability escalation is not a price ladder. No replay after ambiguous effects/committed output; cancellation/restart reconcile first. Count router/review/sunk costs without double counting.
5. **Measure before growth.** Four fair arms, approved preregistration, actual cost per verified success, complete accounting, hard severe-failure stops and explicit promote/simplify/reject/inconclusive outcomes.
6. **Prefer original policy over copied implementations.** No runtime dependency now. MIT/Apache ideas do not establish correctness; noncommercial/source-available/no-grant/AGPL materials need appropriate permission/compatibility checks before any future copy. SmartRouter's chosen MIT grant covers only the newly authored planning documents listed in LICENSE, not upstream or historical content.
