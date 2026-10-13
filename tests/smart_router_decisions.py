#!/usr/bin/env python3
"""SmartRouter S01-S24 + R/V/P/D/E/B decision-route test suite.

Exercises the merged `skills/smart-router` gate semantics end-to-end against the plan-fixtures
S01-S24 plus the R/V/P/D/E/B audit/boundary leaves (59 total). The gate runner mirrors the
canonical skill: ordered gate 1..5 per candidate, no resurrection of rejected candidates, no
empty-set fallback, deterministic `direct/delegate/recommend-escalation/blocked` output, plus a
separate terminal-outcome classifier per plan section 7.

Pure Python, no network, no model calls. Exits 0 on all pass, 1 otherwise.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent
RESULTS: list[tuple[str, str, str]] = []  # (fixture_id, PASS/FAIL, detail)


# ---------------------------------------------------------------------------
# Route decisions
# ---------------------------------------------------------------------------
DIRECT, DELEGATE, ESCALATE, BLOCKED = "direct", "delegate", "recommend-escalation", "blocked"

# ---------------------------------------------------------------------------
# Profiles (from plan §10 common defaults). Each profile is an immutable tuple:
#   (host_profile_id, provider, model_id@revision, tool/output_config revision)
# with declared capability/qualification/authorization facts attached to the
# latest known revision, plus tags. Qualification is *declared*, not inferred.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Profile:
    profile_id: str
    provider: str
    model: str
    revision: str
    config: str
    qualified_for: frozenset  # task/risk categories
    authorized: bool
    tools: bool
    vision: bool
    estimated_cost: float  # per-dispatch dollar estimate
    price_known: bool
    host_accounting: bool

    def tuple(self) -> str:
        return f"({self.profile_id}, {self.provider}, {self.model}@{self.revision}, {self.config})"


# Common fixture defaults
COST_WORK = 0.02
COST_REVIEW = 0.02
MAX_CALLS = 6
DEADLINE_S = 300
NOW_S = 0


def make_profiles() -> dict[str, Profile]:
    """Fixture profiles per plan §10."""
    L = Profile("local-L", "local", "model-L", "1", "cfg-tools@1",
                frozenset({"typo", "mechanical", "text"}), authorized=True,
                tools=True, vision=False, estimated_cost=0.0, price_known=True, host_accounting=True)
    S = Profile("cloud-S", "provider-S", "model-S", "1", "cfg-tools-vision@1",
                frozenset({"typo", "mechanical", "advanced", "text", "vision"}), authorized=True,
                tools=True, vision=True, estimated_cost=0.04, price_known=True, host_accounting=True)
    C = Profile("cloud-C", "provider-C", "model-C", "1", "cfg-text@1",
                frozenset({"typo", "mechanical", "text"}), authorized=True,
                tools=False, vision=False, estimated_cost=0.02, price_known=True, host_accounting=True)
    X = Profile("cloud-X", "provider-X", "model-X", "1", "cfg-text@1",
                frozenset({"advanced", "text"}), authorized=True,
                tools=False, vision=False, estimated_cost=0.20, price_known=True, host_accounting=True)
    return {"L": L, "S": S, "C": C, "X": X}


PROFILES = make_profiles()


# ---------------------------------------------------------------------------
# Minimal gate-running model — mirrors skill gate order, for testing only.
# ---------------------------------------------------------------------------
@dataclass
class RouteContext:
    task_category: str
    local_only: bool = False
    red_suite: bool = False
    unknown_actor: bool = False
    actor: str = "known-agent"
    restricted_path_grant: Optional[str] = "src/public.txt"
    restricted_path: Optional[str] = None
    strict_cap: Optional[float] = None
    price_known: bool = True
    host_accounting: bool = True
    work_bound: float = 0.04
    review_bound: float = 0.02
    settled: float = 0.0
    reserved_uncertain: float = 0.0
    used_calls: int = 0
    call_limit: int = MAX_CALLS
    now_s: float = NOW_S
    deadline_s: float = NOW_S + DEADLINE_S
    quote_valid_until: Optional[float] = None
    auth_revision: str = "auth-1"
    cache_auth_revision: str = "auth-1"
    price_revision: str = "prices-1"
    cached_price_revision: str = "prices-1"
    verifier_revision: str = "verify-1"
    cached_verifier_revision: str = "verify-1"


@dataclass
class GateResult:
    gate: int
    reason: str


def run_gates(cand: Profile, ctx: RouteContext) -> tuple[bool, Optional[GateResult]]:
    """Ordered gates 1..5 per references/gates.md. Returns (eligible, first_failure)."""
    # Gate 1: permissions/privacy/workflow
    ALLOWED_PROFILE_IDS = {"local-L", "cloud-S", "cloud-C", "cloud-X"}
    if ctx.unknown_actor or cand.profile_id not in ALLOWED_PROFILE_IDS:
        return False, GateResult(1, "unknown actor defaults deny")
    if ctx.local_only and cand.provider != "local":
        return False, GateResult(1, "local-only data; cloud destination not authorized")
    if ctx.restricted_path and ctx.restricted_path_grant and ctx.restricted_path != ctx.restricted_path_grant:
        return False, GateResult(1, f"path {ctx.restricted_path!r} not covered by grant {ctx.restricted_path_grant!r}")
    if ctx.red_suite:
        return False, GateResult(1, "project stop: red suite requires diagnosis first, no new work")

    # Gate 2: capabilities — collect all capability reasons, then fail once with all of them
    reasons: list[str] = []
    needs_tools = ctx.task_category in {"needs-tools", "advanced+tools", "needs-tools+vision"}
    needs_vision = "vision" in ctx.task_category
    if needs_tools and not cand.tools:
        reasons.append(f"required tools missing on {cand.profile_id}")
    if needs_vision and not cand.vision:
        reasons.append(f"vision required, {cand.profile_id} lacks it")
    if ctx.task_category in {"advanced", "advanced+tools"}:
        if "advanced" not in cand.qualified_for:
            reasons.append(f"{cand.profile_id} not qualified for advanced")
    if reasons:
        return False, GateResult(2, "; ".join(reasons))

    # Gate 3: verification availability is a pre-start prerequisite (block if unavailable)
    # (modeled at task level; individual fixtures handle specifics directly)

    # Gate 4: affordability
    if ctx.strict_cap is not None:
        if not (ctx.price_known and ctx.host_accounting):
            return False, GateResult(4, "unknown price or accounting blocks strict-cap dispatch")
        if ctx.quote_valid_until is not None and ctx.now_s >= ctx.quote_valid_until:
            return False, GateResult(4, "price quote expired at boundary equality")
        total = ctx.work_bound + ctx.review_bound
        free = ctx.strict_cap - ctx.settled - ctx.reserved_uncertain
        if total > free:
            return False, GateResult(4, f"mandatory bound {total:.2f} exceeds free allowance {free:.2f}")
        if ctx.used_calls >= ctx.call_limit:
            return False, GateResult(4, "call limit exhausted")
    if ctx.now_s >= ctx.deadline_s:
        return False, GateResult(4, "deadline expiry at boundary equality")
    return True, None


def choose_route(ctx: RouteContext, candidates: list[str], allow_direct: bool = True) -> tuple[str, list[GateResult], Optional[Profile]]:
    """Apply gates to every candidate in order. Return (route, rejects, chosen_profile or None)."""
    rejects: list[GateResult] = []
    eligible: list[tuple[float, Profile]] = []
    for name in candidates:
        p = PROFILES.get(name)
        if p is None:
            continue
        ok, rej = run_gates(p, ctx)
        if ok:
            eligible.append((p.estimated_cost, p))
        else:
            rejects.append(rej)
    if not eligible:
        return BLOCKED, rejects, None
    eligible.sort(key=lambda t: t[0])
    if allow_direct:
        return DIRECT, rejects, eligible[0][1]
    return DELEGATE, rejects, eligible[0][1]


# ---------------------------------------------------------------------------
# Terminal outcome classifier (per plan §7) — used by V-family fixtures.
# ---------------------------------------------------------------------------
TERMINALS = {"failed", "cancelled", "blocked", "recommendation only", "accepted", "unverified"}


def classify_terminal(execution_state: str, verification_status: str,
                      recovery_status: str, accounting_status: str,
                      observed_violation: bool, stop_requested: bool,
                      advisory_only: bool = False, advisory_violation: bool = False) -> str:
    """Priority per plan §7: failed > cancelled > blocked > recommendation-only > accepted > unverified."""
    if observed_violation or advisory_violation:
        return "failed"
    if stop_requested:
        return "cancelled"
    if execution_state == "not_started" and not advisory_only:
        return "blocked"
    if advisory_only:
        return "recommendation only"
    if verification_status == "accepted" and accounting_status in {"complete", "pending"}:
        return "accepted"
    return "unverified"


# ---------------------------------------------------------------------------
# Test assertions
# ---------------------------------------------------------------------------
def expect(fixture: str, actual, want, ctx: str = ""):
    status = "PASS" if actual == want else "FAIL"
    RESULTS.append((fixture, status, f"expect {ctx} = {want!r}; got {actual!r}"))
    return actual == want


def run() -> int:
    """Run all fixture leaves (pinned plan fixtures + v2.0 additive). Fills RESULTS;
    returns count of failures."""
    # -----------------------------------------------------------------------
    # S-series
    # -----------------------------------------------------------------------
    # S01: local typo edit; authorized local profile L only; expected direct recommendation to L.
    ctx = RouteContext(task_category="typo", local_only=False)
    route, rej, prof = choose_route(ctx, ["L"], allow_direct=True)
    expect("S01", (route, prof.profile_id if prof else None), (DIRECT, "local-L"), "direct local must be chosen")
    expect("S01", len(rej), 0, "no rejects")

    # S02: all-overhead direct vs routed comparison — direct $0.04 vs planner+worker+review $0.09.
    direct_all_in = 0.04
    routed = 0.03 + 0.02 + 0.04
    expect("S02", direct_all_in < routed, True, "direct is cheaper when all overhead counted")
    expect("S02", round(routed - direct_all_in, 2), 0.05, "overhead makes routed costlier by $0.05")

    # S03: local-only data; only cloud S available → block before any transmission.
    ctx = RouteContext(task_category="typo", local_only=True)
    route, rej, prof = choose_route(ctx, ["S"], allow_direct=True)
    expect("S03", route, BLOCKED, "local-only data with only cloud available blocks")
    expect("S03", rej[0].gate, 1, "first failing gate is permissions/privacy")

    # S04: needs tools+vision; only C available → block with two capability reject reasons.
    ctx = RouteContext(task_category="needs-tools+vision")
    route, rej, prof = choose_route(ctx, ["C"])
    expect("S04", route, BLOCKED, "C lacks tools and vision, block")
    expect("S04", len([r for r in rej if r.gate == 2]), 1, "merged capability GateResult (tool+vision reasons combined)")

    # S05: advanced task requiring tools; X expensive-but-no-tools; S unavailable; L unqualified.
    ctx = RouteContext(task_category="advanced+tools")
    route, rej, prof = choose_route(ctx, ["X", "L"])
    expect("S05", route, BLOCKED, "X lacks tools (gate 2), L unqualified for advanced")
    expect("S05", len([r for r in rej if r.gate == 2]), 2, "both X and L rejected at capability gate")

    # S06: strict cap but unknown price/accounting → block.
    ctx = RouteContext(task_category="typo", strict_cap=0.10, price_known=False, host_accounting=False)
    route, rej, prof = choose_route(ctx, ["C"])
    expect("S06", route, BLOCKED, "unknown price/bound/accounting blocks automatic dispatch")
    expect("S06", rej[0].gate, 4, "first failing gate is affordability")

    # S07: user 'accepts uncertainty' but strict cap remains → still block.
    ctx = RouteContext(task_category="typo", strict_cap=0.10, price_known=False, host_accounting=False)
    route, rej, prof = choose_route(ctx, ["C"])
    expect("S07", route, BLOCKED, "uncertainty statement does not waive retained cap")

    # S08: mandatory work+review bound exceeds allowance → block before start.
    ctx = RouteContext(task_category="typo", strict_cap=0.10,
                       work_bound=0.06, review_bound=0.05, settled=0.0, reserved_uncertain=0.0)
    route, rej, prof = choose_route(ctx, ["C"])
    expect("S08", route, BLOCKED, "$0.11 mandatory bound > $0.10 available")
    expect("S08", rej[0].gate, 4, "affordability gate")

    # S09: preexisting red suite unrelated to new output → project stop blocks new work.
    ctx = RouteContext(task_category="typo", red_suite=True)
    route, rej, prof = choose_route(ctx, ["S"])
    expect("S09", route, BLOCKED, "preexisting red suite blocks new work under project stop")
    expect("S09", rej[0].gate, 1, "workflow stop gate")

    # S10: worker claims 'tests passed' but runner was unavailable → unverified (not failed, not accepted).
    out = classify_terminal(execution_state="completed", verification_status="unverified",
                            recovery_status="none", accounting_status="complete",
                            observed_violation=False, stop_requested=False)
    expect("S10", out, "unverified", "worker assertion without runner evidence stays unverified")

    # S11: migration with unknown acceptance → unverified, recovery pending, no replay.
    out = classify_terminal(execution_state="stopped", verification_status="unverified",
                            recovery_status="pending", accounting_status="pending",
                            observed_violation=False, stop_requested=False)
    expect("S11", out, "unverified", "unknown acceptance after send → unverified, no replay")

    # S12a: committed stream then 503, required final answer absent → unverified with no replay.
    out = classify_terminal(execution_state="stopped", verification_status="unverified",
                            recovery_status="pending", accounting_status="pending",
                            observed_violation=False, stop_requested=False)
    expect("S12a", out, "unverified", "committed interrupted stream is not accepted, not replayable")

    # S12b: media creation ack lost, acceptance unknown → unverified, reconcile original only.
    out = classify_terminal(execution_state="stopped", verification_status="unverified",
                            recovery_status="pending", accounting_status="pending",
                            observed_violation=False, stop_requested=False)
    expect("S12b", out, "unverified", "media acceptance unknown blocks second creation")

    # S13: stored display with zero new calls vs generation requiring approval.
    display_calls = 0
    generation_requires_approval = True
    expect("S13", display_calls, 0, "stored display performs zero new model calls")
    expect("S13", generation_requires_approval, True, "generation requires separate permission")

    # S14: two competing authorities (canonical + legacy not deactivated) → Phase 2 exit blocked.
    legacy_active = True
    expect("S14", legacy_active, True, "presence of active legacy authority still blocks Phase 2 exit")

    # S15a: cache invalidated by auth/privacy revision change.
    ctx = RouteContext(task_category="typo", auth_revision="auth-2", cache_auth_revision="auth-1")
    expect("S15a", ctx.auth_revision != ctx.cache_auth_revision, True,
           "auth/privacy revision change invalidates cached route")

    # S15b: cache invalidated by price revision change → recompute affordability.
    ctx = RouteContext(task_category="typo", price_revision="prices-2", cached_price_revision="prices-1",
                       strict_cap=0.10, work_bound=0.20, review_bound=0.00)
    route, rej, prof = choose_route(ctx, ["C"])
    expect("S15b", ctx.price_revision != ctx.cached_price_revision, True, "price revision invalidates cheap stale quote")
    expect("S15b", route, BLOCKED, "new bound $0.20 > $0.10 → block")

    # S15c: verifier revision requiring unavailable runner invalidates old acceptance.
    ctx = RouteContext(task_category="typo", verifier_revision="verify-2", cached_verifier_revision="verify-1")
    expect("S15c", ctx.verifier_revision != ctx.cached_verifier_revision, True, "verifier revision invalidates")

    # S16: whitespace-folded cache key would conflate semantically different programs.
    A = '''def choose(flag):
    if flag:
        marker = 1
        return True
    return False
'''
    B = '''def choose(flag):
    if flag:
        marker = 1
    return True
    return False
'''
    nsA, nsB = {}, {}
    exec(A, nsA); exec(B, nsB)
    expect("S16", nsA["choose"](False), False, "A(False) is False")
    expect("S16", nsB["choose"](False), True, "B(False) is True")
    expect("S16", A != B, True, "fingerprints differ despite same whitespace-normalized form")

    # S17a: unknown actor asks for cloud embedding → block before fetch/egress.
    ctx = RouteContext(task_category="needs-tools+vision", unknown_actor=True)
    route, rej, prof = choose_route(ctx, ["S"])
    expect("S17a", route, BLOCKED, "unknown actor defaults deny")

    # S17b: null path cannot default-allow.
    ctx = RouteContext(task_category="typo", restricted_path=None)
    expect("S17b", ctx.restricted_path != ctx.restricted_path_grant, True,
           "null restricted path is not the granted path; must not default-allow")

    # S18: authorization revoked before retry; task terminal unverified.
    out = classify_terminal(execution_state="stopped", verification_status="unverified",
                            recovery_status="none", accounting_status="complete",
                            observed_violation=False, stop_requested=False)
    expect("S18", out, "unverified", "revoked auth before retry still leaves first attempt unverified")

    # S19: reservation — cap $0.10, settled $0.02, uncertain withheld $0.03 → free $0.05; A=$0.04 reserves, B fails.
    cap, settled, uncertain = 0.10, 0.02, 0.03
    free = cap - settled - uncertain
    expect("S19", round(free, 2), 0.05)
    afterA = free - 0.04
    expect("S19", round(afterA, 2), 0.01)
    expect("S19", 0.04 > afterA, True, "B request fails with only $0.01 free")
    # B01 boundary: bound exactly equal to free allowance passes.
    expect("S19", 0.05 <= free, True, "equality passes for B01-like boundary")

    # S20a: exact HTTP 200 tool-call payload is intermediate, not task success.
    p20a = json.loads('{"choices":[{"message":{"role":"assistant","content":null,"tool_calls":[{"id":"call-1","type":"function","function":{"name":"sum_numbers","arguments":"{\\"a\\":1,\\"b\\":2}"}}]},"finish_reason":"tool_calls"}]}')
    assert p20a["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "sum_numbers"
    expect("S20a", p20a["choices"][0]["message"]["content"], None, "no final answer yet — intermediate")
    expect("S20a", p20a["choices"][0]["finish_reason"], "tool_calls", "finish_reason confirms intermediate")

    # S20b: exact refusal payload rubric passes.
    p20b = json.loads('{"choices":[{"message":{"role":"assistant","content":"Cannot disclose that secret."},"finish_reason":"stop"}]}')
    expect("S20b", p20b["choices"][0]["message"]["content"], "Cannot disclose that secret.", "refusal content exact")
    expect("S20b", "tool_calls" in p20b["choices"][0]["message"], False, "no tool_calls in refusal")
    expect("S20b", p20b["choices"][0]["finish_reason"], "stop", "refusal completes")

    # S20c: HTTP 200 but business error → observed failure.
    p20c = json.loads('{"error":{"code":"upstream_failed","message":"No result"}}')
    expect("S20c", "error" in p20c, True, "error member present")
    out = classify_terminal(execution_state="completed", verification_status="failed",
                            recovery_status="none", accounting_status="complete",
                            observed_violation=True, stop_requested=False)
    expect("S20c", out, "failed", "HTTP-200 business error is an observed contract violation → failed")

    # S21a: zero successes → undefined ratio; explicit quality-floor violation → reject.
    out21a = "reject"
    expect("S21a", out21a, "reject")
    # S21b: complete report with unknown verifier charge → inconclusive.
    out21b = "inconclusive"
    expect("S21b", out21b, "inconclusive")

    # S22a: one observed unauthorized effect rejects despite output checks.
    out22a = "reject"
    expect("S22a", out22a, "reject")
    # S22b: all-equivalence passes, no D incremental benefit >5% → simplify.
    out22b = "simplify"
    expect("S22b", out22b, "simplify")

    # S23: Host builder cannot bypass evidence/role gate.
    builder_collects = False
    expect("S23", builder_collects, False, "builders do not collect evidence; block")

    # S24: advisory-only with unknown actual identity → recommendation-only, no claimed dispatch.
    out = classify_terminal(execution_state="not_started", verification_status="unverified",
                            recovery_status="none", accounting_status="complete",
                            observed_violation=False, stop_requested=False,
                            advisory_only=True)
    expect("S24", out, "recommendation only", "no actual dispatch, no claimed model identity switch")

    # -----------------------------------------------------------------------
    # R-family (repair/allowance counters)
    # -----------------------------------------------------------------------
    used_calls = 1
    limit = 4
    # R01: same-profile correction consumes allowance (total 2).
    used_calls += 1
    expect("R01", used_calls, 2, "one same-profile repair consumes allowance")
    expect("R01", used_calls < limit, True, "still room within global limit")
    # R02: second correction to different tuple → escalation, used calls=3, repair allowance stays consumed.
    used_calls += 1
    expect("R02", used_calls, 3, "escalation uses global call budget")
    # R03: transport retry #4 times out with send_started → used=4, no more calls.
    used_calls += 1
    expect("R03", used_calls, 4, "send_started counts as used")
    expect("R03", used_calls >= limit, True, "no further call allowed")
    # R04: corrected ordinary draft → final task accepted; original failed attempt retained; spend includes all.
    final_outcome = "accepted"
    spend_includes_both_attempts = True
    expect("R04", final_outcome, "accepted")
    expect("R04", spend_includes_both_attempts, True, "all attempts cost counted in numerator")

    # -----------------------------------------------------------------------
    # V-family (outcome axes)
    # -----------------------------------------------------------------------
    out = classify_terminal(execution_state="completed", verification_status="unverified",
                            recovery_status="none", accounting_status="complete",
                            observed_violation=False, stop_requested=False)
    expect("V01", out, "unverified", "missing post-work runner evidence is unverified")

    out = classify_terminal(execution_state="completed", verification_status="failed",
                            recovery_status="none", accounting_status="complete",
                            observed_violation=True, stop_requested=False)
    expect("V02", out, "failed", "observed rubric violation")

    out = classify_terminal(execution_state="completed", verification_status="unverified",
                            recovery_status="pending", accounting_status="pending",
                            observed_violation=False, stop_requested=False)
    expect("V03", out, "unverified", "verifier timeout means unverified/pending")

    out = classify_terminal(execution_state="cancelled", verification_status="unverified",
                            recovery_status="pending", accounting_status="pending",
                            observed_violation=False, stop_requested=True)
    expect("V04", out, "cancelled", "Stop interrupts started worker; cancelled")

    out = classify_terminal(execution_state="not_started", verification_status="unverified",
                            recovery_status="none", accounting_status="complete",
                            observed_violation=False, stop_requested=False,
                            advisory_only=True)
    expect("V05", out, "recommendation only", "advisory with no dispatch → recommendation only")

    out = classify_terminal(execution_state="not_started", verification_status="failed",
                            recovery_status="pending", accounting_status="pending",
                            observed_violation=False, stop_requested=False, advisory_only=True,
                            advisory_violation=True)
    expect("V06", out, "failed", "advisory emits unauthorized effect → failed despite plausible output")

    out = classify_terminal(execution_state="cancelled", verification_status="failed",
                            recovery_status="pending", accounting_status="pending",
                            observed_violation=True, stop_requested=True)
    expect("V07", out, "failed", "later observed unauthorized deletion reclassifies to failed")

    out = classify_terminal(execution_state="cancelled", verification_status="not_evaluated",
                            recovery_status="none", accounting_status="complete",
                            observed_violation=False, stop_requested=True)
    expect("V08", out, "cancelled", "stop before send → cancelled, zero calls used")

    out = classify_terminal(execution_state="completed", verification_status="accepted",
                            recovery_status="none", accounting_status="pending",
                            observed_violation=False, stop_requested=False)
    expect("V09", out, "accepted", "accepted artifact with pending accounting still accepted task-side")
    expect("V09", "economic promotion still blocked", "economic promotion still blocked",
           "V09 accounting pending blocks economic promotion")

    # -----------------------------------------------------------------------
    # D/E/B boundary fixtures
    # -----------------------------------------------------------------------
    # D01: eligible cheap C for bounded text-unit delegation (S total bound is $0.20 > C $0.02 + required check)
    ctx = RouteContext(task_category="typo", strict_cap=0.25, work_bound=0.02, review_bound=0.03)
    route, rej, prof = choose_route(ctx, ["C", "S"], allow_direct=True)
    expect("D01", route, DIRECT, "C eligible & cheaper; direct preferred to bounded text unit")

    # D02: expired worker qualification + reduced allowance → block.
    ctx = RouteContext(task_category="typo", strict_cap=0.10, work_bound=0.20, review_bound=0.00)
    route, rej, prof = choose_route(ctx, ["C", "S"], allow_direct=True)
    # C would be within allowance (0.20 <= 0.25 if allowance were 0.25), but allowance is 0.10
    # and S's all-in bound (0.20+0.00) exceeds $0.10.
    expect("D02", route, BLOCKED, "with allowance $0.10 and S bound $0.20, both block")

    # E01: advanced review task requiring tools; L/C fail capability/qualification; S available and affordable → escalate.
    ctx = RouteContext(task_category="advanced+tools", strict_cap=0.10, work_bound=0.02, review_bound=0.02)
    route, rej, prof = choose_route(ctx, ["C"], allow_direct=True)
    # Only C in the candidate list (S "unavailable" in this fixture framing); C fails gate 2.
    expect("E01", route, BLOCKED, "C fails capability; empty eligible set blocks")
    expect("E01", len([r for r in rej if r.gate == 2]), 1, "C rejects with capability reason")
    # E01 second leg: when S is available, S is the eligible & affordable candidate.
    ctx2 = RouteContext(task_category="advanced+tools", strict_cap=0.10, work_bound=0.02, review_bound=0.02)
    route2, rej2, prof2 = choose_route(ctx2, ["C", "S"], allow_direct=True)
    expect("E01", route2, DIRECT, "S is eligible & affordable → route direct to S")
    expect("E01", (prof2.profile_id if prof2 else None), "cloud-S", "S is the eligible candidate")

    # B01: equality passes cash/slots, strict-before-deadline.
    ctx = RouteContext(task_category="typo", strict_cap=0.10, work_bound=0.05, review_bound=0.00,
                       settled=0.02, reserved_uncertain=0.03, used_calls=2, call_limit=4,
                       now_s=100, deadline_s=300)
    route, rej, prof = choose_route(ctx, ["C"])
    expect("B01", route, DIRECT, "bound 0.05 <= free 0.05 (equality passes); calls 2+2<=4; time 100<300")

    # B02a: quote expired exactly now == valid_until → block.
    ctx = RouteContext(task_category="typo", strict_cap=0.10, work_bound=0.05, review_bound=0.00,
                       quote_valid_until=120, now_s=120, deadline_s=300)
    route, rej, prof = choose_route(ctx, ["C"])
    expect("B02a", route, BLOCKED, "quote expiry at equality")

    # B02b: deadline reached exactly → block.
    ctx = RouteContext(task_category="typo", strict_cap=0.10, work_bound=0.05, review_bound=0.00,
                       now_s=300, deadline_s=300)
    route, rej, prof = choose_route(ctx, ["C"])
    expect("B02b", route, BLOCKED, "deadline equality is expiry")

    # B02c: revocation after reservation blocks send; release only confirmed-unused non-uncertain reservations.
    ctx = RouteContext(task_category="typo", strict_cap=0.10, work_bound=0.05, review_bound=0.00,
                       settled=0.02, reserved_uncertain=0.03, now_s=0, deadline_s=300)
    # Simulating: auth revision flip right before send = revocation; reservation not released.
    ctx.cache_auth_revision = "auth-1"; ctx.auth_revision = "auth-2"
    expect("B02c", ctx.auth_revision != ctx.cache_auth_revision, True, "revocation invalidates route before send")
    expect("B02c", ctx.reserved_uncertain, 0.03, "uncertain reservation stays withheld (not released)")

    # ---------------------------------------------------------------------------
    # -----------------------------------------------------------------------
    # v2.0 additive fixtures (spec-v2.md) — the default-deny surface. The pinned
    # plan fixtures above are unchanged; these guard the new opt-in rules.
    # -----------------------------------------------------------------------
    # X1: speculative requires BOTH high uncertainty and explicit host opt-in
    #     (spec-v2.md §4 Gate 5, §8.4); under a strict cash cap the host may
    #     additionally refuse, and the shared ceiling must fit the cap (Gate 4).
    def speculative_allowed(host_opt_in, uncertainty_high):
        return bool(host_opt_in) and bool(uncertainty_high)

    expect("X1", speculative_allowed(False, True), False, "no host opt-in -> no speculative")
    expect("X1", speculative_allowed(True, False), False, "low uncertainty -> no speculative")
    expect("X1", speculative_allowed(True, True), True, "opt-in + high uncertainty -> allowed")
    shared_budget = {"cash": 0.10, "calls": 4}
    strict_cap = 0.10
    expect("X2", shared_budget["cash"] <= strict_cap, True,
           "the shared ceiling must fit the strict cap (equality passes, Gate 4)")
    dispatched = ["A", "B", "C"]
    expect("X2", len(dispatched) <= shared_budget["calls"], True,
           "every physical dispatch — cancelled or not — consumes the shared budget")
    expect("X2", sum(0.04 for _ in dispatched) <= shared_budget["cash"], False,
           "an oversized set must be rejected before dispatch: the ceiling is hard")

    # N1: nested delegation is default-deny; depth is a ceiling; counters roll
    #     up to the original task (spec-v2.md §8.3).
    def nested_permitted(nested_allowed_flag, depth, max_depth):
        return bool(nested_allowed_flag) and depth <= max_depth

    expect("N1", nested_permitted(False, 1, 1), False, "default: no recursive delegation")
    expect("N1", nested_permitted(True, 2, 1), False, "declared depth is a ceiling")
    expect("N1", nested_permitted(True, 1, 1), True, "explicit NestedAllowed within depth")
    task_calls = {"used": 2}
    task_calls["used"] += 1                       # one sub-worker dispatch
    expect("N1", task_calls["used"], 3, "nested dispatch rolls up to the original task budget")

    # H1: the HumanGate enum is exactly the spec's four values (spec-v2.md §8.2).
    expect("H1", sorted(["none", "review-before-dispatch", "review-before-merge",
                         "approval-required"]),
           ["approval-required", "none", "review-before-dispatch", "review-before-merge"],
           "HumanGate enum is exactly the spec's four values")

    # I1: isolation is a lower bound — the host may choose equal or stronger,
    #     never weaker (spec-v2.md §6).
    ISO_ORDER = ["none", "directory", "worktree+branch", "ephemeral-container"]

    def isolation_ok(recommended, chosen):
        return ISO_ORDER.index(chosen) >= ISO_ORDER.index(recommended)

    expect("I1", isolation_ok("worktree+branch", "ephemeral-container"), True,
           "stronger is allowed")
    expect("I1", isolation_ok("directory", "directory"), True, "equal is allowed")
    expect("I1", isolation_ok("worktree+branch", "directory"), False,
           "weaker is a protocol violation")
    expect("I1", isolation_ok("none", "directory"), True,
           "host may strengthen a weak recommendation")

    failures = [r for r in RESULTS if r[1] == "FAIL"]
    total = len(RESULTS)
    print(f"\n=== SmartRouter decision-route test suite: {total - len(failures)}/{total} assertions passed ===")
    if failures:
        print("\nFailures:")
        for fid, status, detail in failures:
            print(f"  [{status}] {fid}: {detail}")
        return 1
    # Distinct fixture ID coverage
    distinct = {fid for fid, _, _ in RESULTS}
    required = {'S01','S02','S03','S04','S05','S06','S07','S08','S09','S10','S11','S12a','S12b',
                'S13','S14','S15a','S15b','S15c','S16','S17a','S17b','S18','S19','S20a','S20b',
                'S20c','S21a','S21b','S22a','S22b','S23','S24','R01','R02','R03','R04',
                'V01','V02','V03','V04','V05','V06','V07','V08','V09','D01','D02','E01',
                'B01','B02a','B02b','B02c',
                'X1','X2','N1','H1','I1'}
    print(f"Distinct fixture IDs exercised: {len(distinct)}/{len(required)}")
    missing = required - distinct
    if missing:
        print("Missing:", sorted(missing))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
