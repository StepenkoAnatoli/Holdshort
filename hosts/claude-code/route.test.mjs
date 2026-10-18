// Tests for the SmartRouter host adapter (route.mjs). Each test is named after the SmartRouter
// fixture it mirrors (tests/smart_router_decisions.py and references/gates.md at fbe7bca).
// Node built-ins only: node --test docs/orchestration/smartrouter/route.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, readdirSync, existsSync, appendFileSync, cpSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  ADVISORY, CASH_UNCERTAINTY, RouterError, briefFingerprint, computeDecision, decide, dispatch,
  loadPolicy, rate, readLedger, recordOutcome, status, validateBrief
} from './route.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROUTE = join(HERE, 'route.mjs');
// the committed policy carries the usage-windows block (fail-closed: no reading, no route); the base tests run against
// a feature-off fixture with that block deleted, written to a tmp file (lead's ruling R1(a)). Its source is host-policy-1,
// the policy the base tests were written under, frozen in trace/policies/host-policy-1.json (unit sr-policy-2), so a
// policy revision never moves them; the live policy has its own tests (section 'host-policy-2')
const COMMITTED_POLICY_PATH = join(HERE, 'host-policy.json');
const COMMITTED_POLICY = JSON.parse(readFileSync(COMMITTED_POLICY_PATH, 'utf8'));
// host-policy-2, frozen by unit sr-policy-3 (never edited). The usage-window tests were written against its usage block
// and its profile set (the speculative pairs of SW-1/SW-2), and the host-policy-2 assertions are about it: they run on
// this fixture, so revision 3 of the live policy never moves them. The live policy has its own tests (host-policy-3)
const HP2_POLICY_PATH = join(HERE, 'trace', 'policies', 'host-policy-2.json');
const USAGE_POLICY_PATH = HP2_POLICY_PATH;
const USAGE_POLICY = JSON.parse(readFileSync(USAGE_POLICY_PATH, 'utf8'));
const BASE_POLICY = JSON.parse(readFileSync(join(HERE, 'trace', 'policies', 'host-policy-1.json'), 'utf8'));
const POLICY_PATH = join(mkdtempSync(join(tmpdir(), 'sr-host-fixture-')), 'host-policy.json');
writeFileSync(POLICY_PATH, `${JSON.stringify(Object.fromEntries(Object.entries(BASE_POLICY).filter(([k]) => k !== 'usage-windows')), null, 2)}\n`);
const POLICY_TEXT = readFileSync(POLICY_PATH, 'utf8');
const POLICY = JSON.parse(POLICY_TEXT);
const NOW = '2026-10-17T19:00:00Z';
const DEADLINE = '2026-10-18T06:00:00Z';
const OPUS = POLICY.profiles.find((x) => x.id === 'cc-opus-high');
const OPUS_TUPLE = `(${OPUS.id}, ${POLICY.harness.id}, anthropic, ${OPUS.model}, ${OPUS.effort}, ${OPUS.config})`;

function tmp() { return mkdtempSync(join(tmpdir(), 'sr-host-test-')); }

// the current project-stop state every dispatch must carry (N4): nothing stopped
const CLEAR = { redSuite: false, gateOff: false, researchGateFailing: false };
const CLEAR_JSON = JSON.stringify(CLEAR);

function checksFor(category) {
  return POLICY.categories[category].verification.map((name) => ({ command: `run ${name}`, expect: 'pass' }));
}

function req(over = {}) {
  const category = over.category ?? 'review';
  return {
    taskId: 't-1', objective: 'an objective', category, unit: 'unit-a', permittedEffects: ['docs/x.md'],
    sources: ['docs/src.md'], nonGoals: ['no push'], acceptanceChecks: checksFor(category), needsVision: false,
    dataClasses: ['repo-code'], projectStop: { redSuite: false, gateOff: false, researchGateFailing: false },
    previousResult: null, deadline: DEADLINE, now: NOW, ...over
  };
}

function policyWith(mutate) {
  const p = JSON.parse(POLICY_TEXT);
  mutate(p);
  const path = join(tmp(), 'host-policy.json');
  writeFileSync(path, JSON.stringify(p, null, 2));
  return path;
}

// every CLI call runs on the feature-off fixture unless it names a policy itself (R1(a))
function cli(args) {
  const withPolicy = args.includes('--policy') ? args : [...args, '--policy', POLICY_PATH];
  const r = spawnSync(process.execPath, [ROUTE, ...withPolicy], { encoding: 'utf8' });
  return { code: r.status, stdout: r.stdout, stderr: r.stderr };
}

function writeJson(obj) {
  const path = join(tmp(), 'in.json');
  writeFileSync(path, JSON.stringify(obj));
  return path;
}

function outcome(over = {}) {
  return {
    'task-id': 't-1', outcome: 'verification-failed',
    evidence: { checks: [{ command: 'node --test', 'exit-code': 1, 'output-ref': 'run-1.log' }], 'actual-spend': null, 'files-touched': ['docs/x.md'], notes: 'one failing check' },
    'original-brief-fingerprint': 'none', 'owner-profile': 'cc-opus-high', ...over
  };
}

const run = (r, opts = {}) => decide(r, { policyPath: POLICY_PATH, ...opts });

// ---------------------------------------------------------------------------------------------
// Gate 1 - permissions / privacy / workflow
// ---------------------------------------------------------------------------------------------
test('S03: local-only data denies every cloud profile at Gate 1 before anything else; route blocked', () => {
  const d = computeDecision(req({ dataClasses: ['repo-code', 'local-only'] }), loadPolicy(POLICY_PATH), []);
  assert.equal(d.route, 'blocked');
  for (const p of POLICY.profiles) {
    const c = d.candidates[p.id];
    assert.equal(c.eligible, false, p.id);
    assert.equal(c['first-failing-gate'], 1, p.id);
    assert.match(c.reason, /data class 'local-only' is forbidden/);
    // nothing past Gate 1 was evaluated (S17a/S17b: no Gate 2 reasons leak)
    assert.deepEqual(c.walkthrough.slice(1).map((g) => g.result), ['not-reached', 'not-reached', 'not-reached', 'not-reached']);
  }
});

test('S17a/S17b: unknown profile, unknown category, unknown data class, escaping path and unprovidable isolation deny at Gate 1', () => {
  const policy = loadPolicy(POLICY_PATH);
  const unknownProfile = computeDecision(req({ candidates: ['cc-ghost', 'cc-opus-high'] }), policy, []);
  assert.equal(unknownProfile.candidates['cc-ghost']['first-failing-gate'], 1);
  assert.match(unknownProfile.candidates['cc-ghost'].reason, /unknown profile 'cc-ghost' \(default deny\)/);
  assert.equal(unknownProfile.route, 'delegate');

  const unknownCategory = computeDecision(req({ category: 'review', acceptanceChecks: checksFor('review') }), policy, []);
  assert.equal(unknownCategory.route, 'delegate');
  const badCat = computeDecision({ ...req(), category: 'astrology' }, policy, []);
  assert.equal(badCat.route, 'blocked');
  assert.match(badCat.candidates['cc-opus-high'].reason, /unknown category 'astrology'/);

  const unknownClass = computeDecision(req({ dataClasses: ['customer-pii'] }), policy, []);
  assert.equal(unknownClass.route, 'blocked');
  assert.match(unknownClass.candidates['cc-opus-high'].reason, /data class 'customer-pii' not covered by authorization/);

  const escaping = computeDecision(req({ permittedEffects: ['../outside.txt'] }), policy, []);
  assert.equal(escaping.route, 'blocked');
  assert.match(escaping.candidates['cc-opus-high'].reason, /permitted effect '..\/outside.txt' is outside the repository/);

  const container = computeDecision(req({ requiredIsolation: 'ephemeral-container' }), policy, []);
  assert.equal(container.route, 'blocked');
  assert.match(container.candidates['cc-opus-high'].reason, /isolation ephemeral-container required; host provides at most worktree\+branch/);
});

test('S09: a project stop rule (red suite) blocks new work at Gate 1 and names the stop', () => {
  const d = computeDecision(req({ projectStop: { redSuite: true, gateOff: false, researchGateFailing: false } }), loadPolicy(POLICY_PATH), []);
  assert.equal(d.route, 'blocked');
  for (const p of POLICY.profiles) {
    assert.equal(d.candidates[p.id]['first-failing-gate'], 1);
    assert.match(d.candidates[p.id].reason, /^project stop: red suite/);
  }
  const g = computeDecision(req({ projectStop: { redSuite: false, gateOff: true, researchGateFailing: false } }), loadPolicy(POLICY_PATH), []);
  assert.match(g.candidates['cc-opus-high'].reason, /^project stop: GATE_OFF or --no-verify in use/);
});

// ---------------------------------------------------------------------------------------------
// Gate 2 - capabilities
// ---------------------------------------------------------------------------------------------
test('S04/S05: vision required and lacking is a Gate 2 reason; the expensive label does not cure it; tools are checked', () => {
  const policy = loadPolicy(POLICY_PATH);
  const d = computeDecision(req({ category: 'docs-mechanical', estimatedTokens: 50000, needsVision: true }), policy, []);
  const haiku = d.candidates['cc-haiku-low'];
  assert.equal(haiku['first-failing-gate'], 2);
  assert.match(haiku.reason, /vision required, cc-haiku-low lacks it/);
  // the expensive profile has vision but no declared qualification: still a Gate 2 reject, no fallback
  assert.equal(d.candidates['cc-fable-high']['first-failing-gate'], 2);
  assert.match(d.candidates['cc-fable-high'].reason, /cc-fable-high not qualified for docs-mechanical/);
  assert.equal(d.route, 'blocked');

  const noTools = loadPolicy(policyWith((p) => { p.profiles.find((x) => x.id === 'cc-opus-high').tools = false; }));
  const t = computeDecision(req(), noTools, []);
  assert.match(t.candidates['cc-opus-high'].reason, /required tools missing on cc-opus-high: bash, read/);
  const listed = loadPolicy(policyWith((p) => { p.profiles.find((x) => x.id === 'cc-opus-high').tools = ['bash']; }));
  assert.match(computeDecision(req(), listed, []).candidates['cc-opus-high'].reason, /required tools missing on cc-opus-high: read/);
});

test('fresh fingerprint: an unqualified or expired profile fails Gate 2 with "missing or stale capability fingerprint"', () => {
  const policy = loadPolicy(POLICY_PATH);
  const d = computeDecision(req({ candidates: ['cc-sonnet-high'] }), policy, []);
  assert.equal(d.candidates['cc-sonnet-high']['first-failing-gate'], 2);
  assert.match(d.candidates['cc-sonnet-high'].reason, /missing or stale capability fingerprint/);
  assert.equal(d.route, 'blocked'); // never dispatched on, and never resurrected by a profile outside the list (E01)

  const expired = loadPolicy(policyWith((p) => { p.profiles.find((x) => x.id === 'cc-opus-high').expires = '2026-10-01'; }));
  const e = computeDecision(req({ candidates: ['cc-opus-high'] }), expired, []);
  assert.equal(e.candidates['cc-opus-high']['first-failing-gate'], 2);
  assert.match(e.candidates['cc-opus-high'].reason, /missing or stale capability fingerprint \(expired 2026-10-01\)/);

  // equality is expiry (gates.md B02a/B02b): expires on the day `now` starts
  const edge = loadPolicy(policyWith((p) => { p.profiles.find((x) => x.id === 'cc-opus-high').expires = '2026-10-17'; }));
  const eq = computeDecision(req({ candidates: ['cc-opus-high'], now: '2026-10-17T00:00:00Z' }), edge, []);
  assert.equal(eq.candidates['cc-opus-high']['first-failing-gate'], 2);
});

test('context headroom: estimated tokens must be strictly below headroom-tested', () => {
  const policy = loadPolicy(POLICY_PATH);
  const at = computeDecision(req({ category: 'docs-mechanical', estimatedTokens: 92000, allowDirect: false }), policy, []);
  assert.match(at.candidates['cc-haiku-low'].reason, /context: 92000 tokens not below headroom-tested 92000 on cc-haiku-low/);
  const below = computeDecision(req({ category: 'docs-mechanical', estimatedTokens: 91999, allowDirect: false }), policy, []);
  assert.equal(below.candidates['cc-haiku-low'].eligible, true);
});

// ---------------------------------------------------------------------------------------------
// Gate 3 - verification
// ---------------------------------------------------------------------------------------------
test('S10/S15c: a missing required verification check blocks at Gate 3 before start', () => {
  const policy = loadPolicy(POLICY_PATH);
  const checks = checksFor('build-core').filter((c) => !/refute-first review/.test(c.command));
  const d = computeDecision(req({ category: 'build-core', acceptanceChecks: checks }), policy, []);
  assert.equal(d.route, 'blocked');
  for (const id of ['cc-opus-high', 'cc-fable-xhigh']) {
    assert.equal(d.candidates[id]['first-failing-gate'], 3, id);
    assert.equal(d.candidates[id].reason, 'verification prerequisite missing: refute-first review (blocked before start)');
  }
  // names are matched case-insensitively against command or expect
  const upper = checksFor('build-core').map((c) => ({ command: c.command.toUpperCase(), expect: 'PASS' }));
  assert.equal(computeDecision(req({ category: 'build-core', acceptanceChecks: upper }), policy, []).route, 'delegate');
  // a required review with no review-qualified fresh profile is an unavailable check
  const noReviewer = loadPolicy(policyWith((p) => { for (const x of p.profiles) x['qualified-for'] = x['qualified-for'].filter((c) => c !== 'review'); }));
  const r = computeDecision(req({ category: 'build-core' }), noReviewer, []);
  assert.equal(r.route, 'blocked');
  assert.match(r.candidates['cc-opus-high'].reason, /verification prerequisite missing: no candidate passes Gates 1-2 as reviewer for 'refute-first review'/);
});

// ---------------------------------------------------------------------------------------------
// Gate 4 - affordability
// ---------------------------------------------------------------------------------------------
function dispatchRecords(taskId, profileIds) {
  return profileIds.map((id, i) => {
    const p = POLICY.profiles.find((x) => x.id === id);
    const tuple = `(${p.id}, ${POLICY.harness.id}, anthropic, ${p.model}, ${p.effort}, ${p.config})`;
    return { 'task-id': taskId, seq: i + 1, kind: 'dispatch', ts: NOW, profile: tuple, counters: { 'calls-used': i + 1, 'calls-limit': 6, 'cash-spent': null, 'cash-cap': null, 'repairs-used': 0, 'repairs-allowed': 1 }, deadline: DEADLINE, 'brief-fingerprint': null, detail: 'x', 'outcome-ref': null };
  });
}
const FIVE = ['cc-fable-high', 'cc-opus-high', 'cc-haiku-low', 'cc-sonnet-high', 'cc-fable-xhigh'];

test('S08-shaped: exhausted call slots and deadline equality block at Gate 4; cash never blocks', () => {
  const policy = loadPolicy(POLICY_PATH);
  const full = computeDecision(req(), policy, dispatchRecords('t-1', [...FIVE, 'cc-opus-high']));
  assert.equal(full.route, 'blocked');
  assert.equal(full.candidates['cc-opus-high']['first-failing-gate'], 4);
  assert.match(full.candidates['cc-opus-high'].reason, /call slots exhausted: 6 used \+ 1 > 6 calls-per-task/);
  // five used: equality passes (used + 1 <= limit)
  const five = computeDecision(req(), policy, dispatchRecords('t-1', FIVE));
  assert.equal(five.route, 'delegate');
  assert.equal(five.candidates['cc-opus-high'].eligible, true);

  const eq = computeDecision(req({ now: DEADLINE }), policy, []);
  assert.equal(eq.route, 'blocked');
  assert.match(eq.candidates['cc-opus-high'].reason, /deadline expired: now 2026-10-18T06:00:00Z not strictly before 2026-10-18T06:00:00Z/);
  const justBefore = computeDecision(req({ now: '2026-10-18T05:59:59Z' }), policy, []);
  assert.equal(justBefore.route, 'delegate');

  // cash is estimate-only: a huge bound still routes, and the Uncertainty line says why
  const big = computeDecision(req({ category: 'build-core', estimatedTokens: 500000 }), policy, []);
  assert.equal(big.route, 'delegate');
  assert.ok(big['all-in-bound-usd'] > 15);
  assert.ok(big.uncertainty.includes(CASH_UNCERTAINTY));
  assert.equal(CASH_UNCERTAINTY, 'cash: estimate only, no host accounting (subscription); not a strict cap');

  // an unpriced model is an unknown bound: Gate 4 reject, not a silent zero
  const unpriced = loadPolicy(policyWith((p) => { delete p.prices[OPUS.model]; }));
  const u = computeDecision(req({ candidates: ['cc-opus-high'] }), unpriced, []);
  assert.ok(u.candidates['cc-opus-high'].reason.startsWith(`unknown price for ${OPUS.model}`), u.candidates['cc-opus-high'].reason);
});

test('deadline-per-task-hours caps the Brief deadline from the task start', () => {
  const d = computeDecision(req({ deadline: '2026-10-20T00:00:00Z' }), loadPolicy(POLICY_PATH), []);
  assert.equal(d.brief.allowance.deadline, '2026-10-18T07:00:00Z');
  assert.match(d.text, /capped by deadline-per-task-hours 12/);
});

test('R01-R03: a second same-profile repair is refused by dispatch (exit 3) and by Gate 4; a different profile is a fresh decision', () => {
  const trace = tmp();
  const fixReq = (over) => req({ taskId: 'r-1', category: 'fix', ...over });
  const first = run(fixReq(), { traceDir: trace });
  assert.equal(first.decision.profile, 'cc-opus-high');
  dispatch('r-1', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  const prev = outcome({ 'task-id': 'r-1', 'original-brief-fingerprint': first.briefFingerprint });
  recordOutcome(prev, { traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  const second = run(fixReq({ previousResult: prev }), { traceDir: trace });
  assert.equal(second.decision.profile, 'cc-opus-high'); // first repair allowed
  const rep = dispatch('r-1', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  assert.equal(rep.counters['repairs-used'], 1);
  recordOutcome({ ...prev, 'original-brief-fingerprint': second.briefFingerprint }, { traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  const third = run(fixReq({ previousResult: prev }), { traceDir: trace });
  assert.equal(third.decision.candidates['cc-opus-high']['first-failing-gate'], 4);
  assert.match(third.decision.candidates['cc-opus-high'].reason, /same-profile repairs exhausted: 1 used \+ 1 > 1/);
  assert.equal(third.decision.profile, 'cc-fable-high'); // fresh decision on a different profile, not a repair
  const refused = cli(['dispatch', 'r-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW, '--deviation', 'try anyway']);
  assert.equal(refused.code, 3);
  assert.match(refused.stderr, /same-profile repairs exhausted/);
  const fresh = dispatch('r-1', 'cc-fable-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  assert.equal(fresh.counters['repairs-used'], 1);
  assert.equal(fresh.counters['calls-used'], 3);
});

test('dispatch refuses without a decision, against a blocked decision, on an unrecorded profile switch, and on a second dispatch of one decision', () => {
  const trace = tmp();
  const none = cli(['dispatch', 'd-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW]);
  assert.equal(none.code, 3);
  assert.match(none.stderr, /no decision recorded for task d-1/);
  run(req({ taskId: 'd-1', projectStop: { redSuite: true, gateOff: false, researchGateFailing: false } }), { traceDir: trace });
  const blocked = cli(['dispatch', 'd-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW, '--deviation', 'x']);
  assert.equal(blocked.code, 3);
  assert.match(blocked.stderr, /latest decision for d-1 is blocked/);
  run(req({ taskId: 'd-1' }), { traceDir: trace });
  const switched = cli(['dispatch', 'd-1', 'cc-fable-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW]);
  assert.equal(switched.code, 3);
  assert.match(switched.stderr, /decided cc-opus-high; dispatching cc-fable-high is a host deviation: pass --deviation/);
  const ok = cli(['dispatch', 'd-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW]);
  assert.equal(ok.code, 0, ok.stderr);
  const again = cli(['dispatch', 'd-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW]);
  assert.equal(again.code, 3);
  assert.match(again.stderr, /already dispatched/);
  const late = cli(['dispatch', 'd-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', DEADLINE]);
  assert.equal(late.code, 3); // refused as already dispatched; the deadline refusal is pinned by 'F6 dispatch deadline'
  const unknown = cli(['dispatch', 'd-1', 'cc-ghost', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW]);
  assert.equal(unknown.code, 2);
  // a recorded deviation is allowed and marked
  run(req({ taskId: 'd-2' }), { traceDir: trace });
  const dev = dispatch('d-2', 'cc-fable-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW, deviation: 'pre-adapter profile' });
  assert.equal(dev.deviation, true);
  assert.match(dev.detail, /^host deviation: pre-adapter profile; route said cc-opus-high/);
});

// ---------------------------------------------------------------------------------------------
// Gate 5 - economics
// ---------------------------------------------------------------------------------------------
test('S02/D01: economics picks the lowest all-in bound; direct wins small tasks, delegation wins above direct-max-tokens', () => {
  const policy = loadPolicy(POLICY_PATH);
  const tiny = computeDecision(req({ category: 'build-core', estimatedTokens: 15000 }), policy, []);
  assert.equal(tiny.route, 'direct');
  assert.equal(tiny.profile, 'cc-fable-xhigh');
  assert.equal(tiny['all-in-bound-usd'], 0.75);
  const above = computeDecision(req({ category: 'build-core', estimatedTokens: 15001 }), policy, []);
  assert.equal(above.route, 'delegate');
  assert.equal(above.candidates['cc-fable-xhigh'].reason, 'direct unsuitable: 15001 tokens > direct-max-tokens 15000');
  const noDirect = computeDecision(req({ category: 'build-core', estimatedTokens: 1000, allowDirect: false }), policy, []);
  assert.equal(noDirect.route, 'delegate');
  assert.equal(noDirect.candidates['cc-fable-xhigh'].reason, 'direct unsuitable: allowDirect is false');

  const core = computeDecision(req({ category: 'build-core' }), policy, []);
  assert.equal(core.route, 'delegate');
  assert.equal(core.profile, 'cc-opus-high');
  assert.equal(core['all-in-bound-usd'], 11.5); // 6.32 work + 4.18 review + 1.00 brief overhead
  const review = computeDecision(req({ category: 'review' }), policy, []);
  assert.equal(review.profile, 'cc-opus-high');
  assert.deepEqual(review['eligible-ordered'], ['cc-opus-high', 'cc-fable-high']);
  assert.equal(review.candidates['cc-fable-high']['all-in-bound-usd'], 11.45);
  assert.equal(review.candidates['cc-opus-high']['review-bound-usd'], 0);
  const docs = computeDecision(req({ category: 'docs-mechanical', estimatedTokens: 50000 }), policy, []);
  assert.equal(docs.route, 'delegate');
  assert.equal(docs.profile, 'cc-haiku-low');

  // ties: lower output rate, then alphabetical id
  const twin = loadPolicy(policyWith((p) => { p.profiles.push({ ...p.profiles.find((x) => x.id === 'cc-opus-high'), id: 'cc-aaa-opus' }); }));
  assert.equal(computeDecision(req(), twin, []).profile, 'cc-aaa-opus');
});

test('E01: an empty eligible set is blocked even when a qualified profile sits outside candidates; listed, it routes', () => {
  const policy = loadPolicy(POLICY_PATH);
  // first leg (fixture E01): the only candidate fails Gate 2; the qualified profile is unavailable (not a candidate)
  const d = computeDecision(req({ candidates: ['cc-sonnet-high'] }), policy, []);
  assert.equal(d.route, 'blocked');
  assert.equal(d.profile, null);
  assert.equal(Object.values(d.candidates).filter((c) => c['first-failing-gate'] === 2).length, 1);
  assert.match(d.text, /^Route: {13}blocked$/m);
  assert.match(d.text, /^Profile: {11}none — blocked$/m);
  assert.equal(d.brief, null);
  // a would-be-eligible non-candidate is a hint in Uncertainty, never a route (no empty-set resurrection)
  assert.deepEqual(d['eligible-outside-candidates'], ['cc-opus-high', 'cc-fable-high']);
  assert.ok(d.uncertainty.some((u) => /^not among candidates: cc-opus-high, cc-fable-high would pass all five gates/.test(u)), d.uncertainty.join('|'));
  // no fallback to a cheaper tier to avoid blocking (gates.md Gate 5)
  const docs = computeDecision(req({ category: 'docs-mechanical', estimatedTokens: 50000, candidates: ['cc-fable-xhigh', 'cc-opus-high'] }), policy, []);
  assert.equal(docs.route, 'blocked');
  assert.equal(docs.profile, null);
  // second leg: with the qualified profile available, it is the eligible candidate and the route delegates to it
  const d2 = computeDecision(req({ candidates: ['cc-sonnet-high', 'cc-opus-high'] }), policy, []);
  assert.equal(d2.route, 'delegate');
  assert.equal(d2.profile, 'cc-opus-high');
  assert.equal(d2.candidates['cc-sonnet-high']['first-failing-gate'], 2);
});

test('speculative only with the host opt-in and high uncertainty', () => {
  const policy = loadPolicy(POLICY_PATH);
  assert.equal(computeDecision(req({ uncertainty: 'high' }), policy, []).route, 'delegate');
  const s = computeDecision(req({ uncertainty: 'high', hostOptIns: { speculative: true } }), policy, []);
  assert.equal(s.route, 'speculative');
  assert.deepEqual(s['speculative-set'].candidates.map((c) => c.profile), ['cc-opus-high', 'cc-fable-high']);
  assert.equal(s['speculative-set']['shared-budget'].calls, 2);
  assert.equal(s['speculative-set']['winner-owns'], true);
  assert.equal(computeDecision(req({ hostOptIns: { speculative: true } }), policy, []).route, 'delegate');
});

// ---------------------------------------------------------------------------------------------
// Output, Brief and ledger
// ---------------------------------------------------------------------------------------------
test('S24: every output carries the Advisory line and the adapter never claims or records a dispatch', () => {
  assert.equal(ADVISORY, 'Advisory: recommendation only — no dispatch performed or claimed');
  const trace = tmp();
  const cases = [req({ taskId: 'a-1' }), req({ taskId: 'a-2', projectStop: { redSuite: true, gateOff: false, researchGateFailing: false } }),
    req({ taskId: 'a-3', estimatedTokens: 1000 }), req({ taskId: 'a-4', category: 'docs-mechanical', estimatedTokens: 50000, candidates: ['cc-opus-high'] })];
  const routes = [];
  for (const r of cases) {
    const out = cli(['decide', writeJson(r), '--trace', trace]);
    assert.equal(out.code, 0, out.stderr);
    assert.ok(out.stdout.includes(`\n${ADVISORY}\n`), out.stdout);
    assert.doesNotMatch(out.stdout, /dispatched to|dispatch performed(?! or claimed)/i);
    routes.push(/^Route: +(\S+)/m.exec(out.stdout)[1]);
  }
  assert.deepEqual(routes, ['delegate', 'blocked', 'direct', 'blocked']);
  assert.deepEqual(readLedger(trace).map((r) => r.kind), ['decision', 'decision', 'decision', 'decision']);
  const blocked = cli(['decide', writeJson(req({ taskId: 'a-5', dataClasses: ['secrets'] })), '--trace', trace]);
  assert.match(blocked.stdout, /^Profile: {11}none — blocked$/m);
  assert.match(blocked.stdout, /^Reservations: {6}unknown\/blocked$/m);
  // a nested opt-in cannot be honoured: this host cannot produce or enforce a NestedBrief (spec §14)
  const nested = computeDecision(req({ hostOptIns: { 'nested-allowed': true, 'max-nesting-depth': 1 } }), loadPolicy(POLICY_PATH), []);
  assert.match(nested.text, /^NestedAllowed: {5}no$/m);
  assert.ok(nested.uncertainty.some((u) => /nested-allowed opt-in refused/.test(u)));
});

test('decide prints the Required output format block, the Advisory line and the Brief for delegate; exit 2 on an invalid request', () => {
  const trace = tmp();
  const out = cli(['decide', writeJson(req({ taskId: 'o-1', unit: 'Host Adapter' })), '--trace', trace]);
  assert.equal(out.code, 0, out.stderr);
  const labels = out.stdout.split('\n').slice(0, 13).map((l) => l.split(':')[0]);
  assert.deepEqual(labels, ['Difficulty', 'Route', 'Profile', 'Isolation', 'IsolationReason', 'Owner', 'HumanGate', 'NestedAllowed', 'MaxNestingDepth', 'Reservations', 'Calls', 'Deadline', 'Uncertainty']);
  assert.ok(out.stdout.split('\n').includes(`Profile:           ${OPUS_TUPLE}`), out.stdout);
  const brief = JSON.parse(out.stdout.slice(out.stdout.indexOf('Brief:\n') + 7));
  assert.equal(brief['branch-hint'], 'build/host-adapter');
  assert.equal(brief.allowance['cash-basis'], 'estimate-only');
  assert.equal(brief.allowance.calls, 6);
  assert.equal(brief.ownership, 'worker');
  assert.equal(brief['nested-allowed'], false);
  assert.ok(existsSync(join(trace, 'decisions', 'o-1-1.json')));
  const bad = cli(['decide', writeJson({ ...req(), taskId: '../evil' }), '--trace', trace]);
  assert.equal(bad.code, 2);
  const missing = cli(['decide', writeJson({ taskId: 'x' }), '--trace', trace]);
  assert.equal(missing.code, 2);
  // a Brief whose allowance exceeds the remaining slots is refused by validation
  assert.throws(() => validateBrief({ ...brief, allowance: { ...brief.allowance, calls: 7 } }, { callsRemaining: 6, repairsAllowed: 1, now: NOW }), RouterError);
});

test('ledger: seq is monotonic per task, counters are task totals, fingerprints are canonical; bad outcomes and corrupt ledgers are refused', () => {
  const trace = tmp();
  const d1 = run(req({ taskId: 'l-1' }), { traceDir: trace });
  const d1b = run(req({ taskId: 'l-1' }), { traceDir: trace });
  assert.equal(d1.record.seq, 1);
  assert.equal(d1b.record.seq, 2); // a second decision continues, never restarts
  run(req({ taskId: 'l-2' }), { traceDir: trace });
  const disp = dispatch('l-1', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  assert.equal(disp.seq, 3);
  assert.equal(disp['brief-fingerprint'], d1b.briefFingerprint);
  const out = recordOutcome(outcome({ 'task-id': 'l-1', outcome: 'accepted', 'original-brief-fingerprint': d1b.briefFingerprint }), { traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  assert.equal(out.seq, 4);
  assert.equal(out['outcome-ref'], 'l-1');
  assert.equal(out['dispatch-seq'], 3);
  assert.deepEqual(out.counters, { 'calls-used': 1, 'calls-limit': 6, 'cash-spent': null, 'cash-cap': null, 'repairs-used': 0, 'repairs-allowed': 1 });
  const ledger = readLedger(trace);
  assert.deepEqual(ledger.filter((r) => r['task-id'] === 'l-1').map((r) => [r.seq, r.kind]), [[1, 'decision'], [2, 'decision'], [3, 'dispatch'], [4, 'outcome']]);
  assert.equal(ledger.find((r) => r['task-id'] === 'l-2').seq, 1);

  const s = status('l-1', { traceDir: trace, policyPath: POLICY_PATH });
  assert.match(s.text, /calls: 1 \/ 6/);
  assert.match(s.text, /repairs: 0 \/ 1/);

  // fingerprint: stable for the same Brief (key order irrelevant), different for a changed objective
  assert.equal(d1.briefFingerprint, d1b.briefFingerprint);
  const reordered = Object.fromEntries(Object.entries(d1.brief).reverse());
  assert.equal(briefFingerprint(reordered), d1.briefFingerprint);
  assert.match(d1.briefFingerprint, /^[0-9a-f]{64}$/);
  assert.notEqual(run(req({ taskId: 'l-3', objective: 'another objective' }), { traceDir: trace }).briefFingerprint, d1.briefFingerprint);

  const unknownTask = cli(['outcome', writeJson(outcome({ 'task-id': 'nope' })), '--trace', trace, '--now', NOW]);
  assert.equal(unknownTask.code, 3);
  assert.match(unknownTask.stderr, /unknown task nope/);
  const noDispatch = cli(['outcome', writeJson(outcome({ 'task-id': 'l-2' })), '--trace', trace, '--now', NOW]);
  assert.equal(noDispatch.code, 3);
  assert.match(noDispatch.stderr, /no dispatch of cc-opus-high recorded for task l-2/);
  const wrongFp = cli(['outcome', writeJson(outcome({ 'task-id': 'l-1', 'original-brief-fingerprint': 'f'.repeat(64) })), '--trace', trace, '--now', NOW]);
  assert.equal(wrongFp.code, 3);
  const badEnum = cli(['outcome', writeJson(outcome({ 'task-id': 'l-1', outcome: 'great' })), '--trace', trace, '--now', NOW]);
  assert.equal(badEnum.code, 2);

  const before = readFileSync(join(trace, 'ledger.jsonl'), 'utf8');
  appendFileSync(join(trace, 'ledger.jsonl'), '{"task-id": "l-1", "seq": 5, broken\n');
  const corrupt = cli(['decide', writeJson(req({ taskId: 'l-1' })), '--trace', trace]);
  assert.equal(corrupt.code, 4);
  assert.match(corrupt.stderr, /ledger line \d+ is unparseable; refusing to read or append/);
  assert.equal(readFileSync(join(trace, 'ledger.jsonl'), 'utf8'), `${before}{"task-id": "l-1", "seq": 5, broken\n`);
});

test('determinism: the same request and ledger give a byte-identical decision file', () => {
  const a = tmp();
  const b = tmp();
  run(req({ taskId: 'det-1' }), { traceDir: a });
  run(req({ taskId: 'det-1' }), { traceDir: b });
  assert.equal(readFileSync(join(a, 'decisions', 'det-1-1.json'), 'utf8'), readFileSync(join(b, 'decisions', 'det-1-1.json'), 'utf8'));
  assert.equal(readFileSync(join(a, 'ledger.jsonl'), 'utf8'), readFileSync(join(b, 'ledger.jsonl'), 'utf8'));
});

// ---------------------------------------------------------------------------------------------
// Learning loop
// ---------------------------------------------------------------------------------------------
function cycle(trace, taskId, category, profile, value, deviation) {
  const d = run(req({ taskId, category }), { traceDir: trace });
  dispatch(taskId, profile, { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW, deviation });
  recordOutcome(outcome({ 'task-id': taskId, outcome: value, 'owner-profile': profile, 'original-brief-fingerprint': d.briefFingerprint }), { traceDir: trace, policyPath: POLICY_PATH, now: NOW });
}
const failedFix = (trace, taskId) => cycle(trace, taskId, 'fix', 'cc-opus-high', 'verification-failed');
// a qualification run on an unqualified profile: dispatch refuses it (F3), so the record stands for a run the lead
// recorded by hand, outside SmartRouter routing (README 'How to add evidence'); it is marked as a deviation
function handQualificationRun(trace, taskId, category, profile, value) {
  const d = run(req({ taskId, category }), { traceDir: trace });
  const p = POLICY.profiles.find((x) => x.id === profile);
  const tuple = `(${p.id}, ${POLICY.harness.id}, anthropic, ${p.model}, ${p.effort}, ${p.config})`;
  appendFileSync(join(trace, 'ledger.jsonl'), `${JSON.stringify({ 'task-id': taskId, seq: 2, kind: 'dispatch', ts: NOW, profile: tuple, counters: { 'calls-used': 1, 'calls-limit': 6, 'cash-spent': null, 'cash-cap': null, 'repairs-used': 0, 'repairs-allowed': 1 }, deadline: d.decision.deadline, 'brief-fingerprint': null, detail: 'host deviation: qualification run recorded by hand', 'outcome-ref': null, deviation: true })}\n`);
  recordOutcome(outcome({ 'task-id': taskId, outcome: value, 'owner-profile': profile, 'original-brief-fingerprint': d.briefFingerprint }), { traceDir: trace, policyPath: POLICY_PATH, now: NOW });
}

test('learning: two verification-failed fixes propose demotion, change no policy, and the next decide names the proposal', () => {
  const trace = tmp();
  failedFix(trace, 'f-1');
  assert.equal(rate({ traceDir: trace, policyPath: POLICY_PATH, now: NOW }).proposals.length, 0);
  failedFix(trace, 'f-2');
  const r = rate({ traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  assert.deepEqual(r.proposals.map((p) => [p.kind, p.profile, p.category]), [['demote', 'cc-opus-high', 'fix']]);
  assert.match(r.text, /PROPOSAL demote cc-opus-high from fix: 2 consecutive verification-failed \(f-1, f-2\); not applied/);
  assert.equal(r.stats.stats['cc-opus-high'].fix['verification-failed'], 2);
  assert.equal(readFileSync(POLICY_PATH, 'utf8'), POLICY_TEXT);
  const next = run(req({ taskId: 'f-3', category: 'fix' }), { traceDir: trace });
  assert.equal(next.decision.profile, 'cc-opus-high'); // routed by the policy as it stands
  assert.ok(next.decision.uncertainty.some((u) => /pending proposal \(not applied\): demote cc-opus-high from fix/.test(u)));
  assert.match(next.text, /^Uncertainty: .*pending proposal \(not applied\): demote cc-opus-high from fix/m);
  rate({ traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  const first = readFileSync(join(trace, 'qualification-stats.json'), 'utf8');
  const cliRate = cli(['rate', '--trace', trace, '--now', NOW]);
  assert.equal(cliRate.code, 0, cliRate.stderr);
  assert.equal(readFileSync(join(trace, 'qualification-stats.json'), 'utf8'), first);
  // an accepted outcome in between breaks "consecutive"
  const t2 = tmp();
  failedFix(t2, 'g-1');
  cycle(t2, 'g-2', 'fix', 'cc-opus-high', 'accepted');
  failedFix(t2, 'g-3');
  assert.equal(rate({ traceDir: t2, policyPath: POLICY_PATH, now: NOW }).proposals.length, 0);
});

test('learning: cost-overrun demotes, three accepted hand-recorded qualification runs propose qualification, near expiry is flagged', () => {
  const trace = tmp();
  cycle(trace, 'c-1', 'review', 'cc-opus-high', 'cost-overrun');
  for (const id of ['q-1', 'q-2']) handQualificationRun(trace, id, 'build-core', 'cc-fable-high', 'accepted');
  assert.ok(!rate({ traceDir: trace, policyPath: POLICY_PATH, now: NOW }).proposals.some((p) => p.kind === 'qualify'), 'two accepted outcomes are not enough');
  handQualificationRun(trace, 'q-3', 'build-core', 'cc-fable-high', 'accepted');
  const r = rate({ traceDir: trace, policyPath: POLICY_PATH, now: '2027-01-05T00:00:00Z' });
  const kinds = r.proposals.map((p) => `${p.kind} ${p.profile} ${p.category}`);
  assert.ok(kinds.includes('demote cc-opus-high review'), kinds.join('|'));
  assert.ok(kinds.includes('qualify cc-fable-high build-core'), kinds.join('|'));
  assert.equal(r.stats.stats['cc-fable-high']['build-core'].deviations, 3);
  assert.ok(r.flags.some((f) => f.profile === 'cc-opus-high' && /expires 2027-01-15/.test(f.reason)));
  assert.equal(rate({ traceDir: trace, policyPath: POLICY_PATH, now: NOW }).flags.length, 0);
});

// ---------------------------------------------------------------------------------------------
// Golden: the lead's hand-walked decisions
// ---------------------------------------------------------------------------------------------
const goldenDir = join(HERE, 'trace', 'decisions');
// the hand-walked decisions were walked under host-policy-1, frozen as a fixture (trace/policies/host-policy-1.json,
// never edited; unit sr-policy-2): each golden is decided through the CLI with --policy on that fixture's feature-off
// derivative (R1(a)), so a policy revision never moves a golden
const FIXTURE_POLICY_PATH = join(HERE, 'trace', 'policies', 'host-policy-1.json');
const featureOff = (p) => `${JSON.stringify(Object.fromEntries(Object.entries(p).filter(([k]) => k !== 'usage-windows')), null, 2)}\n`;
function fixtureOffPath() {
  const path = join(tmp(), 'host-policy-1-off.json');
  writeFileSync(path, featureOff(JSON.parse(readFileSync(FIXTURE_POLICY_PATH, 'utf8'))));
  return path;
}
function cliDecide(request, policyPath) {
  const trace = tmp();
  const r = cli(['decide', writeJson(request), '--trace', trace, '--policy', policyPath]);
  assert.equal(r.code, 0, r.stderr);
  return JSON.parse(readFileSync(join(trace, 'decisions', `${request.taskId}-1.json`), 'utf8'));
}
const HAND = readdirSync(goldenDir).filter((f) => f.startsWith('hand-')).sort();
for (const file of HAND) {
  test(`golden: ${file} is reproduced exactly under its fixture host-policy-1 (--policy)`, () => {
    const golden = JSON.parse(readFileSync(join(goldenDir, file), 'utf8'));
    const decided = cliDecide(golden.request, fixtureOffPath());
    assert.equal(decided.bindings['policy-revision'], 'host-policy-1');
    const got = decided.decision;
    const want = golden.decision;
    for (const k of ['route', 'profile', 'isolation', 'owner', 'human-gate', 'nested-allowed', 'max-nesting-depth', 'estimated-tokens', 'all-in-bound-usd', 'eligible-ordered', 'advisory']) {
      assert.deepEqual(got[k], want[k], k);
    }
    // the hand-walked decisions predate the usage windows and are never hand-edited: uncertainty is compared after
    // dropping every 'usage windows:' line (lead's ruling R1(b)); everything else stays an exact comparison
    const dropUsage = (lines) => lines.filter((l) => !l.startsWith('usage windows:'));
    assert.deepEqual(dropUsage(got.uncertainty), dropUsage(want.uncertainty), 'uncertainty');
    assert.deepEqual(Object.keys(got.candidates), Object.keys(want.candidates), 'the five host-policy-1 profiles, in order');
    for (const [id, c] of Object.entries(want.candidates)) {
      assert.equal(got.candidates[id].eligible, c.eligible, id);
      if (c.eligible) {
        for (const k of ['kind', 'all-in-bound-usd', 'work-bound-usd', 'review-bound-usd']) assert.equal(got.candidates[id][k], c[k], `${id} ${k}`);
      } else {
        assert.equal(got.candidates[id]['first-failing-gate'], c['first-failing-gate'], id);
        assert.ok(got.candidates[id].reason.includes(c.reason), `${id}: "${got.candidates[id].reason}" lacks "${c.reason}"`);
      }
    }
  });
}

test('monotonic task clock: decide, dispatch and outcome refuse a `now` earlier than the task\'s latest ledger event', () => {
  const trace = tmp();
  const d = run(req({ taskId: 'm-1', now: '2026-10-17T20:00:00Z' }), { traceDir: trace });
  const early = cli(['decide', writeJson(req({ taskId: 'm-1', now: '2026-10-17T19:59:59Z' })), '--trace', trace]);
  assert.equal(early.code, 2);
  assert.match(early.stderr, /now 2026-10-17T19:59:59Z precedes the latest ledger event for m-1 \(2026-10-17T20:00:00Z\)/);
  const earlyDispatch = cli(['dispatch', 'm-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', '2026-10-17T19:00:00Z']);
  assert.equal(earlyDispatch.code, 2);
  dispatch('m-1', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: '2026-10-17T20:00:00Z' });
  const earlyOutcome = cli(['outcome', writeJson(outcome({ 'task-id': 'm-1', 'original-brief-fingerprint': d.briefFingerprint })), '--trace', trace, '--now', '2026-10-17T19:00:00Z']);
  assert.equal(earlyOutcome.code, 2);
  assert.deepEqual(readLedger(trace).map((r) => r.kind), ['decision', 'dispatch']);
});

test('S08-shaped dispatch: with calls-per-task dispatches already recorded, dispatch refuses (exit 3) and writes nothing', () => {
  const trace = tmp();
  const ids = [...FIVE, 'cc-opus-high'];
  const recs = dispatchRecords('s-1', ids).map((r, i) => ({ ...r, counters: { ...r.counters, 'repairs-used': i === 5 ? 1 : 0 } }));
  const decided = { ...recs[1], seq: 7, kind: 'decision', counters: recs[5].counters, detail: 'route delegate (hand-walked)' };
  writeFileSync(join(trace, 'ledger.jsonl'), [...recs, decided].map((r) => JSON.stringify(r)).join('\n') + '\n');
  const before = readFileSync(join(trace, 'ledger.jsonl'), 'utf8');
  const out = cli(['dispatch', 's-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW]);
  assert.equal(out.code, 3);
  assert.match(out.stderr, /call slots exhausted: 6 used \+ 1 > 6 calls-per-task/);
  assert.equal(readFileSync(join(trace, 'ledger.jsonl'), 'utf8'), before);
});

test('R01-R03 under a profile rename: the same model, effort and config under a new id is still the same profile', () => {
  const trace = tmp();
  const fixReq = (over) => req({ taskId: 'rn-1', category: 'fix', ...over });
  const first = run(fixReq(), { traceDir: trace });
  dispatch('rn-1', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  const prev = outcome({ 'task-id': 'rn-1', 'original-brief-fingerprint': first.briefFingerprint });
  recordOutcome(prev, { traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  const second = run(fixReq({ previousResult: prev }), { traceDir: trace });
  dispatch('rn-1', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  recordOutcome({ ...prev, 'original-brief-fingerprint': second.briefFingerprint }, { traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  const renamed = policyWith((p) => { p.profiles.find((x) => x.id === 'cc-opus-high').id = 'cc-opus-renamed'; });
  const third = decide(fixReq({ previousResult: { ...prev, 'owner-profile': OPUS_TUPLE } }), { traceDir: trace, policyPath: renamed });
  assert.equal(third.decision.candidates['cc-opus-renamed']['first-failing-gate'], 4);
  assert.match(third.decision.candidates['cc-opus-renamed'].reason, /same-profile repairs exhausted/);
  const out = cli(['dispatch', 'rn-1', 'cc-opus-renamed', '--project-stop', CLEAR_JSON, '--trace', trace, '--policy', renamed, '--now', NOW, '--deviation', 'rename']);
  assert.equal(out.code, 3);
  assert.match(out.stderr, /same-profile repairs exhausted/);
});

test('F1 pre-dispatch recheck (gates.md binding item 3): an expiry crossing, a revocation or a changed route between decide and dispatch refuses the dispatch', () => {
  const trace = tmp();
  const ledger = join(trace, 'ledger.jsonl');
  // (A) the capability fingerprint expires between decide and dispatch
  const d = run(req({ taskId: 'pb-1', category: 'fix', now: '2027-01-14T23:00:00Z', deadline: '2027-01-15T06:00:00Z' }), { traceDir: trace });
  assert.equal(d.decision.profile, 'cc-opus-high');
  let before = readFileSync(ledger, 'utf8');
  const expired = cli(['dispatch', 'pb-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', '2027-01-15T00:30:00Z']);
  assert.equal(expired.code, 3, expired.stdout);
  assert.match(expired.stderr, /pre-dispatch recheck refused cc-opus-high \(decision seq 1\): gate 2: missing or stale capability fingerprint \(expired 2027-01-15\)/);
  assert.equal(readFileSync(ledger, 'utf8'), before);
  // (B) the data class is revoked between decide and dispatch: revocation wins over the stored decision
  run(req({ taskId: 'pb-2' }), { traceDir: trace });
  const revoked = policyWith((p) => {
    p.authorization['data-classes-forbidden'].push('repo-code');
    p.authorization['data-classes-permitted'] = [];
  });
  before = readFileSync(ledger, 'utf8');
  const rev = cli(['dispatch', 'pb-2', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--policy', revoked, '--now', NOW]);
  assert.equal(rev.code, 3, rev.stdout);
  assert.match(rev.stderr, /pre-dispatch recheck refused cc-opus-high \(decision seq 1\): gate 1: data class 'repo-code' is forbidden/);
  assert.equal(readFileSync(ledger, 'utf8'), before);
  // (C) the decided profile is still eligible but no longer the route's choice (a price change)
  const repriced = policyWith((p) => { p.prices[OPUS.model].output_rate_per_mtok = 500; });
  const moved = cli(['dispatch', 'pb-2', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--policy', repriced, '--now', NOW]);
  assert.equal(moved.code, 3, moved.stdout);
  assert.match(moved.stderr, /pre-dispatch recheck: the route changed since decision seq 1 \(now delegate cc-fable-high\); decide again/);
  assert.equal(readFileSync(ledger, 'utf8'), before);
  // (D) unchanged evidence: the decided dispatch goes through
  assert.equal(dispatch('pb-2', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW }).detail, 'dispatch as decided (decision seq 1)');
  // (E) a decision record with no decision file behind it is unknown evidence: refused, nothing appended
  const bare = tmp();
  const hand = { 'task-id': 'pb-3', seq: 1, kind: 'decision', ts: NOW, profile: OPUS_TUPLE, counters: { 'calls-used': 0, 'calls-limit': 6, 'cash-spent': null, 'cash-cap': null, 'repairs-used': 0, 'repairs-allowed': 1 }, deadline: DEADLINE, 'brief-fingerprint': null, detail: 'route delegate (hand-walked)', 'outcome-ref': null };
  writeFileSync(join(bare, 'ledger.jsonl'), `${JSON.stringify(hand)}\n`);
  const noFile = cli(['dispatch', 'pb-3', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', bare, '--now', NOW]);
  assert.equal(noFile.code, 3, noFile.stdout);
  assert.match(noFile.stderr, /decision file pb-3-1\.json is missing: the route cannot be rechecked before dispatch/);
  assert.equal(readLedger(bare).length, 1);
});

test('F3: a host deviation is refused unless the deviating profile passes Gates 1-4 on the stored request', () => {
  const trace = tmp();
  const ledger = join(trace, 'ledger.jsonl');
  run(req({ taskId: 'dv-1', category: 'fix' }), { traceDir: trace });
  const before = readFileSync(ledger, 'utf8');
  // no capability fingerprint: a Gate 2 failure is never dispatched, deviation or not (spec-v2 §11.2, §11.10, §12)
  const unq = cli(['dispatch', 'dv-1', 'cc-sonnet-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW, '--deviation', 'try it']);
  assert.equal(unq.code, 3, unq.stdout);
  assert.match(unq.stderr, /pre-dispatch recheck refused deviation cc-sonnet-high \(decision seq 1\): gate 2: missing or stale capability fingerprint \(qualified-at null\)/);
  assert.equal(readFileSync(ledger, 'utf8'), before);
  // qualified for other categories but not this one: still Gate 2
  run(req({ taskId: 'dv-2', category: 'build-core' }), { traceDir: trace });
  const other = cli(['dispatch', 'dv-2', 'cc-fable-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW, '--deviation', 'qualification run']);
  assert.equal(other.code, 3, other.stdout);
  assert.match(other.stderr, /gate 2: .*cc-fable-high not qualified for build-core/);
  // an eligible profile that is not the route's choice is an allowed, marked deviation
  const ok = dispatch('dv-1', 'cc-fable-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW, deviation: 'second-cheapest eligible' });
  assert.equal(ok.deviation, true);
  assert.match(ok.detail, /^host deviation: second-cheapest eligible; route said cc-opus-high/);
});

test('F4: a superseding outcome for the same dispatch replaces the first in the learning step; it is not counted twice', () => {
  const trace = tmp();
  const d = run(req({ taskId: 'sup-1', category: 'fix' }), { traceDir: trace });
  dispatch('sup-1', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  const o = outcome({ 'task-id': 'sup-1', 'original-brief-fingerprint': d.briefFingerprint });
  recordOutcome(o, { traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  recordOutcome(o, { traceDir: trace, policyPath: POLICY_PATH, now: NOW }); // spec-v2 §10.5: a superseding outcome appends
  const r = rate({ traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  assert.deepEqual(r.proposals, []);
  assert.equal(r.stats.stats['cc-opus-high'].fix['verification-failed'], 1);
  assert.equal(r.stats['outcomes-counted'], 1);
  // the latest outcome wins: a superseding accepted outcome leaves no failure behind
  recordOutcome({ ...o, outcome: 'accepted' }, { traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  const r2 = rate({ traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  assert.equal(r2.stats.stats['cc-opus-high'].fix['verification-failed'], 0);
  assert.equal(r2.stats.stats['cc-opus-high'].fix.accepted, 1);
});

test('F5: a ledger whose last line has no trailing newline is refused (exit 4) before anything is appended', () => {
  const trace = tmp();
  run(req({ taskId: 'nl-1' }), { traceDir: trace });
  const path = join(trace, 'ledger.jsonl');
  const stripped = readFileSync(path, 'utf8').replace(/\n$/, '');
  writeFileSync(path, stripped);
  const out = cli(['dispatch', 'nl-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW]);
  assert.equal(out.code, 4, out.stdout);
  assert.match(out.stderr, /ledger does not end with a newline/);
  assert.equal(readFileSync(path, 'utf8'), stripped);
  assert.equal(cli(['status', 'nl-1', '--trace', trace]).code, 4);
});

// ---------------------------------------------------------------------------------------------
// F6: enforced duties the README claims, each pinned by its own refusal
// ---------------------------------------------------------------------------------------------
test('F6 dispatch deadline: a fresh decision dispatched at now == deadline is refused by dispatch\'s own deadline check', () => {
  const trace = tmp();
  run(req({ taskId: 'dl-1' }), { traceDir: trace });
  const before = readFileSync(join(trace, 'ledger.jsonl'), 'utf8');
  const out = cli(['dispatch', 'dl-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', DEADLINE]);
  assert.equal(out.code, 3, out.stdout);
  assert.match(out.stderr, /deadline 2026-10-18T06:00:00Z reached: now 2026-10-18T06:00:00Z is not strictly before it/);
  assert.equal(readFileSync(join(trace, 'ledger.jsonl'), 'utf8'), before);
});

test('F6 reconcile first: a same-profile re-dispatch with no outcome for the earlier dispatch is refused', () => {
  const trace = tmp();
  run(req({ taskId: 'rc-1' }), { traceDir: trace });
  dispatch('rc-1', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  run(req({ taskId: 'rc-1' }), { traceDir: trace }); // decided again without recording an outcome
  const out = cli(['dispatch', 'rc-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW]);
  assert.equal(out.code, 3, out.stdout);
  assert.match(out.stderr, /previous dispatch of cc-opus-high \(seq 2\) has no outcome; reconcile before any re-dispatch/);
});

test('F6 one dispatch per delegate decision: a different profile after the decision was dispatched is refused, deviation or not', () => {
  const trace = tmp();
  run(req({ taskId: 'ad-1' }), { traceDir: trace });
  dispatch('ad-1', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  const out = cli(['dispatch', 'ad-1', 'cc-fable-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW, '--deviation', 'second opinion']);
  assert.equal(out.code, 3, out.stdout);
  assert.match(out.stderr, /decision seq 1 for ad-1 was already dispatched \(seq 2\); decide again/);
});

test('F6 outcome after decision: once an outcome follows the decision, no further dispatch of its set without a fresh decision', () => {
  const trace = tmp();
  const d = run(req({ taskId: 'sp-1', uncertainty: 'high', hostOptIns: { speculative: true } }), { traceDir: trace });
  assert.equal(d.route, 'speculative');
  dispatch('sp-1', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  recordOutcome(outcome({ 'task-id': 'sp-1', outcome: 'accepted', 'original-brief-fingerprint': d.briefFingerprint }), { traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  const out = cli(['dispatch', 'sp-1', 'cc-fable-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW]);
  assert.equal(out.code, 3, out.stdout);
  assert.match(out.stderr, /an outcome \(seq 3\) follows the latest decision \(seq 1\); decide again with previousResult first/);
});

test('F6 ledger integrity: a seq gap and a parseable non-§10.5 line are refused (exit 4) with nothing appended', () => {
  const base = { 'task-id': 'li-1', kind: 'decision', ts: NOW, profile: OPUS_TUPLE, counters: { 'calls-used': 0, 'calls-limit': 6, 'cash-spent': null, 'cash-cap': null, 'repairs-used': 0, 'repairs-allowed': 1 }, deadline: DEADLINE, 'brief-fingerprint': null, detail: 'route delegate (hand)', 'outcome-ref': null };
  const gap = tmp();
  writeFileSync(join(gap, 'ledger.jsonl'), `${JSON.stringify({ ...base, seq: 1 })}\n${JSON.stringify({ ...base, seq: 3 })}\n`);
  const gapBefore = readFileSync(join(gap, 'ledger.jsonl'), 'utf8');
  const g = cli(['decide', writeJson(req({ taskId: 'li-2' })), '--trace', gap]);
  assert.equal(g.code, 4, g.stdout);
  assert.match(g.stderr, /ledger line 2: seq 3 for li-1 does not follow 1; refusing to read or append/);
  assert.equal(readFileSync(join(gap, 'ledger.jsonl'), 'utf8'), gapBefore);
  const schema = tmp();
  writeFileSync(join(schema, 'ledger.jsonl'), `${JSON.stringify({ ...base, seq: 1, kind: 'payment' })}\n`);
  const schemaBefore = readFileSync(join(schema, 'ledger.jsonl'), 'utf8');
  const s = cli(['decide', writeJson(req({ taskId: 'li-2' })), '--trace', schema]);
  assert.equal(s.code, 4, s.stdout);
  assert.match(s.stderr, /ledger line 1 is not a §10\.5 LedgerRecord \(kind\); refusing to read or append/);
  assert.equal(readFileSync(join(schema, 'ledger.jsonl'), 'utf8'), schemaBefore);
});

test('F6 project stop: a failing research gate blocks every candidate at Gate 1 and names the stop', () => {
  const d = computeDecision(req({ projectStop: { redSuite: false, gateOff: false, researchGateFailing: true } }), loadPolicy(POLICY_PATH), []);
  assert.equal(d.route, 'blocked');
  for (const p of POLICY.profiles) {
    assert.equal(d.candidates[p.id]['first-failing-gate'], 1, p.id);
    assert.equal(d.candidates[p.id].reason, 'project stop: research gate failing on the project');
  }
});

test('F6 Brief attempts: the first decision allows one repair, the repair decision leaves none', () => {
  const trace = tmp();
  const first = run(req({ taskId: 'at-1', category: 'fix' }), { traceDir: trace });
  assert.equal(first.brief.attempts, 1);
  dispatch('at-1', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  const prev = outcome({ 'task-id': 'at-1', 'original-brief-fingerprint': first.briefFingerprint });
  recordOutcome(prev, { traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  const repair = run(req({ taskId: 'at-1', category: 'fix', previousResult: prev }), { traceDir: trace });
  assert.equal(repair.decision.profile, 'cc-opus-high');
  assert.equal(repair.brief.attempts, 0);
});

test('F7: an unpriced model is a deliberate Gate 4 reject in this host (no silent zero, no unranked bound); the route moves to the next priced candidate', () => {
  const unpriced = loadPolicy(policyWith((p) => { delete p.prices[OPUS.model]; }));
  const d = computeDecision(req({ category: 'fix' }), unpriced, []);
  assert.equal(d.candidates['cc-opus-high']['first-failing-gate'], 4);
  assert.equal(d.candidates['cc-opus-high'].reason, `unknown price for ${OPUS.model}: the bound cannot be computed (no silent zero)`);
  assert.equal(d.route, 'delegate');
  assert.equal(d.profile, 'cc-fable-high');
  assert.ok(d['all-in-bound-usd'] > 0);
});

test('F8: the required reviewer is drawn from the candidates and gate-walked (Gates 1-2 against the review median)', () => {
  const policy = loadPolicy(POLICY_PATH);
  // the host offered only cc-fable-high: the review is priced at cc-fable-high, not at a profile outside the list
  const only = computeDecision(req({ category: 'fix', candidates: ['cc-fable-high'] }), policy, []);
  assert.equal(only.route, 'delegate');
  assert.equal(only['review-profile'], 'cc-fable-high');
  assert.equal(only.candidates['cc-fable-high']['review-bound-usd'], 10.45);
  assert.equal(only['all-in-bound-usd'], 21.1);
  // a reviewer whose tested headroom is below the review median fails Gate 2 as a reviewer; the next one reviews
  const tight = loadPolicy(policyWith((p) => { p.profiles.find((x) => x.id === 'cc-opus-high')['headroom-tested'] = 200000; }));
  const t = computeDecision(req({ category: 'fix' }), tight, []);
  assert.equal(t.profile, 'cc-opus-high'); // 193000 fix tokens still fit as the worker
  assert.equal(t['review-profile'], 'cc-fable-high');
  assert.match(t['review-candidates']['cc-opus-high'], /^gate 2: context: 209000 tokens not below headroom-tested 200000 on cc-opus-high/);
  // no candidate can review: blocked at Gate 3 before start, naming why
  const none = computeDecision(req({ category: 'fix', candidates: ['cc-opus-high'] }), loadPolicy(policyWith((p) => { p.profiles.find((x) => x.id === 'cc-opus-high')['qualified-for'] = ['fix']; })), []);
  assert.equal(none.route, 'blocked');
  assert.equal(none.candidates['cc-opus-high']['first-failing-gate'], 3);
  assert.match(none.candidates['cc-opus-high'].reason, /verification prerequisite missing: no candidate passes Gates 1-2 as reviewer for 'fresh re-review' \(cc-opus-high: gate 2: .*cc-opus-high not qualified for review\)/);
  // Gate 1 applies to the reviewer too: a delegated review needs worktree+branch even when the work itself is direct
  const dirOnly = loadPolicy(policyWith((p) => {
    p.isolation.capability = 'directory';
    p.categories['docs-mechanical'].verification = ['review the diff'];
  }));
  const tiny = computeDecision(req({ category: 'docs-mechanical', estimatedTokens: 1000 }), dirOnly, []);
  assert.equal(tiny.route, 'blocked');
  assert.equal(tiny.candidates['cc-fable-xhigh']['first-failing-gate'], 3);
  assert.match(tiny['review-candidates']['cc-opus-high'], /^gate 1: isolation worktree\+branch required; host provides at most directory/);
});

// ---------------------------------------------------------------------------------------------
// Fix round 2 (N1-N6)
// ---------------------------------------------------------------------------------------------
// a policy copy in which cc-sonnet-high is qualified for review, so a speculative review set is
// [cc-sonnet-high, cc-opus-high] and cc-fable-high is an eligible profile outside the set
const sonnetReviewPolicy = (more = () => {}) => policyWith((p) => {
  Object.assign(p.profiles.find((x) => x.id === 'cc-sonnet-high'), { 'qualified-for': ['review'], 'qualified-at': '2026-10-17', expires: '2027-01-15', 'context-tested': 1000000, 'headroom-tested': 352000 });
  more(p);
});

test('N1: a speculative set is capped at its shared-budget calls, and a speculative route admits no host deviation', () => {
  const trace = tmp();
  const ledger = join(trace, 'ledger.jsonl');
  const pol = sonnetReviewPolicy();
  const d = decide(req({ taskId: 'sc-1', uncertainty: 'high', hostOptIns: { speculative: true } }), { traceDir: trace, policyPath: pol });
  assert.equal(d.route, 'speculative');
  assert.deepEqual(d.decision['speculative-set'].candidates.map((c) => c.profile), ['cc-sonnet-high', 'cc-opus-high']);
  assert.equal(d.record['speculative-calls'], 2); // the set's hard ceiling travels with the decision record
  // (a) a deviation outside the set is refused before any member is dispatched, with or without --deviation
  let before = readFileSync(ledger, 'utf8');
  const dev = cli(['dispatch', 'sc-1', 'cc-fable-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--policy', pol, '--now', NOW, '--deviation', 'a third opinion']);
  assert.equal(dev.code, 3, dev.stdout);
  assert.match(dev.stderr, /decision seq 1 is speculative: dispatching cc-fable-high outside its set \(cc-sonnet-high, cc-opus-high\) is refused; a speculative route admits no host deviation/);
  const bare = cli(['dispatch', 'sc-1', 'cc-fable-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--policy', pol, '--now', NOW]);
  assert.equal(bare.code, 3, bare.stdout);
  assert.match(bare.stderr, /a speculative route admits no host deviation/);
  assert.equal(readFileSync(ledger, 'utf8'), before);
  // (b) both members dispatch as decided
  assert.equal(dispatch('sc-1', 'cc-sonnet-high', { projectStop: CLEAR, traceDir: trace, policyPath: pol, now: NOW }).detail, 'dispatch as decided (decision seq 1)');
  assert.equal(dispatch('sc-1', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: pol, now: NOW }).detail, 'dispatch as decided (decision seq 1)');
  // (c) the set has spent its shared budget: a third dispatch is refused at the ceiling
  before = readFileSync(ledger, 'utf8');
  const third = cli(['dispatch', 'sc-1', 'cc-fable-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--policy', pol, '--now', NOW, '--deviation', 'a third opinion']);
  assert.equal(third.code, 3, third.stdout);
  assert.match(third.stderr, /speculative set of decision seq 1 has used its shared budget: 2 of 2 calls dispatched; the shared budget is a hard ceiling across the set \(spec-v2 §8\.4\); decide again/);
  assert.equal(readFileSync(ledger, 'utf8'), before);
  // (d) the review finding's probe on host-policy-1: the lead profile as a third member is refused too
  const t2 = tmp();
  decide(req({ taskId: 'sc-2', uncertainty: 'high', hostOptIns: { speculative: true } }), { traceDir: t2, policyPath: POLICY_PATH });
  dispatch('sc-2', 'cc-opus-high', { projectStop: CLEAR, traceDir: t2, policyPath: POLICY_PATH, now: NOW });
  dispatch('sc-2', 'cc-fable-high', { projectStop: CLEAR, traceDir: t2, policyPath: POLICY_PATH, now: NOW });
  const lead = cli(['dispatch', 'sc-2', 'cc-fable-xhigh', '--project-stop', CLEAR_JSON, '--trace', t2, '--now', NOW, '--deviation', 'one more']);
  assert.equal(lead.code, 3, lead.stdout);
  assert.deepEqual(readLedger(t2).map((r) => r.kind), ['decision', 'dispatch', 'dispatch']);
});

test('N2: reconcile first: no dispatch while an earlier dispatch of the task has no outcome, except the other members of the same speculative decision', () => {
  const trace = tmp();
  const ledger = join(trace, 'ledger.jsonl');
  // the review's probe: a fresh decision naming a different profile while the first dispatch is open
  const first = run(req({ taskId: 'ip-1', category: 'fix' }), { traceDir: trace });
  dispatch('ip-1', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  const fresh = run(req({ taskId: 'ip-1', category: 'fix', candidates: ['cc-fable-high'] }), { traceDir: trace });
  assert.equal(fresh.decision.profile, 'cc-fable-high');
  let before = readFileSync(ledger, 'utf8');
  const open = cli(['dispatch', 'ip-1', 'cc-fable-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW]);
  assert.equal(open.code, 3, open.stdout);
  assert.match(open.stderr, /previous dispatch of cc-opus-high \(seq 2\) has no outcome; reconcile before any re-dispatch \(spec-v2 §12\)/);
  assert.equal(readFileSync(ledger, 'utf8'), before);
  // reconciled: an outcome names the open dispatch, a fresh decision follows it, and the other profile dispatches
  const prev = outcome({ 'task-id': 'ip-1', outcome: 'cancelled', 'original-brief-fingerprint': first.briefFingerprint });
  assert.equal(recordOutcome(prev, { traceDir: trace, policyPath: POLICY_PATH, now: NOW })['dispatch-seq'], 2);
  run(req({ taskId: 'ip-1', category: 'fix', candidates: ['cc-fable-high'], previousResult: prev }), { traceDir: trace });
  assert.equal(dispatch('ip-1', 'cc-fable-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW }).detail, 'dispatch as decided (decision seq 5)');
  // the exception is the same speculative decision only: a member of a later decision waits for the open one
  const t2 = tmp();
  const spec = { uncertainty: 'high', hostOptIns: { speculative: true } };
  run(req({ taskId: 'ip-2', ...spec }), { traceDir: t2 });
  dispatch('ip-2', 'cc-opus-high', { projectStop: CLEAR, traceDir: t2, policyPath: POLICY_PATH, now: NOW });
  run(req({ taskId: 'ip-2', ...spec }), { traceDir: t2 }); // decided again with the first member still open
  before = readFileSync(join(t2, 'ledger.jsonl'), 'utf8');
  const later = cli(['dispatch', 'ip-2', 'cc-fable-high', '--project-stop', CLEAR_JSON, '--trace', t2, '--now', NOW]);
  assert.equal(later.code, 3, later.stdout);
  assert.match(later.stderr, /previous dispatch of cc-opus-high \(seq 2\) has no outcome; reconcile before any re-dispatch/);
  assert.equal(readFileSync(join(t2, 'ledger.jsonl'), 'utf8'), before);
});

test('N3: an as-decided dispatch is refused when the recomputed Brief differs from the decided one (call limit, deadline cap)', () => {
  const trace = tmp();
  const ledger = join(trace, 'ledger.jsonl');
  // the review's probe: calls-per-task lowered between decide and dispatch while the route stays cc-opus-high
  const d = run(req({ taskId: 'cl-1', category: 'fix' }), { traceDir: trace });
  assert.equal(d.brief.allowance.calls, 6);
  const before = readFileSync(ledger, 'utf8');
  const three = policyWith((p) => { p.accounting.strict['calls-per-task'] = 3; });
  const calls = cli(['dispatch', 'cl-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--policy', three, '--now', NOW]);
  assert.equal(calls.code, 3, calls.stdout);
  assert.match(calls.stderr, /pre-dispatch recheck: the Brief changed since decision seq 1; decide again \(changed: allowance, stop-triggers\)/);
  // a changed deadline cap (12 h -> 6 h) moves allowance.deadline and the stop trigger that names it
  const six = policyWith((p) => { p.accounting.strict['deadline-per-task-hours'] = 6; });
  const cap = cli(['dispatch', 'cl-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--policy', six, '--now', NOW]);
  assert.equal(cap.code, 3, cap.stdout);
  assert.match(cap.stderr, /the Brief changed since decision seq 1; decide again \(changed: allowance, stop-triggers\)/);
  assert.equal(readFileSync(ledger, 'utf8'), before);
  // unchanged inputs: the dispatch goes through and records the decided fingerprint
  const ok = dispatch('cl-1', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  assert.equal(ok['brief-fingerprint'], d.briefFingerprint);
  // the second member of a speculative set is compared with the set's decided Brief: its sibling's dispatch is
  // the decision's own consumption (N1 shows it dispatching), while a lowered call limit still refuses it
  const t2 = tmp();
  const pol = sonnetReviewPolicy();
  decide(req({ taskId: 'cl-2', uncertainty: 'high', hostOptIns: { speculative: true } }), { traceDir: t2, policyPath: pol });
  dispatch('cl-2', 'cc-sonnet-high', { projectStop: CLEAR, traceDir: t2, policyPath: pol, now: NOW });
  const lowered = sonnetReviewPolicy((p) => { p.accounting.strict['calls-per-task'] = 3; });
  const member = cli(['dispatch', 'cl-2', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', t2, '--policy', lowered, '--now', NOW]);
  assert.equal(member.code, 3, member.stdout);
  assert.match(member.stderr, /the Brief changed since decision seq 1; decide again \(changed: allowance, stop-triggers\)/);
});

test('N4: dispatch requires the current project-stop state (exit 2 when missing or malformed) and re-walks Gate 1 with it', () => {
  const trace = tmp();
  const ledger = join(trace, 'ledger.jsonl');
  run(req({ taskId: 'ps-1' }), { traceDir: trace }); // decided with every stop clear
  const before = readFileSync(ledger, 'utf8');
  const base = ['dispatch', 'ps-1', 'cc-opus-high', '--trace', trace, '--now', NOW];
  const missing = cli(base);
  assert.equal(missing.code, 2, missing.stdout);
  assert.match(missing.stderr, /dispatch needs the current project-stop state: --project-stop/);
  for (const bad of ['not json', '{"redSuite":false}', '{"redSuite":"no","gateOff":false,"researchGateFailing":false}', '[]']) {
    const out = cli([...base, '--project-stop', bad]);
    assert.equal(out.code, 2, `${bad}: ${out.stdout}`);
  }
  assert.throws(() => dispatch('ps-1', 'cc-opus-high', { traceDir: trace, policyPath: POLICY_PATH, now: NOW }), (e) => e instanceof RouterError && e.code === 2);
  // a stop that appeared after the decision refuses the dispatch at Gate 1 and names the rule
  const red = cli([...base, '--project-stop', JSON.stringify({ ...CLEAR, redSuite: true })]);
  assert.equal(red.code, 3, red.stdout);
  assert.match(red.stderr, /pre-dispatch recheck refused cc-opus-high \(decision seq 1\): gate 1: project stop: red suite/);
  const off = cli([...base, '--project-stop', JSON.stringify({ ...CLEAR, gateOff: true })]);
  assert.equal(off.code, 3, off.stdout);
  assert.match(off.stderr, /gate 1: project stop: GATE_OFF or --no-verify in use/);
  // a deviation is re-walked with the same current state
  const dev = cli(['dispatch', 'ps-1', 'cc-fable-high', '--trace', trace, '--now', NOW, '--deviation', 'x', '--project-stop', JSON.stringify({ ...CLEAR, researchGateFailing: true })]);
  assert.equal(dev.code, 3, dev.stdout);
  assert.match(dev.stderr, /refused deviation cc-fable-high \(decision seq 1\): gate 1: project stop: research gate failing on the project/);
  assert.equal(readFileSync(ledger, 'utf8'), before);
  const ok = cli([...base, '--project-stop', CLEAR_JSON]);
  assert.equal(ok.code, 0, ok.stderr);
});

test('N5: a deviation to the lead-direct profile is refused; the lead works direct only, never as a delegated worker', () => {
  const trace = tmp();
  const ledger = join(trace, 'ledger.jsonl');
  // the review's probe: a build-core decision delegates to cc-opus-high; the lead is direct-unsuitable at 316000 tokens
  const d = run(req({ taskId: 'ld-1', category: 'build-core' }), { traceDir: trace });
  assert.equal(d.decision.profile, 'cc-opus-high');
  assert.equal(d.decision.candidates['cc-fable-xhigh'].reason, 'direct unsuitable: 316000 tokens > direct-max-tokens 15000');
  const before = readFileSync(ledger, 'utf8');
  assert.throws(() => dispatch('ld-1', 'cc-fable-xhigh', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW, deviation: 'lead does it as a worker' }),
    (e) => e instanceof RouterError && e.code === 3 && /cc-fable-xhigh is the lead-direct profile \(economics\.lead-direct-profile\): it works direct only, up to direct-max-tokens 15000, and is never dispatched as a delegated worker, --deviation or not/.test(e.message));
  const bare = cli(['dispatch', 'ld-1', 'cc-fable-xhigh', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW]);
  assert.equal(bare.code, 3, bare.stdout);
  assert.match(bare.stderr, /is the lead-direct profile/);
  assert.equal(readFileSync(ledger, 'utf8'), before);
});

test('R3-1: a host deviation is held to the decided Brief too: a changed allowance refuses it, and a deviation whose repair status differs from the decided profile\'s is refused', () => {
  // (A) the re-review's probe: calls-per-task lowered between decide and a deviation dispatch on a delegate route
  const trace = tmp();
  const ledger = join(trace, 'ledger.jsonl');
  const d = run(req({ taskId: 'dv-1', category: 'fix' }), { traceDir: trace });
  assert.equal(d.decision.profile, 'cc-opus-high');
  assert.equal(d.brief.allowance.calls, 6);
  const before = readFileSync(ledger, 'utf8');
  const three = policyWith((p) => { p.accounting.strict['calls-per-task'] = 3; });
  const r = cli(['dispatch', 'dv-1', 'cc-fable-high', '--deviation', 'second opinion', '--project-stop', CLEAR_JSON, '--trace', trace, '--policy', three, '--now', NOW]);
  assert.equal(r.code, 3, r.stdout);
  assert.match(r.stderr, /pre-dispatch recheck: the Brief changed since decision seq 1; decide again \(changed: allowance, stop-triggers\)/);
  assert.equal(readFileSync(ledger, 'utf8'), before);
  // unchanged inputs: the deviation goes through, and its record carries the decided Brief's fingerprint - the one
  // Brief the worker is handed (README step 2), which recordOutcome will look for
  const ok = dispatch('dv-1', 'cc-fable-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW, deviation: 'second opinion' });
  assert.equal(ok['brief-fingerprint'], d.briefFingerprint);
  // (B) the decided Brief assumed a fresh profile (attempts 1); a deviation back to the profile that already failed
  // would be a same-profile repair under that Brief, so it is refused: a fresh decision must list the profile
  const t2 = tmp();
  const l2 = join(t2, 'ledger.jsonl');
  const first = run(req({ taskId: 'dv-2', candidates: ['cc-fable-high'] }), { traceDir: t2 });
  assert.equal(first.decision.profile, 'cc-fable-high');
  dispatch('dv-2', 'cc-fable-high', { projectStop: CLEAR, traceDir: t2, policyPath: POLICY_PATH, now: NOW });
  const failed = outcome({ 'task-id': 'dv-2', 'owner-profile': 'cc-fable-high', 'original-brief-fingerprint': first.briefFingerprint });
  recordOutcome(failed, { traceDir: t2, policyPath: POLICY_PATH, now: NOW });
  const second = run(req({ taskId: 'dv-2', previousResult: failed }), { traceDir: t2 });
  assert.equal(second.decision.profile, 'cc-opus-high');
  assert.equal(second.brief.attempts, 1);
  const b2 = readFileSync(l2, 'utf8');
  assert.throws(() => dispatch('dv-2', 'cc-fable-high', { projectStop: CLEAR, traceDir: t2, policyPath: POLICY_PATH, now: NOW, deviation: 'retry the same profile' }),
    (e) => e instanceof RouterError && e.code === 3 && /deviation to cc-fable-high would be a same-profile repair under a Brief decided for a fresh profile \(attempts 1\); decide again with cc-fable-high among the candidates/.test(e.message));
  assert.equal(readFileSync(l2, 'utf8'), b2);
});

test('N6: a request that declares no data class is invalid (exit 2) and is never routed', () => {
  // the review's probe: dataClasses [] used to pass Gate 1 and route to cc-opus-high
  assert.throws(() => computeDecision(req({ dataClasses: [] }), loadPolicy(POLICY_PATH), []),
    (e) => e instanceof RouterError && e.code === 2 && e.message === 'invalid request: declare at least one data class');
  const trace = tmp();
  const out = cli(['decide', writeJson(req({ taskId: 'dc-1', dataClasses: [] })), '--trace', trace]);
  assert.equal(out.code, 2, out.stdout);
  assert.match(out.stderr, /invalid request: declare at least one data class/);
  assert.equal(existsSync(join(trace, 'ledger.jsonl')), false);
  assert.equal(existsSync(join(trace, 'decisions')), false);
});

// ---------------------------------------------------------------------------------------------
// Usage windows (unit sr-windows): Gate 4 on a subscription host. Every reading below is synthetic, built by the
// test relative to its own clock; none is a real rate_limit_event observation.
// ---------------------------------------------------------------------------------------------
const MIN = 60000;
const HOUR = 3600000;
const NOW_MS = Date.parse(NOW);
const isoAt = (ms) => new Date(ms).toISOString().replace('.000Z', 'Z');
const USAGE_BASIS_LINE = `usage windows: coefficients host-declared (${USAGE_POLICY['usage-windows']['coefficient-basis']})`;
const LIVE_BASIS_LINE = `usage windows: coefficients host-declared (${COMMITTED_POLICY['usage-windows']['coefficient-basis']})`;
// a synthetic rate_limit_info as the platform reports it (resetsAt in epoch seconds), relative to `at`
function rateLimitInfo(at, { five = 0.2, seven = 0.05, fiveResetMs = 4 * HOUR, sevenResetMs = 144 * HOUR } = {}) {
  const ms = Date.parse(at);
  return { unifiedWindows: { five_hour: { resetsAt: (ms + fiveResetMs) / 1000, utilization: five }, seven_day: { resetsAt: (ms + sevenResetMs) / 1000, utilization: seven } } };
}
const usageCli = (trace, reading, now, policy = USAGE_POLICY_PATH) => cli(['usage', writeJson(reading), '--trace', trace, '--now', now, '--policy', policy]);
const decideOn = (r, trace, policyPath = USAGE_POLICY_PATH) => decide(r, { traceDir: trace, policyPath });
test('P2-4: the gate walk keeps a space between every profile id and its route kind, whatever the longest id is (cc-sonnet-medium is 16 characters)', () => {
  const trace = tmp();
  usageCli(trace, rateLimitInfo(NOW), NOW, COMMITTED_POLICY_PATH);
  const d = decideOn(req({ taskId: 'gw-1' }), trace, COMMITTED_POLICY_PATH);
  const walk = d.text.split('\n').filter((l) => /^ {2}cc-/.test(l));
  assert.equal(walk.length, COMMITTED_POLICY.profiles.length, `walk lines: ${walk.length}`);   // one line per policy profile
  for (const line of walk) assert.match(line, /^ {2}(\S+) +(direct|delegate) +\S/, line);
  assert.match(d.text, /^ {2}cc-sonnet-medium +delegate +gate 2: /m);
});

// the committed block in a feature-off copy, mutated
const usagePolicy = (mutate = () => {}) => policyWith((p) => { p['usage-windows'] = structuredClone(USAGE_POLICY['usage-windows']); mutate(p['usage-windows'], p); });

test('usage windows: the policy block is validated whole (exit 2): a missing or non-positive coefficient, a reserve >= stop-at, a bad stop-at or length', () => {
  assert.deepEqual(Object.keys(loadPolicy(USAGE_POLICY_PATH)['usage-windows'].windows), ['five_hour', 'seven_day']);
  const coefficient = /^invalid policy: usage-windows\.windows\.five_hour\.utilization-per-mtok must be a finite number > 0 \(a window with no coefficient cannot be projected; declare one with its basis\)$/;
  const cases = [
    [(u) => { delete u.windows.five_hour['utilization-per-mtok']; }, coefficient],
    [(u) => { u.windows.five_hour['utilization-per-mtok'] = null; }, coefficient],
    [(u) => { u.windows.five_hour['utilization-per-mtok'] = 0; }, coefficient],
    [(u) => { u.windows.five_hour['utilization-per-mtok'] = -0.24; }, coefficient],
    [(u) => { u.windows.five_hour['utilization-per-mtok'] = '0.24'; }, coefficient],
    [(u) => { u.windows.seven_day['lead-reserve'] = 0.9; }, /^invalid policy: usage-windows\.windows\.seven_day\.lead-reserve must be in \[0, stop-at\) \(lead-reserve 0\.9, stop-at 0\.9\)$/],
    [(u) => { u.windows.seven_day['lead-reserve'] = -0.01; }, /seven_day\.lead-reserve must be in \[0, stop-at\)/],
    [(u) => { u.windows.five_hour['stop-at'] = 1.01; }, /^invalid policy: usage-windows\.windows\.five_hour\.stop-at must be in \(0, 1\]$/],
    [(u) => { u.windows.five_hour['stop-at'] = 0; }, /five_hour\.stop-at must be in \(0, 1\]/],
    [(u) => { u.windows.five_hour['length-seconds'] = 18000.5; }, /^invalid policy: usage-windows\.windows\.five_hour\.length-seconds must be a positive integer$/],
    [(u) => { u['reading-max-age-minutes'] = 0; }, /^invalid policy: usage-windows\.reading-max-age-minutes must be a number > 0$/],
    [(u) => { delete u['coefficient-basis']; }, /^invalid policy: usage-windows\.coefficient-basis missing/],
    [(u) => { u.source = ''; }, /^invalid policy: usage-windows\.source missing/],
    [(u) => { u.windows = {}; }, /^invalid policy: usage-windows\.windows must name at least one window$/]
  ];
  for (const [mutate, re] of cases) {
    const path = usagePolicy(mutate);
    assert.throws(() => loadPolicy(path), (e) => e instanceof RouterError && e.code === 2 && re.test(e.message), String(re));
  }
  const out = cli(['decide', writeJson(req({ taskId: 'pv-1' })), '--trace', tmp(), '--policy', usagePolicy(cases[0][0])]);
  assert.equal(out.code, 2, out.stdout);
  assert.match(out.stderr, /usage-windows\.windows\.five_hour\.utilization-per-mtok must be a finite number > 0/);
  // a complete block in a copy loads, and leaves everything else as it was
  assert.equal(loadPolicy(usagePolicy())['usage-windows']['reading-max-age-minutes'], 30);
});

test('usage: a reading is appended to trace/usage.jsonl in any of three forms, normalised; the ledger is untouched', () => {
  const trace = tmp();
  const info = rateLimitInfo(NOW);
  const a = usageCli(trace, info, NOW);
  assert.equal(a.code, 0, a.stderr);
  assert.match(a.stdout, /^usage reading recorded: 2026-10-17T19:00:00Z five_hour 0\.2 \(resets 2026-10-17T23:00:00Z\), seven_day 0\.05 \(resets 2026-10-23T19:00:00Z\)$/m);
  assert.equal(usageCli(trace, info.unifiedWindows, isoAt(NOW_MS + MIN)).code, 0);
  const normalised = { windows: { five_hour: { utilization: 0.3, 'resets-at': '2026-10-17T23:00:00Z' }, seven_day: { utilization: 0.07, 'resets-at': '2026-10-23T19:00:00Z' } }, note: 'synthetic, normalised form' };
  const c = usageCli(trace, normalised, isoAt(NOW_MS + 2 * MIN));
  assert.equal(c.code, 0, c.stderr);
  const recs = readFileSync(join(trace, 'usage.jsonl'), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
  const windows = { five_hour: { utilization: 0.2, 'resets-at': '2026-10-17T23:00:00Z' }, seven_day: { utilization: 0.05, 'resets-at': '2026-10-23T19:00:00Z' } };
  assert.deepEqual(recs, [
    { ts: NOW, windows, source: 'rate_limit_event', note: null },
    { ts: '2026-10-17T19:01:00Z', windows, source: 'rate_limit_event', note: null },
    { ts: '2026-10-17T19:02:00Z', windows: normalised.windows, source: 'rate_limit_event', note: 'synthetic, normalised form' }
  ]);
  assert.equal(existsSync(join(trace, 'ledger.jsonl')), false);
  // a window the policy does not name is not recorded (the policy decides which windows bind)
  const extra = rateLimitInfo(isoAt(NOW_MS + 3 * MIN));
  extra.unifiedWindows.seven_day_opus = { resetsAt: null, utilization: null };
  assert.equal(usageCli(trace, extra, isoAt(NOW_MS + 3 * MIN)).code, 0);
  assert.deepEqual(Object.keys(JSON.parse(readFileSync(join(trace, 'usage.jsonl'), 'utf8').trim().split('\n').pop()).windows), ['five_hour', 'seven_day']);
  // the feature off: a reading has nothing to bind against
  const off = cli(['usage', writeJson(info), '--trace', tmp(), '--now', NOW]);
  assert.equal(off.code, 2, off.stdout);
  assert.match(off.stderr, /usage windows are not configured in the policy \(no usage-windows block\)/);
});

test('usage: a reading is refused (exit 2, nothing appended) on a missing window, a utilization outside [0,1], a reset not after ts, or a ts not after the previous reading', () => {
  const trace = tmp();
  const path = join(trace, 'usage.jsonl');
  const refusedWith = (reading, now, re) => {
    const before = existsSync(path) ? readFileSync(path, 'utf8') : null;
    const r = usageCli(trace, reading, now);
    assert.equal(r.code, 2, `${re}: ${r.stdout}`);
    assert.match(r.stderr, re);
    assert.equal(existsSync(path) ? readFileSync(path, 'utf8') : null, before);
  };
  const info = rateLimitInfo(NOW);
  const noSeven = { unifiedWindows: { five_hour: info.unifiedWindows.five_hour } };
  refusedWith(noSeven, NOW, /invalid usage reading: window seven_day \(named in the policy\) is missing/);
  const over = structuredClone(info); over.unifiedWindows.five_hour.utilization = 1.2;
  refusedWith(over, NOW, /invalid usage reading: five_hour utilization 1\.2 is not a number in \[0, 1\]/);
  const under = structuredClone(info); under.unifiedWindows.seven_day.utilization = -0.01;
  refusedWith(under, NOW, /invalid usage reading: seven_day utilization -0\.01 is not a number in \[0, 1\]/);
  const text = structuredClone(info); text.unifiedWindows.five_hour.utilization = '0.2';
  refusedWith(text, NOW, /invalid usage reading: five_hour utilization "0\.2" is not a number in \[0, 1\]/);
  const atTs = structuredClone(info); atTs.unifiedWindows.five_hour.resetsAt = NOW_MS / 1000;
  refusedWith(atTs, NOW, /invalid usage reading: five_hour resets-at 2026-10-17T19:00:00Z is not strictly after the reading ts 2026-10-17T19:00:00Z/);
  const noReset = structuredClone(info); delete noReset.unifiedWindows.five_hour.resetsAt;
  refusedWith(noReset, NOW, /invalid usage reading: five_hour resets-at missing or not a time/);
  // a reset further out than one window length cannot describe that window (e.g. milliseconds pasted as seconds)
  const millis = structuredClone(info); millis.unifiedWindows.five_hour.resetsAt = NOW_MS + 4 * HOUR;
  refusedWith(millis, NOW, /invalid usage reading: five_hour resets-at .* is more than one window length \(18000 s\) after the reading ts/);
  refusedWith(['not', 'a', 'reading'], NOW, /invalid usage reading: expected rate_limit_info, its unifiedWindows, or \{ windows: \{ <name>: \{ utilization, resets-at \} \} \}/);
  // monotonic: each reading's ts follows the previous one strictly
  assert.equal(usageCli(trace, info, NOW).code, 0);
  refusedWith(info, NOW, /invalid usage reading: ts 2026-10-17T19:00:00Z does not follow the previous reading's ts 2026-10-17T19:00:00Z \(readings are monotonic\)/);
  refusedWith(rateLimitInfo(isoAt(NOW_MS - MIN)), isoAt(NOW_MS - MIN), /does not follow the previous reading's ts/);
  assert.equal(usageCli(trace, rateLimitInfo(isoAt(NOW_MS + MIN)), isoAt(NOW_MS + MIN)).code, 0);
  assert.equal(readFileSync(path, 'utf8').split('\n').filter(Boolean).length, 2);
  // an unterminated last line is refused like the ledger's (exit 4), before anything is appended
  writeFileSync(path, readFileSync(path, 'utf8').replace(/\n$/, ''));
  const cut = usageCli(trace, rateLimitInfo(isoAt(NOW_MS + 2 * MIN)), isoAt(NOW_MS + 2 * MIN));
  assert.equal(cut.code, 4, cut.stdout);
  assert.match(cut.stderr, /usage\.jsonl does not end with a newline/);
});

test('usage: with no file it prints the latest reading, its age and each window\'s headroom in Mtok', () => {
  const trace = tmp();
  const none = cli(['usage', '--trace', trace, '--now', NOW, '--policy', USAGE_POLICY_PATH]);
  assert.equal(none.code, 0, none.stderr);
  assert.match(none.stdout, /^no usage reading recorded in .*usage\.jsonl; paste one with route\.mjs usage <reading\.json>$/m);
  usageCli(trace, rateLimitInfo(NOW, { five: 0.6 }), NOW);
  const s = cli(['usage', '--trace', trace, '--now', isoAt(NOW_MS + 12 * MIN), '--policy', USAGE_POLICY_PATH]);
  assert.equal(s.code, 0, s.stderr);
  assert.match(s.stdout, /^latest usage reading 2026-10-17T19:00:00Z \(age 12 min, max 30\)$/m);
  // (stop-at - lead-reserve - utilization) / utilization-per-mtok
  assert.match(s.stdout, /^ {2}five_hour: utilization 0\.6, resets 2026-10-17T23:00:00Z, headroom 1\.0417 Mtok \(\(0\.9 - 0\.05 - 0\.6\) \/ 0\.24\)$/m);
  assert.match(s.stdout, /^ {2}seven_day: utilization 0\.05, resets 2026-10-23T19:00:00Z, headroom 13\.3333 Mtok \(\(0\.9 - 0\.05 - 0\.05\) \/ 0\.06\)$/m);
  const stale = cli(['usage', '--trace', trace, '--now', isoAt(NOW_MS + 31 * MIN), '--policy', USAGE_POLICY_PATH]);
  assert.match(stale.stdout, /^latest usage reading 2026-10-17T19:00:00Z \(age 31 min, max 30\): stale; refresh with route\.mjs usage$/m);
  const reset = cli(['usage', '--trace', trace, '--now', isoAt(NOW_MS + 4 * HOUR), '--policy', USAGE_POLICY_PATH]);
  assert.match(reset.stdout, /^ {2}five_hour: utilization 0\.6, resets 2026-10-17T23:00:00Z: reset since the reading; refresh with route\.mjs usage$/m);
});

test('Gate 4 usage step 1: no reading, or a reading older than reading-max-age-minutes, fails every candidate that reaches Gate 4', () => {
  const trace = tmp();
  const missing = decideOn(req({ taskId: 'g4-1' }), trace);
  assert.equal(missing.route, 'blocked');
  for (const id of ['cc-fable-xhigh', 'cc-opus-high', 'cc-fable-high']) {
    assert.equal(missing.decision.candidates[id]['first-failing-gate'], 4, id);
    assert.equal(missing.decision.candidates[id].reason, 'usage reading missing', id);
  }
  assert.equal(missing.decision.candidates['cc-sonnet-high']['first-failing-gate'], 2); // earlier gates keep their reasons
  assert.deepEqual(missing.decision.usage, { 'reading-ts': null, 'reading-age-minutes': null, 'dispatched-not-in-reading-tokens': null, windows: {} });
  assert.equal(missing.record['usage-tokens'], null);
  usageCli(trace, rateLimitInfo(NOW), NOW);
  const atLimit = decideOn(req({ taskId: 'g4-2', now: isoAt(NOW_MS + 30 * MIN) }), trace);
  assert.equal(atLimit.route, 'delegate'); // age == max passes
  const stale = decideOn(req({ taskId: 'g4-3', now: isoAt(NOW_MS + 31 * MIN) }), trace);
  assert.equal(stale.route, 'blocked');
  assert.equal(stale.decision.candidates['cc-opus-high'].reason, 'usage reading stale: age 31 min > 30; refresh with route.mjs usage');
  assert.equal(stale.decision.usage['reading-age-minutes'], 31);
  // a reading taken after the decision's `now` is not used for it: the latest reading at or before `now` is
  const early = decideOn(req({ taskId: 'g4-4', now: isoAt(NOW_MS - MIN) }), trace);
  assert.equal(early.decision.candidates['cc-opus-high'].reason, 'usage reading missing');
});

test('Gate 4 usage step 2: a window that reset after the reading fails closed', () => {
  const trace = tmp();
  usageCli(trace, rateLimitInfo(NOW, { fiveResetMs: 10 * MIN }), NOW);
  const d = decideOn(req({ taskId: 'g4-5', now: isoAt(NOW_MS + 20 * MIN) }), trace);
  assert.equal(d.route, 'blocked');
  assert.equal(d.decision.candidates['cc-opus-high']['first-failing-gate'], 4);
  assert.equal(d.decision.candidates['cc-opus-high'].reason, 'usage window five_hour reset at 2026-10-17T19:10:00Z after the reading; refresh with route.mjs usage');
  // equality is a reset (now must be strictly before resets-at)
  const eq = decideOn(req({ taskId: 'g4-6', now: isoAt(NOW_MS + 10 * MIN) }), trace);
  assert.match(eq.decision.candidates['cc-opus-high'].reason, /^usage window five_hour reset at 2026-10-17T19:10:00Z after the reading/);
  assert.equal(decideOn(req({ taskId: 'g4-7', now: isoAt(NOW_MS + 9 * MIN) }), trace).route, 'delegate');
});

test('Gate 4 usage step 3: a projection over stop-at - lead-reserve fails with the reason text, and the defer suffix when the window resets before the deadline', () => {
  const trace = tmp();
  usageCli(trace, rateLimitInfo(NOW, { five: 0.8 }), NOW);
  // review: 209000 work tokens; no required review; + 20000 overhead = 229000 for a delegate, 209000 direct
  const d = decideOn(req({ taskId: 'g4-8' }), trace);
  assert.equal(d.route, 'blocked');
  assert.equal(d.decision.candidates['cc-opus-high'].reason, 'usage window five_hour: projected 0.855 > 0.85 (stop-at 0.9 - lead-reserve 0.05); resets 2026-10-17T23:00:00Z; defer until the reset');
  assert.equal(d.decision.candidates['cc-fable-xhigh'].reason, 'usage window five_hour: projected 0.8502 > 0.85 (stop-at 0.9 - lead-reserve 0.05); resets 2026-10-17T23:00:00Z; defer until the reset');
  assert.equal(d.decision.usage.windows.five_hour.projected, null); // blocked: nothing projected for a chosen profile
  // the window resets after the task deadline: no defer suffix
  const late = decideOn(req({ taskId: 'g4-9', deadline: '2026-10-17T22:00:00Z' }), trace);
  assert.equal(late.decision.candidates['cc-opus-high'].reason, 'usage window five_hour: projected 0.855 > 0.85 (stop-at 0.9 - lead-reserve 0.05); resets 2026-10-17T23:00:00Z');
  // the seven-day window binds on its own
  const t2 = tmp();
  usageCli(t2, rateLimitInfo(NOW, { seven: 0.84 }), NOW);
  const week = decideOn(req({ taskId: 'g4-10', deadline: '2026-10-17T22:00:00Z' }), t2);
  assert.equal(week.decision.candidates['cc-opus-high'].reason, 'usage window seven_day: projected 0.8537 > 0.85 (stop-at 0.9 - lead-reserve 0.05); resets 2026-10-23T19:00:00Z');
});

test('Gate 4 usage step 3: under the limit the decision carries the usage block, and tokens are work for direct, work + review + overhead for delegate', () => {
  const trace = tmp();
  usageCli(trace, rateLimitInfo(NOW), NOW);
  const core = decideOn(req({ taskId: 'g4-11', category: 'build-core', now: isoAt(NOW_MS + 6 * MIN) }), trace);
  assert.equal(core.route, 'delegate');
  assert.equal(core.decision.profile, 'cc-opus-high');
  // 316000 work + 209000 review (build-core names a review) + 20000 delegate overhead
  assert.equal(core.decision['usage-tokens'], 545000);
  assert.equal(core.record['usage-tokens'], 545000);
  assert.deepEqual(core.decision.usage, {
    'reading-ts': NOW, 'reading-age-minutes': 6, 'dispatched-not-in-reading-tokens': 0,
    windows: {
      five_hour: { utilization: 0.2, 'resets-at': '2026-10-17T23:00:00Z', projected: 0.3308, 'headroom-mtok': 2.7083 },
      seven_day: { utilization: 0.05, 'resets-at': '2026-10-23T19:00:00Z', projected: 0.0827, 'headroom-mtok': 13.3333 }
    }
  });
  assert.ok(core.decision.uncertainty.includes(USAGE_BASIS_LINE), core.decision.uncertainty.join('|'));
  assert.ok(!core.decision.uncertainty.includes('usage windows: not configured'));
  const g4 = core.decision.candidates['cc-opus-high'].walkthrough[3];
  assert.match(g4.note, /; usage window five_hour binds: projected 0\.3308 <= 0\.85$/);
  // the stored decision file carries the usage block too, for dispatch to re-check
  assert.deepEqual(JSON.parse(readFileSync(core.decisionPath, 'utf8')).decision.usage, core.decision.usage);
  // review: no required review, so a delegate projects work + overhead only
  const review = decideOn(req({ taskId: 'g4-12', now: isoAt(NOW_MS + 6 * MIN) }), trace);
  assert.equal(review.decision['usage-tokens'], 229000);
  assert.equal(review.decision.usage.windows.five_hour.projected, 0.255);
  // direct: the work tokens alone
  const direct = decideOn(req({ taskId: 'g4-13', estimatedTokens: 10000, now: isoAt(NOW_MS + 6 * MIN) }), trace);
  assert.equal(direct.route, 'direct');
  assert.equal(direct.decision['usage-tokens'], 10000);
  assert.equal(direct.decision.usage.windows.five_hour.projected, 0.2024);
  assert.equal(direct.brief, null);
});

test('Gate 4 usage: a candidate over the window is ineligible and economics orders what is left', () => {
  // host-policy-1 makes direct cheaper than every delegate whenever direct is eligible (20000 overhead tokens at
  // the lead's rate exceed 15000 direct tokens), and every delegate projects the same tokens. A copy that lets a
  // 40000-token docs-mechanical unit go direct shows the cheaper delegate (haiku, $0.27) losing to the window and
  // the pricier direct ($2.00) that fits being chosen
  const pol = usagePolicy((u, p) => { p.economics['direct-max-tokens'] = 50000; p.economics['delegate-overhead-tokens'] = 5000; });
  const r = (taskId, now) => req({ taskId, category: 'docs-mechanical', estimatedTokens: 40000, now });
  const roomy = tmp();
  usageCli(roomy, rateLimitInfo(NOW, { five: 0.5 }), NOW, pol);
  const free = decideOn(r('ec-1', NOW), roomy, pol);
  assert.equal(free.decision.profile, 'cc-haiku-low');
  assert.deepEqual(free.decision['eligible-ordered'], ['cc-haiku-low', 'cc-fable-xhigh']);
  const tight = tmp();
  usageCli(tight, rateLimitInfo(NOW, { five: 0.84 }), NOW, pol);
  const d = decideOn(r('ec-2', NOW), tight, pol);
  assert.equal(d.route, 'direct');
  assert.equal(d.decision.profile, 'cc-fable-xhigh'); // 0.84 + 0.04 x 0.24 = 0.8496 fits
  assert.equal(d.decision.candidates['cc-haiku-low']['first-failing-gate'], 4); // 0.84 + 0.045 x 0.24 = 0.8508 does not
  assert.match(d.decision.candidates['cc-haiku-low'].reason, /^usage window five_hour: projected 0\.8508 > 0\.85/);
  assert.deepEqual(d.decision['eligible-ordered'], ['cc-fable-xhigh']);
  // on host-policy-1: a cheaper profile within the window is chosen over a pricier one that exceeds it (ineligible,
  // not merely ranked lower): 15000 tokens direct fit, the 35000-token delegates do not
  const t3 = tmp();
  usageCli(t3, rateLimitInfo(NOW, { five: 0.8455 }), NOW);
  const small = decideOn(req({ taskId: 'ec-3', estimatedTokens: 15000 }), t3);
  assert.equal(small.decision.profile, 'cc-fable-xhigh');
  assert.equal(small.decision.candidates['cc-opus-high']['first-failing-gate'], 4);
  assert.deepEqual(small.decision['eligible-ordered'], ['cc-fable-xhigh']);
});

test('dispatch re-checks the usage windows at its --now: a reading gone stale or a projection now over refuses (exit 3) with the same reason text', () => {
  const trace = tmp();
  const ledger = join(trace, 'ledger.jsonl');
  usageCli(trace, rateLimitInfo(NOW), NOW);
  const d = decideOn(req({ taskId: 'ud-1', now: isoAt(NOW_MS + 5 * MIN) }), trace);
  assert.equal(d.decision.profile, 'cc-opus-high');
  const before = readFileSync(ledger, 'utf8');
  const args = (now) => ['dispatch', 'ud-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', now, '--policy', USAGE_POLICY_PATH];
  // decided 5 minutes after the reading, dispatched 31 minutes after it
  const stale = cli(args(isoAt(NOW_MS + 31 * MIN)));
  assert.equal(stale.code, 3, stale.stdout);
  assert.match(stale.stderr, /usage check refused cc-opus-high \(decision seq 1, usage-tokens 229000\): usage reading stale: age 31 min > 30; refresh with route\.mjs usage/);
  assert.equal(readFileSync(ledger, 'utf8'), before);
  // a fresh reading shows the window filled up since the decision
  usageCli(trace, rateLimitInfo(isoAt(NOW_MS + 32 * MIN), { five: 0.8 }), isoAt(NOW_MS + 32 * MIN));
  const over = cli(args(isoAt(NOW_MS + 33 * MIN)));
  assert.equal(over.code, 3, over.stdout);
  assert.match(over.stderr, /usage check refused cc-opus-high \(decision seq 1, usage-tokens 229000\): usage window five_hour: projected 0\.855 > 0\.85 \(stop-at 0\.9 - lead-reserve 0\.05\); resets 2026-10-17T23:32:00Z; defer until the reset/);
  assert.equal(readFileSync(ledger, 'utf8'), before);
  // a deviation is held to the windows as well
  const dev = cli([...args(isoAt(NOW_MS + 33 * MIN)).map((a) => (a === 'cc-opus-high' ? 'cc-fable-high' : a)), '--deviation', 'second opinion']);
  assert.equal(dev.code, 3, dev.stdout);
  assert.match(dev.stderr, /usage check refused cc-fable-high .*usage window five_hour: projected 0\.855 > 0\.85/);
  // room again: the dispatch goes through as decided
  usageCli(trace, rateLimitInfo(isoAt(NOW_MS + 34 * MIN), { five: 0.3 }), isoAt(NOW_MS + 34 * MIN));
  const ok = cli(args(isoAt(NOW_MS + 35 * MIN)));
  assert.equal(ok.code, 0, ok.stderr);
  assert.equal(readLedger(trace).pop().detail, 'dispatch as decided (decision seq 1)');
});

test('usage windows off (no usage-windows block): Uncertainty says not configured, no usage block, no usage-tokens, usage.jsonl never read', () => {
  const trace = tmp();
  writeFileSync(join(trace, 'usage.jsonl'), 'not json, and never read when the feature is off\n');
  const d = run(req({ taskId: 'off-1' }), { traceDir: trace });
  assert.equal(d.route, 'delegate');
  assert.ok(d.decision.uncertainty.includes('usage windows: not configured'), d.decision.uncertainty.join('|'));
  assert.equal(d.decision.usage, null);
  assert.equal('usage-tokens' in d.record, false);
  assert.equal(d.decision.candidates['cc-opus-high'].walkthrough[3].note, 'cash estimate $5.18: estimate only, never a strict cap in this host');
  assert.equal(dispatch('off-1', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW }).detail, 'dispatch as decided (decision seq 1)');
});

// the two compensating tests on the committed policy (lead's ruling R1(a)), on the stored build request
const STORED_BUILD = JSON.parse(readFileSync(join(goldenDir, 'hand-sr-host-build.json'), 'utf8'));

test('committed policy (i): with no reading, the stored build request is blocked; every candidate that reaches Gate 4 fails it with "usage reading missing"', () => {
  const d = decideOn(STORED_BUILD.request, tmp(), COMMITTED_POLICY_PATH);
  assert.equal(d.route, 'blocked');
  for (const [id, want] of Object.entries(STORED_BUILD.decision.candidates)) {
    const got = d.decision.candidates[id];
    assert.equal(got.eligible, false, id);
    if (want.eligible || want['first-failing-gate'] > 4) {
      assert.equal(got['first-failing-gate'], 4, id);
      assert.equal(got.reason, 'usage reading missing', id);
    } else {
      assert.equal(got['first-failing-gate'], want['first-failing-gate'], id); // earlier gates are unchanged
    }
  }
  assert.ok(d.decision.uncertainty.includes(LIVE_BASIS_LINE));
});

test('committed policy (ii): after a fresh synthetic reading, the stored build request delegates to cc-opus-high with the usage block filled', () => {
  const trace = tmp();
  const at = STORED_BUILD.request.now;
  const r = usageCli(trace, rateLimitInfo(at, { five: 0.2, seven: 0.05, fiveResetMs: 4 * HOUR, sevenResetMs: 144 * HOUR }), at, COMMITTED_POLICY_PATH);
  assert.equal(r.code, 0, r.stderr);
  const d = decideOn(STORED_BUILD.request, trace, COMMITTED_POLICY_PATH);
  assert.equal(d.route, 'delegate');
  assert.equal(d.decision.profile, 'cc-opus-high');
  assert.equal(d.decision.usage['reading-ts'], at);
  const uw = COMMITTED_POLICY['usage-windows'].windows;
  for (const w of ['five_hour', 'seven_day']) {
    const u = d.decision.usage.windows[w];
    assert.equal(typeof u.projected, 'number', w);
    assert.ok(u.projected < uw[w]['stop-at'] - uw[w]['lead-reserve'], `${w} ${u.projected}`);
    assert.ok(u['headroom-mtok'] > 0, w);
  }
  // everything else is the golden decision
  assert.equal(d.decision['all-in-bound-usd'], STORED_BUILD.decision['all-in-bound-usd']);
  assert.deepEqual(d.decision['eligible-ordered'], STORED_BUILD.decision['eligible-ordered']);
});

// ---------------------------------------------------------------------------------------------
// Usage windows, learning: outcome tokens and observed coefficients (synthetic readings and token counts)
// ---------------------------------------------------------------------------------------------
const withTokens = (over, tokens) => {
  const o = outcome(over);
  if (tokens !== undefined) o.evidence = { ...o.evidence, 'actual-tokens': tokens };
  return o;
};

test('outcome: evidence.actual-tokens is recorded as the additive field tokens (integer >= 0, or null = unknown; absent = null); anything else is exit 2', () => {
  const trace = tmp();
  const cycleWith = (taskId, tokens) => {
    const d = run(req({ taskId }), { traceDir: trace });
    dispatch(taskId, 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW });
    return { d, rec: () => recordOutcome(withTokens({ 'task-id': taskId, outcome: 'accepted', 'original-brief-fingerprint': d.briefFingerprint }, tokens), { traceDir: trace, policyPath: POLICY_PATH, now: NOW }) };
  };
  assert.equal(cycleWith('ot-1', 412345).rec().tokens, 412345);
  assert.equal(cycleWith('ot-2', 0).rec().tokens, 0);
  assert.equal(cycleWith('ot-3', null).rec().tokens, null);
  const absent = cycleWith('ot-4', undefined).rec();
  assert.ok(Object.hasOwn(absent, 'tokens'));
  assert.equal(absent.tokens, null);
  // §10.5 counters stay as they are; the outcome file keeps the Outcome as given
  assert.deepEqual(absent.counters, { 'calls-used': 1, 'calls-limit': 6, 'cash-spent': null, 'cash-cap': null, 'repairs-used': 0, 'repairs-allowed': 1 });
  const { d } = cycleWith('ot-5', undefined);
  for (const bad of [-1, 1.5, '1000', true, {}]) {
    const out = cli(['outcome', writeJson(withTokens({ 'task-id': 'ot-5', outcome: 'accepted', 'original-brief-fingerprint': d.briefFingerprint }, bad)), '--trace', trace, '--now', NOW]);
    assert.equal(out.code, 2, `${JSON.stringify(bad)}: ${out.stdout}`);
    assert.match(out.stderr, /invalid Outcome \(spec-v2 §10\.3\): evidence\.actual-tokens \(an integer >= 0, or null = unknown\)/);
  }
  assert.equal(readLedger(trace).filter((r) => r['task-id'] === 'ot-5' && r.kind === 'outcome').length, 0);
});

// one review unit decided, dispatched and closed at `at` with `tokens` recorded (feature-off fixture: the windows
// do not gate here; rate reads them through the committed policy)
function unitAt(trace, taskId, at, tokens) {
  const d = run(req({ taskId, now: at }), { traceDir: trace });
  dispatch(taskId, 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: at });
  recordOutcome(withTokens({ 'task-id': taskId, outcome: 'accepted', 'original-brief-fingerprint': d.briefFingerprint }, tokens), { traceDir: trace, policyPath: POLICY_PATH, now: at });
  return d.briefFingerprint;
}
const FIVE_RESET = '2026-10-17T23:00:00Z';
const SEVEN_RESET = '2026-10-23T19:00:00Z';
function readingAt(trace, at, five, seven, fiveReset = FIVE_RESET) {
  const r = usageCli(trace, { windows: { five_hour: { utilization: five, 'resets-at': fiveReset }, seven_day: { utilization: seven, 'resets-at': SEVEN_RESET } }, note: 'synthetic' }, at);
  assert.equal(r.code, 0, r.stderr);
}
const at = (minutes) => isoAt(NOW_MS + minutes * MIN);
const rateOn = (trace) => rate({ traceDir: trace, policyPath: USAGE_POLICY_PATH, now: at(600) });

test('rate: observed coefficients from consecutive readings and the outcome tokens between them; an upward proposal at once; skipped pairs counted', () => {
  const trace = tmp();
  readingAt(trace, at(0), 0.2, 0.05);
  const fp = unitAt(trace, 'ob-1', at(30), 400000);
  // a superseding outcome for the same dispatch counts once (one outcome per dispatch, F4): T stays 400000
  recordOutcome(withTokens({ 'task-id': 'ob-1', outcome: 'accepted', 'original-brief-fingerprint': fp }, 400000), { traceDir: trace, policyPath: POLICY_PATH, now: at(45) });
  readingAt(trace, at(60), 0.32, 0.08); // pair 1: 0.12 / 0.4 Mtok = 0.3 (five_hour), 0.03 / 0.4 = 0.075 (seven_day)
  readingAt(trace, at(90), 0.32, 0.08); // pair 2: no outcome in (60, 90]: T = 0, skipped
  unitAt(trace, 'ob-2', at(105), null);
  readingAt(trace, at(120), 0.4, 0.1); // pair 3: an outcome with unknown tokens: skipped
  unitAt(trace, 'ob-3', at(150), 100000); // at the later reading's ts: inside (ts1, ts2]
  readingAt(trace, at(150), 0.025, 0.1015, '2026-10-18T01:30:00Z'); // pair 4: five_hour reset in between: skipped; seven_day 0.0015 / 0.1
  const r = rateOn(trace);
  assert.deepEqual(r.stats.usage, {
    five_hour: {
      observed: [{ from: at(0), to: at(60), delta: 0.12, tokens: 400000, coefficient: 0.3 }],
      considered: 1, 'ratified-at': null,
      'max-observed': 0.3, current: 0.24, skipped: { reset: 1, spanning: 0, 'unknown-tokens': 1, 'zero-tokens': 1, 'negative-delta': 0 }
    },
    seven_day: {
      observed: [{ from: at(0), to: at(60), delta: 0.03, tokens: 400000, coefficient: 0.075 }, { from: at(120), to: at(150), delta: 0.0015, tokens: 100000, coefficient: 0.015 }],
      considered: 2, 'ratified-at': null,
      'max-observed': 0.075, current: 0.06, skipped: { reset: 0, spanning: 0, 'unknown-tokens': 1, 'zero-tokens': 1, 'negative-delta': 0 }
    }
  });
  assert.match(r.text, /^PROPOSAL usage-windows\.windows\.five_hour\.utilization-per-mtok: 0\.24 -> 0\.3 \(max observed exceeds the current by more than 10 %; upward at once\); not applied — the lead ratifies by editing host-policy\.json$/m);
  assert.match(r.text, /^PROPOSAL usage-windows\.windows\.seven_day\.utilization-per-mtok: 0\.06 -> 0\.075 /m);
  assert.deepEqual(r.usageProposals.map((p) => [p.window, p.from, p.to, p.direction]), [['five_hour', 0.24, 0.3, 'up'], ['seven_day', 0.06, 0.075, 'up']]);
  assert.deepEqual(JSON.parse(readFileSync(USAGE_POLICY_PATH, 'utf8')), USAGE_POLICY); // proposed, never applied
  assert.doesNotMatch(r.text, /^no proposals$/m);
  // regenerated byte-identically from the same ledger and readings
  const first = readFileSync(join(trace, 'qualification-stats.json'), 'utf8');
  rateOn(trace);
  assert.equal(readFileSync(join(trace, 'qualification-stats.json'), 'utf8'), first);
  // within 10 % above the current: no proposal
  const t2 = tmp();
  readingAt(t2, at(0), 0.2, 0.05);
  unitAt(t2, 'ob-4', at(30), 1000000);
  readingAt(t2, at(60), 0.46, 0.11); // 0.26 vs 0.24 (+8 %), 0.06 vs 0.06
  const r2 = rateOn(t2);
  assert.equal(r2.stats.usage.five_hour['max-observed'], 0.26);
  assert.deepEqual(r2.usageProposals, []);
  // the feature off: no usage section, nothing proposed
  assert.equal('usage' in rate({ traceDir: trace, policyPath: POLICY_PATH, now: at(600) }).stats, false);
});

test('rate: a lower coefficient is proposed only after three consecutive observations all below 90 % of the current', () => {
  const trace = tmp();
  // five_hour coefficients per pair (0.5 Mtok each): 0.20, 0.21, 0.23, 0.15, 0.18, 0.19; seven_day stays at 0.06
  const five = [0.1, 0.2, 0.305, 0.42, 0.495, 0.585, 0.68];
  const seven = [0.05, 0.08, 0.11, 0.14, 0.17, 0.2, 0.23];
  const proposalsAfter = (n) => {
    readingAt(trace, at(30 * n), five[n], seven[n]);
    return rateOn(trace).usageProposals;
  };
  readingAt(trace, at(0), five[0], seven[0]);
  const seen = [];
  for (let n = 1; n <= 6; n += 1) {
    unitAt(trace, `dn-${n}`, at(30 * n - 15), 500000);
    seen.push(proposalsAfter(n));
  }
  const r = rateOn(trace);
  assert.deepEqual(r.stats.usage.five_hour.observed.map((o) => o.coefficient), [0.2, 0.21, 0.23, 0.15, 0.18, 0.19]);
  assert.deepEqual(r.stats.usage.seven_day.observed.map((o) => o.coefficient), [0.06, 0.06, 0.06, 0.06, 0.06, 0.06]);
  // two low observations: too few; the third (0.23) is not below 0.216, so the run restarts; 0.15, 0.18 after it: two
  assert.deepEqual(seen.slice(0, 5), [[], [], [], [], []]);
  // 0.15, 0.18, 0.19: three consecutive below 0.216 -> propose the highest of the three (downward slowly)
  assert.deepEqual(seen[5].map((p) => [p.window, p.from, p.to, p.direction]), [['five_hour', 0.24, 0.19, 'down']]);
  assert.match(r.text, /^PROPOSAL usage-windows\.windows\.five_hour\.utilization-per-mtok: 0\.24 -> 0\.19 \(the last three observations are all below 90 % of the current; downward slowly\); not applied/m);
});

// the committed policy with its usage-windows block mutated, written to a tmp file
function policyWithUsage(mutate) {
  const p = JSON.parse(JSON.stringify(USAGE_POLICY));
  mutate(p['usage-windows']);
  const path = join(tmp(), 'host-policy.json');
  writeFileSync(path, JSON.stringify(p, null, 2));
  return path;
}

// a unit decided and dispatched at `start` (feature-off fixture) and closed at `end` with `tokens`
function spanAt(trace, taskId, start, end, tokens) {
  const d = run(req({ taskId, now: start }), { traceDir: trace });
  dispatch(taskId, 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: start });
  recordOutcome(withTokens({ 'task-id': taskId, outcome: 'accepted', 'original-brief-fingerprint': d.briefFingerprint }, tokens), { traceDir: trace, policyPath: POLICY_PATH, now: end });
}

test('SW-8: rate skips a pair of readings with a unit in flight at either end (its tokens cannot be split across the pairs it spans) and counts it as skipped.spanning', () => {
  const trace = tmp();
  readingAt(trace, at(0), 0.10, 0.05);
  // a 500000-token unit runs from minute 10 to minute 50: in flight at the minute-30 reading, so neither
  // pair around that reading says what its tokens cost; crediting all of them to (30, 60] would halve the rate
  spanAt(trace, 'sp-1', at(10), at(50), 500000);
  readingAt(trace, at(30), 0.16, 0.065);
  readingAt(trace, at(60), 0.22, 0.08);
  let r = rateOn(trace);
  assert.deepEqual(r.stats.usage.five_hour.observed, []);
  assert.equal(r.stats.usage.five_hour.skipped.spanning, 2);
  assert.deepEqual(r.usageProposals, []);
  // a unit that starts after one reading and closes before the next is a clean observation
  spanAt(trace, 'sp-2', at(70), at(80), 500000);
  readingAt(trace, at(90), 0.34, 0.11);
  r = rateOn(trace);
  assert.deepEqual(r.stats.usage.five_hour.observed.map((o) => [o.from, o.to, o.coefficient]), [[at(60), at(90), 0.24]]);
  assert.equal(r.stats.usage.five_hour.skipped.spanning, 2);
  // a unit still open (no outcome) at the latest reading keeps that pair out too
  const d = run(req({ taskId: 'sp-3', now: at(100) }), { traceDir: trace });
  dispatch('sp-3', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: at(100) });
  readingAt(trace, at(120), 0.40, 0.125);
  r = rateOn(trace);
  assert.equal(r.stats.usage.five_hour.observed.length, 1);
  assert.equal(r.stats.usage.five_hour.skipped.spanning, 3);
  assert.ok(d.briefFingerprint);
});

test('SW-5: a window\'s ratified-at marks the last ratified coefficient; rate considers only observations after it, so a ratified downward proposal is not followed by an upward one from older history', () => {
  const trace = tmp();
  // five_hour coefficients per pair (0.5 Mtok each): 0.23, 0.15, 0.18, 0.19 -> a downward proposal to 0.19
  const five = [0.1, 0.215, 0.29, 0.38, 0.475];
  const seven = [0.05, 0.08, 0.11, 0.14, 0.17];
  readingAt(trace, at(0), five[0], seven[0]);
  for (let n = 1; n <= 4; n += 1) { unitAt(trace, `rf-${n}`, at(30 * n - 15), 500000); readingAt(trace, at(30 * n), five[n], seven[n]); }
  const before = rateOn(trace);
  assert.deepEqual(before.usageProposals.map((p) => [p.window, p.from, p.to, p.direction]), [['five_hour', 0.24, 0.19, 'down']]);
  // the lead ratifies 0.19 at the time of the last reading; without the marker the all-history maximum (0.23)
  // would propose going straight back up (the reviewer's flip-flop probe)
  const ratified = policyWithUsage((u) => { u.windows.five_hour['utilization-per-mtok'] = 0.19; u.windows.five_hour['ratified-at'] = at(120); });
  const after = rate({ traceDir: trace, policyPath: ratified, now: at(600) });
  assert.deepEqual(after.usageProposals, []);
  assert.equal(after.stats.usage.five_hour['ratified-at'], at(120));
  assert.equal(after.stats.usage.five_hour.considered, 0);
  assert.equal(after.stats.usage.five_hour.observed.length, 4);
  // an observation after the marker counts again: 0.25 > 0.19 x 1.1 -> upward
  unitAt(trace, 'rf-5', at(135), 500000);
  readingAt(trace, at(150), five[4] + 0.125, seven[4] + 0.03);
  const later = rate({ traceDir: trace, policyPath: ratified, now: at(600) });
  assert.deepEqual(later.usageProposals.map((p) => [p.window, p.from, p.to, p.direction]), [['five_hour', 0.19, 0.25, 'up']]);
  assert.equal(later.stats.usage.five_hour.considered, 1);
  // a malformed marker is a policy error
  const bad = policyWithUsage((u) => { u.windows.five_hour['ratified-at'] = 'yesterday'; });
  const r = cli(['rate', '--trace', trace, '--policy', bad, '--now', at(600)]);
  assert.equal(r.code, 2, r.stdout);
  assert.match(r.stderr, /usage-windows\.windows\.five_hour\.ratified-at must be ISO-8601 when present/);
});

// ---------------------------------------------------------------------------------------------
// Review round 1 of the usage-windows unit (SW-1..SW-4)
// ---------------------------------------------------------------------------------------------
test('SW-1: a speculative set projects its summed tokens (both members run at once); a set that does not fit is not routed speculative, and dispatch re-checks the sum', () => {
  const spec = (taskId) => req({ taskId, uncertainty: 'high', hostOptIns: { speculative: true } });
  // review: 229000 tokens per delegate. One member fits, the pair does not:
  // 0.79 + 0.229 x 0.24 = 0.84496 <= 0.85, 0.79 + 0.458 x 0.24 = 0.89992 > 0.85
  const tight = tmp();
  usageCli(tight, rateLimitInfo(NOW, { five: 0.79 }), NOW);
  const d = decideOn(spec('sw1-1'), tight);
  assert.equal(d.route, 'delegate');
  assert.equal(d.decision.profile, 'cc-opus-high');
  assert.equal(d.decision['usage-tokens'], 229000);
  assert.equal(d.decision['speculative-set'], null);
  assert.ok(d.decision.uncertainty.includes('uncertainty high; speculative not used (the set\'s summed usage projection, 458000 tokens, does not fit: usage window five_hour: projected 0.8999 > 0.85 (stop-at 0.9 - lead-reserve 0.05); resets 2026-10-17T23:00:00Z; defer until the reset)'), d.decision.uncertainty.join('|'));
  // the pair fits: speculative, with the set's sum projected and recorded
  const roomy = tmp();
  usageCli(roomy, rateLimitInfo(NOW, { five: 0.2 }), NOW);
  const s = decideOn(spec('sw1-2'), roomy);
  assert.equal(s.route, 'speculative');
  assert.deepEqual(s.decision['speculative-set'].candidates.map((c) => c.profile), ['cc-opus-high', 'cc-fable-high']);
  assert.equal(s.decision['usage-tokens'], 458000);
  assert.equal(s.record['usage-tokens'], 458000);
  assert.equal(s.decision.usage.windows.five_hour.projected, 0.3099); // 0.2 + 0.458 x 0.24
  // dispatch re-checks the sum: a new reading in which one member still fits and the pair does not refuses
  // (0.75 + 0.229 x 0.24 = 0.805 fits, 0.75 + 0.458 x 0.24 = 0.8599 does not)
  usageCli(roomy, rateLimitInfo(at(1), { five: 0.75 }), at(1));
  const ledger = join(roomy, 'ledger.jsonl');
  const before = readFileSync(ledger, 'utf8');
  const out = cli(['dispatch', 'sw1-2', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', roomy, '--now', at(2), '--policy', USAGE_POLICY_PATH]);
  assert.equal(out.code, 3, out.stdout);
  assert.match(out.stderr, /usage check refused cc-opus-high \(decision seq 1, usage-tokens 458000\): usage window five_hour: projected 0\.8599 > 0\.85/);
  assert.equal(readFileSync(ledger, 'utf8'), before);
});

test('SW-2: Gate 4 counts the usage-tokens of every dispatch made since the reading, in decide and in dispatch; a speculative set\'s own members are its sum, not extra', () => {
  const trace = tmp();
  const ledger = join(trace, 'ledger.jsonl');
  // build-core: 545000 tokens per delegate, 0.1308 of five_hour. 0.70 + 0.1308 = 0.8308 fits alone
  usageCli(trace, rateLimitInfo(NOW, { five: 0.70 }), NOW);
  const core = (taskId, now) => req({ taskId, category: 'build-core', now });
  const dispatchAt = (taskId, now, profile = 'cc-opus-high') => cli(['dispatch', taskId, profile, '--project-stop', CLEAR_JSON, '--trace', trace, '--now', now, '--policy', USAGE_POLICY_PATH]);
  const da = decideOn(core('cum-a', at(1)), trace);
  assert.equal(da.route, 'delegate');
  assert.equal(decideOn(core('cum-c', at(1)), trace).route, 'delegate'); // decided before cum-a's dispatch
  const a = dispatchAt('cum-a', at(2));
  assert.equal(a.code, 0, a.stderr);
  assert.equal(readLedger(trace).pop()['usage-tokens'], 545000); // the dispatch record carries the tokens it commits
  // decide: 0.70 + (545000 dispatched since the reading + 545000) x 0.24 = 0.9616 > 0.85
  const b = decideOn(core('cum-b', at(3)), trace);
  assert.equal(b.route, 'blocked');
  assert.equal(b.decision.candidates['cc-opus-high'].reason, 'usage window five_hour: projected 0.9616 (with 545000 tokens dispatched and not in the reading) > 0.85 (stop-at 0.9 - lead-reserve 0.05); resets 2026-10-17T23:00:00Z; defer until the reset');
  assert.equal(b.decision.usage['dispatched-not-in-reading-tokens'], 545000);
  assert.equal(b.decision.usage.windows.five_hour['headroom-mtok'], 0.08); // (0.85 - 0.70) / 0.24 - 0.545
  // dispatch: cum-c was decided before cum-a was dispatched; its dispatch counts cum-a now
  const before = readFileSync(ledger, 'utf8');
  const c = dispatchAt('cum-c', at(4));
  assert.equal(c.code, 3, c.stdout);
  assert.match(c.stderr, /usage check refused cc-opus-high \(decision seq 1, usage-tokens 545000\): usage window five_hour: projected 0\.9616 \(with 545000 tokens dispatched and not in the reading\) > 0\.85/);
  assert.equal(readFileSync(ledger, 'utf8'), before);
  // the summary shows the dispatched tokens and the headroom after them
  const s = cli(['usage', '--trace', trace, '--now', at(4), '--policy', USAGE_POLICY_PATH]);
  assert.match(s.stdout, /^ {2}dispatched and not in the reading: 545000 tokens \(545000 since the reading, 0 in flight from before it\)$/m);
  assert.match(s.stdout, /^ {2}five_hour: utilization 0\.7, resets 2026-10-17T23:00:00Z, headroom 0\.08 Mtok \(\(0\.9 - 0\.05 - 0\.7\) \/ 0\.24 - 0\.545 dispatched and not in the reading\)$/m);
  // a reading taken at or after a dispatch's outcome holds all of it: cum-a no longer counts (SW-7: before its
  // outcome, a reading taken while it runs does not close it)
  recordOutcome(outcome({ 'task-id': 'cum-a', outcome: 'accepted', 'original-brief-fingerprint': da.briefFingerprint }), { traceDir: trace, policyPath: USAGE_POLICY_PATH, now: at(5) });
  usageCli(trace, rateLimitInfo(at(5), { five: 0.71 }), at(5));
  assert.equal(decideOn(core('cum-d', at(6)), trace).route, 'delegate'); // 0.71 + 0.1308 = 0.8408
  // a speculative set: its sum covers its own members, so the second member is not counted twice
  // (review: 229000 per member; 0.70 + 0.458 x 0.24 = 0.8099 fits, 0.70 + 0.687 x 0.24 = 0.8649 would not)
  const t2 = tmp();
  usageCli(t2, rateLimitInfo(NOW, { five: 0.70 }), NOW);
  const s2 = decideOn(req({ taskId: 'cum-s', uncertainty: 'high', hostOptIns: { speculative: true } }), t2);
  assert.equal(s2.route, 'speculative');
  for (const p of ['cc-opus-high', 'cc-fable-high']) {
    const r = cli(['dispatch', 'cum-s', p, '--project-stop', CLEAR_JSON, '--trace', t2, '--now', at(1), '--policy', USAGE_POLICY_PATH]);
    assert.equal(r.code, 0, `${p}: ${r.stderr}`);
    assert.equal(readLedger(t2).pop()['usage-tokens'], 229000); // each member commits its share of the set's sum
  }
  // a dispatch since the reading with no usage-tokens (dispatched with the feature off) is unknown: fail closed
  const t3 = tmp();
  usageCli(t3, rateLimitInfo(NOW), NOW);
  run(req({ taskId: 'unk-a', now: at(1) }), { traceDir: t3 });
  dispatch('unk-a', 'cc-opus-high', { projectStop: CLEAR, traceDir: t3, policyPath: POLICY_PATH, now: at(1) });
  const u = decideOn(req({ taskId: 'unk-b', now: at(2) }), t3);
  assert.equal(u.route, 'blocked');
  assert.equal(u.decision.candidates['cc-opus-high'].reason, 'usage reading 2026-10-17T19:00:00Z predates dispatch seq 2 of unk-a, whose usage-tokens are unknown; refresh with route.mjs usage');
});

test('SW-3: rate skips a pair whose utilization fell (counted as negative-delta) and never proposes a coefficient <= 0', () => {
  // five_hour falls 0.5 -> 0.45 -> 0.40 -> 0.35 under one resets-at, a 500k-token unit between each pair
  const trace = tmp();
  const five = [0.5, 0.45, 0.4, 0.35];
  const seven = [0.05, 0.08, 0.11, 0.14];
  readingAt(trace, at(0), five[0], seven[0]);
  for (let n = 1; n <= 3; n += 1) {
    unitAt(trace, `neg-${n}`, at(30 * n - 15), 500000);
    readingAt(trace, at(30 * n), five[n], seven[n]);
  }
  const r = rateOn(trace);
  assert.deepEqual(r.stats.usage.five_hour, { observed: [], considered: 0, 'ratified-at': null, 'max-observed': null, current: 0.24, skipped: { reset: 0, spanning: 0, 'unknown-tokens': 0, 'zero-tokens': 0, 'negative-delta': 3 } });
  assert.deepEqual(r.stats.usage.seven_day.observed.map((o) => o.coefficient), [0.06, 0.06, 0.06]);
  assert.deepEqual(r.usageProposals, []);
  // an unchanged utilization is an observation of 0, and three of them never propose 0
  const flat = tmp();
  readingAt(flat, at(0), 0.5, seven[0]);
  for (let n = 1; n <= 3; n += 1) {
    unitAt(flat, `flat-${n}`, at(30 * n - 15), 500000);
    readingAt(flat, at(30 * n), 0.5, seven[n]);
  }
  const f = rateOn(flat);
  assert.deepEqual(f.stats.usage.five_hour.observed.map((o) => o.coefficient), [0, 0, 0]);
  assert.deepEqual(f.usageProposals, []);
  assert.match(f.text, /^no proposals$/m);
});

test('SW-4: a reading\'s ts is when the platform observed it: pasted with its event\'s --now it is stale 83 minutes later; without --now the clock is used and a note says so', () => {
  // the brief's 2026-10-17T19:00:22Z event, pasted at 20:23:46Z with its own timestamp: stale for a decision then
  const trace = tmp();
  const event = { unifiedWindows: { five_hour: { resetsAt: 1792278000, utilization: 0.2 }, seven_day: { resetsAt: 1792864800, utilization: 0.05 } } };
  const pasted = usageCli(trace, event, '2026-10-17T19:00:22Z');
  assert.equal(pasted.code, 0, pasted.stderr);
  assert.equal(pasted.stderr, ''); // --now given: no note
  const d = decideOn(req({ taskId: 'sw4-1', now: '2026-10-17T20:23:46Z' }), trace);
  assert.equal(d.route, 'blocked');
  assert.equal(d.decision.candidates['cc-opus-high'].reason, 'usage reading stale: age 83.4 min > 30; refresh with route.mjs usage');
  // without --now the reading is recorded at the clock (the brief's default), with a note on stderr
  const t2 = tmp();
  const live = cli(['usage', writeJson(rateLimitInfo(new Date().toISOString())), '--trace', t2, '--policy', USAGE_POLICY_PATH]);
  assert.equal(live.code, 0, live.stderr);
  assert.match(live.stderr, /^route\.mjs: note: no --now, so the reading's ts is the clock \(\S+\); pass --now <the rate_limit_event's own timestamp>, because staleness is measured from ts$/m);
});

test('SW-7: a unit dispatched before the reading and still running counts at its full usage-tokens until a reading taken at or after its outcome; two such delegations cannot both pass Gate 4', () => {
  // the reviewer's trace: build-core, 545000 tokens per delegate = 0.1308 of five_hour; limit 0.85
  const trace = tmp();
  const ledger = join(trace, 'ledger.jsonl');
  const core = (taskId, now) => req({ taskId, category: 'build-core', now });
  const dispatchAt = (taskId, now) => cli(['dispatch', taskId, 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', now, '--policy', USAGE_POLICY_PATH]);
  usageCli(trace, rateLimitInfo(NOW, { five: 0.70 }), NOW);
  const a = decideOn(core('inf-a', at(1)), trace);
  assert.equal(a.route, 'delegate');
  assert.equal(decideOn(core('inf-c', at(1)), trace).route, 'delegate'); // decided before inf-a's dispatch
  assert.equal(dispatchAt('inf-a', at(6)).code, 0);
  // the staleness rule forces a refresh while inf-a runs; the reading holds almost none of it
  usageCli(trace, rateLimitInfo(at(31), { five: 0.71 }), at(31));
  // decide: 0.71 + (545000 in flight + 545000) x 0.24 = 0.9716 > 0.85
  const b = decideOn(core('inf-b', at(32)), trace);
  assert.equal(b.route, 'blocked');
  assert.equal(b.decision.candidates['cc-opus-high'].reason, 'usage window five_hour: projected 0.9716 (with 545000 tokens dispatched and not in the reading) > 0.85 (stop-at 0.9 - lead-reserve 0.05); resets 2026-10-17T23:31:00Z; defer until the reset');
  assert.equal(b.decision.usage['dispatched-not-in-reading-tokens'], 545000);
  // dispatch: inf-c was decided against the first reading; at its dispatch inf-a is still in flight
  const before = readFileSync(ledger, 'utf8');
  const c = dispatchAt('inf-c', at(33));
  assert.equal(c.code, 3, c.stdout);
  assert.match(c.stderr, /usage check refused cc-opus-high \(decision seq 1, usage-tokens 545000\): usage window five_hour: projected 0\.9716 \(with 545000 tokens dispatched and not in the reading\) > 0\.85/);
  assert.equal(readFileSync(ledger, 'utf8'), before);
  const s = cli(['usage', '--trace', trace, '--now', at(33), '--policy', USAGE_POLICY_PATH]);
  assert.match(s.stdout, /^ {2}dispatched and not in the reading: 545000 tokens \(0 since the reading, 545000 in flight from before it\)$/m);
  // an outcome alone does not close it: the reading still predates the work inf-a did after 19:31
  recordOutcome({ ...outcome({ 'task-id': 'inf-a', outcome: 'accepted', 'original-brief-fingerprint': a.briefFingerprint }), evidence: { ...outcome().evidence, 'actual-tokens': 540000 } }, { traceDir: trace, policyPath: USAGE_POLICY_PATH, now: at(40) });
  assert.equal(decideOn(core('inf-d', at(41)), trace).route, 'blocked');
  // a reading taken at or after the outcome holds all of inf-a: it stops counting
  usageCli(trace, rateLimitInfo(at(42), { five: 0.83 - 0.1308 }), at(42));
  assert.equal(decideOn(core('inf-e', at(43)), trace).route, 'delegate'); // 0.6992 + 0.1308 = 0.83
  // a unit in flight from before the reading with no usage-tokens (dispatched with the feature off) is unknown: fail closed
  const t3 = tmp();
  run(req({ taskId: 'unk-a', now: at(1) }), { traceDir: t3 });
  dispatch('unk-a', 'cc-opus-high', { projectStop: CLEAR, traceDir: t3, policyPath: POLICY_PATH, now: at(1) });
  usageCli(t3, rateLimitInfo(at(2)), at(2));
  const u = decideOn(req({ taskId: 'unk-b', now: at(3) }), t3);
  assert.equal(u.route, 'blocked');
  assert.equal(u.decision.candidates['cc-opus-high'].reason, 'usage reading 2026-10-17T19:02:00Z does not hold dispatch seq 2 of unk-a (in flight since 2026-10-17T19:01:00Z, no outcome before the reading), whose usage-tokens are unknown; record its outcome, then refresh with route.mjs usage');
});

// ---------------------------------------------------------------------------------------------
// host-policy-2 (unit sr-policy-2): calibration-1 evidence under the lead's qualification rules
// (briefs/policy2-builder.md); the live policy is decided on its feature-off derivative (R1(a))
// ---------------------------------------------------------------------------------------------
const LIVE_OFF_PATH = join(tmp(), 'host-policy-live-off.json');
writeFileSync(LIVE_OFF_PATH, featureOff(COMMITTED_POLICY));
const livePolicyWith = (mutate) => {
  const p = JSON.parse(readFileSync(LIVE_OFF_PATH, 'utf8'));
  mutate(p);
  const path = join(tmp(), 'host-policy.json');
  writeFileSync(path, JSON.stringify(p, null, 2));
  return path;
};
// the host-policy-2 fixture's feature-off derivative (R1(a)), for the host-policy-2 assertions below
const HP2_OFF_PATH = join(tmp(), 'host-policy-2-off.json');
writeFileSync(HP2_OFF_PATH, featureOff(JSON.parse(readFileSync(HP2_POLICY_PATH, 'utf8'))));
const hp2PolicyWith = (mutate) => {
  const p = JSON.parse(readFileSync(HP2_OFF_PATH, 'utf8'));
  mutate(p);
  const path = join(tmp(), 'host-policy.json');
  writeFileSync(path, JSON.stringify(p, null, 2));
  return path;
};
const CAL1 = JSON.parse(readFileSync(join(HERE, 'trace', 'calibration-1', 'observations.json'), 'utf8'));
// the calibration tasks and the categories they represent (rule 4: the pin task is pin-tests, not build-tests)
const CAL_TASKS = [['pin-tests', 'pin', (o) => o.pin.score], ['fix', 'fix', (o) => o.fix.score], ['review', 'review', (o) => o['review-grade'].score]];
// an observation's profile is the policy profile with its model and effort (the observation key ends in the effort)
const calProfile = (policy, o) => policy.profiles.find((x) => x.model === o.usage.pin.model && x.effort === o.profile.split('-').pop()) ?? null;
// the largest tokens an accepted outcome in the committed ledger completed, per profile id (outcome records carry the
// additive field tokens, null when unknown)
// The committed ledger grows with every unit, so the tests that read it bind to an instant: records after `cutoff` are
// left out. 2026-10-18T01:45:00Z is after every record the host-policy-2 fixture was frozen with (sr-policy-3 seq 1-4)
// and before that unit's accepted outcome (seq 5, 02:20), which raised cc-opus-high again (the lead's P3-L2).
const FREEZE_HP2 = '2026-10-18T01:45:00Z';
function frozenTrace(cutoff) {
  const dir = tmp();
  cpSync(join(HERE, 'trace'), dir, { recursive: true });
  const kept = readFileSync(join(dir, 'ledger.jsonl'), 'utf8').split('\n').filter((l) => l && JSON.parse(l).ts <= cutoff);
  writeFileSync(join(dir, 'ledger.jsonl'), kept.join('\n') + '\n');
  return dir;
}
function acceptedTokens(cutoff) {
  const max = {};
  for (const r of readLedger(join(HERE, 'trace'))) {
    if (r.kind !== 'outcome' || !/^outcome accepted /.test(r.detail) || !Number.isInteger(r.tokens)) continue;
    if (cutoff && !(r.ts <= cutoff)) continue;
    const id = /^\(([^,]+),/.exec(r.profile)[1];
    max[id] = Math.max(max[id] ?? 0, r.tokens);
  }
  return max;
}
const NEW_PROFILES = ['cc-sonnet-low', 'cc-sonnet-medium', 'cc-sonnet-high', 'cc-opus-medium', 'cc-haiku-low', 'cc-haiku-medium', 'cc-haiku-high', 'cc-fable-medium'];

test('fixture: trace/policies/host-policy-1.json is the pre-revision policy, byte-identical to the policy the sr-policy-2 decision was bound to', () => {
  assert.ok(existsSync(FIXTURE_POLICY_PATH), 'the host-policy-1 fixture exists');
  const bound = JSON.parse(readFileSync(join(goldenDir, 'sr-policy-2-1.json'), 'utf8')).bindings;
  assert.equal(bound['policy-revision'], 'host-policy-1');
  assert.equal(createHash('sha256').update(readFileSync(FIXTURE_POLICY_PATH)).digest('hex'), bound['policy-sha256']);
  assert.equal(loadPolicy(FIXTURE_POLICY_PATH)['policy-revision'], 'host-policy-1');
  // the goldens' categories map never mistakes the fixture for a decision file
  assert.equal(JSON.parse(readFileSync(FIXTURE_POLICY_PATH, 'utf8')).request, undefined);
});

// a policy fixture is not a decision: in trace/decisions/ it would sit in the <task>-<seq>.json namespace, and a task
// with id host-policy could never be decided at seq 1 (P2-3)
test('fixture: no policy fixture sits among the decisions; every trace/decisions file is a decision, and a task host-policy decides at seq 1', () => {
  for (const f of readdirSync(goldenDir).filter((x) => x.endsWith('.json'))) {
    const j = JSON.parse(readFileSync(join(goldenDir, f), 'utf8'));
    assert.ok(typeof j.request?.taskId === 'string', `${f} is not a decision file`);
  }
  const trace = tmp();
  cpSync(join(HERE, 'trace'), trace, { recursive: true });
  const before = readFileSync(join(trace, 'ledger.jsonl'), 'utf8');
  const r = cli(['decide', writeJson(req({ taskId: 'host-policy' })), '--trace', trace, '--policy', LIVE_OFF_PATH]);
  assert.equal(r.code, 0, r.stderr);
  assert.equal(JSON.parse(readFileSync(join(trace, 'decisions', 'host-policy-1.json'), 'utf8')).request.taskId, 'host-policy');
  assert.ok(readFileSync(join(trace, 'ledger.jsonl'), 'utf8').startsWith(before), 'appended, never rewritten');
});

test('host-policy-2: the pin-tests category and qualified-for per the lead\'s rules from calibration-1; evidence entries record every grade, fails included', () => {
  const live = loadPolicy(HP2_POLICY_PATH);
  const fixture = loadPolicy(FIXTURE_POLICY_PATH);
  assert.equal(live['policy-revision'], 'host-policy-2');
  const pin = live.categories['pin-tests'];
  assert.equal(pin.risk, 'normal');
  assert.equal(pin['median-tokens'], 120000);
  assert.deepEqual(pin.verification, ['lint', 'the new tests green', 'guard-removal proof', 'the lead reads the diff']);
  assert.ok(!pin.verification.some((v) => /review/i.test(v)), 'a pin needs no reviewer: verified mechanically plus the lead\'s diff read');
  assert.equal(live.economics['lead-direct-profile'], 'cc-fable-xhigh');
  for (const id of [...fixture.profiles.map((x) => x.id), ...NEW_PROFILES]) assert.ok(live.profiles.some((x) => x.id === id), id);
  const fails = [];
  for (const o of Object.values(CAL1)) {
    const pr = calProfile(live, o);
    if (!pr) continue; // a calibrated profile the revision does not add
    for (const [cat, , score] of CAL_TASKS) {
      const entry = `calibration-1: ${cat} ${score(o) ? 'PASS' : 'FAIL'} (n=1)`;
      assert.ok(pr.evidence.includes(entry), `${pr.id} lacks "${entry}"`);
      if (!score(o)) fails.push(`${pr.id} ${cat}`);
    }
    // rule 4 and the table: every pin PASS qualifies for pin-tests
    assert.equal(pr['qualified-for'].includes('pin-tests'), CAL_TASKS[0][2](o), pr.id);
    const before = fixture.profiles.find((x) => x.id === pr.id);
    // rule 2: one calibration pass never qualifies a high-risk category; the existing (production) ones are kept
    const highRisk = (ids) => ids.filter((c) => live.categories[c]?.risk === 'high').sort();
    assert.deepEqual(highRisk(pr['qualified-for']), highRisk(before ? before['qualified-for'] : []), pr.id);
    if (before) assert.deepEqual([...pr['qualified-for']].sort(), [...before['qualified-for'], 'pin-tests'].sort(), pr.id);
    if (!before || !before['qualified-at']) {
      assert.deepEqual([pr['qualified-for'], pr['qualified-at'], pr.expires, pr.reviewer], [['pin-tests'], '2026-10-17', '2027-01-15', 'host-declared (lead) from calibration-1 grades'], pr.id);
    }
  }
  assert.deepEqual(fails.sort(), ['cc-haiku-high review', 'cc-haiku-low review', 'cc-haiku-medium review', 'cc-sonnet-high review']);
  // headroom is the largest completed run, rounded up to the next thousand (the host-policy-1 basis: a 91k run gave
  // 92000), and never lowered: a calibration run, or an accepted outcome in the ledger (the policy maintenance of
  // 490b7ed raised cc-opus-high to 771000 from the accepted sr-policy-2 outcome, 770527 tokens)
  const accepted = acceptedTokens(FREEZE_HP2);
  for (const o of Object.values(CAL1)) {
    const pr = calProfile(live, o);
    if (!pr) continue;
    const max = Math.max(...Object.values(o.usage).filter((u) => u.state === 'done').map((u) => u.tokens), accepted[pr.id] ?? 0);
    const before = fixture.profiles.find((x) => x.id === pr.id)?.['headroom-tested'] ?? 0;
    assert.equal(pr['headroom-tested'], Math.max(before, Math.ceil(max / 1000) * 1000), pr.id);
  }
});

test('host-policy-2 validation: qualified-for and calibration evidence entries must name policy categories and be well formed (exit 2)', () => {
  const bad = [
    [(p) => { p.profiles.find((x) => x.id === 'cc-haiku-low')['qualified-for'].push('pin-test'); }, /profile cc-haiku-low qualified-for names unknown category 'pin-test'/],
    [(p) => { p.profiles.find((x) => x.id === 'cc-haiku-low').evidence = 'calibration-1'; }, /profile cc-haiku-low evidence must be an array of strings/],
    [(p) => { p.profiles.find((x) => x.id === 'cc-haiku-low').evidence.push('calibration-1: pin-tests pass'); }, /profile cc-haiku-low evidence 'calibration-1: pin-tests pass' is not 'calibration-<n>: <category> PASS\|PARTIAL\|FAIL \(n=<k>\)'/],
    [(p) => { p.profiles.find((x) => x.id === 'cc-haiku-low').evidence.push('calibration-1: pin PASS (n=1)'); }, /profile cc-haiku-low evidence 'calibration-1: pin PASS \(n=1\)' names unknown category 'pin'/]
  ];
  for (const [mutate, message] of bad) {
    const path = hp2PolicyWith(mutate);
    assert.throws(() => loadPolicy(path), (e) => e instanceof RouterError && e.code === 2 && message.test(e.message), String(message));
    const r = cli(['rate', '--trace', tmp(), '--policy', path]);
    assert.equal(r.code, 2, r.stdout);
    assert.match(r.stderr, message);
  }
  assert.equal(loadPolicy(HP2_POLICY_PATH)['policy-revision'], 'host-policy-2');
  assert.equal(loadPolicy(FIXTURE_POLICY_PATH)['policy-revision'], 'host-policy-1');
});

test('host-policy-2 golden-style: the three hand-walked requests still route to the same profiles; the new profiles are ineligible at Gate 2', () => {
  const live = JSON.parse(readFileSync(HP2_OFF_PATH, 'utf8'));
  for (const file of HAND) {
    const golden = JSON.parse(readFileSync(join(goldenDir, file), 'utf8'));
    const decided = cliDecide(golden.request, HP2_OFF_PATH);
    assert.equal(decided.bindings['policy-revision'], 'host-policy-2', file);
    const got = decided.decision;
    const want = golden.decision;
    for (const k of ['route', 'profile', 'all-in-bound-usd', 'eligible-ordered']) assert.deepEqual(got[k], want[k], `${file} ${k}`);
    assert.deepEqual(Object.keys(got.candidates), live.profiles.map((x) => x.id), `${file}: every host-policy-2 profile is walked`);
    for (const [id, c] of Object.entries(want.candidates)) {
      if (!c.eligible) assert.equal(got.candidates[id]['first-failing-gate'], c['first-failing-gate'], `${file} ${id}`);
    }
    for (const id of NEW_PROFILES.filter((x) => !(x in want.candidates))) {
      const c = got.candidates[id];
      assert.equal(c.eligible, false, `${file} ${id}`);
      assert.equal(c['first-failing-gate'], 2, `${file} ${id}`);
      assert.match(c.reason, new RegExp(`${id} not qualified for ${golden.request.category}`), `${file} ${id}`);
    }
  }
});

test('host-policy-2 routing: review and fix still route to cc-opus-high, with the same reviewer for the work categories', () => {
  const live = loadPolicy(HP2_OFF_PATH);
  for (const category of ['review', 'fix', 'build-core']) {
    const d = computeDecision(req({ category }), live, []);
    assert.equal(d.route, 'delegate', category);
    assert.equal(d.profile, 'cc-opus-high', category);
    for (const id of NEW_PROFILES) assert.equal(d.candidates[id]['first-failing-gate'], 2, `${category} ${id}`);
  }
  assert.equal(computeDecision(req({ category: 'build-core' }), live, [])['review-profile'], 'cc-opus-high');
  assert.equal(computeDecision(req({ category: 'review' }), live, [])['all-in-bound-usd'], computeDecision(req({ category: 'review' }), loadPolicy(POLICY_PATH), [])['all-in-bound-usd']);
});

test('host-policy-2 routing: a pin-tests request routes to cc-haiku-low at the output-rate bound $0.06 (no reviewer); equal bounds rank the lower effort first', () => {
  const live = loadPolicy(HP2_OFF_PATH);
  // req() draws its checks from the base fixture, which has no pin-tests: the live category's checks are named here
  const pinReq = () => ({ ...req(), category: 'pin-tests', acceptanceChecks: live.categories['pin-tests'].verification.map((name) => ({ command: `run ${name}`, expect: 'pass' })) });
  const d = computeDecision(pinReq(), live, []);
  assert.equal(d.route, 'delegate');
  assert.equal(d.profile, 'cc-haiku-low');
  const c = d.candidates['cc-haiku-low'];
  assert.deepEqual([c['work-bound-usd'], c['review-bound-usd'], c['overhead-bound-usd'], c['all-in-bound-usd']], [0.06, 0, 1, 1.06]);
  assert.equal(d['review-profile'], null);
  // the three same-model profiles share the bound; calibration-1 spent fewer tokens at the lower effort on every task
  assert.deepEqual(d['eligible-ordered'].slice(0, 3), ['cc-haiku-low', 'cc-haiku-medium', 'cc-haiku-high']);
  for (const id of ['cc-haiku-medium', 'cc-haiku-high']) assert.equal(d.candidates[id]['all-in-bound-usd'], 1.06, id);
  // headroom is per profile: a 120000-token pin does not fit the smallest calibrated runs
  assert.match(d.candidates['cc-sonnet-low'].reason, /context: 120000 tokens not below headroom-tested 110000 on cc-sonnet-low/);
  assert.match(d.candidates['cc-opus-medium'].reason, /context: 120000 tokens not below headroom-tested 115000 on cc-opus-medium/);
  assert.equal(d.candidates['cc-fable-xhigh'].reason, 'direct unsuitable: 120000 tokens > direct-max-tokens 15000');
  assert.match(d.text, /^Profile: {11}\(cc-haiku-low, /m);
  // the id still breaks a tie of rate and effort (S02/D01 twin)
  const twin = loadPolicy(hp2PolicyWith((p) => { p.profiles.push({ ...p.profiles.find((x) => x.id === 'cc-haiku-low'), id: 'cc-aaa-haiku' }); }));
  assert.equal(computeDecision(pinReq(), twin, []).profile, 'cc-aaa-haiku');
});

// the README's qualification table is generated from host-policy.json: every row is the policy verbatim, in policy order (P2-2)
test('README: the host-policy-3 qualification table matches host-policy.json row for row (15 rows), qualified-for in policy order, both runs\' grades', () => {
  const readme = readFileSync(join(HERE, 'README.md'), 'utf8');
  const start = readme.indexOf('### The table (host-policy-3');
  assert.ok(start >= 0, 'the README carries the host-policy-3 table');
  const section = readme.slice(start, readme.indexOf('\n#', start + 1));
  const rows = section.split('\n').filter((l) => /^\| `cc-/.test(l)).map((l) => l.split('|').slice(1, -1).map((c) => c.trim()));
  assert.equal(rows.length, 15);
  assert.deepEqual(rows.map((r) => r[0]), COMMITTED_POLICY.profiles.map((p) => `\`${p.id}\``), 'one row per profile, in policy order');
  for (const p of COMMITTED_POLICY.profiles) {
    const [, , qual, headroom, run1, run2] = rows.find((r) => r[0] === `\`${p.id}\``);
    assert.equal(qual, p['qualified-for'].join(', ') || 'none', `${p.id} qualified-for`);
    assert.equal(headroom, `${p['headroom-tested'] / 1000}k`, `${p.id} headroom-tested`);
    const grade = (run, cat) => (p.evidence.find((e) => e.startsWith(`calibration-${run}: ${cat} `)) ?? '').split(' ')[2] ?? '-';
    for (const [run, cell] of [[1, run1], [2, run2]]) {
      assert.equal(cell, ['pin-tests', 'fix', 'review'].map((cat) => grade(run, cat) || '-').join(' / '), `${p.id} calibration-${run} grades`);
    }
  }
});

// calibration evidence in rate: counted apart from the outcomes, printed as CALIBRATION lines, never a proposal
function calibrationTrace(runs) {
  const trace = tmp();
  runs.forEach((obs, i) => {
    mkdirSync(join(trace, `calibration-${i + 1}`));
    writeFileSync(join(trace, `calibration-${i + 1}`, 'observations.json'), typeof obs === 'string' ? obs : JSON.stringify(obs, null, 1));
  });
  return trace;
}

test('rate: a CALIBRATION line per profile and category from trace/calibration-1/observations.json, counted apart from the outcomes', () => {
  const live = loadPolicy(HP2_OFF_PATH);
  const trace = calibrationTrace([CAL1]);
  const r = rate({ traceDir: trace, policyPath: HP2_OFF_PATH, now: NOW });
  const lines = r.text.split('\n').filter((l) => l.startsWith('CALIBRATION '));
  assert.equal(lines.length, Object.keys(CAL1).length * CAL_TASKS.length, r.text);
  for (const o of Object.values(CAL1)) {
    const label = calProfile(live, o)?.id ?? `${o.profile} (no policy profile)`;
    for (const [cat, , score] of CAL_TASKS) {
      assert.ok(lines.includes(`CALIBRATION ${label} ${cat}: ${score(o) ? '1 pass, 0 partial, 0 fail' : '0 pass, 0 partial, 1 fail'} (calibration-1)`), `${label} ${cat}`);
    }
  }
  assert.equal(Object.values(CAL1).filter((o) => !calProfile(live, o)).length, 1, 'one calibrated profile is not in host-policy-2');
  assert.ok(r.text.indexOf('CALIBRATION ') > r.text.indexOf('regenerated'), 'next to the outcome stats');
  // the derived stats keep calibration apart: no outcome counted, no outcome stats, the observations pinned by digest
  const doc = JSON.parse(readFileSync(join(trace, 'qualification-stats.json'), 'utf8'));
  assert.equal(doc['outcomes-counted'], 0);
  assert.deepEqual(doc.stats, {});
  assert.deepEqual(doc.calibration.profiles['cc-haiku-low'], { fix: { fail: 0, partial: 0, pass: 1, ungraded: 0 }, 'pin-tests': { fail: 0, partial: 0, pass: 1, ungraded: 0 }, review: { fail: 1, partial: 0, pass: 0, ungraded: 0 } });
  assert.deepEqual(doc.calibration.runs, [{ run: 'calibration-1', 'observations-sha256': createHash('sha256').update(readFileSync(join(trace, 'calibration-1', 'observations.json'))).digest('hex') }]);
  assert.deepEqual(r.proposals, []);
  // regenerated identically, and the CLI prints the same lines
  const cliRate = cli(['rate', '--trace', trace, '--now', NOW, '--policy', HP2_OFF_PATH]);
  assert.equal(cliRate.code, 0, cliRate.stderr);
  assert.deepEqual(cliRate.stdout.split('\n').filter((l) => l.startsWith('CALIBRATION ')), lines);
  assert.equal(readFileSync(join(trace, 'qualification-stats.json'), 'utf8'), `${JSON.stringify(doc, null, 2)}\n`);
  // no calibration directory: no lines and no calibration block (the stats are what they were)
  const none = rate({ traceDir: tmp(), policyPath: HP2_OFF_PATH, now: NOW });
  assert.ok(!none.text.includes('CALIBRATION'), none.text);
  assert.equal('calibration' in none.stats, false);
});

test('rate: calibration passes and fails never make a proposal; proposals stay outcome-based; an unreadable observations file is exit 4', () => {
  const live = loadPolicy(HP2_OFF_PATH);
  const of = (id) => structuredClone(Object.values(CAL1).find((o) => calProfile(live, o)?.id === id));
  // three review passes for a profile not qualified for review (the outcome rule would propose qualification), and
  // three fix fails for a profile qualified for fix (the outcome rule would propose demotion)
  const oneRun = () => {
    const passer = of('cc-sonnet-high');
    passer['review-grade'].score = true;
    const failer = of('cc-opus-high');
    failer.fix.score = false;
    return { a: passer, b: failer };
  };
  const third = oneRun();
  third.b.fix.score = null; // not graded
  const trace = calibrationTrace([oneRun(), oneRun(), third]);
  const r = rate({ traceDir: trace, policyPath: HP2_OFF_PATH, now: NOW });
  assert.match(r.text, /^CALIBRATION cc-sonnet-high review: 3 pass, 0 partial, 0 fail \(calibration-1, calibration-2, calibration-3\)$/m);
  assert.match(r.text, /^CALIBRATION cc-opus-high fix: 0 pass, 0 partial, 2 fail, 1 ungraded \(calibration-1, calibration-2, calibration-3\)$/m);
  assert.deepEqual(r.proposals, []);
  assert.ok(!/PROPOSAL/.test(r.text), r.text);
  assert.match(r.text, /^no proposals$/m);
  // the outcome loop is untouched next to them: two failed fixes still propose the demotion
  const both = calibrationTrace([oneRun()]);
  failedFix(both, 'f-1');
  failedFix(both, 'f-2');
  const r2 = rate({ traceDir: both, policyPath: POLICY_PATH, now: NOW });
  assert.deepEqual(r2.proposals.map((p) => `${p.kind} ${p.profile} ${p.category}`), ['demote cc-opus-high fix']);
  assert.match(r2.text, /^CALIBRATION cc-opus-high fix: 0 pass, 0 partial, 1 fail \(calibration-1\)$/m);
  // an unreadable observations file refuses the run, as an unreadable decision file does
  const bad = cli(['rate', '--trace', calibrationTrace(['{ not json']), '--now', NOW, '--policy', HP2_OFF_PATH]);
  assert.equal(bad.code, 4, bad.stdout);
  assert.match(bad.stderr, /calibration-1\/observations\.json is unparseable/);
  // parseable, but an observation that is not a plain object (null, a string, an array) is refused too, not a crash (P2-1)
  for (const obs of ['{"haiku-low": null}', '{"haiku-low": "PASS"}', '{"haiku-low": []}']) {
    const t = calibrationTrace([obs]);
    const nul = cli(['rate', '--trace', t, '--now', NOW, '--policy', HP2_OFF_PATH]);
    assert.equal(nul.code, 4, `${obs}: ${nul.stderr}`);
    assert.match(nul.stderr, /calibration-1\/observations\.json: observation "haiku-low" is not an object/, obs);
    assert.ok(!/TypeError| {4}at /.test(nul.stderr), nul.stderr);
    assert.equal(existsSync(join(t, 'qualification-stats.json')), false, obs);
  }
  // an observations.json that cannot be read (here a directory) is exit 4, not an EISDIR stack trace (P2-1)
  const td = tmp();
  mkdirSync(join(td, 'calibration-1', 'observations.json'), { recursive: true });
  const dir = cli(['rate', '--trace', td, '--now', NOW, '--policy', HP2_OFF_PATH]);
  assert.equal(dir.code, 4, dir.stderr);
  assert.match(dir.stderr, /calibration-1\/observations\.json is unreadable/);
  assert.ok(!/ {4}at /.test(dir.stderr), dir.stderr);
  assert.equal(existsSync(join(td, 'qualification-stats.json')), false);
});

// ---------------------------------------------------------------------------------------------
// host-policy-3 (unit sr-policy-3): calibration-2 under the lead's qualification rules, the four new profiles, the
// PARTIAL grade word (briefs/policy3-builder.md); the host-policy-2 assertions stay on the host-policy-2 fixture
// ---------------------------------------------------------------------------------------------
const CAL2 = JSON.parse(readFileSync(join(HERE, 'trace', 'calibration-2', 'observations.json'), 'utf8'));
const RUN_IDS = { 1: 'wf_052c5f34-973 (calibration-1): ', 2: 'wf_fe91e1d6-d78 (calibration-2): ' };
// an observation's profile: the model of any of its own tasks (never the grader's), at the effort its name ends in
const calProfileAny = (policy, o) => {
  const model = ['pin', 'fix', 'review'].map((t) => o.usage?.[t]?.model).find((m) => typeof m === 'string');
  return policy.profiles.find((x) => x.model === model && x.effort === o.profile.split('-').pop()) ?? null;
};
// the grade entries a run gives an observation: run 1 grades every task with a boolean score; run 2 grades pin and
// fix with a boolean score and review with the three-valued review-grade.result; a task the run did not set is absent
function gradeEntries(run, o) {
  const word = (b) => (b ? 'PASS' : 'FAIL');
  const out = [];
  if (o.pin) out.push(`calibration-${run}: pin-tests ${word(o.pin.score)} (n=1)`);
  if (o.fix) out.push(`calibration-${run}: fix ${word(o.fix.score)} (n=1)`);
  const g = o['review-grade'];
  if (g) out.push(`calibration-${run}: review ${typeof g.result === 'string' ? g.result : word(g.score)} (n=1)`);
  return out;
}
// the lead's applied table (briefs/policy3-builder.md): categories added to the host-policy-2 qualified-for (or the
// whole list of a new profile), and headroom-tested
const HP3_TABLE = {
  'cc-haiku-low': { add: ['fix'], headroom: 175000 },
  'cc-haiku-medium': { add: ['fix'], headroom: 183000 },
  'cc-haiku-high': { add: ['fix'], headroom: 261000 },
  'cc-sonnet-low': { add: ['fix'], headroom: 114000 },
  'cc-sonnet-medium': { add: ['fix'], headroom: 128000 },
  'cc-sonnet-high': { add: ['fix'], headroom: 183000 },
  'cc-opus-medium': { add: ['fix'], headroom: 154000 },
  'cc-opus-high': { add: [], headroom: 848000 },   // rate's proposal on the accepted sr-policy-3 outcome (847844 tokens), ratified
  'cc-opus-xhigh': { new: ['review', 'fix', 'pin-tests'], headroom: 246000 },
  'cc-fable-medium': { add: ['review', 'fix'], headroom: 172000 },
  'cc-fable-high': { add: [], headroom: 352000 },
  'cc-fable-xhigh': { add: [], headroom: 460000 },
  'cc-sonnet-xhigh': { new: [], headroom: 328000 },
  'cc-opus-max': { new: [], headroom: 307000 },
  'cc-fable-max': { new: [], headroom: 230000 }
};
const HP3_REVIEWER = 'host-declared (lead) from calibration-1 and calibration-2 grades';
const reqFor = (policy, category, over = {}) => ({ ...req(over), category, acceptanceChecks: policy.categories[category].verification.map((name) => ({ command: `run ${name}`, expect: 'pass' })) });

test('fixture: trace/policies/host-policy-2.json is the pre-revision policy, byte-identical to the policy the sr-policy-3 decisions were bound to', () => {
  assert.ok(existsSync(HP2_POLICY_PATH), 'the host-policy-2 fixture exists');
  const bound = JSON.parse(readFileSync(join(goldenDir, 'sr-policy-3-3.json'), 'utf8')).bindings;
  assert.equal(bound['policy-revision'], 'host-policy-2');
  assert.equal(createHash('sha256').update(readFileSync(HP2_POLICY_PATH)).digest('hex'), bound['policy-sha256']);
  assert.equal(loadPolicy(HP2_POLICY_PATH)['policy-revision'], 'host-policy-2');
  assert.equal(loadPolicy(COMMITTED_POLICY_PATH)['policy-revision'], 'host-policy-3');
});

test('host-policy-2 fixture routing (--policy): pin-tests -> cc-haiku-low, review -> cc-opus-high, fix -> cc-opus-high', () => {
  const hp2 = loadPolicy(HP2_OFF_PATH);
  for (const [category, want] of [['pin-tests', 'cc-haiku-low'], ['review', 'cc-opus-high'], ['fix', 'cc-opus-high']]) {
    const decided = cliDecide(reqFor(hp2, category, { taskId: `hp2-${category}` }), HP2_OFF_PATH);
    assert.equal(decided.bindings['policy-revision'], 'host-policy-2', category);
    assert.equal(decided.decision.route, 'delegate', category);
    assert.equal(decided.decision.profile, want, category);
  }
});

test('host-policy-3: the lead\'s table applied - qualified-for, headroom-tested, both runs\' grade entries and run ids, the four new profiles', () => {
  const live = loadPolicy(COMMITTED_POLICY_PATH);
  const hp2 = loadPolicy(HP2_POLICY_PATH);
  assert.equal(live['policy-revision'], 'host-policy-3');
  assert.deepEqual(live.profiles.map((p) => p.id).sort(), Object.keys(HP3_TABLE).sort(), 'fifteen profiles: the eleven of host-policy-2 and four new');
  assert.deepEqual(live.categories, hp2.categories, 'no category changes');
  assert.deepEqual(live.economics, hp2.economics);
  for (const [id, want] of Object.entries(HP3_TABLE)) {
    const pr = live.profiles.find((p) => p.id === id);
    const before = hp2.profiles.find((p) => p.id === id);
    assert.equal(Boolean(before), !want.new, `${id}: new in host-policy-3 exactly when the table says so`);
    const expected = want.new ?? [...before['qualified-for'], ...want.add];
    assert.deepEqual([...pr['qualified-for']].sort(), [...expected].sort(), `${id} qualified-for`);
    assert.equal(pr['headroom-tested'], want.headroom, `${id} headroom-tested`);
    assert.equal(pr.expires, '2027-01-15', id);
    if (want.new || want.add.length) {
      assert.deepEqual([pr['qualified-at'], pr.reviewer], ['2026-10-18', HP3_REVIEWER], `${id}: added or changed in host-policy-3`);
    } else {
      assert.deepEqual([pr['qualified-at'], pr.reviewer], [before['qualified-at'], before.reviewer], `${id}: unchanged, gains the entries`);
    }
    if (want.new) {
      // a new profile copies its siblings' shape (the same model in host-policy-2, the lead's role excluded)
      const sib = hp2.profiles.find((p) => p.model === pr.model && !p.role);
      for (const k of ['config', 'tools', 'vision', 'context-tested']) assert.deepEqual(pr[k], sib[k], `${id} ${k}`);
      assert.equal(pr.role, undefined, id);
    } else {
      for (const e of before.evidence) assert.ok(pr.evidence.includes(e), `${id} keeps "${e}"`);
    }
  }
  // the grade entries are exactly the two runs' grades (fails and partials included), each with its run id; headroom is
  // the largest completed run rounded up to the next thousand, never lowered
  const accepted = acceptedTokens();
  const seen = new Set();
  for (const [run, obs] of [[1, CAL1], [2, CAL2]]) {
    for (const o of Object.values(obs)) {
      const pr = calProfileAny(live, o);
      assert.ok(pr, `${o.profile} (calibration-${run}) has a policy profile`);
      seen.add(pr.id);
      for (const e of gradeEntries(run, o)) assert.ok(pr.evidence.includes(e), `${pr.id} lacks "${e}"`);
      assert.ok(pr.evidence.some((e) => e.startsWith(RUN_IDS[run])), `${pr.id} lacks the calibration-${run} run id`);
    }
  }
  for (const id of seen) {
    const pr = live.profiles.find((p) => p.id === id);
    const want = [CAL1, CAL2].flatMap((obs, i) => Object.values(obs).filter((o) => calProfileAny(live, o)?.id === id).flatMap((o) => gradeEntries(i + 1, o)));
    assert.deepEqual(pr.evidence.filter((e) => e.startsWith('calibration-')).sort(), want.sort(), `${id}: no grade entry beyond the runs'`);
    const runs = [CAL1, CAL2].flatMap((obs) => Object.values(obs).filter((o) => calProfileAny(live, o)?.id === id))
      .flatMap((o) => ['pin', 'fix', 'review'].map((t) => o.usage?.[t]).filter((u) => u && u.state === 'done').map((u) => u.tokens));
    const before = hp2.profiles.find((p) => p.id === id)?.['headroom-tested'] ?? 0;
    assert.equal(pr['headroom-tested'], Math.max(before, Math.ceil(Math.max(...runs, accepted[id] ?? 0) / 1000) * 1000), `${id} headroom rule`);
  }
  assert.equal(seen.size, 15, 'every calibrated profile is in the policy');
  assert.ok(live.profiles.find((p) => p.id === 'cc-sonnet-low').evidence.includes('calibration-2: review PARTIAL (n=1)'));
});

test('host-policy-3 validation: PARTIAL is a grade word; any other word is refused (exit 2)', () => {
  const ok = livePolicyWith((p) => { p.profiles.find((x) => x.id === 'cc-haiku-low').evidence.push('calibration-3: review PARTIAL (n=2)'); });
  assert.ok(loadPolicy(ok).profiles.find((x) => x.id === 'cc-haiku-low').evidence.includes('calibration-3: review PARTIAL (n=2)'));
  for (const word of ['partial', 'PARTIALLY', 'UNGRADED', 'PASS/PARTIAL']) {
    const entry = `calibration-2: review ${word} (n=1)`;
    const path = livePolicyWith((p) => { p.profiles.find((x) => x.id === 'cc-sonnet-low').evidence.push(entry); });
    const message = new RegExp(`profile cc-sonnet-low evidence '${entry.replace(/[()/]/g, '\\$&')}' is not 'calibration-<n>: <category> PASS\\|PARTIAL\\|FAIL \\(n=<k>\\)'`);
    assert.throws(() => loadPolicy(path), (e) => e instanceof RouterError && e.code === 2 && message.test(e.message), entry);
    const r = cli(['rate', '--trace', tmp(), '--policy', path]);
    assert.equal(r.code, 2, r.stdout);
    assert.match(r.stderr, message);
  }
});

test('host-policy-3 routing: pin-tests -> cc-haiku-low; review -> cc-opus-high (cc-opus-xhigh ties, loses on effort); fix -> cc-haiku-high (the economics); the review-only profiles alone are blocked', () => {
  const live = loadPolicy(LIVE_OFF_PATH);
  const pin = computeDecision(reqFor(live, 'pin-tests'), live, []);
  assert.deepEqual([pin.route, pin.profile, pin['all-in-bound-usd']], ['delegate', 'cc-haiku-low', 1.06]);
  const review = computeDecision(reqFor(live, 'review'), live, []);
  assert.deepEqual([review.route, review.profile, review['all-in-bound-usd']], ['delegate', 'cc-opus-high', 5.18]);
  assert.deepEqual(review['eligible-ordered'], ['cc-opus-high', 'cc-opus-xhigh', 'cc-fable-high']);
  assert.equal(review.candidates['cc-opus-xhigh']['all-in-bound-usd'], 5.18, 'the same bound: the lower effort ranks first');
  assert.equal(review.candidates['cc-fable-medium'].reason, 'context: 209000 tokens not below headroom-tested 172000 on cc-fable-medium');
  // a default fix (the category median, 193000 tokens) fits only the fix-qualified profiles whose headroom admits it;
  // the cheapest of them carries the bound: 193000 x 0.5 / 1e6 + the review at cc-opus-high + the brief overhead
  const fix = computeDecision(reqFor(live, 'fix'), live, []);
  assert.deepEqual([fix.route, fix.profile, fix['review-profile']], ['delegate', 'cc-haiku-high', 'cc-opus-high']);
  const c = fix.candidates['cc-haiku-high'];
  assert.deepEqual([c['work-bound-usd'], c['review-bound-usd'], c['overhead-bound-usd'], c['all-in-bound-usd']], [0.0965, 4.18, 1, 5.2765]);
  assert.deepEqual(fix['eligible-ordered'], ['cc-haiku-high', 'cc-opus-high', 'cc-opus-xhigh', 'cc-fable-high']);
  for (const [id, h] of [['cc-haiku-low', 175000], ['cc-haiku-medium', 183000], ['cc-sonnet-low', 114000], ['cc-sonnet-medium', 128000], ['cc-sonnet-high', 183000], ['cc-opus-medium', 154000], ['cc-fable-medium', 172000]]) {
    assert.equal(fix.candidates[id].reason, `context: 193000 tokens not below headroom-tested ${h} on ${id}`, id);
  }
  for (const id of ['cc-sonnet-xhigh', 'cc-opus-max', 'cc-fable-max']) assert.equal(fix.candidates[id].reason, `${id} not qualified for fix`, id);
  // one review pass is not a qualification: the three review-only profiles alone route blocked at Gate 2
  const trio = computeDecision(reqFor(live, 'review', { candidates: ['cc-sonnet-xhigh', 'cc-opus-max', 'cc-fable-max'] }), live, []);
  assert.equal(trio.route, 'blocked');
  for (const id of ['cc-sonnet-xhigh', 'cc-opus-max', 'cc-fable-max']) {
    assert.equal(trio.candidates[id]['first-failing-gate'], 2, id);
    assert.match(trio.candidates[id].reason, new RegExp(`^${id} not qualified for review`), id);
  }
  // the CLI on the live policy agrees (feature-off derivative, as the other live-policy decisions)
  const decided = cliDecide(reqFor(live, 'fix', { taskId: 'hp3-fix' }), LIVE_OFF_PATH);
  assert.equal(decided.bindings['policy-revision'], 'host-policy-3');
  assert.equal(decided.decision.profile, 'cc-haiku-high');
});

// P3-R2: the README's 'routing consequence' names what decide does above cc-haiku-high's headroom, and no tie that never
// decides: at 261000 tokens cc-opus-xhigh (246k) fails Gate 2 too, so cc-opus-high is the only opus left
test('README: a fix at cc-haiku-high\'s headroom or above routes to cc-opus-high, and the routing-consequence sentence says so without a cc-opus-xhigh tie', () => {
  const live = loadPolicy(LIVE_OFF_PATH);
  const haiku = live.profiles.find((p) => p.id === 'cc-haiku-high')['headroom-tested'];
  const xhigh = live.profiles.find((p) => p.id === 'cc-opus-xhigh')['headroom-tested'];
  const big = computeDecision(reqFor(live, 'fix', { estimatedTokens: haiku }), live, []);
  assert.deepEqual([big.route, big.profile], ['delegate', 'cc-opus-high']);
  assert.equal(big.candidates['cc-opus-xhigh'].reason, `context: ${haiku} tokens not below headroom-tested ${xhigh} on cc-opus-xhigh`);
  assert.equal(big.candidates['cc-haiku-high'].reason, `context: ${haiku} tokens not below headroom-tested ${haiku} on cc-haiku-high`);
  const bound = big.candidates['cc-opus-high']['all-in-bound-usd'].toFixed(2);
  const readme = readFileSync(join(HERE, 'README.md'), 'utf8').replace(/\s+/g, ' ');
  const sentence = `A fix estimated at ${haiku} tokens or more no longer fits \`cc-haiku-high\` (or \`cc-opus-xhigh\`, ${xhigh / 1000}k) and goes to \`cc-opus-high\` ($${bound} at ${haiku}).`;
  assert.ok(readme.includes(sentence), `README lacks: ${sentence}`);
  assert.ok(!/cc-opus-xhigh` ties on the bound and loses on effort up to/.test(readme), 'the tie that never decides a fix route is gone');
});

// rate reads both calibration formats: run 1 grades review with the boolean review-grade.score, run 2 with the
// three-valued review-grade.result (PASS | PARTIAL | FAIL); a task an observation does not carry (run 2's review-only
// profiles have pin and fix null) was not run and is not counted
test('rate: CALIBRATION lines read both observation formats - run 1\'s boolean review score, run 2\'s PASS/PARTIAL/FAIL result - and count pass, partial, fail across runs', () => {
  const live = loadPolicy(LIVE_OFF_PATH);
  const trace = calibrationTrace([CAL1, CAL2]);
  const r = rate({ traceDir: trace, policyPath: LIVE_OFF_PATH, now: NOW });
  const lines = r.text.split('\n').filter((l) => l.startsWith('CALIBRATION '));
  // every count is the observation files' own grades, across both runs
  const want = {};
  for (const [run, obs] of [[1, CAL1], [2, CAL2]]) {
    for (const o of Object.values(obs)) {
      const id = calProfileAny(live, o).id;
      for (const e of gradeEntries(run, o)) {
        const [, cat, word] = /^calibration-\d+: (\S+) (\S+) /.exec(e);
        const c = ((want[id] ??= {})[cat] ??= { pass: 0, partial: 0, fail: 0, runs: [] });
        c[word.toLowerCase()] += 1;
        c.runs.push(`calibration-${run}`);
      }
    }
  }
  const expected = Object.keys(want).sort().flatMap((id) => ['pin-tests', 'fix', 'review'].filter((cat) => want[id][cat])
    .map((cat) => { const c = want[id][cat]; return `CALIBRATION ${id} ${cat}: ${c.pass} pass, ${c.partial} partial, ${c.fail} fail (${c.runs.join(', ')})`; }));
  assert.deepEqual(lines, expected, r.text);
  // the cells the lead's table turns on, spelled out
  for (const line of [
    'CALIBRATION cc-sonnet-low review: 1 pass, 1 partial, 0 fail (calibration-1, calibration-2)',
    'CALIBRATION cc-sonnet-medium review: 1 pass, 0 partial, 1 fail (calibration-1, calibration-2)',
    'CALIBRATION cc-sonnet-high review: 1 pass, 0 partial, 1 fail (calibration-1, calibration-2)',
    'CALIBRATION cc-opus-medium review: 1 pass, 0 partial, 1 fail (calibration-1, calibration-2)',
    'CALIBRATION cc-haiku-low fix: 2 pass, 0 partial, 0 fail (calibration-1, calibration-2)',
    'CALIBRATION cc-opus-xhigh pin-tests: 2 pass, 0 partial, 0 fail (calibration-1, calibration-2)',
    'CALIBRATION cc-sonnet-xhigh review: 1 pass, 0 partial, 0 fail (calibration-2)',
    'CALIBRATION cc-opus-max review: 1 pass, 0 partial, 0 fail (calibration-2)',
    'CALIBRATION cc-fable-max review: 1 pass, 0 partial, 0 fail (calibration-2)'
  ]) assert.ok(lines.includes(line), `missing: ${line}`);
  // a review-only profile has no pin or fix line: those cells were not run, not ungraded
  for (const id of ['cc-sonnet-xhigh', 'cc-opus-max', 'cc-fable-max']) {
    assert.ok(!lines.some((l) => l.startsWith(`CALIBRATION ${id} pin-tests`) || l.startsWith(`CALIBRATION ${id} fix`)), id);
  }
  assert.ok(!lines.some((l) => /no policy profile|ungraded/.test(l)), r.text);
  const doc = JSON.parse(readFileSync(join(trace, 'qualification-stats.json'), 'utf8'));
  assert.deepEqual(doc.calibration.profiles['cc-sonnet-low'].review, { fail: 0, partial: 1, pass: 1, ungraded: 0 });
  assert.deepEqual(Object.keys(doc.calibration.profiles['cc-opus-max']), ['review']);
  assert.deepEqual(doc.calibration.runs.map((x) => x.run), ['calibration-1', 'calibration-2']);
  // calibration never proposes, partial or not
  assert.deepEqual(r.proposals, []);
  // a run-2 review result outside PASS/PARTIAL/FAIL is ungraded, never a pass; result wins over a stray boolean score
  const odd = structuredClone(CAL2['sonnet-low']);
  odd['review-grade'].result = 'pass';
  const both = structuredClone(CAL2['sonnet-medium']);
  both['review-grade'].score = true;
  const t2 = calibrationTrace([{ 'sonnet-low': odd, 'sonnet-medium': both }]);
  const r2 = rate({ traceDir: t2, policyPath: LIVE_OFF_PATH, now: NOW });
  assert.match(r2.text, /^CALIBRATION cc-sonnet-low review: 0 pass, 0 partial, 0 fail, 1 ungraded \(calibration-1\)$/m);
  assert.match(r2.text, /^CALIBRATION cc-sonnet-medium review: 0 pass, 0 partial, 1 fail \(calibration-1\)$/m);
});

// P3-R1: a profile is matched by its own tasks' usage, never the grader's. A review-only run-2 observation whose own
// usage carries no model must not borrow usage.grade's (opus) model: its grades would land on an opus profile's line.
test('rate: a calibration observation whose own usage has no model is never matched through the grader\'s usage (labelled no policy profile, not counted under the grader\'s profile)', () => {
  const obs = structuredClone(CAL2['sonnet-xhigh']);
  delete obs.usage.review.model;
  assert.ok(typeof obs.usage.grade.model === 'string' && obs.usage.grade.model.startsWith('claude-opus'), 'the grader is an opus model');
  const grader = loadPolicy(LIVE_OFF_PATH).profiles.find((p) => p.model === obs.usage.grade.model && p.effort === 'xhigh');
  assert.ok(grader, 'the grader\'s model at the observation\'s effort names a policy profile: the case the guard exists for');
  const trace = calibrationTrace([{}, { 'sonnet-xhigh': obs }]);
  const r = rate({ traceDir: trace, policyPath: LIVE_OFF_PATH, now: NOW });
  const lines = r.text.split('\n').filter((l) => l.startsWith('CALIBRATION '));
  assert.deepEqual(lines, ['CALIBRATION sonnet-xhigh (no policy profile) review: 1 pass, 0 partial, 0 fail (calibration-2)'], r.text);
  assert.ok(!lines.some((l) => l.startsWith(`CALIBRATION ${grader.id} `)), r.text);
  const doc = JSON.parse(readFileSync(join(trace, 'qualification-stats.json'), 'utf8'));
  assert.deepEqual(Object.keys(doc.calibration.profiles), ['sonnet-xhigh (no policy profile)']);
});

// deliverable F: an accepted outcome that completed more tokens than the profile's headroom-tested proposes the raise
// (headroom-tested is the largest completed run, rounded up to the next thousand, never lowered); proposed, never applied
const HEADROOM_SUFFIX = 'not applied — the lead ratifies by editing host-policy.json';
test('rate: an accepted outcome above headroom-tested proposes the raise (the stale cc-opus-high headroom behind sr-policy-3 seq 1); unknown or lower tokens propose nothing', () => {
  // the committed trace under the policy the sr-policy-2 unit ran on (host-policy-1, cc-opus-high 514000): the
  // accepted sr-policy-2 outcome completed 770527 tokens, and the raise the lead applied by hand in 490b7ed is proposed
  const real = frozenTrace(FREEZE_HP2);   // the sr-policy-3 outcome (847844 tokens, after the freeze) is left out
  const policyBefore = readFileSync(FIXTURE_POLICY_PATH, 'utf8');
  const r1 = cli(['rate', '--trace', real, '--now', '2026-10-18T02:00:00Z', '--policy', FIXTURE_POLICY_PATH]);
  assert.equal(r1.code, 0, r1.stderr);
  const headroomLines = (text) => text.split('\n').filter((l) => /^PROPOSAL profiles\./.test(l));
  assert.deepEqual(headroomLines(r1.stdout), [`PROPOSAL profiles.cc-opus-high.headroom-tested: 514000 -> 771000 (accepted outcome sr-policy-2 completed 770527 tokens); ${HEADROOM_SUFFIX}`]);
  assert.equal(readFileSync(FIXTURE_POLICY_PATH, 'utf8'), policyBefore, 'proposed, never applied');
  const doc = JSON.parse(readFileSync(join(real, 'qualification-stats.json'), 'utf8'));
  assert.deepEqual(doc['headroom-proposals'], [{ profile: 'cc-opus-high', from: 514000, to: 771000, tokens: 770527, task: 'sr-policy-2' }]);
  // once raised (host-policy-2 after 490b7ed, and host-policy-3), the same ledger proposes nothing
  for (const policy of [HP2_OFF_PATH, LIVE_OFF_PATH]) {
    const r = cli(['rate', '--trace', real, '--now', '2026-10-18T02:00:00Z', '--policy', policy]);
    assert.equal(r.code, 0, r.stderr);
    assert.deepEqual(headroomLines(r.stdout), [], policy);
  }

  // synthetic outcomes on the base fixture (cc-opus-high headroom-tested 514000)
  const trace = tmp();
  const cycleWith = (taskId, value, tokens) => {
    const d = run(req({ taskId }), { traceDir: trace });
    dispatch(taskId, 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW });
    return recordOutcome(withTokens({ 'task-id': taskId, outcome: value, 'original-brief-fingerprint': d.briefFingerprint }, tokens), { traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  };
  const rateHere = () => rate({ traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  cycleWith('h-unknown', 'accepted', null);       // tokens unknown
  cycleWith('h-absent', 'accepted', undefined);   // tokens absent
  cycleWith('h-below', 'accepted', 300000);
  cycleWith('h-equal', 'accepted', 514000);       // completed exactly the headroom: nothing to raise
  cycleWith('h-failed', 'verification-failed', 900000); // not accepted: not a completed run
  assert.deepEqual(rateHere().headroomProposals, []);
  assert.ok(!/PROPOSAL profiles\./.test(rateHere().text));
  cycleWith('h-above', 'accepted', 600001);
  cycleWith('h-most', 'accepted', 700500);
  const r = rateHere();
  // one proposal per profile, from its largest accepted run, rounded up to the next thousand
  assert.deepEqual(r.headroomProposals, [{ profile: 'cc-opus-high', from: 514000, to: 701000, tokens: 700500, task: 'h-most' }]);
  assert.match(r.text, new RegExp(`^PROPOSAL profiles\\.cc-opus-high\\.headroom-tested: 514000 -> 701000 \\(accepted outcome h-most completed 700500 tokens\\); ${HEADROOM_SUFFIX}$`, 'm'));
  assert.ok(!/^no proposals$/m.test(r.text));
  // a superseded outcome does not count: h-most's dispatch is re-recorded verification-failed, so h-above carries it
  const most = readLedger(trace).filter((x) => x['task-id'] === 'h-most' && x.kind === 'outcome').pop();
  recordOutcome(withTokens({ 'task-id': 'h-most', outcome: 'verification-failed', 'original-brief-fingerprint': most['brief-fingerprint'] }, 700500), { traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  assert.deepEqual(rateHere().headroomProposals, [{ profile: 'cc-opus-high', from: 514000, to: 601000, tokens: 600001, task: 'h-above' }]);
  // decide is not changed by a headroom proposal: it routes by the policy as it stands
  assert.deepEqual(run(req({ taskId: 'h-next' }), { traceDir: trace }).decision['pending-proposals'], []);
});

// the usage-window coefficients ratified from calibration run 2's measurement (host-policy-3); the gate's arithmetic
// is unchanged, only the declared numbers and their basis
const RUN2_TOKENS = 7872276; // trace/calibration-2/results-table.md 'Totals': the workflow's reported sub-agent tokens
test('usage windows (host-policy-3): the coefficients ratified from run 2 (0.05, 0.015) are above the measured values, the lead reserve raised (0.25, 0.10), ratified-at the second reading, the basis names the measurement', () => {
  const uw = COMMITTED_POLICY['usage-windows'];
  const readings = readFileSync(join(HERE, 'trace', 'usage.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l));
  const at = (ts) => readings.find((r) => r.ts === ts);
  const [from, to] = [at('2026-10-17T23:22:51Z'), at('2026-10-18T01:23:32Z')];
  assert.ok(from && to, 'both readings of the measurement are in trace/usage.jsonl');
  const want = { five_hour: [0.05, 0.25, 18000], seven_day: [0.015, 0.1, 604800] };
  for (const [w, [coefficient, reserve, length]] of Object.entries(want)) {
    const x = uw.windows[w];
    assert.deepEqual([x['utilization-per-mtok'], x['lead-reserve'], x['ratified-at'], x['stop-at'], x['length-seconds']], [coefficient, reserve, '2026-10-18T01:23:32Z', 0.9, length], w);
    // the measured coefficient over the run, and the declared one above it (the conservative direction), within 1.6x
    const measured = (to.windows[w].utilization - from.windows[w].utilization) / (RUN2_TOKENS / 1e6);
    assert.ok(coefficient > measured && coefficient < measured * 1.6, `${w}: declared ${coefficient}, measured ${measured}`);
  }
  assert.equal(Math.round(((to.windows.five_hour.utilization - from.windows.five_hour.utilization) / (RUN2_TOKENS / 1e6)) * 1e4) / 1e4, 0.0343);
  assert.equal(Math.round(((to.windows.seven_day.utilization - from.windows.seven_day.utilization) / (RUN2_TOKENS / 1e6)) * 1e4) / 1e4, 0.0102);
  for (const part of ['wf_fe91e1d6-d78', '2026-10-17T23:22:51Z', '2026-10-18T01:23:32Z', '7872276', '2026-10-17T23:07:08Z', 'not dispatched through the adapter']) {
    assert.ok(uw['coefficient-basis'].includes(part), `coefficient-basis names ${part}`);
  }
  // the gate's arithmetic: the limit is stop-at - lead-reserve, as before
  const d = computeDecision(req({ category: 'build-core' }), loadPolicy(COMMITTED_POLICY_PATH), [], {}, { readings: [{ ts: NOW, windows: { five_hour: { utilization: 0.6, 'resets-at': isoAt(NOW_MS + 4 * HOUR) }, seven_day: { utilization: 0.05, 'resets-at': isoAt(NOW_MS + 144 * HOUR) } } }] });
  assert.equal(d.route, 'delegate');
  assert.equal(d.usage.windows.five_hour.projected, 0.6273); // 0.6 + 0.545 x 0.05
  assert.equal(d.usage.windows.five_hour['headroom-mtok'], 1); // (0.9 - 0.25 - 0.6) / 0.05
  assert.match(d.candidates['cc-opus-high'].walkthrough[3].note, /usage window five_hour binds: projected 0\.6273 <= 0\.65$/);
  assert.ok(d.uncertainty.includes(`usage windows: coefficients host-declared (${uw['coefficient-basis']})`));
  // rate on the committed readings: the ratification is after every observation, so nothing is considered or proposed
  const real = tmp();
  cpSync(join(HERE, 'trace'), real, { recursive: true });
  const r = rate({ traceDir: real, policyPath: COMMITTED_POLICY_PATH, now: '2026-10-18T02:00:00Z' });
  for (const w of ['five_hour', 'seven_day']) {
    assert.equal(r.stats.usage[w]['ratified-at'], '2026-10-18T01:23:32Z', w);
    assert.equal(r.stats.usage[w].considered, 0, w);
  }
  assert.deepEqual(r.usageProposals, []);
});

test('usage (host-policy-3): with no file it prints the headroom from the ratified coefficients and reserve, on a synthetic reading and on the committed readings', () => {
  const trace = tmp();
  usageCli(trace, rateLimitInfo(NOW, { five: 0.6 }), NOW, COMMITTED_POLICY_PATH);
  const s = cli(['usage', '--trace', trace, '--now', isoAt(NOW_MS + 12 * MIN), '--policy', COMMITTED_POLICY_PATH]);
  assert.equal(s.code, 0, s.stderr);
  assert.match(s.stdout, /^ {2}five_hour: utilization 0\.6, resets 2026-10-17T23:00:00Z, headroom 1 Mtok \(\(0\.9 - 0\.25 - 0\.6\) \/ 0\.05\)$/m);
  assert.match(s.stdout, /^ {2}seven_day: utilization 0\.05, resets 2026-10-23T19:00:00Z, headroom 50 Mtok \(\(0\.9 - 0\.1 - 0\.05\) \/ 0\.015\)$/m);
  // the committed readings (copied), pinned to two instants no later record can change: readings are monotonic and the
  // trace already holds later ones, so the latest at or before 01:35:00 is 01:30:06 for good, with nothing dispatched after
  // it yet (the sr-policy-3 dispatch is at 01:38:00); at 01:38:30 the latest is 01:37:37 and that dispatch (829000
  // usage-tokens) is after it (the lead's P3-L1: the builder's --now 01:45 picked up every later reading).
  const real = tmp();
  cpSync(join(HERE, 'trace'), real, { recursive: true });
  const live = cli(['usage', '--trace', real, '--now', '2026-10-18T01:35:00Z', '--policy', COMMITTED_POLICY_PATH]);
  assert.equal(live.code, 0, live.stderr);
  assert.equal(live.stdout, [
    'latest usage reading 2026-10-18T01:30:06Z (age 4.9 min, max 30)',
    '  five_hour: utilization 0.42, resets 2026-10-18T04:00:00Z, headroom 4.6 Mtok ((0.9 - 0.25 - 0.42) / 0.05)',
    '  seven_day: utilization 0.36, resets 2026-10-24T18:00:00Z, headroom 29.3333 Mtok ((0.9 - 0.1 - 0.36) / 0.015)',
    ''
  ].join('\n'));
  const dispatched = cli(['usage', '--trace', real, '--now', '2026-10-18T01:38:30Z', '--policy', COMMITTED_POLICY_PATH]);
  assert.equal(dispatched.code, 0, dispatched.stderr);
  assert.equal(dispatched.stdout, [
    'latest usage reading 2026-10-18T01:37:37Z (age 0.88 min, max 30)',
    '  dispatched and not in the reading: 829000 tokens (829000 since the reading, 0 in flight from before it)',
    '  five_hour: utilization 0.47, resets 2026-10-18T04:00:00Z, headroom 2.771 Mtok ((0.9 - 0.25 - 0.47) / 0.05 - 0.829 dispatched and not in the reading)',
    '  seven_day: utilization 0.38, resets 2026-10-24T18:00:00Z, headroom 27.171 Mtok ((0.9 - 0.1 - 0.38) / 0.015 - 0.829 dispatched and not in the reading)',
    ''
  ].join('\n'));
});
