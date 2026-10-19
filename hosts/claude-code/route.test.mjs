// Tests for the SmartRouter host adapter (route.mjs). Each test is named after the SmartRouter
// fixture it mirrors (tests/smart_router_decisions.py and references/gates.md at fbe7bca).
// Node built-ins only: node --test docs/orchestration/smartrouter/route.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, readdirSync, existsSync, appendFileSync, cpSync, rmSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  ADVISORY, CASH_UNCERTAINTY, RouterError, TIERS, TIERS_OFF, briefFingerprint, computeDecision, decide, dispatch,
  loadPolicy, rate, readLedger, recordOutcome, requestTier, status, validateBrief
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
// host-policy-3, frozen by unit sr-policy-4 (never edited): the host-policy-3 assertions (its table, validation and
// routing, the README routing consequence, its usage tests) run on it, so revision 4 of the live policy never moves
// them. The live policy has its own tests (host-policy-4)
const HP3_POLICY_PATH = join(HERE, 'trace', 'policies', 'host-policy-3.json');
// host-policy-4, frozen by unit sr-policy-5 (never edited): the host-policy-4 assertions (its table, its routing, the
// README routing consequence of run 3, its rate tests) run on it, so revision 5 of the live policy never moves them.
// The live policy has its own tests (host-policy-5)
const HP4_POLICY_PATH = join(HERE, 'trace', 'policies', 'host-policy-4.json');
// host-policy-5, frozen by unit sr-policy-6 (never edited): the host-policy-5 assertions (its table, its routing, the
// README tiers section's routing consequence, its rate and dispatch tests) run on it, so revision 6 of the live policy
// never moves them. The live policy has its own tests (host-policy-6)
const HP5_POLICY_PATH = join(HERE, 'trace', 'policies', 'host-policy-5.json');
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
  // the record carries the Item 4 marker beside its null cash (estimate-only host)
  assert.deepEqual(out.counters, { 'calls-used': 1, 'calls-limit': 6, 'cash-spent': null, 'cash-cap': null, 'repairs-used': 0, 'repairs-allowed': 1, 'cash-basis': 'estimate-only' });
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

// pinned to the host-policy-3 fixture by sr-policy-4: its last two assertions are the golden's bound and order, whose
// required reviewer is cc-opus-high; under host-policy-4 the reviewer is cc-sonnet-xhigh (the live policy's own test is
// 'host-policy-4 routing: the stored build request')
test('committed policy (ii), host-policy-3 fixture: after a fresh synthetic reading, the stored build request delegates to cc-opus-high with the usage block filled', () => {
  const trace = tmp();
  const at = STORED_BUILD.request.now;
  const r = usageCli(trace, rateLimitInfo(at, { five: 0.2, seven: 0.05, fiveResetMs: 4 * HOUR, sevenResetMs: 144 * HOUR }), at, HP3_POLICY_PATH);
  assert.equal(r.code, 0, r.stderr);
  const d = decideOn(STORED_BUILD.request, trace, HP3_POLICY_PATH);
  assert.equal(d.route, 'delegate');
  assert.equal(d.decision.profile, 'cc-opus-high');
  assert.equal(d.decision.usage['reading-ts'], at);
  const uw = loadPolicy(HP3_POLICY_PATH)['usage-windows'].windows;
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
  // §10.5 counters stay as they are (plus the Item 4 marker every record of this host carries)
  assert.deepEqual(absent.counters, { 'calls-used': 1, 'calls-limit': 6, 'cash-spent': null, 'cash-cap': null, 'repairs-used': 0, 'repairs-allowed': 1, 'cash-basis': 'estimate-only' });
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
// since host-policy-6 the live policy's typed references resolve against the policy file's directory (E1), so its
// derivative is written beside a copy of the committed store (ledger, decisions, outcomes), as an upstream copy would be
const LIVE_OFF_DIR = tmp();
for (const d of ['decisions', 'outcomes']) cpSync(join(HERE, 'trace', d), join(LIVE_OFF_DIR, 'trace', d), { recursive: true });
cpSync(join(HERE, 'trace', 'ledger.jsonl'), join(LIVE_OFF_DIR, 'trace', 'ledger.jsonl'));
const LIVE_OFF_PATH = join(LIVE_OFF_DIR, 'host-policy-live-off.json');
writeFileSync(LIVE_OFF_PATH, featureOff(COMMITTED_POLICY));
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
// the host-policy-3 fixture's feature-off derivative (R1(a)), for the host-policy-3 assertions; written only when the
// fixture exists, so a missing fixture fails the tests that read it (ENOENT), not the whole file at load
const HP3_OFF_PATH = join(tmp(), 'host-policy-3-off.json');
if (existsSync(HP3_POLICY_PATH)) writeFileSync(HP3_OFF_PATH, featureOff(JSON.parse(readFileSync(HP3_POLICY_PATH, 'utf8'))));
const hp3PolicyWith = (mutate) => {
  const p = JSON.parse(readFileSync(HP3_OFF_PATH, 'utf8'));
  mutate(p);
  const path = join(tmp(), 'host-policy.json');
  writeFileSync(path, JSON.stringify(p, null, 2));
  return path;
};
// the host-policy-4 fixture's feature-off derivative (R1(a)), for the host-policy-4 assertions; written only when the
// fixture exists, as HP3_OFF_PATH is
const HP4_OFF_PATH = join(tmp(), 'host-policy-4-off.json');
if (existsSync(HP4_POLICY_PATH)) writeFileSync(HP4_OFF_PATH, featureOff(JSON.parse(readFileSync(HP4_POLICY_PATH, 'utf8'))));
// the host-policy-5 fixture's feature-off derivative (R1(a)), for the host-policy-5 assertions; written only when the
// fixture exists, as HP4_OFF_PATH is
const HP5_OFF_PATH = join(tmp(), 'host-policy-5-off.json');
if (existsSync(HP5_POLICY_PATH)) writeFileSync(HP5_OFF_PATH, featureOff(JSON.parse(readFileSync(HP5_POLICY_PATH, 'utf8'))));
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
// The host-policy-3 fixture was frozen with every record of the sr-policy-4 base commit (the last, that unit's dispatch
// at 09:07:43Z): its headroom figures are the accepted outcomes up to that instant, never a later one
const FREEZE_HP3 = '2026-10-18T09:07:43Z';
// The host-policy-4 fixture was frozen with every record of the sr-policy-5 base commit (the last, that unit's dispatch
// at 18:56:28.087Z)
const FREEZE_HP4 = '2026-10-18T18:56:28.087Z';
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
test('README: the host-policy-4 qualification table matches the host-policy-4 fixture row for row (15 rows), qualified-for in policy order, the three runs\' grades', () => {
  const readme = readFileSync(join(HERE, 'README.md'), 'utf8');
  const hp4 = JSON.parse(readFileSync(HP4_POLICY_PATH, 'utf8'));
  const start = readme.indexOf('### The table (host-policy-4');
  assert.ok(start >= 0, 'the README carries the host-policy-4 table');
  const section = readme.slice(start, readme.indexOf('\n#', start + 1));
  const rows = section.split('\n').filter((l) => /^\| `cc-/.test(l)).map((l) => l.split('|').slice(1, -1).map((c) => c.trim()));
  assert.equal(rows.length, 15);
  assert.deepEqual(rows.map((r) => r[0]), hp4.profiles.map((p) => `\`${p.id}\``), 'one row per profile, in policy order');
  for (const p of hp4.profiles) {
    const [, , qual, headroom, run1, run2, run3] = rows.find((r) => r[0] === `\`${p.id}\``);
    assert.equal(qual, p['qualified-for'].join(', ') || 'none', `${p.id} qualified-for`);
    assert.equal(headroom, `${p['headroom-tested'] / 1000}k`, `${p.id} headroom-tested`);
    const grade = (run, cat) => (p.evidence.find((e) => e.startsWith(`calibration-${run}: ${cat} `)) ?? '').split(' ')[2] ?? '-';
    for (const [run, cell] of [[1, run1], [2, run2], [3, run3]]) {
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
  'cc-haiku-high': { add: ['fix'], headroom: 726000 },
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
  assert.equal(loadPolicy(HP3_POLICY_PATH)['policy-revision'], 'host-policy-3');
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
  const live = loadPolicy(HP3_POLICY_PATH);
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
  // the largest completed run rounded up to the next thousand, never lowered (accepted outcomes up to the fixture's freeze)
  const accepted = acceptedTokens(FREEZE_HP3);
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
  const ok = hp3PolicyWith((p) => { p.profiles.find((x) => x.id === 'cc-haiku-low').evidence.push('calibration-3: review PARTIAL (n=2)'); });
  assert.ok(loadPolicy(ok).profiles.find((x) => x.id === 'cc-haiku-low').evidence.includes('calibration-3: review PARTIAL (n=2)'));
  for (const word of ['partial', 'PARTIALLY', 'UNGRADED', 'PASS/PARTIAL']) {
    const entry = `calibration-2: review ${word} (n=1)`;
    const path = hp3PolicyWith((p) => { p.profiles.find((x) => x.id === 'cc-sonnet-low').evidence.push(entry); });
    const message = new RegExp(`profile cc-sonnet-low evidence '${entry.replace(/[()/]/g, '\\$&')}' is not 'calibration-<n>: <category> PASS\\|PARTIAL\\|FAIL \\(n=<k>\\)'`);
    assert.throws(() => loadPolicy(path), (e) => e instanceof RouterError && e.code === 2 && message.test(e.message), entry);
    const r = cli(['rate', '--trace', tmp(), '--policy', path]);
    assert.equal(r.code, 2, r.stdout);
    assert.match(r.stderr, message);
  }
});

test('host-policy-3 routing: pin-tests -> cc-haiku-low; review -> cc-opus-high (cc-opus-xhigh ties, loses on effort); fix -> cc-haiku-high (the economics); the review-only profiles alone are blocked', () => {
  const live = loadPolicy(HP3_OFF_PATH);
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
  // the CLI on the host-policy-3 fixture agrees (feature-off derivative, as the other policy decisions; --policy)
  const decided = cliDecide(reqFor(live, 'fix', { taskId: 'hp3-fix' }), HP3_OFF_PATH);
  assert.equal(decided.bindings['policy-revision'], 'host-policy-3');
  assert.equal(decided.decision.profile, 'cc-haiku-high');
});

// P3-R2: the README's 'routing consequence' names what decide does above cc-haiku-high's headroom, and no tie that never
// decides: at 726000 tokens cc-opus-xhigh (246k) fails Gate 2 too, so cc-opus-high is the only opus left
test('README: a fix at cc-haiku-high\'s headroom or above routes to cc-opus-high under host-policy-3, and the routing-consequence sentence says so without a cc-opus-xhigh tie', () => {
  const live = loadPolicy(HP3_OFF_PATH);
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
  for (const policy of [HP2_OFF_PATH, HP3_OFF_PATH]) {
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
  const uw = loadPolicy(HP3_POLICY_PATH)['usage-windows'];
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
  const d = computeDecision(req({ category: 'build-core' }), loadPolicy(HP3_POLICY_PATH), [], {}, { readings: [{ ts: NOW, windows: { five_hour: { utilization: 0.6, 'resets-at': isoAt(NOW_MS + 4 * HOUR) }, seven_day: { utilization: 0.05, 'resets-at': isoAt(NOW_MS + 144 * HOUR) } } }] });
  assert.equal(d.route, 'delegate');
  assert.equal(d.usage.windows.five_hour.projected, 0.6273); // 0.6 + 0.545 x 0.05
  assert.equal(d.usage.windows.five_hour['headroom-mtok'], 1); // (0.9 - 0.25 - 0.6) / 0.05
  assert.match(d.candidates['cc-opus-high'].walkthrough[3].note, /usage window five_hour binds: projected 0\.6273 <= 0\.65$/);
  assert.ok(d.uncertainty.includes(`usage windows: coefficients host-declared (${uw['coefficient-basis']})`));
  // rate on the committed readings: the ratification is after every observation, so nothing is considered or proposed
  // The copied trace is cut at that instant: the live trace keeps growing, and its first clean reading pair after the
  // ratification (2026-10-18T21:59:28Z to 2026-10-19T03:01:34Z, sr-pack and sr-evidence inside it, nothing in flight at
  // either) is considered by rate - which is what the lead reserve and the coefficients exist to be measured by. The
  // test pins the state at the ratification, so it stays a function of records no later record can change.
  const real = tmp();
  cpSync(join(HERE, 'trace'), real, { recursive: true });
  for (const file of ['usage.jsonl', 'ledger.jsonl']) {
    const kept = readFileSync(join(real, file), 'utf8').split('\n').filter((l) => l.trim() && JSON.parse(l).ts <= '2026-10-18T02:00:00Z');
    writeFileSync(join(real, file), kept.map((l) => `${l}\n`).join(''));
  }
  const r = rate({ traceDir: real, policyPath: HP3_POLICY_PATH, now: '2026-10-18T02:00:00Z' });
  for (const w of ['five_hour', 'seven_day']) {
    assert.equal(r.stats.usage[w]['ratified-at'], '2026-10-18T01:23:32Z', w);
    assert.equal(r.stats.usage[w].considered, 0, w);
  }
  assert.deepEqual(r.usageProposals, []);
});

test('usage (host-policy-3): with no file it prints the headroom from the ratified coefficients and reserve, on a synthetic reading and on the committed readings', () => {
  const trace = tmp();
  usageCli(trace, rateLimitInfo(NOW, { five: 0.6 }), NOW, HP3_POLICY_PATH);
  const s = cli(['usage', '--trace', trace, '--now', isoAt(NOW_MS + 12 * MIN), '--policy', HP3_POLICY_PATH]);
  assert.equal(s.code, 0, s.stderr);
  assert.match(s.stdout, /^ {2}five_hour: utilization 0\.6, resets 2026-10-17T23:00:00Z, headroom 1 Mtok \(\(0\.9 - 0\.25 - 0\.6\) \/ 0\.05\)$/m);
  assert.match(s.stdout, /^ {2}seven_day: utilization 0\.05, resets 2026-10-23T19:00:00Z, headroom 50 Mtok \(\(0\.9 - 0\.1 - 0\.05\) \/ 0\.015\)$/m);
  // the committed readings (copied), pinned to two instants no later record can change: readings are monotonic and the
  // trace already holds later ones, so the latest at or before 01:35:00 is 01:30:06 for good, with nothing dispatched after
  // it yet (the sr-policy-3 dispatch is at 01:38:00); at 01:38:30 the latest is 01:37:37 and that dispatch (829000
  // usage-tokens) is after it (the lead's P3-L1: the builder's --now 01:45 picked up every later reading).
  const real = tmp();
  cpSync(join(HERE, 'trace'), real, { recursive: true });
  const live = cli(['usage', '--trace', real, '--now', '2026-10-18T01:35:00Z', '--policy', HP3_POLICY_PATH]);
  assert.equal(live.code, 0, live.stderr);
  assert.equal(live.stdout, [
    'latest usage reading 2026-10-18T01:30:06Z (age 4.9 min, max 30)',
    '  five_hour: utilization 0.42, resets 2026-10-18T04:00:00Z, headroom 4.6 Mtok ((0.9 - 0.25 - 0.42) / 0.05)',
    '  seven_day: utilization 0.36, resets 2026-10-24T18:00:00Z, headroom 29.3333 Mtok ((0.9 - 0.1 - 0.36) / 0.015)',
    ''
  ].join('\n'));
  const dispatched = cli(['usage', '--trace', real, '--now', '2026-10-18T01:38:30Z', '--policy', HP3_POLICY_PATH]);
  assert.equal(dispatched.code, 0, dispatched.stderr);
  assert.equal(dispatched.stdout, [
    'latest usage reading 2026-10-18T01:37:37Z (age 0.88 min, max 30)',
    '  dispatched and not in the reading: 829000 tokens (829000 since the reading, 0 in flight from before it)',
    '  five_hour: utilization 0.47, resets 2026-10-18T04:00:00Z, headroom 2.771 Mtok ((0.9 - 0.25 - 0.47) / 0.05 - 0.829 dispatched and not in the reading)',
    '  seven_day: utilization 0.38, resets 2026-10-24T18:00:00Z, headroom 27.171 Mtok ((0.9 - 0.1 - 0.38) / 0.015 - 0.829 dispatched and not in the reading)',
    ''
  ].join('\n'));
});

// ---------------------------------------------------------------------------------------------
// host-policy-4 (unit sr-policy-4): calibration-3 under the lead's qualification rules (briefs/policy4-builder.md);
// the host-policy-3 assertions above stay on the host-policy-3 fixture
// ---------------------------------------------------------------------------------------------
test('fixture: trace/policies/host-policy-3.json is the pre-revision policy, byte-identical to the policy the sr-policy-4 decisions were bound to', () => {
  assert.ok(existsSync(HP3_POLICY_PATH), 'the host-policy-3 fixture exists');
  for (const seq of [1, 2]) {
    const bound = JSON.parse(readFileSync(join(goldenDir, `sr-policy-4-${seq}.json`), 'utf8')).bindings;
    assert.equal(bound['policy-revision'], 'host-policy-3', `sr-policy-4-${seq}`);
    assert.equal(createHash('sha256').update(readFileSync(HP3_POLICY_PATH)).digest('hex'), bound['policy-sha256'], `sr-policy-4-${seq}`);
  }
  assert.equal(loadPolicy(HP3_POLICY_PATH)['policy-revision'], 'host-policy-3');
  assert.equal(JSON.parse(readFileSync(HP3_POLICY_PATH, 'utf8')).request, undefined, 'a policy, never a decision');
});

const CAL3 = JSON.parse(readFileSync(join(HERE, 'trace', 'calibration-3', 'observations.json'), 'utf8'));
const RUN3_ID = 'wf_4e9ef48d-066 (calibration-3): ';
const RUN3_SUPPLEMENTARY = '; fix (cc-haiku-high) and review (cc-haiku-low) from the supplementary run wf_dbe29a64-3b2 (amendment A-1)';
// the lead's applied table (briefs/policy4-builder.md): categories added to or removed from the host-policy-3
// qualified-for; every other field of every profile is unchanged but for the entries
const HP4_TABLE = {
  'cc-haiku-low': { remove: ['fix'] },
  'cc-haiku-medium': {},
  'cc-haiku-high': {},
  'cc-sonnet-low': { add: ['review'] },
  'cc-sonnet-medium': {},
  'cc-sonnet-high': { add: ['review'] },
  'cc-sonnet-xhigh': { add: ['review'] },
  'cc-opus-medium': {},
  'cc-opus-high': {},
  'cc-opus-xhigh': {},
  'cc-opus-max': { add: ['review'] },
  'cc-fable-medium': { remove: ['pin-tests'] },
  'cc-fable-high': {},
  'cc-fable-xhigh': {},
  'cc-fable-max': { add: ['review'] }
};
const HP4_REVIEWER = 'host-declared (lead) from calibration-1, calibration-2 and calibration-3 grades';
const HP4_EXTRA = {
  'cc-haiku-low': 'demoted from fix 2026-10-18: two consecutive verification-failed outcomes (fix-u7-r3 seq 4, fix-x2-2 seq 3; rate proposal ratified); re-qualification needs two later passes',
  'cc-fable-medium': 'pin-tests blocked 2026-10-18: calibration-3 pin FAIL (over-specified pin, lead-notes N-1); two later passes needed'
};
// the entries revision 4 appends to a profile's host-policy-3 evidence, in order: the run-3 run id (a review-only
// profile's says so, as revision 3 wrote it), its run-3 grades, then the demotion or block entry
function hp4NewEntries(id, o) {
  const graded = o.pin ? 'pin, fix and review graded in trace/calibration-3/ (results-table.md, observations.json)'
    : 'review graded in trace/calibration-3/ (results-table.md, observations.json); a review-only profile in that run (no pin or fix cell)';
  const supplementary = ['cc-haiku-high', 'cc-haiku-low'].includes(id) ? RUN3_SUPPLEMENTARY : '';
  return [`${RUN3_ID}${graded}${supplementary}`, ...gradeEntries(3, o), ...(HP4_EXTRA[id] ? [HP4_EXTRA[id]] : [])];
}

test('host-policy-4 (fixture): the lead\'s table applied - qualified-for, the three runs\' grade entries and run ids, the demotion and block entries, headroom rule over the three runs; nothing else changes', () => {
  const raw = JSON.parse(readFileSync(HP4_POLICY_PATH, 'utf8'));
  const hp3 = JSON.parse(readFileSync(HP3_POLICY_PATH, 'utf8'));
  const live = loadPolicy(HP4_POLICY_PATH);
  assert.equal(live['policy-revision'], 'host-policy-4');
  // categories, economics, usage windows, prices, harness, authorization, isolation, accounting, opt-ins: untouched
  const rest = (p) => Object.fromEntries(Object.entries(p).filter(([k]) => !['policy-revision', 'profiles'].includes(k)));
  assert.deepEqual(rest(raw), rest(hp3), 'only the revision and the profiles change');
  assert.deepEqual(raw.profiles.map((p) => p.id), hp3.profiles.map((p) => p.id), 'the fifteen profiles of host-policy-3, in order');
  assert.deepEqual(Object.keys(HP4_TABLE).sort(), raw.profiles.map((p) => p.id).sort());
  const fixed = (p) => Object.fromEntries(Object.entries(p).filter(([k]) => !['qualified-for', 'qualified-at', 'reviewer', 'evidence'].includes(k)));
  const seen = new Set();
  for (const o of Object.values(CAL3)) {
    const pr = calProfileAny(live, o);
    assert.ok(pr, `${o.profile} (calibration-3) has a policy profile`);
    seen.add(pr.id);
    const before = hp3.profiles.find((p) => p.id === pr.id);
    const want = HP4_TABLE[pr.id];
    const after = raw.profiles.find((p) => p.id === pr.id);
    assert.deepEqual(fixed(after), fixed(before), `${pr.id}: model, effort, config, tools, vision, context, headroom, expires unchanged`);
    const expected = before['qualified-for'].filter((c) => !(want.remove ?? []).includes(c)).concat(want.add ?? []);
    assert.deepEqual([...after['qualified-for']].sort(), [...expected].sort(), `${pr.id} qualified-for`);
    for (const c of want.remove ?? []) assert.ok(before['qualified-for'].includes(c), `${pr.id} held ${c} before its removal`);
    for (const c of want.add ?? []) assert.ok(!before['qualified-for'].includes(c), `${pr.id} lacked ${c} before its addition`);
    if (want.add || want.remove) {
      assert.deepEqual([after['qualified-at'], after.reviewer], ['2026-10-18', HP4_REVIEWER], `${pr.id}: a qualification added or removed in host-policy-4`);
    } else {
      assert.deepEqual([after['qualified-at'], after.reviewer], [before['qualified-at'], before.reviewer], `${pr.id}: unchanged, gains the entries`);
    }
    assert.equal(after.expires, '2027-01-15', pr.id);
    // host-policy-3's evidence kept verbatim, then exactly the run-3 entries
    assert.deepEqual(after.evidence, [...before.evidence, ...hp4NewEntries(pr.id, o)], `${pr.id} evidence`);
  }
  assert.equal(seen.size, 15, 'every profile was calibrated in run 3');
  // the grade entries are exactly the three runs' grades, each run with its run id (accepted outcomes up to the
  // fixture's freeze, P3-L2: a later accepted outcome raises the live policy, never the fixture)
  const accepted = acceptedTokens(FREEZE_HP4);
  for (const pr of raw.profiles) {
    const obs = [CAL1, CAL2, CAL3].map((cal) => Object.values(cal).filter((o) => calProfileAny(live, o)?.id === pr.id));
    const grades = obs.flatMap((list, i) => list.flatMap((o) => gradeEntries(i + 1, o)));
    assert.deepEqual(pr.evidence.filter((e) => e.startsWith('calibration-')).sort(), grades.sort(), `${pr.id}: no grade entry beyond the three runs'`);
    obs.forEach((list, i) => { if (list.length) assert.ok(pr.evidence.some((e) => e.startsWith({ ...RUN_IDS, 3: RUN3_ID }[i + 1])), `${pr.id} lacks the calibration-${i + 1} run id`); });
    // headroom-tested: the largest completed run (three calibration runs, accepted outcomes), rounded up to the next
    // thousand, never lowered below host-policy-3's
    const runs = obs.flat().flatMap((o) => ['pin', 'fix', 'review'].map((t) => o.usage?.[t]).filter((u) => u && u.state === 'done').map((u) => u.tokens));
    const before = hp3.profiles.find((p) => p.id === pr.id)['headroom-tested'];
    assert.equal(pr['headroom-tested'], Math.max(before, Math.ceil(Math.max(...runs, accepted[pr.id] ?? 0) / 1000) * 1000), `${pr.id} headroom rule`);
    // run 3 raises nothing: every run-3 cell is below the profile's current figure
    const run3 = obs[2].flatMap((o) => ['pin', 'fix', 'review'].map((t) => o.usage?.[t]).filter((u) => u && u.state === 'done').map((u) => u.tokens));
    assert.ok(Math.max(...run3) < pr['headroom-tested'], `${pr.id}: run 3 max ${Math.max(...run3)} below ${pr['headroom-tested']}`);
  }
  // the brief's largest run-3 cells, spelled out
  const cell = (key, task) => CAL3[key].usage[task].tokens;
  assert.deepEqual([cell('sonnet-xhigh', 'review'), cell('opus-max', 'review'), cell('fable-max', 'review'), cell('haiku-high', 'fix')], [227264, 266339, 189364, 142418]);
  assert.deepEqual(['cc-sonnet-xhigh', 'cc-opus-max', 'cc-fable-max', 'cc-haiku-high'].map((id) => live.profiles.find((p) => p.id === id)['headroom-tested']), [328000, 307000, 230000, 726000]);
  // the demotion and the block are recorded on their profiles only
  for (const [id, entry] of Object.entries(HP4_EXTRA)) {
    assert.deepEqual(raw.profiles.filter((p) => p.evidence.includes(entry)).map((p) => p.id), [id], entry);
  }
  assert.ok(raw.profiles.find((p) => p.id === 'cc-fable-medium').evidence.includes('calibration-3: pin-tests FAIL (n=1)'));
  assert.ok(!raw.profiles.some((p) => p.evidence.some((e) => / PARTIAL /.test(e) && e.startsWith('calibration-3:'))), 'no PARTIAL in run 3');
});

const hp4Req = (category, over = {}) => reqFor(loadPolicy(HP4_OFF_PATH), category, over);
test('host-policy-4 routing (fixture): pin-tests -> cc-haiku-low; fix -> cc-haiku-high with cc-sonnet-xhigh the reviewer; review -> cc-sonnet-xhigh; the demoted, blocked and one-later-pass profiles alone are blocked', () => {
  const live = loadPolicy(HP4_OFF_PATH);
  // pin-tests: unchanged, cc-haiku-low at $1.06; cc-fable-medium no longer qualified
  const pin = computeDecision(hp4Req('pin-tests'), live, []);
  assert.deepEqual([pin.route, pin.profile, pin['all-in-bound-usd'], pin['review-profile']], ['delegate', 'cc-haiku-low', 1.06, null]);
  assert.equal(pin.candidates['cc-fable-medium'].reason, 'cc-fable-medium not qualified for pin-tests');
  // fix (193000): cc-haiku-low gone, cc-haiku-medium's 183000 does not admit it, so cc-haiku-high; the required reviewer is
  // now the cheapest review-qualified profile whose headroom admits the 209000-token median: cc-sonnet-xhigh
  const fix = computeDecision(hp4Req('fix'), live, []);
  assert.deepEqual([fix.route, fix.profile, fix['review-profile']], ['delegate', 'cc-haiku-high', 'cc-sonnet-xhigh']);
  const c = fix.candidates['cc-haiku-high'];
  assert.deepEqual([c['work-bound-usd'], c['review-bound-usd'], c['overhead-bound-usd'], c['all-in-bound-usd']], [0.0965, 2.09, 1, 3.1865]);
  assert.deepEqual(fix['eligible-ordered'], ['cc-haiku-high', 'cc-opus-high', 'cc-opus-xhigh', 'cc-fable-high']);
  assert.deepEqual(['cc-opus-high', 'cc-opus-xhigh', 'cc-fable-high'].map((id) => fix.candidates[id]['all-in-bound-usd']), [6.95, 6.95, 12.74]);
  assert.equal(fix.candidates['cc-haiku-low'].reason, 'cc-haiku-low not qualified for fix; context: 193000 tokens not below headroom-tested 175000 on cc-haiku-low');
  assert.equal(fix.candidates['cc-haiku-medium'].reason, 'context: 193000 tokens not below headroom-tested 183000 on cc-haiku-medium');
  // P4-R2: a fix estimated below cc-haiku-low's 175k headroom went to cc-haiku-low under host-policy-3 and now goes to
  // cc-haiku-medium, the cheapest fix-qualified profile whose 183k headroom admits it
  const small = computeDecision(reqFor(live, 'fix', { estimatedTokens: 150000 }), live, []);
  assert.deepEqual([small.route, small.profile, small['review-profile']], ['delegate', 'cc-haiku-medium', 'cc-sonnet-xhigh']);
  assert.equal(small.candidates['cc-haiku-low'].reason, 'cc-haiku-low not qualified for fix');
  // review (209000): the newly qualified cc-sonnet-xhigh is the cheapest whose headroom admits it; cc-sonnet-low and
  // cc-sonnet-high are qualified and fail Gate 2 on headroom
  const review = computeDecision(hp4Req('review'), live, []);
  assert.deepEqual([review.route, review.profile, review['all-in-bound-usd']], ['delegate', 'cc-sonnet-xhigh', 3.09]);
  const s = review.candidates['cc-sonnet-xhigh'];
  assert.deepEqual([s['work-bound-usd'], s['review-bound-usd'], s['overhead-bound-usd']], [2.09, 0, 1]);
  assert.deepEqual(review['eligible-ordered'], ['cc-sonnet-xhigh', 'cc-opus-high', 'cc-opus-xhigh', 'cc-opus-max', 'cc-fable-high', 'cc-fable-max']);
  for (const [id, h] of [['cc-sonnet-low', 114000], ['cc-sonnet-high', 183000], ['cc-fable-medium', 172000]]) {
    assert.equal(review.candidates[id].reason, `context: 209000 tokens not below headroom-tested ${h} on ${id}`, id);
  }
  // one later pass is not a qualification: these five alone route blocked at Gate 2
  const five = ['cc-haiku-low', 'cc-haiku-medium', 'cc-haiku-high', 'cc-sonnet-medium', 'cc-opus-medium'];
  const later = computeDecision(hp4Req('review', { candidates: five }), live, []);
  assert.equal(later.route, 'blocked');
  for (const id of five) {
    assert.equal(later.candidates[id]['first-failing-gate'], 2, id);
    assert.match(later.candidates[id].reason, new RegExp(`^${id} not qualified for review`), id);
  }
  // demoted: cc-haiku-low alone routes a fix blocked; blocked: cc-fable-medium alone routes a pin blocked
  const demoted = computeDecision(hp4Req('fix', { candidates: ['cc-haiku-low'] }), live, []);
  assert.deepEqual([demoted.route, demoted.candidates['cc-haiku-low']['first-failing-gate']], ['blocked', 2]);
  assert.match(demoted.candidates['cc-haiku-low'].reason, /^cc-haiku-low not qualified for fix/);
  const pinBlocked = computeDecision(hp4Req('pin-tests', { candidates: ['cc-fable-medium'] }), live, []);
  assert.deepEqual([pinBlocked.route, pinBlocked.candidates['cc-fable-medium']['first-failing-gate'], pinBlocked.candidates['cc-fable-medium'].reason],
    ['blocked', 2, 'cc-fable-medium not qualified for pin-tests']);
  // the CLI on the fixture agrees (feature-off derivative, as the other policy decisions)
  for (const [category, profile] of [['fix', 'cc-haiku-high'], ['review', 'cc-sonnet-xhigh'], ['pin-tests', 'cc-haiku-low']]) {
    const decided = cliDecide(hp4Req(category, { taskId: `hp4-${category}` }), HP4_OFF_PATH);
    assert.equal(decided.bindings['policy-revision'], 'host-policy-4', category);
    assert.deepEqual([decided.decision.route, decided.decision.profile], ['delegate', profile], category);
  }
});

test('host-policy-4 routing (fixture): the stored build request, after a fresh synthetic reading, delegates to cc-opus-high with cc-sonnet-xhigh the required reviewer ($9.41, the golden\'s $11.50 less the review difference)', () => {
  const trace = tmp();
  const at = STORED_BUILD.request.now;
  const r = usageCli(trace, rateLimitInfo(at, { five: 0.2, seven: 0.05, fiveResetMs: 4 * HOUR, sevenResetMs: 144 * HOUR }), at, HP4_POLICY_PATH);
  assert.equal(r.code, 0, r.stderr);
  const d = decideOn(STORED_BUILD.request, trace, HP4_POLICY_PATH);
  assert.deepEqual([d.route, d.decision.profile, d.decision['review-profile']], ['delegate', 'cc-opus-high', 'cc-sonnet-xhigh']);
  const c = d.decision.candidates['cc-opus-high'];
  assert.deepEqual([c['work-bound-usd'], c['review-bound-usd'], c['overhead-bound-usd'], c['all-in-bound-usd']], [6.32, 2.09, 1, 9.41]);
  assert.equal(STORED_BUILD.decision['all-in-bound-usd'], 11.5, 'the golden: the same work and overhead with the review at cc-opus-high ($4.18)');
  assert.deepEqual(d.decision['eligible-ordered'], STORED_BUILD.decision['eligible-ordered']);
  // the usage projection counts tokens, not the reviewer's price: work + the review median + overhead, as before
  assert.equal(d.decision['usage-tokens'], 545000);
  assert.equal(d.decision.usage['reading-ts'], at);
});

// deliverable C: a demotion proposal concerns a qualified profile. Once the lead ratified it (cc-haiku-low no longer
// holds fix), the same ledger proposes nothing for that pair - a proposal that outlived its ratification would be
// re-proposed forever - and the outcome stats still count the two verification-failed fixes
const DEMOTE_HAIKU_LOW = 'PROPOSAL demote cc-haiku-low from fix: 2 consecutive verification-failed (fix-u7-r3, fix-x2-2); not applied — the lead ratifies by editing host-policy.json';
test('rate (host-policy-4 fixture): no demotion proposal for cc-haiku-low from fix once it no longer holds the category; the host-policy-3 fixture still proposes it from the same ledger; the stats keep the two failures', () => {
  const at = '2026-10-18T09:30:00Z';
  const before = cli(['rate', '--trace', frozenTrace(FREEZE_HP3), '--now', at, '--policy', HP3_POLICY_PATH]);
  assert.equal(before.code, 0, before.stderr);
  assert.ok(before.stdout.split('\n').includes(DEMOTE_HAIKU_LOW), before.stdout);
  const trace = frozenTrace(FREEZE_HP3);
  const after = cli(['rate', '--trace', trace, '--now', at, '--policy', HP4_POLICY_PATH]);
  assert.equal(after.code, 0, after.stderr);
  assert.ok(!/^PROPOSAL (demote|qualify|re-qualify) cc-haiku-low /m.test(after.stdout), after.stdout);
  const r = rate({ traceDir: frozenTrace(FREEZE_HP3), policyPath: HP4_POLICY_PATH, now: at });
  assert.deepEqual(r.proposals, [], 'no outcome proposal under host-policy-4');
  assert.deepEqual(r.headroomProposals, [], 'no headroom raise either');
  const doc = JSON.parse(readFileSync(join(trace, 'qualification-stats.json'), 'utf8'));
  assert.equal(doc['policy-revision'], 'host-policy-4');
  assert.deepEqual(doc.proposals, []);
  assert.equal(doc.stats['cc-haiku-low'].fix['verification-failed'], 2, 'the history is kept; only the proposal is gone');
});

test('rate (host-policy-4 fixture): the CALIBRATION lines count calibration-1, -2 and -3 per profile and category - the counts the lead\'s table turns on', () => {
  const live = loadPolicy(HP4_OFF_PATH);
  const r = rate({ traceDir: calibrationTrace([CAL1, CAL2, CAL3]), policyPath: HP4_OFF_PATH, now: NOW });
  const lines = r.text.split('\n').filter((l) => l.startsWith('CALIBRATION '));
  const want = {};
  for (const [run, obs] of [[1, CAL1], [2, CAL2], [3, CAL3]]) {
    for (const o of Object.values(obs)) {
      for (const e of gradeEntries(run, o)) {
        const [, cat, word] = /^calibration-\d+: (\S+) (\S+) /.exec(e);
        const c = ((want[calProfileAny(live, o).id] ??= {})[cat] ??= { pass: 0, partial: 0, fail: 0, runs: [] });
        c[word.toLowerCase()] += 1;
        c.runs.push(`calibration-${run}`);
      }
    }
  }
  const expected = Object.keys(want).sort().flatMap((id) => ['pin-tests', 'fix', 'review'].filter((cat) => want[id][cat])
    .map((cat) => { const c = want[id][cat]; return `CALIBRATION ${id} ${cat}: ${c.pass} pass, ${c.partial} partial, ${c.fail} fail (${c.runs.join(', ')})`; }));
  assert.deepEqual(lines, expected, r.text);
  const all = '(calibration-1, calibration-2, calibration-3)';
  for (const line of [
    `CALIBRATION cc-sonnet-high review: 2 pass, 0 partial, 1 fail ${all}`,
    `CALIBRATION cc-sonnet-low review: 2 pass, 1 partial, 0 fail ${all}`,
    'CALIBRATION cc-sonnet-xhigh review: 2 pass, 0 partial, 0 fail (calibration-2, calibration-3)',
    'CALIBRATION cc-opus-max review: 2 pass, 0 partial, 0 fail (calibration-2, calibration-3)',
    'CALIBRATION cc-fable-max review: 2 pass, 0 partial, 0 fail (calibration-2, calibration-3)',
    `CALIBRATION cc-sonnet-medium review: 2 pass, 0 partial, 1 fail ${all}`,
    `CALIBRATION cc-opus-medium review: 2 pass, 0 partial, 1 fail ${all}`,
    `CALIBRATION cc-haiku-low review: 1 pass, 0 partial, 2 fail ${all}`,
    `CALIBRATION cc-haiku-medium review: 1 pass, 0 partial, 2 fail ${all}`,
    `CALIBRATION cc-haiku-high review: 1 pass, 0 partial, 2 fail ${all}`,
    `CALIBRATION cc-haiku-low fix: 3 pass, 0 partial, 0 fail ${all}`,
    `CALIBRATION cc-fable-medium pin-tests: 2 pass, 0 partial, 1 fail ${all}`
  ]) assert.ok(lines.includes(line), `missing: ${line}`);
  // the committed trace (all three runs under trace/) prints the same lines
  const committed = rate({ traceDir: frozenTrace(FREEZE_HP3), policyPath: HP4_OFF_PATH, now: NOW });
  assert.deepEqual(committed.text.split('\n').filter((l) => l.startsWith('CALIBRATION ')), expected);
  assert.deepEqual(r.proposals, [], 'calibration counts never propose');
});

// deliverable D of sr-policy-4: the README's revision-4 section quotes decide on host-policy-4 (pinned to its fixture's
// feature-off derivative by sr-policy-5): every gate-walk line, the Profile line (model elided) and the Reservations
// line of a default fix and a default review, the bounds above each cheapest profile's headroom, and the sentences the
// brief asks for
test('README: how calibration run 3 was applied (host-policy-4 fixture) - the routing consequence is decide\'s own output for a default fix and review, with the G-2 sentence, the demotion, the pin block and friction items 19-20', () => {
  const readme = readFileSync(join(HERE, 'README.md'), 'utf8');
  const start = readme.indexOf('### How calibration run 3 was applied (host-policy-4)');
  assert.ok(start >= 0, 'the README carries the run-3 section');
  const section = readme.slice(start, readme.indexOf('\n### ', start + 1));
  const live = loadPolicy(HP4_OFF_PATH);
  for (const category of ['fix', 'review']) {
    const trace = tmp();
    const r = cli(['decide', writeJson(hp4Req(category, { taskId: `readme-${category}` })), '--trace', trace, '--policy', HP4_OFF_PATH]);
    assert.equal(r.code, 0, r.stderr);
    const out = r.stdout.split('\n');
    const walk = out.slice(out.indexOf('Gate walk (per candidate):'), out.findIndex((l) => l.startsWith('Brief')));
    assert.equal(walk.length, 1 + live.profiles.length, category);
    const profile = out.find((l) => l.startsWith('Profile:'));
    const model = live.profiles.find((p) => profile.includes(`(${p.id},`)).model;
    for (const line of [out.find((l) => l.startsWith('Route:')), profile.replace(model, '<model>'), out.find((l) => l.startsWith('Reservations:')), ...walk]) {
      assert.ok(section.includes(`\n${line}\n`), `${category}: README lacks the line\n${line}`);
    }
  }
  const flat = section.replace(/\s+/g, ' ');
  // above each cheapest profile's headroom: the bound decide computes
  const bigFix = computeDecision(hp4Req('fix', { estimatedTokens: 726000 }), live, []);
  const bigReview = computeDecision(hp4Req('review', { estimatedTokens: 328000 }), live, []);
  assert.deepEqual([bigFix.profile, bigFix['all-in-bound-usd'], bigReview.profile, bigReview['all-in-bound-usd']], ['cc-opus-high', 17.61, 'cc-opus-high', 7.56]);
  for (const sentence of [
    'A fix estimated at 726000 tokens or more no longer fits `cc-haiku-high` (or `cc-opus-xhigh`, 246k) and goes to `cc-opus-high` ($17.61 at 726000).',
    'A review estimated at 328000 tokens or more no longer fits `cc-sonnet-xhigh` (or `cc-opus-max`, 307k) and goes to `cc-opus-high` ($7.56 at 328000).',
    'G-2 (lead-notes.md): two of the five adjudicated clusters rest on two prongs of the classification; under the full definition the run-3 review of cc-haiku-medium and cc-haiku-high would be FAIL. The preregistered score (PASS) is what the evidence entries record, and it changes nothing above (both profiles need two later passes either way).'
  ]) assert.ok(flat.includes(sentence), `README lacks: ${sentence}`);
  for (const part of ['fix-u7-r3 seq 4', 'fix-x2-2 seq 3', 'two later passes dated after 2026-10-18', '`pin-tests` for `cc-fable-medium`', 'required reviewer']) {
    assert.ok(flat.includes(part), `the run-3 section names ${part}`);
  }
  const friction = readme.slice(readme.indexOf('## Friction log for SmartRouter upstream'));
  assert.match(friction, /\n19\. \*\*The workflow harness relays the operator's latest chat message into every worker/);
  assert.match(friction, /\n20\. \*\*The three-lens adjudication's output schema has no `forbidden` prong/);
});

// ---------------------------------------------------------------------------------------------
// SmartRouter Item 4 (accepted upstream 2026-10-18): a null cash counter or spend carries its estimate-only marker
// ---------------------------------------------------------------------------------------------
const ledgerLines = (trace) => readFileSync(join(trace, 'ledger.jsonl'), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));

test('Item 4: every record a decision, dispatch and outcome cycle appends carries counters.cash-basis "estimate-only" (accounting.mode); the decision file does not, and old unmarked lines are still read', () => {
  assert.equal(POLICY.accounting.mode, 'estimate-only');
  assert.equal(COMMITTED_POLICY.accounting.mode, 'estimate-only');
  const trace = tmp();
  const d = run(req({ taskId: 'cb-1' }), { traceDir: trace });
  const disp = dispatch('cb-1', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  const out = recordOutcome(outcome({ 'task-id': 'cb-1', outcome: 'accepted', 'original-brief-fingerprint': d.briefFingerprint }), { traceDir: trace, policyPath: POLICY_PATH, now: NOW });
  const marked = { 'calls-limit': 6, 'cash-spent': null, 'cash-cap': null, 'repairs-used': 0, 'repairs-allowed': 1, 'cash-basis': 'estimate-only' };
  assert.deepEqual(d.record.counters, { ...marked, 'calls-used': 0 });
  assert.deepEqual(disp.counters, { ...marked, 'calls-used': 1 });
  assert.deepEqual(out.counters, { ...marked, 'calls-used': 1 });
  // on disk: the three lines as appended, each marked
  assert.deepEqual(ledgerLines(trace).map((r) => [r.kind, r.counters['cash-basis']]), [['decision', 'estimate-only'], ['dispatch', 'estimate-only'], ['outcome', 'estimate-only']]);
  // the marker is additive to records, not to decisions: the decision file's counters stay §10.5's six
  const file = JSON.parse(readFileSync(d.decisionPath, 'utf8'));
  assert.equal(Object.hasOwn(file['ledger-before'], 'cash-basis'), false);
  assert.equal(Object.hasOwn(d.decision.counters, 'cash-basis'), false);
  // a CLI cycle writes the same marker
  const cliTrace = tmp();
  assert.equal(cli(['decide', writeJson(req({ taskId: 'cb-2' })), '--trace', cliTrace]).code, 0);
  assert.equal(cli(['dispatch', 'cb-2', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', cliTrace, '--now', NOW]).code, 0);
  assert.ok(ledgerLines(cliTrace).every((r) => r.counters['cash-basis'] === 'estimate-only'));
  // a host whose accounting is not estimate-only gets no marker (the marker states why the counters are null)
  const metered = policyWith((p) => { p.accounting.mode = 'metered'; });
  const mTrace = tmp();
  const md = decide(req({ taskId: 'cb-3' }), { policyPath: metered, traceDir: mTrace });
  assert.equal(Object.hasOwn(md.record.counters, 'cash-basis'), false);
  assert.equal(Object.hasOwn(dispatch('cb-3', 'cc-opus-high', { projectStop: CLEAR, traceDir: mTrace, policyPath: metered, now: NOW }).counters, 'cash-basis'), false);
  // the committed ledger is append-only: its lines written before Item 4 stay unmarked and are still read
  const committed = readLedger(join(HERE, 'trace'));
  assert.ok(committed.length > 0);
  assert.ok(committed.some((r) => !Object.hasOwn(r.counters, 'cash-basis')));
});

test('Item 4: an outcome with evidence.actual-spend null and no actual-spend-basis (absent or null) is stored and recorded with actual-spend-basis "estimate-only"; a supplied "estimate-only" is kept; any other basis is exit 2; a non-null spend gets none', () => {
  const trace = tmp();
  const cycle = (taskId, evidence, policyPath = POLICY_PATH, dir = trace) => {
    const d = decide(req({ taskId }), { policyPath, traceDir: dir });
    dispatch(taskId, 'cc-opus-high', { projectStop: CLEAR, traceDir: dir, policyPath, now: NOW });
    const o = outcome({ 'task-id': taskId, outcome: 'accepted', 'original-brief-fingerprint': d.briefFingerprint });
    o.evidence = { ...o.evidence, ...evidence };
    const given = JSON.parse(JSON.stringify(o));
    const rec = recordOutcome(o, { traceDir: dir, policyPath, now: NOW });
    assert.deepEqual(o, given, 'the caller\'s Outcome is not mutated');
    const stored = JSON.parse(readFileSync(join(dir, 'outcomes', `${taskId}-${rec.seq}.json`), 'utf8'));
    return { rec, stored, given };
  };
  // null spend, no basis: the stored copy and the record carry the marker; nothing else in the Outcome moves
  const unmarked = cycle('sb-1', {});
  assert.equal(unmarked.given.evidence['actual-spend'], null);
  assert.equal(unmarked.stored.evidence['actual-spend-basis'], 'estimate-only');
  assert.equal(unmarked.stored.evidence['actual-spend'], null);
  assert.deepEqual({ ...unmarked.stored, evidence: { ...unmarked.stored.evidence, 'actual-spend-basis': undefined } }, { ...unmarked.given, evidence: { ...unmarked.given.evidence, 'actual-spend-basis': undefined } });
  assert.equal(unmarked.rec['actual-spend-basis'], 'estimate-only');
  assert.equal(ledgerLines(trace).find((r) => r['task-id'] === 'sb-1' && r.kind === 'outcome')['actual-spend-basis'], 'estimate-only');
  // a supplied basis is kept as given, on the stored copy and the record
  const supplied = cycle('sb-2', { 'actual-spend-basis': 'estimate-only' });
  assert.equal(supplied.stored.evidence['actual-spend-basis'], 'estimate-only');
  assert.deepEqual(supplied.stored, supplied.given);
  assert.equal(supplied.rec['actual-spend-basis'], 'estimate-only');
  // R1: a null basis is no basis - it is defaulted like an absent one, never stored or recorded as null
  const nullBasis = cycle('sb-3', { 'actual-spend-basis': null });
  assert.equal(nullBasis.stored.evidence['actual-spend-basis'], 'estimate-only');
  assert.equal(nullBasis.rec['actual-spend-basis'], 'estimate-only');
  const knownNull = cycle('sb-7', { 'actual-spend': 0.42, 'actual-spend-basis': null });
  assert.equal(Object.hasOwn(knownNull.stored.evidence, 'actual-spend-basis'), false);
  assert.equal(Object.hasOwn(knownNull.rec, 'actual-spend-basis'), false);
  // R1: upstream conform_spec.py refuses any other basis (sr-ci-item4 B), so the adapter refuses it (exit 2) and
  // stores and appends nothing
  for (const [i, bad] of ['lead estimate', 'metered', 42, true, {}].entries()) {
    const taskId = `sb-8${i}`;
    const d = decide(req({ taskId }), { policyPath: POLICY_PATH, traceDir: trace });
    dispatch(taskId, 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: POLICY_PATH, now: NOW });
    const o = outcome({ 'task-id': taskId, outcome: 'accepted', 'original-brief-fingerprint': d.briefFingerprint });
    o.evidence = { ...o.evidence, 'actual-spend-basis': bad };
    assert.throws(() => recordOutcome(o, { traceDir: trace, policyPath: POLICY_PATH, now: NOW }), (e) => e instanceof RouterError && e.code === 2 && /invalid Outcome \(spec-v2 §10\.3\): evidence\.actual-spend-basis must be "estimate-only" when present \(SmartRouter Item 4\)/.test(e.message), JSON.stringify(bad));
    const out = cli(['outcome', writeJson(o), '--trace', trace, '--now', NOW]);
    assert.equal(out.code, 2, `${JSON.stringify(bad)}: ${out.stdout}`);
    assert.match(out.stderr, /evidence\.actual-spend-basis must be "estimate-only" when present/);
    assert.equal(readLedger(trace).filter((r) => r['task-id'] === taskId && r.kind === 'outcome').length, 0);
    assert.equal(existsSync(join(trace, 'outcomes', `${taskId}-3.json`)), false);
  }
  // a known spend needs no marker
  const known = cycle('sb-4', { 'actual-spend': 0.42 });
  assert.deepEqual(known.stored, known.given);
  assert.equal(Object.hasOwn(known.stored.evidence, 'actual-spend-basis'), false);
  assert.equal(Object.hasOwn(known.rec, 'actual-spend-basis'), false);
  // the CLI stores the same marker
  const cliTrace = tmp();
  const cd = run(req({ taskId: 'sb-5' }), { traceDir: cliTrace });
  dispatch('sb-5', 'cc-opus-high', { projectStop: CLEAR, traceDir: cliTrace, policyPath: POLICY_PATH, now: NOW });
  const r = cli(['outcome', writeJson(outcome({ 'task-id': 'sb-5', outcome: 'accepted', 'original-brief-fingerprint': cd.briefFingerprint })), '--trace', cliTrace, '--now', NOW]);
  assert.equal(r.code, 0, r.stderr);
  assert.equal(JSON.parse(readFileSync(join(cliTrace, 'outcomes', 'sb-5-3.json'), 'utf8')).evidence['actual-spend-basis'], 'estimate-only');
  // a host whose accounting is not estimate-only does not claim the basis
  const metered = cycle('sb-6', {}, policyWith((p) => { p.accounting.mode = 'metered'; }), tmp());
  assert.equal(Object.hasOwn(metered.stored.evidence, 'actual-spend-basis'), false);
  assert.equal(Object.hasOwn(metered.rec, 'actual-spend-basis'), false);
  // R1: nor does it keep a null basis there
  const meteredNull = cycle('sb-9', { 'actual-spend-basis': null }, policyWith((p) => { p.accounting.mode = 'metered'; }), tmp());
  assert.equal(Object.hasOwn(meteredNull.stored.evidence, 'actual-spend-basis'), false);
  assert.equal(Object.hasOwn(meteredNull.rec, 'actual-spend-basis'), false);
});

// ---------------------------------------------------------------------------------------------
// host-policy-5 (unit sr-policy-5): difficulty tiers (SmartRouter docs/proposals/difficulty-tiers.md, merged as PR
// #100) under the lead's decisions D1-D9 (briefs/policy5-builder.md); the host-policy-4 assertions above stay on the
// host-policy-4 fixture
// ---------------------------------------------------------------------------------------------
test('fixture: trace/policies/host-policy-4.json is the pre-revision policy, byte-identical to the policy the sr-policy-5 decision was bound to', () => {
  assert.ok(existsSync(HP4_POLICY_PATH), 'the host-policy-4 fixture exists');
  const bound = JSON.parse(readFileSync(join(goldenDir, 'sr-policy-5-1.json'), 'utf8')).bindings;
  assert.equal(bound['policy-revision'], 'host-policy-4');
  assert.equal(createHash('sha256').update(readFileSync(HP4_POLICY_PATH)).digest('hex'), bound['policy-sha256']);
  assert.equal(loadPolicy(HP4_POLICY_PATH)['policy-revision'], 'host-policy-4');
  assert.equal(JSON.parse(readFileSync(HP4_POLICY_PATH, 'utf8')).request, undefined, 'a policy, never a decision');
});

// an enforced or untiered derivative of the host-policy-4 fixture (feature-off, R1(a)), mutated; revision 5 itself is
// tested on the live policy below
const hp4PolicyWith = (mutate) => {
  const p = JSON.parse(readFileSync(HP4_OFF_PATH, 'utf8'));
  mutate(p);
  const path = join(tmp(), 'host-policy.json');
  writeFileSync(path, JSON.stringify(p, null, 2));
  return path;
};
const enforce = (p) => { p['difficulty-tiers'] = 'enforced'; };
const profileOf = (p, id) => p.profiles.find((x) => x.id === id);
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const exit2 = (fn, re) => assert.throws(fn, (e) => e instanceof RouterError && e.code === 2 && re.test(e.message), String(re));
const FIVE_FILES = ['src/a.ts', 'src/b.ts', 'src/c.ts', 'tests/a.test.ts', 'tests/b.test.ts'];

test('tiers D1/D2: "difficulty-tiers" is "enforced" or absent; tiered qualified-for and grade entries load under both, a malformed or doubled entry is refused (exit 2)', () => {
  assert.equal(loadPolicy(hp4PolicyWith(enforce))['difficulty-tiers'], 'enforced');
  for (const bad of ['on', 'Enforced', true, null, 1]) {
    exit2(() => loadPolicy(hp4PolicyWith((p) => { p['difficulty-tiers'] = bad; })), new RegExp(`^invalid policy: difficulty-tiers must be "enforced" when present \\(absent: untiered\\); got ${JSON.stringify(bad)}$`));
  }
  // the tiered forms, and a tiered grade entry, load under an enforced and an untiered policy alike (the form is checked)
  const tiered = (p) => {
    profileOf(p, 'cc-opus-high')['qualified-for'] = ['build-core@T3', 'build-ui@T3', 'build-tests@T2', 'review@T1', 'fix@T2', 'research-collect', 'pin-tests'];
    profileOf(p, 'cc-opus-high').evidence.push('calibration-4: fix@T3 PASS (n=1)', 'calibration-4: review@T2 PARTIAL (n=1)');
  };
  for (const mode of [enforce, () => {}]) {
    const pol = loadPolicy(hp4PolicyWith((p) => { mode(p); tiered(p); }));
    assert.deepEqual(profileOf(pol, 'cc-opus-high')['qualified-for'].slice(0, 2), ['build-core@T3', 'build-ui@T3']);
  }
  for (const mode of [enforce, () => {}]) {
    for (const entry of ['fix@T4', 'fix@t2', 'fix@', 'fix@T1@T2', 'fix T2']) {
      exit2(() => loadPolicy(hp4PolicyWith((p) => { mode(p); profileOf(p, 'cc-haiku-high')['qualified-for'] = [entry]; })),
        new RegExp(`^invalid policy: profile cc-haiku-high qualified-for entry '${esc(entry)}' is not '<category>' or '<category>@T1\\|T2\\|T3'$`));
    }
    exit2(() => loadPolicy(hp4PolicyWith((p) => { mode(p); profileOf(p, 'cc-haiku-high')['qualified-for'] = ['astrology@T2']; })),
      /^invalid policy: profile cc-haiku-high qualified-for names unknown category 'astrology'$/);
    for (const pair of [['fix', 'fix@T2'], ['fix@T1', 'fix@T3'], ['fix', 'fix']]) {
      exit2(() => loadPolicy(hp4PolicyWith((p) => { mode(p); profileOf(p, 'cc-haiku-high')['qualified-for'] = ['pin-tests', ...pair]; })),
        new RegExp(`^invalid policy: profile cc-haiku-high qualified-for names fix twice \\('${pair[0]}', '${pair[1]}'\\): one entry per category$`));
    }
    for (const entry of ['calibration-4: fix@T4 PASS (n=1)', 'calibration-4: fix@ PASS (n=1)', 'calibration-4: fix @T2 PASS (n=1)']) {
      exit2(() => loadPolicy(hp4PolicyWith((p) => { mode(p); profileOf(p, 'cc-haiku-high').evidence.push(entry); })),
        new RegExp(`^invalid policy: profile cc-haiku-high evidence '${esc(entry)}' is not 'calibration-<n>: <category> PASS\\|PARTIAL\\|FAIL \\(n=<k>\\)'`));
    }
    exit2(() => loadPolicy(hp4PolicyWith((p) => { mode(p); profileOf(p, 'cc-haiku-high').evidence.push('calibration-4: astrology@T3 PASS (n=1)'); })),
      /^invalid policy: profile cc-haiku-high evidence 'calibration-4: astrology@T3 PASS \(n=1\)' names unknown category 'astrology'$/);
  }
  // the CLI refuses such a policy before deciding anything
  const r = cli(['decide', writeJson(req({ taskId: 'tp-1' })), '--trace', tmp(), '--policy', hp4PolicyWith((p) => { p['difficulty-tiers'] = 'on'; })]);
  assert.equal(r.code, 2, r.stdout);
  assert.match(r.stderr, /difficulty-tiers must be "enforced" when present/);
});

test('tiers D3: difficultyTier is T1, T2 or T3 when present; the floor is mechanical (uncertainty, the edit set without the architecture map, docs-mechanical T1); undeclared reads T3 high-risk, T2 otherwise, raised to the floor', () => {
  const on = loadPolicy(hp4PolicyWith(enforce));
  const off = loadPolicy(HP4_OFF_PATH);
  for (const pol of [on, off]) {
    for (const bad of ['T4', 't1', 'T0', '', 1, null, ['T1']]) {
      exit2(() => computeDecision(reqFor(pol, 'fix', { difficultyTier: bad }), pol, []), new RegExp(`^${esc(`invalid request: difficultyTier must be "T1", "T2" or "T3" when present (got ${JSON.stringify(bad)})`)}$`));
    }
  }
  const tierOf = (category, over = {}) => requestTier(reqFor(on, category, over), on);
  // undeclared: the proposal's default, raised to the floor
  assert.deepEqual(tierOf('fix'), { tier: 'T3', declared: null, floor: 'T1', default: 'T3' });
  assert.deepEqual(tierOf('review'), { tier: 'T3', declared: null, floor: 'T1', default: 'T3' });
  assert.deepEqual(tierOf('build-core'), { tier: 'T3', declared: null, floor: 'T1', default: 'T3' });
  assert.deepEqual(tierOf('build-ui'), { tier: 'T2', declared: null, floor: 'T1', default: 'T2' });
  assert.deepEqual(tierOf('pin-tests'), { tier: 'T2', declared: null, floor: 'T1', default: 'T2' });
  assert.deepEqual(tierOf('docs-mechanical'), { tier: 'T2', declared: null, floor: 'T1', default: 'T2' });
  assert.deepEqual(tierOf('build-ui', { permittedEffects: FIVE_FILES }), { tier: 'T3', declared: null, floor: 'T3', default: 'T2' });
  assert.deepEqual(tierOf('build-ui', { permittedEffects: FIVE_FILES.slice(0, 3) }), { tier: 'T2', declared: null, floor: 'T2', default: 'T2' });
  assert.deepEqual(tierOf('pin-tests', { uncertainty: 'high' }), { tier: 'T3', declared: null, floor: 'T3', default: 'T2' });
  // docs-mechanical is always T1 at the floor, whatever the edit set or the uncertainty
  assert.deepEqual(tierOf('docs-mechanical', { permittedEffects: FIVE_FILES, uncertainty: 'high', difficultyTier: 'T1' }), { tier: 'T1', declared: 'T1', floor: 'T1', default: 'T2' });
  // declared at or above the floor: accepted as given
  assert.deepEqual(tierOf('fix', { difficultyTier: 'T1' }), { tier: 'T1', declared: 'T1', floor: 'T1', default: 'T3' });
  assert.deepEqual(tierOf('build-ui', { difficultyTier: 'T3' }), { tier: 'T3', declared: 'T3', floor: 'T1', default: 'T2' });
  assert.deepEqual(tierOf('docs-mechanical', { difficultyTier: 'T3' }), { tier: 'T3', declared: 'T3', floor: 'T1', default: 'T2' });
  // the architecture map is not in the edit set: four entries, one the map, is an edit set of three
  const withMap = [...FIVE_FILES.slice(0, 3), 'docs/ARCHITECTURE.md'];
  assert.deepEqual(tierOf('fix', { permittedEffects: withMap, difficultyTier: 'T2' }), { tier: 'T2', declared: 'T2', floor: 'T2', default: 'T3' });
  assert.deepEqual(tierOf('fix', { permittedEffects: FIVE_FILES.slice(0, 2), difficultyTier: 'T1' }).floor, 'T1');
  // declared below the floor: an invalid request naming both and the reason (exit 2), under the API and the CLI
  const below = [
    [{ permittedEffects: FIVE_FILES, difficultyTier: 'T1' }, 'difficultyTier T1 is below the floor T3 (edit set of 5 files, more than three)'],
    [{ permittedEffects: FIVE_FILES, difficultyTier: 'T2' }, 'difficultyTier T2 is below the floor T3 (edit set of 5 files, more than three)'],
    [{ permittedEffects: withMap, difficultyTier: 'T1' }, 'difficultyTier T1 is below the floor T2 (edit set of exactly three files)'],
    [{ uncertainty: 'high', difficultyTier: 'T2' }, 'difficultyTier T2 is below the floor T3 (uncertainty high)'],
    [{ uncertainty: 'high', permittedEffects: FIVE_FILES, difficultyTier: 'T1' }, 'difficultyTier T1 is below the floor T3 (uncertainty high; edit set of 5 files, more than three)']
  ];
  for (const [over, why] of below) {
    const tail = '; a declared tier above the floor is accepted as given, one below it never';
    exit2(() => computeDecision(reqFor(on, 'fix', over), on, []), new RegExp(`^invalid request: ${why.replace(/[()]/g, '\\$&')}${tail}$`));
    const trace = tmp();
    const r = cli(['decide', writeJson(reqFor(on, 'fix', { ...over, taskId: 'floor-1' })), '--trace', trace, '--policy', hp4PolicyWith(enforce)]);
    assert.equal(r.code, 2, r.stdout);
    assert.ok(r.stderr.includes(why), r.stderr);
    assert.equal(existsSync(join(trace, 'ledger.jsonl')), false, 'nothing appended');
    assert.equal(existsSync(join(trace, 'decisions')), false, 'no decision file');
  }
});

test('tiers D1/D3: an untiered policy behaves as today - a declared tier is checked for form only (no floor), adds the not-enforced Uncertainty clause and nothing else; a tiered entry qualifies for its category', () => {
  const off = loadPolicy(HP4_OFF_PATH);
  const base = computeDecision(reqFor(off, 'fix'), off, []);
  assert.equal(requestTier(reqFor(off, 'fix', { difficultyTier: 'T1' }), off).tier, null);
  assert.equal(base.uncertainty.includes(TIERS_OFF), false, 'no clause without a declared tier');
  assert.equal(TIERS_OFF, 'difficulty tiers: not enforced by this policy');
  // a tier below the floor is no error here: nothing is enforced
  const declared = computeDecision(reqFor(off, 'fix', { difficultyTier: 'T1', permittedEffects: FIVE_FILES }), off, []);
  const same = computeDecision(reqFor(off, 'fix', { permittedEffects: FIVE_FILES }), off, []);
  assert.deepEqual(declared.uncertainty, [...same.uncertainty, TIERS_OFF]);
  const strip = (d) => ({ ...d, uncertainty: null, text: d.text.replace(`; ${TIERS_OFF}`, '') });
  assert.deepEqual(strip(declared), strip(same), 'the rest of the decision is the undeclared one');
  // tiered entries under an untiered policy: the tier is ignored, the category qualifies (a tiered policy that loses its key)
  const tieredOff = loadPolicy(hp4PolicyWith((p) => {
    for (const pr of p.profiles) pr['qualified-for'] = pr['qualified-for'].map((c) => `${c}@T${1 + (pr.id.length % 3)}`);
  }));
  for (const category of ['fix', 'review', 'pin-tests', 'build-core']) {
    const a = computeDecision(reqFor(off, category), off, []);
    const b = computeDecision(reqFor(off, category), tieredOff, []);
    assert.deepEqual([b.route, b.profile, b['review-profile'], b['eligible-ordered']], [a.route, a.profile, a['review-profile'], a['eligible-ordered']], category);
  }
});

// an enforced derivative of the host-policy-4 fixture whose production-derived profiles hold tiered entries in the
// shape of revision 5's table (the live revision 5 is tested on its own below)
const TIERED_PATH = hp4PolicyWith((p) => {
  enforce(p);
  profileOf(p, 'cc-opus-high')['qualified-for'] = ['build-core@T3', 'build-ui@T3', 'build-tests@T3', 'review@T1', 'fix@T2', 'research-collect@T2', 'pin-tests'];
  profileOf(p, 'cc-fable-high')['qualified-for'] = ['review@T1', 'fix@T2', 'pin-tests'];
  const fx = profileOf(p, 'cc-fable-xhigh');
  fx['qualified-for'] = fx['qualified-for'].map((c) => `${c}@T3`);
});

test('tiers D4: Gate 2 passes a profile only at a tier >= the request\'s (tier k covers lower tiers), with the tier reason; the empty set stays blocked and the outside hint names who would pass', () => {
  const pol = loadPolicy(TIERED_PATH);
  const fix = (tier, over = {}) => computeDecision(reqFor(pol, 'fix', { ...(tier ? { difficultyTier: tier } : {}), ...over }), pol, []);
  const t1 = fix('T1');
  assert.deepEqual([t1.route, t1.profile, t1['review-profile']], ['delegate', 'cc-haiku-high', 'cc-sonnet-xhigh']);
  const t2 = fix('T2');
  assert.deepEqual([t2.route, t2.profile], ['delegate', 'cc-opus-high']);
  assert.deepEqual(t2['eligible-ordered'], ['cc-opus-high', 'cc-fable-high']);
  assert.equal(t2.candidates['cc-haiku-high'].reason, 'cc-haiku-high not qualified for fix@T2 (holds fix@T1)');
  assert.equal(t2.candidates['cc-haiku-medium'].reason, 'cc-haiku-medium not qualified for fix@T2 (holds fix@T1); context: 193000 tokens not below headroom-tested 183000 on cc-haiku-medium');
  assert.equal(t2.candidates['cc-fable-max'].reason, 'cc-fable-max not qualified for fix');
  for (const t3 of [fix('T3'), fix(null)]) {
    assert.equal(t3.route, 'blocked');
    assert.equal(t3.candidates['cc-opus-high'].reason, 'cc-opus-high not qualified for fix@T3 (holds fix@T2)');
    assert.equal(t3.candidates['cc-fable-high'].reason, 'cc-fable-high not qualified for fix@T3 (holds fix@T2)');
    assert.deepEqual([t3.candidates['cc-fable-xhigh']['first-failing-gate'], t3.candidates['cc-fable-xhigh'].reason], [5, 'direct unsuitable: 193000 tokens > direct-max-tokens 15000']);
  }
  // T3 covers T1 and T2: build-ui@T3 passes at every tier
  for (const tier of TIERS) assert.equal(computeDecision(reqFor(pol, 'build-ui', { difficultyTier: tier }), pol, []).profile, 'cc-opus-high', tier);
  // no eligible candidate at the tier: blocked (no new route, no recommend-escalation), and the existing hint names the
  // profile outside the candidates that would pass (proposal Item 3's "names it"); cc-sonnet-xhigh is among the
  // candidates as the required reviewer, which is drawn from them
  const outside = fix('T2', { candidates: ['cc-haiku-low', 'cc-haiku-high', 'cc-sonnet-xhigh'] });
  assert.equal(outside['review-profile'], 'cc-sonnet-xhigh');
  assert.equal(outside.route, 'blocked');
  assert.deepEqual(outside['eligible-outside-candidates'], ['cc-opus-high', 'cc-fable-high']);
  assert.ok(outside.uncertainty.some((u) => u.startsWith('not among candidates: cc-opus-high, cc-fable-high would pass all five gates')), outside.uncertainty.join('\n'));
  assert.equal(outside.candidates['cc-haiku-high'].reason, 'cc-haiku-high not qualified for fix@T2 (holds fix@T1)');
  // the same requests under the untiered fixture: Gate 2 per category, as before
  const off = loadPolicy(HP4_OFF_PATH);
  assert.equal(computeDecision(reqFor(off, 'fix', { difficultyTier: 'T3' }), off, []).profile, 'cc-haiku-high');
});

test('tiers D5: the required reviewer is walked at review@T1 whatever the unit\'s tier; a T3 unit is reviewed by a review@T1 profile', () => {
  const pol = loadPolicy(TIERED_PATH);
  const build = computeDecision(reqFor(pol, 'build-core'), pol, []);
  assert.deepEqual([build.route, build.profile, build['review-profile'], build['difficulty-tier']], ['delegate', 'cc-opus-high', 'cc-sonnet-xhigh', 'T3']);
  assert.equal(build['review-candidates']['cc-sonnet-xhigh'], null);
  assert.equal(build['review-candidates']['cc-haiku-high'], 'gate 2: cc-haiku-high not qualified for review');
  // on this policy every review entry is bare or @T1, so the walk at review@T1 is the untiered walk, profile for profile
  const off = loadPolicy(HP4_OFF_PATH);
  const untiered = computeDecision(reqFor(off, 'build-core'), off, []);
  assert.deepEqual(build['review-candidates'], untiered['review-candidates']);
});

test('tiers D6: under an enforced policy the DifficultyTier line follows Difficulty, and difficulty-tier is recorded on the decision, the Brief and the ledger decision record; the Brief round-trips through the pre-dispatch recheck', () => {
  const trace = tmp();
  const pol = loadPolicy(TIERED_PATH);
  const r = cli(['decide', writeJson(reqFor(pol, 'fix', { taskId: 'dt-1', difficultyTier: 'T2' })), '--trace', trace, '--policy', TIERED_PATH]);
  assert.equal(r.code, 0, r.stderr);
  assert.match(r.stdout, /^Difficulty: {8}high-or-ambiguous\nDifficultyTier: {4}T2\nRoute: {13}delegate\n/);
  const file = JSON.parse(readFileSync(join(trace, 'decisions', 'dt-1-1.json'), 'utf8'));
  assert.equal(file.decision['difficulty-tier'], 'T2');
  assert.equal(file.brief['difficulty-tier'], 'T2');
  assert.match(r.stdout, /\n {2}"difficulty-tier": "T2"\n/);
  const rec = ledgerLines(trace)[0];
  assert.deepEqual([rec.kind, rec['difficulty-tier'], rec['brief-fingerprint']], ['decision', 'T2', briefFingerprint(file.brief)]);
  // the recheck recomputes the Brief with the field: the decision dispatches as decided
  const disp = cli(['dispatch', 'dt-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW, '--policy', TIERED_PATH]);
  assert.equal(disp.code, 0, disp.stderr);
  assert.match(disp.stdout, /dispatch as decided \(decision seq 1\)/);
  // a blocked decision carries the line and the fields too (no Brief)
  const blocked = decide(reqFor(pol, 'fix', { taskId: 'dt-2' }), { traceDir: trace, policyPath: TIERED_PATH });
  assert.equal(blocked.route, 'blocked');
  assert.match(blocked.text, /^Difficulty: {8}high-or-ambiguous\nDifficultyTier: {4}T3\nRoute: {13}blocked\n/);
  assert.deepEqual([blocked.decision['difficulty-tier'], blocked.record['difficulty-tier'], blocked.brief], ['T3', 'T3', null]);
  // untiered: no line, no field anywhere, a declared tier included
  const off = decide(reqFor(pol, 'fix', { taskId: 'dt-3', difficultyTier: 'T1' }), { traceDir: trace, policyPath: HP4_OFF_PATH });
  assert.equal(off.route, 'delegate');
  assert.doesNotMatch(off.text, /DifficultyTier/);
  assert.equal(JSON.stringify(off.decision).includes('difficulty-tier'), false);
  assert.equal('difficulty-tier' in off.brief, false);
  assert.equal('difficulty-tier' in off.record, false);
  // a decision made untiered does not dispatch under the enforced policy: the recomputed Brief gains the field (the
  // README's pending-decision note), even where the route is unchanged
  const stale = cli(['dispatch', 'dt-3', 'cc-haiku-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW, '--policy', TIERED_PATH]);
  assert.equal(stale.code, 3, stale.stdout);
  assert.match(stale.stderr, /pre-dispatch recheck: the Brief changed since decision seq 1; decide again \(changed: difficulty-tier\)/);
  // and under the policy it was decided by, it dispatches
  assert.equal(cli(['dispatch', 'dt-3', 'cc-haiku-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW, '--policy', HP4_OFF_PATH]).code, 0);
});

// D6: a decision taken under an untiered revision cannot be dispatched under the enforced one (its Brief changes), so
// the ledger must hold no pending decision when revision 5 lands: every task's latest decision is blocked or dispatched
test('tiers D6: the committed ledger at the base commit holds no undispatched decision (every task\'s latest decision is blocked or followed by a dispatch)', () => {
  const records = readLedger(frozenTrace(FREEZE_HP4));
  const tasks = [...new Set(records.map((r) => r['task-id']))];
  assert.equal(tasks.length, 16, 'the sixteen tasks of the base commit');
  for (const t of tasks) {
    const own = records.filter((r) => r['task-id'] === t);
    const last = own.filter((r) => r.kind === 'decision').pop();
    if (!last) continue;
    const blocked = /^route blocked/.test(last.detail);
    const dispatched = own.some((r) => r.kind === 'dispatch' && r.seq > last.seq);
    assert.ok(blocked || dispatched, `${t}: decision seq ${last.seq} (${last.detail}) is pending`);
  }
});

const proposalLine = (p) => `${p.kind === 'demote' ? `demote ${p.profile} from` : `qualify ${p.profile} for`} ${p.category}: ${p.reason}`;
// after every profile's qualified-at (the learning streams count outcomes from it) and before DEADLINE
const LATE = '2026-10-18T02:00:00Z';
// one decide - dispatch - outcome cycle on a policy, at a declared tier (or none); returns the decision
function tieredCycle(trace, policyPath, taskId, category, tier, profile, value, over = {}) {
  const pol = loadPolicy(policyPath);
  const d = decide(reqFor(pol, category, { taskId, now: LATE, ...(tier ? { difficultyTier: tier } : {}), ...over }), { traceDir: trace, policyPath });
  assert.equal(d.decision.profile, profile, `${taskId}: decided ${d.decision.profile}`);
  dispatch(taskId, profile, { projectStop: CLEAR, traceDir: trace, policyPath, now: LATE });
  recordOutcome(outcome({ 'task-id': taskId, outcome: value, 'owner-profile': profile, 'original-brief-fingerprint': d.briefFingerprint }), { traceDir: trace, policyPath, now: LATE });
  return d;
}

test('tiers D7: the learning loop keys its streams by (profile, category, tier): stats keys and proposals read <category>@T<k>; a decision without a tier counts at T1; untiered output is unchanged', () => {
  // two consecutive verification-failed fixes at T2 on cc-opus-high
  const trace = tmp();
  for (const id of ['f-1', 'f-2']) tieredCycle(trace, TIERED_PATH, id, 'fix', 'T2', 'cc-opus-high', 'verification-failed');
  const r = rate({ traceDir: trace, policyPath: TIERED_PATH, now: LATE });
  assert.deepEqual(r.proposals.map(proposalLine), ['demote cc-opus-high from fix@T2: 2 consecutive verification-failed (f-1, f-2)']);
  assert.match(r.text, /^PROPOSAL demote cc-opus-high from fix@T2: 2 consecutive verification-failed \(f-1, f-2\); not applied/m);
  assert.deepEqual(Object.keys(r.stats.stats['cc-opus-high']), ['fix@T2']);
  assert.equal(JSON.parse(readFileSync(join(trace, 'qualification-stats.json'), 'utf8')).stats['cc-opus-high']['fix@T2']['verification-failed'], 2);
  // the next decide names the pending proposal by its tier
  const next = decide(reqFor(loadPolicy(TIERED_PATH), 'fix', { taskId: 'f-3', difficultyTier: 'T2', now: LATE }), { traceDir: trace, policyPath: TIERED_PATH });
  assert.ok(next.decision.uncertainty.includes('pending proposal (not applied): demote cc-opus-high from fix@T2: 2 consecutive verification-failed (f-1, f-2)'), next.decision.uncertainty.join('\n'));
  // the same ledger read by the untiered fixture: no tier anywhere (its decisions carry one, the policy reads none)
  const off = rate({ traceDir: trace, policyPath: HP4_OFF_PATH, now: LATE });
  assert.deepEqual(off.proposals.map(proposalLine), ['demote cc-opus-high from fix: 2 consecutive verification-failed (f-1, f-2)']);
  assert.deepEqual(Object.keys(off.stats.stats['cc-opus-high']), ['fix']);
  assert.doesNotMatch(off.text, /@T/);
  // decisions taken untiered (no difficulty-tier) count at T1 under the enforced policy
  const old = tmp();
  for (const id of ['o-1', 'o-2']) tieredCycle(old, HP4_OFF_PATH, id, 'fix', null, 'cc-haiku-high', 'verification-failed');
  const read = rate({ traceDir: old, policyPath: TIERED_PATH, now: LATE });
  assert.deepEqual(read.proposals.map(proposalLine), ['demote cc-haiku-high from fix@T1: 2 consecutive verification-failed (o-1, o-2)']);
  // a failure at a tier the profile does not hold proposes nothing (it was not qualified there); two at a tier it holds
  // through a higher entry (cc-opus-high holds fix@T2, so fix@T1) demote that tier
  const low = tmp();
  for (const id of ['l-1', 'l-2']) tieredCycle(low, TIERED_PATH, id, 'fix', 'T1', 'cc-opus-high', 'verification-failed', { candidates: ['cc-opus-high', 'cc-sonnet-xhigh'] });
  assert.deepEqual(rate({ traceDir: low, policyPath: TIERED_PATH, now: LATE }).proposals.map(proposalLine), ['demote cc-opus-high from fix@T1: 2 consecutive verification-failed (l-1, l-2)']);
});

test('tiers D7: an outcome counts at the tier of the decision its dispatch was made under, not the task\'s latest one; three accepted outcomes at a tier the profile does not hold propose qualify for <category>@T<k>', () => {
  const trace = tmp();
  const pol = loadPolicy(TIERED_PATH);
  // g-1: a T1 fix fails on cc-haiku-high; the lead raises the tier and the fresh decision routes to cc-opus-high
  tieredCycle(trace, TIERED_PATH, 'g-1', 'fix', 'T1', 'cc-haiku-high', 'verification-failed');
  const failed = outcome({ 'task-id': 'g-1', outcome: 'verification-failed', 'owner-profile': 'cc-haiku-high', 'original-brief-fingerprint': readLedger(trace)[0]['brief-fingerprint'] });
  const raised = decide(reqFor(pol, 'fix', { taskId: 'g-1', difficultyTier: 'T2', previousResult: failed, now: LATE }), { traceDir: trace, policyPath: TIERED_PATH });
  assert.deepEqual([raised.decision.profile, raised.decision['difficulty-tier'], raised.record.seq], ['cc-opus-high', 'T2', 4]);
  dispatch('g-1', 'cc-opus-high', { projectStop: CLEAR, traceDir: trace, policyPath: TIERED_PATH, now: LATE });
  recordOutcome(outcome({ 'task-id': 'g-1', outcome: 'accepted', 'owner-profile': 'cc-opus-high', 'original-brief-fingerprint': raised.briefFingerprint }), { traceDir: trace, policyPath: TIERED_PATH, now: LATE });
  tieredCycle(trace, TIERED_PATH, 'g-2', 'fix', 'T1', 'cc-haiku-high', 'verification-failed');
  const r = rate({ traceDir: trace, policyPath: TIERED_PATH, now: LATE });
  assert.deepEqual(r.proposals.map(proposalLine), ['demote cc-haiku-high from fix@T1: 2 consecutive verification-failed (g-1, g-2)']);
  assert.deepEqual([r.stats.stats['cc-haiku-high']['fix@T1']['verification-failed'], r.stats.stats['cc-opus-high']['fix@T2'].accepted], [2, 1]);
  assert.equal(r.stats.stats['cc-haiku-high']['fix@T2'], undefined, 'g-1\'s first outcome is not counted at the task\'s later tier');
  // three accepted outcomes at T2 on cc-haiku-high (holds fix@T1), recorded by hand as host deviations (dispatch refuses
  // a deviation that fails Gate 2, F3): qualify for fix@T2, the tier they were decided at
  const q = tmp();
  for (const id of ['q-1', 'q-2', 'q-3']) {
    const d = decide(reqFor(pol, 'fix', { taskId: id, difficultyTier: 'T2', now: LATE }), { traceDir: q, policyPath: TIERED_PATH });
    const h = profileOf(pol, 'cc-haiku-high');
    appendFileSync(join(q, 'ledger.jsonl'), `${JSON.stringify({ 'task-id': id, seq: 2, kind: 'dispatch', ts: LATE, profile: `(${h.id}, ${pol.harness.id}, anthropic, ${h.model}, ${h.effort}, ${h.config})`, counters: { 'calls-used': 1, 'calls-limit': 6, 'cash-spent': null, 'cash-cap': null, 'repairs-used': 0, 'repairs-allowed': 1 }, deadline: d.decision.deadline, 'brief-fingerprint': null, detail: 'host deviation: qualification run recorded by hand', 'outcome-ref': null, deviation: true, 'decision-seq': 1 })}\n`);
    recordOutcome(outcome({ 'task-id': id, outcome: 'accepted', 'owner-profile': 'cc-haiku-high', 'original-brief-fingerprint': d.briefFingerprint }), { traceDir: q, policyPath: TIERED_PATH, now: LATE });
  }
  assert.deepEqual(rate({ traceDir: q, policyPath: TIERED_PATH, now: LATE }).proposals.map(proposalLine), ['qualify cc-haiku-high for fix@T2: 3 accepted while unqualified (host deviations: q-1, q-2, q-3)']);
  // a decision file whose difficulty-tier is not a tier is refused (exit 4), never read as T1
  const bad = tmp();
  cpSync(q, bad, { recursive: true });
  const f = join(bad, 'decisions', 'q-1-1.json');
  const j = JSON.parse(readFileSync(f, 'utf8'));
  j.decision['difficulty-tier'] = 'T9';
  writeFileSync(f, JSON.stringify(j));
  assert.throws(() => rate({ traceDir: bad, policyPath: TIERED_PATH, now: LATE }), (e) => e instanceof RouterError && e.code === 4 && /decision file q-1-1\.json: difficulty-tier "T9" is not T1, T2 or T3/.test(e.message));
});

test('tiers D8: rate prints a CALIBRATION line per (category, tier) for an observation task carrying tier T2 or T3; absent or T1 prints as today; any other tier is exit 4', () => {
  const o = CAL3['haiku-high'];
  const run4 = { 'haiku-high': { profile: 'haiku-high', fix: { ...o.fix, tier: 'T3' }, pin: { ...o.pin, tier: 'T1' }, usage: o.usage } };
  const base = rate({ traceDir: calibrationTrace([CAL1, CAL2, CAL3]), policyPath: TIERED_PATH, now: NOW }).text.split('\n').filter((l) => l.startsWith('CALIBRATION '));
  assert.ok(base.every((l) => !/@T/.test(l)), 'runs 1-3 print no tier');
  const r = rate({ traceDir: calibrationTrace([CAL1, CAL2, CAL3, run4]), policyPath: TIERED_PATH, now: NOW });
  const lines = r.text.split('\n').filter((l) => l.startsWith('CALIBRATION '));
  const all = '(calibration-1, calibration-2, calibration-3)';
  assert.ok(lines.includes(`CALIBRATION cc-haiku-high fix: 3 pass, 0 partial, 0 fail ${all}`), lines.join('\n'));
  assert.ok(lines.includes('CALIBRATION cc-haiku-high fix@T3: 1 pass, 0 partial, 0 fail (calibration-4)'), lines.join('\n'));
  assert.ok(lines.includes('CALIBRATION cc-haiku-high pin-tests: 4 pass, 0 partial, 0 fail (calibration-1, calibration-2, calibration-3, calibration-4)'), lines.join('\n'));
  // the tiered line follows its category's untiered one; every other line is the three runs' own
  const i = lines.indexOf(`CALIBRATION cc-haiku-high fix: 3 pass, 0 partial, 0 fail ${all}`);
  assert.equal(lines[i + 1], 'CALIBRATION cc-haiku-high fix@T3: 1 pass, 0 partial, 0 fail (calibration-4)');
  assert.deepEqual(lines.filter((l) => !l.startsWith('CALIBRATION cc-haiku-high ')), base.filter((l) => !l.startsWith('CALIBRATION cc-haiku-high ')));
  assert.deepEqual(r.stats.calibration.profiles['cc-haiku-high']['fix@T3'], { pass: 1, partial: 0, fail: 0, ungraded: 0 });
  assert.deepEqual(r.proposals, [], 'calibration counts never propose');
  // the same under the untiered fixture: D8 reads the observation, not the policy
  const off = rate({ traceDir: calibrationTrace([CAL1, CAL2, CAL3, run4]), policyPath: HP4_OFF_PATH, now: NOW });
  assert.deepEqual(off.text.split('\n').filter((l) => l.startsWith('CALIBRATION ')), lines);
  for (const bad of ['T4', 't3', 3, null]) {
    const trace = calibrationTrace([{ 'haiku-high': { ...run4['haiku-high'], fix: { ...o.fix, tier: bad } } }]);
    assert.throws(() => rate({ traceDir: trace, policyPath: TIERED_PATH, now: NOW }), (e) => e instanceof RouterError && e.code === 4 && e.message.includes(`calibration-1/observations.json: observation "haiku-high" fix tier ${JSON.stringify(bad)} is not T1, T2 or T3; refusing to rate`), JSON.stringify(bad));
    assert.equal(existsSync(join(trace, 'qualification-stats.json')), false);
  }
});

// sr-policy-5 fix round 1, F2: rate splits a tiered calibration observation under any policy (the D8 test pins the
// behaviour on the untiered fixture); the README says so where it claims untiered behaves as before, and in D8
test('README (F2): the observation-tier split of rate applies under any policy, untiered included - said in the tiers opening, the learning-loop paragraph and the D8 bullet', () => {
  const readme = readFileSync(join(HERE, 'README.md'), 'utf8');
  const flat = (a, b) => { const i = readme.indexOf(a); assert.ok(i >= 0, a); return readme.slice(i, readme.indexOf(b, i + 1)).replace(/\s+/g, ' '); };
  assert.ok(flat('## Difficulty tiers (host-policy-5)', '**The tier scale**').includes('Gate 2 per category. One exception: `rate` splits a calibration observation that carries a tier under any policy (D8, below).'), 'the tiers opening');
  assert.ok(flat('**The learning loop and `rate`** (D7, D8).', '**The lead\'s declaration rubric.**').includes('The split applies under any policy, tiered or not: an observation\'s tier is a fact of the cell, not of the policy, so under an untiered policy a tiered observation also prints `<category>@T<k>` and is not counted in the bare line.'), 'the learning-loop paragraph');
  assert.ok(flat('- **D8.**', '- **D9.**').includes('The split applies under any policy, untiered included (D8 is unconditional; D1\'s "exactly as before" holds for every committed observation, none of which carries a tier).'), 'the D8 bullet');
});

// the lead's re-declaration table (briefs/policy5-builder.md): per profile, the tier each production-derived entry is
// re-declared at, and the evidence lines it gains (in addition to the lines it carries); every entry not named stays bare
const HD = 'host-declared (lead), not independent';
const FX_LINE = (c) => `${c}@T3: the lead-direct profile integrates every unit of every tier and fixes inline (U1-R11 d4c4bdb, U2-R15 d37652e); ${HD}; eligible only below direct-max-tokens`;
const FX_CATS = ['build-core', 'build-ui', 'build-tests', 'review', 'fix', 'docs-mechanical', 'research-collect', 'pin-tests'];
const HP5_TABLE = {
  'cc-opus-high': {
    tiers: { 'build-core': 'T3', 'build-ui': 'T3', 'build-tests': 'T3', review: 'T1', fix: 'T2', 'research-collect': 'T2' },
    lines: [
      `build-core@T3: pre-adapter units U1-U5 of github-sign-in (28 builds, RUN.md), multi-file units with new harnesses, would be T3 by the table; ${HD}`,
      'build-ui@T3: accepted outcomes sr-policy-2 seq 3, sr-policy-3 seq 5, sr-policy-4 seq 4 (five files), sr-ci-item4 seq 3 (nine files), would be T3 by the table',
      `build-tests@T3: pre-adapter test units of U1-U5 (RUN.md), new harnesses (fakes, recorders), would be T3 by the table; ${HD}`,
      'review@T1: accepted outcomes sr-host-review seq 3, sr-host-rereview1 seq 3, sr-host-rereview2 seq 3 (one module against gates.md with the shipped tests), would be T1 by the table; calibration-1..3 review PASS',
      'fix@T2: accepted outcomes sr-host-fix1 seq 4, sr-host-fix2 seq 4 (three files, one module, cause named by the findings, existing harness), would be T2 by the table; two passes at T2 (rule 2.3)',
      `research-collect@T2: 26 research runs this session (RUN.md), 20-page budgets with enumerated unknowns, would be T2 by the table (budget over ten pages); ${HD}`
    ]
  },
  'cc-fable-high': {
    tiers: { fix: 'T2', review: 'T1' },
    lines: [
      `fix@T2: U5 fix rounds 3 and 4 (wf_1fcbe585-d1e, wf_7f80ebc5-5a8; src/main/github-signin.ts, its tests and fixtures: three files, cause named by the findings), would be T2 by the table; ${HD}`,
      'review@T1: U5 review and re-review rounds (wf_1fcbe585-d1e) and accepted outcome gsi-u5-rereview4 seq 3 (one module with the shipped tests), would be T1 by the table; calibration-1..3 review PASS'
    ]
  },
  'cc-fable-xhigh': { tiers: Object.fromEntries(FX_CATS.map((c) => [c, 'T3'])), lines: FX_CATS.map(FX_LINE) }
};
const HAIKU_HIGH_LINE = 'fix-x2-1 seq 3 accepted (five files, src/main and tests), would be T3 by the table: one pass at T3, not a qualification (rule 2.3)';

test('host-policy-5 (fixture): the lead\'s table applied - "difficulty-tiers": "enforced", the production-derived entries re-declared at their units\' tier with the evidence lines, calibration-derived entries bare; nothing else changes', () => {
  const raw = JSON.parse(readFileSync(HP5_POLICY_PATH, 'utf8'));
  const hp4 = JSON.parse(readFileSync(HP4_POLICY_PATH, 'utf8'));
  const live = loadPolicy(HP5_POLICY_PATH);
  assert.equal(live['policy-revision'], 'host-policy-5');
  assert.equal(live['difficulty-tiers'], 'enforced');
  // the key sits after the revision; headroom, categories, economics, prices, usage windows, harness, authorization,
  // isolation, accounting, opt-ins: untouched
  const keys = Object.keys(hp4);
  keys.splice(keys.indexOf('policy-revision') + 1, 0, 'difficulty-tiers');
  assert.deepEqual(Object.keys(raw), keys);
  const rest = (p) => Object.fromEntries(Object.entries(p).filter(([k]) => !['policy-revision', 'difficulty-tiers', 'profiles'].includes(k)));
  assert.deepEqual(rest(raw), rest(hp4), 'only the revision, the key and the profiles change');
  assert.deepEqual(raw.profiles.map((p) => p.id), hp4.profiles.map((p) => p.id), 'the fifteen profiles of host-policy-4, in order');
  const fixed = (p) => Object.fromEntries(Object.entries(p).filter(([k]) => !['qualified-for', 'qualified-at', 'evidence'].includes(k)));
  // the one headroom change of this revision: rate's proposal on the accepted sr-policy-5 outcome (1029194 tokens, the
  // unit that built this revision), ratified by the lead at integration under the never-lowered rule; its line closes
  // the profile's evidence
  const RATIFIED = { 'cc-opus-high': { from: 848000, to: 1030000, line: /^sr-policy-5 outcome accepted .*: 1029194 tokens completed \(trace\/outcomes\/sr-policy-5-3\.json\); rate proposed headroom-tested 848000 -> 1030000, ratified by the lead at integration/ } };
  for (const after of raw.profiles) {
    const before = hp4.profiles.find((p) => p.id === after.id);
    const rat = RATIFIED[after.id];
    assert.deepEqual(fixed(after), { ...fixed(before), ...(rat ? { 'headroom-tested': rat.to } : {}) }, `${after.id}: model, effort, config, tools, vision, context, headroom (but the ratified raise), expires, reviewer unchanged`);
    if (rat) {
      assert.equal(before['headroom-tested'], rat.from, `${after.id} headroom before the raise`);
      assert.match(after.evidence.at(-1), rat.line, `${after.id}: the ratification line closes its evidence`);
    }
    const evidence = rat ? after.evidence.slice(0, -1) : after.evidence;
    const want = HP5_TABLE[after.id];
    if (want) {
      assert.deepEqual(after['qualified-for'], before['qualified-for'].map((c) => (want.tiers[c] ? `${c}@${want.tiers[c]}` : c)), `${after.id} qualified-for`);
      for (const c of Object.keys(want.tiers)) assert.ok(before['qualified-for'].includes(c), `${after.id} held ${c} in host-policy-4`);
      assert.deepEqual(evidence, [...before.evidence, ...want.lines], `${after.id} evidence`);
      assert.equal(after['qualified-at'], '2026-10-18', `${after.id} re-declared`);
      assert.equal(after.reviewer, HD, `${after.id} keeps its reviewer line`);
    } else {
      // calibration-derived: bare, read @T1; cc-haiku-high gains the one line of the table and nothing else
      assert.deepEqual(after['qualified-for'], before['qualified-for'], `${after.id} qualified-for`);
      assert.ok(after['qualified-for'].every((c) => !c.includes('@')), `${after.id}: bare entries`);
      assert.equal(after['qualified-at'], before['qualified-at'], after.id);
      assert.deepEqual(evidence, [...before.evidence, ...(after.id === 'cc-haiku-high' ? [HAIKU_HIGH_LINE] : [])], `${after.id} evidence`);
    }
  }
  // pin-tests stays bare on the re-declared profiles that hold it from calibration
  for (const id of ['cc-opus-high', 'cc-fable-high']) assert.ok(raw.profiles.find((p) => p.id === id)['qualified-for'].includes('pin-tests'), id);
  // every production evidence line names the table's tier wording, except the lead-direct profile's (the table gives it whole)
  for (const [id, { lines }] of Object.entries(HP5_TABLE)) {
    for (const l of lines) assert.ok(id === 'cc-fable-xhigh' || /would be T[123] by the table/.test(l), l);
  }
  assert.match(HAIKU_HIGH_LINE, /would be T3 by the table: one pass at T3, not a qualification/);
  // a tiered entry exists only where the table puts one
  const tiered = raw.profiles.flatMap((p) => p['qualified-for'].filter((c) => c.includes('@')).map((c) => `${p.id} ${c}`));
  assert.deepEqual(tiered.sort(), Object.entries(HP5_TABLE).flatMap(([id, { tiers }]) => Object.entries(tiers).map(([c, t]) => `${id} ${c}@${t}`)).sort());
});

const hp5Req = (category, over = {}) => reqFor(loadPolicy(HP5_OFF_PATH), category, over);
const FIX_HOLDERS_T1 = ['cc-fable-medium', 'cc-opus-xhigh', 'cc-opus-medium', 'cc-sonnet-high', 'cc-sonnet-medium', 'cc-sonnet-low', 'cc-haiku-high', 'cc-haiku-medium'];
test('host-policy-5 routing (fixture, deliverable D): fix@T1 -> cc-haiku-high, fix@T2 -> cc-opus-high, undeclared fix (T3) and review (T3) blocked at Gate 2 by tier, review@T1 -> cc-sonnet-xhigh, undeclared build-ui (T2) -> cc-opus-high, docs-mechanical@T3 blocked', () => {
  const live = loadPolicy(HP5_OFF_PATH);
  const decideLive = (category, over) => computeDecision(hp5Req(category, over), live, []);
  // fix 193000 at T1: unchanged from host-policy-4 - cc-haiku-high, with cc-sonnet-xhigh the reviewer (walked at review@T1)
  const t1 = decideLive('fix', { difficultyTier: 'T1' });
  assert.deepEqual([t1.route, t1.profile, t1['review-profile'], t1['difficulty-tier'], t1['all-in-bound-usd']], ['delegate', 'cc-haiku-high', 'cc-sonnet-xhigh', 'T1', 3.1865]);
  assert.deepEqual(t1['eligible-ordered'], ['cc-haiku-high', 'cc-opus-high', 'cc-opus-xhigh', 'cc-fable-high']);
  // fix at T2: the fix@T2 holders only, cc-opus-high the cheaper
  const t2 = decideLive('fix', { difficultyTier: 'T2' });
  assert.deepEqual([t2.route, t2.profile, t2['review-profile'], t2['all-in-bound-usd'], t2['eligible-ordered']], ['delegate', 'cc-opus-high', 'cc-sonnet-xhigh', 6.95, ['cc-opus-high', 'cc-fable-high']]);
  assert.equal(t2.candidates['cc-haiku-high'].reason, 'cc-haiku-high not qualified for fix@T2 (holds fix@T1)');
  assert.equal(t2.candidates['cc-opus-xhigh'].reason, 'cc-opus-xhigh not qualified for fix@T2 (holds fix@T1)');
  // undeclared fix reads T3 (high-risk): blocked; every delegate fails Gate 2 with the tier reason (or holds no fix), the
  // lead-direct profile (fix@T3) passes Gate 2 and fails Gate 5 on direct-max-tokens
  const t3 = decideLive('fix');
  assert.deepEqual([t3.route, t3['difficulty-tier'], t3['eligible-outside-candidates']], ['blocked', 'T3', []]);
  for (const [id, c] of Object.entries(t3.candidates)) {
    if (id === 'cc-fable-xhigh') { assert.deepEqual([c['first-failing-gate'], c.reason], [5, 'direct unsuitable: 193000 tokens > direct-max-tokens 15000']); continue; }
    assert.equal(c['first-failing-gate'], 2, id);
    const held = ['cc-opus-high', 'cc-fable-high'].includes(id) ? 'T2' : FIX_HOLDERS_T1.includes(id) ? 'T1' : null;
    assert.ok(c.reason.startsWith(held ? `${id} not qualified for fix@T3 (holds fix@${held})` : `${id} not qualified for fix`), `${id}: ${c.reason}`);
  }
  // five files declared T1: below the floor (T3), an invalid request
  exit2(() => decideLive('fix', { permittedEffects: FIVE_FILES, difficultyTier: 'T1' }), /^invalid request: difficultyTier T1 is below the floor T3 \(edit set of 5 files, more than three\)/);
  // review 209000 at T1: cc-sonnet-xhigh, as under host-policy-4; undeclared review reads T3: blocked
  const r1 = decideLive('review', { difficultyTier: 'T1' });
  assert.deepEqual([r1.route, r1.profile, r1['all-in-bound-usd']], ['delegate', 'cc-sonnet-xhigh', 3.09]);
  const r3 = decideLive('review');
  assert.deepEqual([r3.route, r3['difficulty-tier']], ['blocked', 'T3']);
  assert.equal(r3.candidates['cc-sonnet-xhigh'].reason, 'cc-sonnet-xhigh not qualified for review@T3 (holds review@T1)');
  assert.equal(r3.candidates['cc-opus-high'].reason, 'cc-opus-high not qualified for review@T3 (holds review@T1)');
  assert.equal(r3.candidates['cc-fable-xhigh'].reason, 'direct unsuitable: 209000 tokens > direct-max-tokens 15000');
  // build-ui 250000 undeclared reads T2 (normal risk): cc-opus-high holds build-ui@T3; the reviewer at review@T1
  const ui = decideLive('build-ui', { estimatedTokens: 250000 });
  assert.deepEqual([ui.route, ui.profile, ui['difficulty-tier'], ui['review-profile'], ui['all-in-bound-usd'], ui['eligible-ordered']], ['delegate', 'cc-opus-high', 'T2', 'cc-sonnet-xhigh', 8.09, ['cc-opus-high']]);
  // docs-mechanical declared T3 (above its T1 floor): accepted as declared; the only docs-mechanical@T3 holder is the
  // lead-direct profile, which takes it only below direct-max-tokens: blocked at the median, direct at 15000
  const dm = decideLive('docs-mechanical', { difficultyTier: 'T3' });
  assert.deepEqual([dm.route, dm['difficulty-tier']], ['blocked', 'T3']);
  assert.equal(dm.candidates['cc-haiku-low'].reason, 'cc-haiku-low not qualified for docs-mechanical@T3 (holds docs-mechanical@T1)');
  assert.equal(dm.candidates['cc-fable-xhigh'].reason, 'direct unsuitable: 92000 tokens > direct-max-tokens 15000');
  const small = decideLive('docs-mechanical', { difficultyTier: 'T3', estimatedTokens: 15000 });
  assert.deepEqual([small.route, small.profile], ['direct', 'cc-fable-xhigh']);
  // the D3 default on the categories whose holders are all bare: undeclared pin-tests and docs-mechanical read T2 and
  // are blocked; declared T1 they route as under host-policy-4
  for (const category of ['pin-tests', 'docs-mechanical']) {
    assert.deepEqual([decideLive(category).route, decideLive(category)['difficulty-tier']], ['blocked', 'T2'], category);
    assert.deepEqual([decideLive(category, { difficultyTier: 'T1' }).route, decideLive(category, { difficultyTier: 'T1' }).profile], ['delegate', 'cc-haiku-low'], category);
  }
  // the CLI on the fixture agrees, and records the revision and the tier
  for (const [category, over, profile, tier] of [['fix', { difficultyTier: 'T1' }, 'cc-haiku-high', 'T1'], ['fix', { difficultyTier: 'T2' }, 'cc-opus-high', 'T2'], ['review', { difficultyTier: 'T1' }, 'cc-sonnet-xhigh', 'T1'], ['build-ui', { estimatedTokens: 250000 }, 'cc-opus-high', 'T2']]) {
    const decided = cliDecide(hp5Req(category, { taskId: `hp5-${category}`, ...over }), HP5_OFF_PATH);
    assert.deepEqual([decided.bindings['policy-revision'], decided.decision.route, decided.decision.profile, decided.decision['difficulty-tier'], decided.brief['difficulty-tier']], ['host-policy-5', 'delegate', profile, tier, tier], category);
  }
});

test('host-policy-5 (fixture): a decision made under revision 5 dispatches - the fixture with a fresh synthetic reading, the recheck accepting the Brief with difficulty-tier; the decision record carries the tier', () => {
  const trace = tmp();
  const at = '2026-10-18T19:00:00Z';
  const r = usageCli(trace, rateLimitInfo(at, { five: 0.2, seven: 0.05 }), at, HP5_POLICY_PATH);
  assert.equal(r.code, 0, r.stderr);
  const request = reqFor(JSON.parse(readFileSync(HP5_POLICY_PATH, 'utf8')), 'build-ui', { taskId: 'hp5-rt', estimatedTokens: 250000, now: at, deadline: '2026-10-19T03:00:00Z' });
  const d = decide(request, { traceDir: trace, policyPath: HP5_POLICY_PATH });
  assert.deepEqual([d.route, d.decision.profile, d.brief['difficulty-tier'], d.record['difficulty-tier'], d.record['usage-tokens']], ['delegate', 'cc-opus-high', 'T2', 'T2', 479000]);
  assert.match(d.text, /\nDifficultyTier: {4}T2\n/);
  const disp = cli(['dispatch', 'hp5-rt', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', '2026-10-18T19:05:00Z', '--policy', HP5_POLICY_PATH]);
  assert.equal(disp.code, 0, disp.stderr);
  assert.equal(ledgerLines(trace).pop()['brief-fingerprint'], d.briefFingerprint);
});

test('rate (host-policy-5 fixture): CALIBRATION lines for runs 1-3 carry no tier; a fix observation with tier T3 prints fix@T3; two consecutive verification-failed fixes at T2 propose demote cc-opus-high from fix@T2', () => {
  const lines = (r) => r.text.split('\n').filter((l) => l.startsWith('CALIBRATION '));
  const committed = rate({ traceDir: frozenTrace(FREEZE_HP4), policyPath: HP5_OFF_PATH, now: NOW });
  assert.ok(lines(committed).length > 0 && lines(committed).every((l) => !/@T/.test(l)), lines(committed).join('\n'));
  assert.deepEqual(lines(committed), lines(rate({ traceDir: frozenTrace(FREEZE_HP4), policyPath: HP4_OFF_PATH, now: NOW })), 'the same lines as under host-policy-4');
  const o = CAL3['opus-high'];
  const run4 = { 'opus-high': { profile: 'opus-high', fix: { ...o.fix, tier: 'T3' }, usage: o.usage } };
  const tiered = lines(rate({ traceDir: calibrationTrace([CAL1, CAL2, CAL3, run4]), policyPath: HP5_OFF_PATH, now: NOW }));
  assert.ok(tiered.includes('CALIBRATION cc-opus-high fix@T3: 1 pass, 0 partial, 0 fail (calibration-4)'), tiered.join('\n'));
  const trace = tmp();
  for (const id of ['d-1', 'd-2']) tieredCycle(trace, HP5_OFF_PATH, id, 'fix', 'T2', 'cc-opus-high', 'verification-failed');
  const r = cli(['rate', '--trace', trace, '--now', LATE, '--policy', HP5_OFF_PATH]);
  assert.equal(r.code, 0, r.stderr);
  assert.ok(r.stdout.split('\n').includes('PROPOSAL demote cc-opus-high from fix@T2: 2 consecutive verification-failed (d-1, d-2); not applied — the lead ratifies by editing host-policy.json'), r.stdout);
  assert.equal(JSON.parse(readFileSync(join(trace, 'qualification-stats.json'), 'utf8')).stats['cc-opus-high']['fix@T2']['verification-failed'], 2);
});

// deliverable E of sr-policy-5: the README's host-policy-5 qualification table is that policy verbatim (P2-2), tiered
// entries included; pinned to the host-policy-5 fixture by sr-policy-6
test('README: the host-policy-5 qualification table matches the host-policy-5 fixture row for row (15 rows), the tiered qualified-for entries in policy order, the three runs\' grades', () => {
  const readme = readFileSync(join(HERE, 'README.md'), 'utf8');
  const hp5 = JSON.parse(readFileSync(HP5_POLICY_PATH, 'utf8'));
  const start = readme.indexOf('### The table (host-policy-5');
  assert.ok(start >= 0, 'the README carries the host-policy-5 table');
  const section = readme.slice(start, readme.indexOf('\n#', start + 1));
  const rows = section.split('\n').filter((l) => /^\| `cc-/.test(l)).map((l) => l.split('|').slice(1, -1).map((c) => c.trim()));
  assert.equal(rows.length, 15);
  assert.deepEqual(rows.map((r) => r[0]), hp5.profiles.map((p) => `\`${p.id}\``), 'one row per profile, in policy order');
  for (const p of hp5.profiles) {
    const [, , qual, headroom, run1, run2, run3] = rows.find((r) => r[0] === `\`${p.id}\``);
    assert.equal(qual, p['qualified-for'].join(', ') || 'none', `${p.id} qualified-for`);
    assert.equal(headroom, `${p['headroom-tested'] / 1000}k`, `${p.id} headroom-tested`);
    const grade = (run, cat) => (p.evidence.find((e) => e.startsWith(`calibration-${run}: ${cat} `)) ?? '').split(' ')[2] ?? '-';
    for (const [run, cell] of [[1, run1], [2, run2], [3, run3]]) {
      assert.equal(cell, ['pin-tests', 'fix', 'review'].map((cat) => grade(run, cat) || '-').join(' / '), `${p.id} calibration-${run} grades`);
    }
  }
});

// deliverable E: the tiers section quotes the proposal's predicate table, states the floor, D5 and D6's pending note,
// carries the re-declaration table and the rubric, and quotes decide's own output for the deliverable-D requests
test('README: Difficulty tiers (host-policy-5 fixture) - the predicate table, the floor, D5, the pending-decision note, the re-declaration table, the rubric, and the routing consequence as decide prints it; rule 5, D1-D9 and friction item 21', () => {
  const readme = readFileSync(join(HERE, 'README.md'), 'utf8');
  const start = readme.indexOf('## Difficulty tiers (host-policy-5)');
  assert.ok(start >= 0, 'the README carries the tiers section');
  const section = readme.slice(start, readme.indexOf('\n## ', start + 1));
  const flat = section.replace(/\s+/g, ' ');
  for (const row of [
    '| `fix`, `build-core`, `build-ui`, `build-tests` | the edit set (`permitted-effects` minus the architecture map) is at most two files in one module; the cause, or the rule, is named in the request; the acceptance checks run on an existing harness | the edit set spans more than three files or more than one seam; the cause is unknown; the acceptance checks need a new harness; the edit set includes the code that handles credentials, persistence, concurrency or an external service (the data class alone does not trigger it); `uncertainty` is `high` |',
    '| `pin-tests` | one rule, one existing harness, one test file | the rule spans two modules, or the harness does not exist (a fake, a recorder, a process boundary) |',
    '| `review` | one module against its own specification section, with the shipped tests as the harness for reproductions | two or more modules and their seam, where a finding can exist only in the interaction; or no shipped harness for reproductions; or the specification is incomplete and the review must say what it would have to say |',
    '| `research-collect` | the unknowns are enumerated and each names its owning page; the budget is under ten pages | an unknown with no known owning page; a contradiction between primary sources to resolve; a budget over thirty pages |',
    '| `docs-mechanical` | always T1 | never |'
  ]) assert.ok(section.includes(`\n${row}\n`), `README lacks the predicate row\n${row}`);
  for (const sentence of [
    'The floor: `T3` when `uncertainty` is `"high"` or the edit set has more than three entries; `T2` when it has exactly three; `T1` otherwise; `docs-mechanical` is always `T1`.',
    'The edit set is `permittedEffects` without the entries ending in `ARCHITECTURE.md`.',
    'Under an enforced policy that walk requires `review@T1`, whatever the unit\'s tier: the review of a unit is its own request when the lead dispatches it, with its own declared tier.',
    'A decision taken under an untiered revision cannot be dispatched under an enforced one:',
    '`dispatch` refuses with `the Brief changed since decision seq N; decide again (changed: difficulty-tier)`'
  ]) assert.ok(flat.includes(sentence), `README lacks: ${sentence}`);
  // the re-declaration table: every evidence line the policy gained, verbatim
  for (const line of [...Object.values(HP5_TABLE).flatMap((t) => t.lines), HAIKU_HIGH_LINE]) {
    if (/^[a-z-]+@T3: the lead-direct profile/.test(line)) continue;   // the eight cc-fable-xhigh lines are one row
    assert.ok(flat.includes(line), `README lacks the evidence line ${line}`);
  }
  assert.ok(flat.includes(FX_LINE('<category>')), 'the cc-fable-xhigh row');
  // the rubric: one line per category
  for (const cat of ['`fix`, `build-core`, `build-ui`, `build-tests`:', '`pin-tests`:', '`review`:', '`research-collect`:', '`docs-mechanical`:']) {
    assert.ok(section.includes(`\n- ${cat}`), `the rubric lacks ${cat}`);
  }
  // the routing consequence: decide's own lines on host-policy-5 (its fixture's feature-off derivative since
  // sr-policy-6), model elided
  const live = loadPolicy(HP5_OFF_PATH);
  const quoted = [
    ['fix', { difficultyTier: 'T1' }, false], ['fix', { difficultyTier: 'T2' }, true], ['fix', {}, true],
    ['review', { difficultyTier: 'T1' }, false], ['review', {}, false], ['build-ui', { estimatedTokens: 250000 }, false], ['docs-mechanical', { difficultyTier: 'T3' }, false]
  ];
  for (const [i, [category, over, walked]] of quoted.entries()) {
    const trace = tmp();
    const r = cli(['decide', writeJson(hp5Req(category, { taskId: `readme5-${i}`, ...over })), '--trace', trace, '--policy', HP5_OFF_PATH]);
    assert.equal(r.code, 0, r.stderr);
    const out = r.stdout.split('\n');
    const pick = (k) => out.find((l) => l.startsWith(`${k}:`));
    const profile = pick('Profile');
    const pr = live.profiles.find((p) => profile.includes(`(${p.id},`));
    const head = [pick('Difficulty'), pick('DifficultyTier'), pick('Route'), pr ? profile.replace(pr.model, '<model>') : profile, pick('Reservations')].join('\n');
    assert.ok(section.includes(`\n${head}\n`), `${category} ${JSON.stringify(over)}: README lacks\n${head}`);
    if (walked) {
      const walk = out.slice(out.findIndex((l) => l.startsWith('Gate walk')), out.findIndex((l, j) => j > 0 && (l.startsWith('Brief') || l === '')));
      assert.equal(walk.length, 1 + live.profiles.length, `${category} walk`);
      assert.ok(section.includes(`\n${walk.join('\n')}\n`), `${category} ${JSON.stringify(over)}: README lacks the gate walk`);
    }
  }
  const refused = cli(['decide', writeJson(hp5Req('fix', { taskId: 'readme5-x', permittedEffects: FIVE_FILES, difficultyTier: 'T1' })), '--trace', tmp(), '--policy', HP5_OFF_PATH]);
  assert.equal(refused.code, 2);
  assert.ok(section.includes(`\n${refused.stderr.trim()}\n`), `README lacks the floor refusal\n${refused.stderr}`);
  // Qualification rules gain rule 5 (proposal 2.3-2.5, quoted)
  const rules = readme.slice(readme.indexOf('### Qualification rules'), readme.indexOf('\n### ', readme.indexOf('### Qualification rules') + 1)).replace(/\n\s*>\s?/g, ' ').replace(/\s+/g, ' ');   // a blockquote's markers are not text
  for (const quote of [
    '5. **Per (category, tier)**',
    'The two-pass rule applies per (category, tier): a high-risk category needs two independent passes **at that tier** (calibration cells of that tier, or an accepted production outcome whose request carried that tier).',
    'A calibration FAIL or a `verification-failed` outcome at tier k is a fail for tier k and every higher tier of the category, and blocks them until two later passes at that tier; lower tiers keep their standing.',
    'The return path after a block is **calibration, never production**:'
  ]) assert.ok(rules.includes(quote), `rule 5 lacks: ${quote}`);
  // the lead's decisions, named
  const applied = readme.slice(readme.indexOf('### How the tiers proposal was applied (host-policy-5)'));
  assert.ok(readme.includes('### How the tiers proposal was applied (host-policy-5)'));
  for (const d of ['D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7', 'D8', 'D9']) assert.match(applied.slice(0, applied.indexOf('\n### ', 5)), new RegExp(`\\n- \\*\\*${d}\\.?\\*\\*`), d);
  const friction = readme.slice(readme.indexOf('## Friction log for SmartRouter upstream'));
  assert.match(friction, /\n21\. \*\*The proposal's Item 3 "names it" clause is the existing `eligible-outside-candidates` hint, and the reviewer-tier question \(D5\) is not addressed by the proposal\.\*\*/);
});

// sr-policy-5 fix round 1, F1: the proposal's own status clause and pending review row, and the basis on which this
// host enforces it anyway, are on record in the README (tiers section, policy finding 7, friction item 22)
const TIERS_STATUS = 'Status: **draft proposal, not normative; revision 2 after the independent review of 2026-10-18 (Request Changes on 987a4e3).** Nothing in `skills/` is amended by this document. If accepted after independent review (plan §15), the items below would become one additional Gate 2 rule, an additive host-policy qualification form, additive §9/§10 fields under the §13 "additive unknown fields remain ignorable" rule, and one calibration-protocol change for the host under `hosts/claude-code/`; until then hosts MUST NOT emit or require them.';
const TIERS_REVIEW_ROW = '| 1-5 (revision 2) | pending delta review | — | — |';
test('README (F1): the proposal\'s status clause ("not normative ... hosts MUST NOT emit or require them") and its pending delta-review row are quoted, with the basis for enforcing anyway, in the tiers section, policy finding 7 and friction item 22', () => {
  const readme = readFileSync(join(HERE, 'README.md'), 'utf8');
  const unquote = (s) => s.replace(/\n\s*>\s?/g, ' ').replace(/\s+/g, ' ');   // a blockquote's markers are not text
  const tiers = unquote(readme.slice(readme.indexOf('## Difficulty tiers (host-policy-5)'), readme.indexOf('**The tier scale**')));
  for (const s of ['not normative', 'MUST NOT emit or require', 'pending delta review', 'policy finding 7', 'friction item 22']) {
    assert.ok(tiers.includes(s), `the tiers section's opening lacks: ${s}`);
  }
  const fStart = readme.indexOf('## Policy findings (host-policy-5)');
  const findings = readme.slice(fStart, readme.indexOf('\n## ', fStart + 1));
  const f7 = findings.slice(findings.indexOf('\n7. **'));
  assert.ok(f7.startsWith('\n7. **The proposal says hosts MUST NOT emit or require its fields until a delta review accepts it; host-policy-5 emits and requires them.**'), 'policy finding 7');
  const f7flat = unquote(f7);
  for (const s of [TIERS_STATUS, '`' + TIERS_REVIEW_ROW + '`', 'PR #100', '`2e30291`', '`7f7fc75`', '`b8e1a1d`', 'D1-D9', 'without the delta review', '"difficulty-tiers": "enforced"']) {
    assert.ok(f7flat.includes(s), `policy finding 7 lacks: ${s}`);
  }
  const friction = readme.slice(readme.indexOf('## Friction log for SmartRouter upstream'));
  const f22 = friction.slice(friction.indexOf('\n22. **'));
  assert.ok(f22.startsWith('\n22. **A merged proposal still says hosts MUST NOT emit or require its fields.**'), 'friction item 22');
  const f22flat = unquote(f22);
  for (const s of ['until then hosts MUST NOT emit or require them', '`' + TIERS_REVIEW_ROW + '`', 'PR #100', 'policy finding 7']) {
    assert.ok(f22flat.includes(s), `friction item 22 lacks: ${s}`);
  }
});

// ---------------------------------------------------------------------------------------------
// host-policy-6 (unit sr-policy-6): calibration-first evidence (SmartRouter docs/proposals/calibration-first-onboarding.md,
// merged as PR #102) under the lead's decisions E1-E7 (briefs/policy6-builder.md); the host-policy-5 assertions above stay
// on the host-policy-5 fixture
// ---------------------------------------------------------------------------------------------
test('fixture: trace/policies/host-policy-5.json is the pre-revision policy, byte-identical to the policy the sr-policy-6 decisions were bound to', () => {
  assert.ok(existsSync(HP5_POLICY_PATH), 'the host-policy-5 fixture exists');
  const digest = createHash('sha256').update(readFileSync(HP5_POLICY_PATH)).digest('hex');
  for (const seq of [1, 2]) {
    const bound = JSON.parse(readFileSync(join(goldenDir, `sr-policy-6-${seq}.json`), 'utf8')).bindings;
    assert.equal(bound['policy-revision'], 'host-policy-5', `sr-policy-6-${seq}`);
    assert.equal(digest, bound['policy-sha256'], `sr-policy-6-${seq}`);
  }
  assert.equal(loadPolicy(HP5_POLICY_PATH)['policy-revision'], 'host-policy-5');
  assert.equal(JSON.parse(readFileSync(HP5_POLICY_PATH, 'utf8')).request, undefined, 'a policy, never a decision');
});

// E1: an outcome store of real decide - dispatch - outcome cycles (decisions, outcomes, ledger under trace/) and the
// policies written beside it, so a reference's path 'trace/outcomes/<task>-<seq>.json' resolves against the policy
// file's directory. ref-t2: a fix decided at T2 (host-policy-5, enforced), accepted; ref-fail: the same, verification-
// failed; ref-pre: a fix decided under the untiered host-policy-4 (no difficulty-tier), accepted. All at LATE (2026-10-18)
const REF_STORE = tmp();
const REF_TRACE = join(REF_STORE, 'trace');
let refStoreBuilt = false;
function refStore() {
  if (refStoreBuilt) return;
  tieredCycle(REF_TRACE, HP5_OFF_PATH, 'ref-t2', 'fix', 'T2', 'cc-opus-high', 'accepted');
  tieredCycle(REF_TRACE, HP5_OFF_PATH, 'ref-fail', 'fix', 'T2', 'cc-opus-high', 'verification-failed');
  tieredCycle(REF_TRACE, HP4_OFF_PATH, 'ref-pre', 'fix', null, 'cc-haiku-high', 'accepted');
  refStoreBuilt = true;
}
let refN = 0;
// the host-policy-5 fixture's feature-off derivative, mutated, written into `dir` (default: beside the store)
function refPolicy(mutate, dir = REF_STORE) {
  refStore();
  const p = JSON.parse(readFileSync(HP5_OFF_PATH, 'utf8'));
  mutate(p);
  refN += 1;
  const path = join(dir, `host-policy-ref-${refN}.json`);
  writeFileSync(path, JSON.stringify(p, null, 2));
  return path;
}
const withLine = (id, line, dir) => refPolicy((p) => { profileOf(p, id).evidence.push(line); }, dir);
const REF_T2 = 'outcome: ref-t2 fix@T2 accepted 2026-10-18 (trace/outcomes/ref-t2-3.json)';
const REF_FORM = "is not 'outcome: <task-id> <category>[@T<k>] accepted <YYYY-MM-DD> (<path>)'";

test('E1: a typed production reference loads when it resolves against the store beside the policy file - an accepted Outcome of that task and profile, recorded that day, decided in that category at that tier; a pre-tier decision takes any tier with the "would be" wording', () => {
  assert.equal(loadPolicy(withLine('cc-opus-high', REF_T2))['policy-revision'], 'host-policy-5');
  // the store as the adapter wrote it: no tier on ref-pre's decision, T2 on ref-t2's; the outcome files carry no ts, so
  // the recorded time is the outcome record's
  const decisions = (t) => JSON.parse(readFileSync(join(REF_TRACE, 'decisions', `${t}-1.json`), 'utf8')).decision['difficulty-tier'];
  assert.deepEqual([decisions('ref-t2'), decisions('ref-pre')], ['T2', undefined]);
  assert.equal(JSON.parse(readFileSync(join(REF_TRACE, 'outcomes', 'ref-t2-3.json'), 'utf8')).ts, undefined);
  for (const line of [
    'outcome: ref-pre fix@T3 accepted 2026-10-18 (trace/outcomes/ref-pre-3.json); would be T3 by the table: one pass at T3, not a qualification',
    'outcome: ref-pre fix@T1 accepted 2026-10-18 (trace/outcomes/ref-pre-3.json); would be T1 by the table',
    'outcome: ref-pre fix accepted 2026-10-18 (trace/outcomes/ref-pre-3.json)'
  ]) assert.equal(loadPolicy(withLine('cc-haiku-high', line))['policy-revision'], 'host-policy-5', line);
  // a reference under a policy that is untiered loads too (the tier is the host's declaration, checked against the decision)
  assert.ok(loadPolicy(refPolicy((p) => { delete p['difficulty-tiers']; profileOf(p, 'cc-opus-high').evidence.push(REF_T2); })));
  // free text that mentions an outcome is prose, never parsed (E4): only a line that starts 'outcome: ' is typed
  assert.ok(loadPolicy(withLine('cc-opus-high', 'ref-t2 outcome accepted 2026-10-18: anything at all')));
  // the fixtures host-policy-1..5 carry no typed reference and load unchanged
  for (const n of [1, 2, 3, 4, 5]) {
    const path = join(HERE, 'trace', 'policies', `host-policy-${n}.json`);
    const raw = JSON.parse(readFileSync(path, 'utf8'));
    assert.ok(raw.profiles.every((p) => (p.evidence ?? []).every((e) => !e.startsWith('outcome:'))), `host-policy-${n}`);
    assert.equal(loadPolicy(path)['policy-revision'], `host-policy-${n}`);
  }
});

test('E1: a reference\'s form is checked from the policy alone (exit 2): the literal "accepted", a known category, a calendar day, a relative path naming outcomes/<task-id>-<seq>.json', () => {
  const formOnly = tmp();   // no store here: a form refusal never reaches resolution
  for (const line of [
    'outcome: ref-t2 fix@T2 verification-failed 2026-10-18 (trace/outcomes/ref-t2-3.json)',
    'outcome: ref-t2 fix@T4 accepted 2026-10-18 (trace/outcomes/ref-t2-3.json)',
    'outcome: ref-t2 fix@T2 accepted 2026-10-18T02:00:00Z (trace/outcomes/ref-t2-3.json)',
    'outcome: ref-t2 fix@T2 accepted 2026-10-18',
    'outcome: ref-t2 fix@T2 accepted 2026-10-18 (trace/outcomes/ref-t2-3.json) trailing',
    'outcome:ref-t2 fix@T2 accepted 2026-10-18 (trace/outcomes/ref-t2-3.json)'
  ]) exit2(() => loadPolicy(withLine('cc-opus-high', line, formOnly)), new RegExp(`^invalid policy: profile cc-opus-high evidence '${esc(line)}' ${esc(REF_FORM)}$`));
  const named = (line, why) => exit2(() => loadPolicy(withLine('cc-opus-high', line, formOnly)), new RegExp(`^invalid policy: profile cc-opus-high evidence '${esc(line)}' ${why}$`));
  named('outcome: ref-t2 astrology accepted 2026-10-18 (trace/outcomes/ref-t2-3.json)', "names unknown category 'astrology'");
  named('outcome: ref-t2 fix@T2 accepted 2026-02-30 (trace/outcomes/ref-t2-3.json)', 'date 2026-02-30 is not a calendar day');
  for (const path of ['/abs/trace/outcomes/ref-t2-3.json', 'C:/trace/outcomes/ref-t2-3.json', 'trace/outcomes/ref-x-3.json', 'trace/ref-t2-3.json', 'trace/outcomes/ref-t2.json', 'trace\\outcomes\\ref-t2-3.json']) {
    named(`outcome: ref-t2 fix@T2 accepted 2026-10-18 (${path})`, esc(`path ${path} must be relative to the policy file's directory and name the outcome file outcomes/ref-t2-<seq>.json`));
  }
});

test('E1: an unresolvable reference is an invalid policy (exit 2, naming the profile and the entry): a wrong category, a non-accepted outcome, a missing file, a tier other than its tiered decision\'s, a pre-tier decision without the "would be" wording, a wrong date, another profile\'s or another task\'s outcome, a file that is not an Outcome', () => {
  refStore();
  const cannot = (id, line, why) => exit2(() => loadPolicy(withLine(id, line)), new RegExp(`^invalid policy: profile ${id} evidence '${esc(line)}' cannot be resolved: ${why}$`));
  cannot('cc-opus-high', 'outcome: ref-t2 review@T2 accepted 2026-10-18 (trace/outcomes/ref-t2-3.json)', esc('ref-t2 was decided as fix, not review'));
  cannot('cc-opus-high', 'outcome: ref-fail fix@T2 accepted 2026-10-18 (trace/outcomes/ref-fail-3.json)', esc('trace/outcomes/ref-fail-3.json records outcome verification-failed, not accepted'));
  cannot('cc-opus-high', 'outcome: ref-t2 fix@T2 accepted 2026-10-18 (trace/outcomes/ref-t2-9.json)', `${esc('trace/outcomes/ref-t2-9.json does not exist (resolved against the policy file\'s directory ')}.+\\)`);
  cannot('cc-opus-high', 'outcome: ref-t2 fix@T3 accepted 2026-10-18 (trace/outcomes/ref-t2-3.json)', esc('ref-t2 was decided at T2, not T3'));
  cannot('cc-opus-high', 'outcome: ref-t2 fix@T1 accepted 2026-10-18 (trace/outcomes/ref-t2-3.json); would be T1 by the table', esc('ref-t2 was decided at T2, not T1'));
  cannot('cc-opus-high', 'outcome: ref-t2 fix accepted 2026-10-18 (trace/outcomes/ref-t2-3.json)', esc('ref-t2 was decided at T2, not T1'));
  for (const note of ['', '; five files', '; would be T2 by the table']) {
    cannot('cc-haiku-high', `outcome: ref-pre fix@T3 accepted 2026-10-18 (trace/outcomes/ref-pre-3.json)${note}`, esc('the decision of ref-pre carries no difficulty tier, so the line must say \'would be T3 by the table\''));
  }
  cannot('cc-opus-high', 'outcome: ref-t2 fix@T2 accepted 2026-10-17 (trace/outcomes/ref-t2-3.json)', esc('trace/outcomes/ref-t2-3.json was recorded 2026-10-18T02:00:00Z, not on 2026-10-17'));
  cannot('cc-haiku-high', 'outcome: ref-t2 fix@T2 accepted 2026-10-18 (trace/outcomes/ref-t2-3.json)', esc('trace/outcomes/ref-t2-3.json is an outcome of cc-opus-high, not cc-haiku-high'));
  // another task's Outcome under this task's name, and a file that is not an Outcome (written into the temp store only)
  writeFileSync(join(REF_TRACE, 'outcomes', 'ref-x-3.json'), readFileSync(join(REF_TRACE, 'outcomes', 'ref-t2-3.json')));
  cannot('cc-opus-high', 'outcome: ref-x fix@T2 accepted 2026-10-18 (trace/outcomes/ref-x-3.json)', esc('trace/outcomes/ref-x-3.json is the outcome of ref-t2, not ref-x'));
  writeFileSync(join(REF_TRACE, 'outcomes', 'ref-y-3.json'), readFileSync(join(REF_TRACE, 'decisions', 'ref-t2-1.json')));
  cannot('cc-opus-high', 'outcome: ref-y fix@T2 accepted 2026-10-18 (trace/outcomes/ref-y-3.json)', `${esc('trace/outcomes/ref-y-3.json is not an Outcome (invalid Outcome (spec-v2 §10.3): ')}.+\\)`);
  writeFileSync(join(REF_TRACE, 'outcomes', 'ref-z-3.json'), '{ not json');
  cannot('cc-opus-high', 'outcome: ref-z fix@T2 accepted 2026-10-18 (trace/outcomes/ref-z-3.json)', esc('trace/outcomes/ref-z-3.json is not JSON'));
  // an accepted Outcome with no outcome record behind it and no ts of its own has no recorded time; with no decision
  // file, no category
  const orphan = { ...JSON.parse(readFileSync(join(REF_TRACE, 'outcomes', 'ref-t2-3.json'), 'utf8')), 'task-id': 'ref-o' };
  writeFileSync(join(REF_TRACE, 'outcomes', 'ref-o-3.json'), JSON.stringify(orphan));
  cannot('cc-opus-high', 'outcome: ref-o fix@T2 accepted 2026-10-18 (trace/outcomes/ref-o-3.json)', `${esc('trace/outcomes/ref-o-3.json has no recorded time (no ts in the Outcome, no outcome record ref-o seq 3 in ')}.+${esc('ledger.jsonl)')}`);
  writeFileSync(join(REF_TRACE, 'outcomes', 'ref-o-3.json'), JSON.stringify({ ...orphan, ts: '2026-10-18T03:00:00Z' }));
  cannot('cc-opus-high', 'outcome: ref-o fix@T2 accepted 2026-10-18 (trace/outcomes/ref-o-3.json)', `${esc('no decision file for ref-o in ')}.+decisions`);
  for (const f of ['ref-x-3.json', 'ref-y-3.json', 'ref-z-3.json', 'ref-o-3.json']) rmSync(join(REF_TRACE, 'outcomes', f));
});

test('E1: references resolve against the policy file\'s directory, never against --trace: the same policy elsewhere is refused even with --trace naming the store; beside its store it decides with any --trace', () => {
  const away = withLine('cc-opus-high', REF_T2, tmp());
  exit2(() => loadPolicy(away), /cannot be resolved: trace\/outcomes\/ref-t2-3\.json does not exist \(resolved against the policy file's directory /);
  const request = (taskId) => writeJson(hp5Req('fix', { taskId, difficultyTier: 'T1' }));
  const refusedCli = cli(['decide', request('away-1'), '--trace', REF_TRACE, '--policy', away]);
  assert.equal(refusedCli.code, 2, refusedCli.stderr);
  assert.match(refusedCli.stderr, /^route\.mjs: invalid policy: profile cc-opus-high evidence 'outcome: ref-t2 fix@T2 accepted 2026-10-18 \(trace\/outcomes\/ref-t2-3\.json\)' cannot be resolved: /);
  const ok = cli(['decide', request('here-1'), '--trace', tmp(), '--policy', withLine('cc-opus-high', REF_T2)]);
  assert.equal(ok.code, 0, ok.stderr);
});

// lead's integration fix of sr-policy-6 (the builder's second note): a fixture copy of a typed policy under
// <root>/trace/policies/ (where every revision's goldens are pinned) resolves its references against <root>, the
// directory that holds that trace, so revision 7 can pin the revision-6 assertions to trace/policies/host-policy-6.json;
// the same copy anywhere else still resolves against its own directory and is refused
test('E1 (fixture root): a typed policy placed at <root>/trace/policies/<name>.json resolves its references against <root>; placed elsewhere under <root> it does not', () => {
  const root = tmp();
  cpSync(join(HERE, 'trace'), join(root, 'trace'), { recursive: true });
  mkdirSync(join(root, 'trace', 'policies'), { recursive: true });
  const fixture = join(root, 'trace', 'policies', 'host-policy-6.json');
  cpSync(COMMITTED_POLICY_PATH, fixture);
  const p = loadPolicy(fixture);
  assert.equal(p['policy-revision'], 'host-policy-6');
  assert.equal(p.evidence, 'typed');
  const elsewhere = join(root, 'elsewhere', 'host-policy-6.json');
  mkdirSync(dirname(elsewhere), { recursive: true });
  cpSync(COMMITTED_POLICY_PATH, elsewhere);
  exit2(() => loadPolicy(elsewhere), /cannot be resolved: trace\/outcomes\/.* does not exist \(resolved against the policy file's directory /);
  // the rule is the two directory names, not any 'policies' folder: <root>/policies/<name>.json resolves against itself
  const flat = join(root, 'policies', 'host-policy-6.json');
  mkdirSync(dirname(flat), { recursive: true });
  cpSync(COMMITTED_POLICY_PATH, flat);
  exit2(() => loadPolicy(flat), /cannot be resolved: trace\/outcomes\/.* does not exist/);
});

// sr-policy-6 fix round 1, F1: a reference's path cannot leave the policy file's directory - not by '..' (either
// spelling) and not through a symlink - so a store that is never committed with the policy (a temp trace) cannot back
// a qualification; and rate prints no paste line for an outcome store outside the policy file's directory
test('E1 (F1): a reference whose path leaves the policy file\'s directory is refused (exit 2) - \'../<dir>/trace/...\', \'trace/../../<dir>/trace/...\' and a symlinked trace/ - while a \'..\' that stays inside resolves', () => {
  refStore();
  const root = tmp();
  const pol = join(root, 'pol');
  mkdirSync(pol);
  cpSync(REF_TRACE, join(root, 'elsewhere', 'trace'), { recursive: true });
  const leaves = (line, path) => exit2(() => loadPolicy(withLine('cc-opus-high', line, pol)), new RegExp(`^invalid policy: profile cc-opus-high evidence '${esc(line)}' cannot be resolved: ${esc(`${path} leaves the policy file's directory ${pol}: a reference names an outcome file under it`)}$`));
  // by its spelling, whether or not the file is there
  for (const path of ['../elsewhere/trace/outcomes/ref-t2-3.json', 'trace/../../elsewhere/trace/outcomes/ref-t2-3.json', '../nowhere/trace/outcomes/ref-t2-3.json']) {
    leaves(`outcome: ref-t2 fix@T2 accepted 2026-10-18 (${path})`, path);
  }
  // the absolute spelling of the same file stays a form refusal
  exit2(() => loadPolicy(withLine('cc-opus-high', `outcome: ref-t2 fix@T2 accepted 2026-10-18 (${join(root, 'elsewhere', 'trace', 'outcomes', 'ref-t2-3.json')})`, pol)), /must be relative to the policy file's directory/);
  // a trace/ beside the policy that is a symlink to the store elsewhere leaves it too
  symlinkSync(join(root, 'elsewhere', 'trace'), join(pol, 'trace'), 'dir');
  leaves(REF_T2, 'trace/outcomes/ref-t2-3.json');
  // a '..' that stays inside the directory is only a spelling: it resolves
  assert.equal(loadPolicy(withLine('cc-opus-high', 'outcome: ref-t2 fix@T2 accepted 2026-10-18 (trace/../trace/outcomes/ref-t2-3.json)'))['policy-revision'], 'host-policy-5');
});

test('E7 (F1): rate prints no typed evidence to paste when the outcome store (--trace) is outside the policy file\'s directory, and says why; the stats file carries no references', () => {
  const root = tmp();
  const policyPath = join(root, 'pol', 'host-policy.json');
  mkdirSync(dirname(policyPath));
  writeFileSync(policyPath, readFileSync(TIERED_PATH));
  const q = join(root, 'forge', 'trace');
  const pol = loadPolicy(policyPath);
  const h = profileOf(pol, 'cc-haiku-high');
  for (const id of ['q-1', 'q-2', 'q-3']) {
    const d = decide(reqFor(pol, 'fix', { taskId: id, difficultyTier: 'T2', now: LATE }), { traceDir: q, policyPath });
    appendFileSync(join(q, 'ledger.jsonl'), `${JSON.stringify({ 'task-id': id, seq: 2, kind: 'dispatch', ts: LATE, profile: `(${h.id}, ${pol.harness.id}, anthropic, ${h.model}, ${h.effort}, ${h.config})`, counters: { 'calls-used': 1, 'calls-limit': 6, 'cash-spent': null, 'cash-cap': null, 'repairs-used': 0, 'repairs-allowed': 1 }, deadline: d.decision.deadline, 'brief-fingerprint': null, detail: 'host deviation: qualification run recorded by hand', 'outcome-ref': null, deviation: true, 'decision-seq': 1 })}\n`);
    recordOutcome(outcome({ 'task-id': id, outcome: 'accepted', 'owner-profile': 'cc-haiku-high', 'original-brief-fingerprint': d.briefFingerprint }), { traceDir: q, policyPath, now: LATE });
  }
  const r = cli(['rate', '--trace', q, '--now', LATE, '--policy', policyPath]);
  assert.equal(r.code, 0, r.stderr);
  const want = `PROPOSAL qualify cc-haiku-high for fix@T2: 3 accepted while unqualified (host deviations: q-1, q-2, q-3); not applied — the lead ratifies by editing host-policy.json; no typed evidence to paste: the outcome store ${q} is outside the policy file's directory ${dirname(policyPath)}, and a reference cannot leave it (E1)`;
  assert.ok(r.stdout.split('\n').includes(want), r.stdout);
  assert.doesNotMatch(r.stdout, /\.\.\/forge/);
  const doc = JSON.parse(readFileSync(join(q, 'qualification-stats.json'), 'utf8'));
  assert.deepEqual(doc.proposals.map((p) => [p.kind, p.category, p.references]), [['qualify', 'fix@T2', undefined]]);
});

// sr-policy-6 fix round 1, F2: one outcome per dispatch (spec-v2 §10.5, decision-trace.md §4, latestOutcomes): a
// reference to an outcome record that a later record for the same dispatch supersedes is refused, as rate counts it
test('E1 (F2): a reference to an accepted outcome that a later outcome record for the same dispatch supersedes is refused (exit 2) naming the superseding record; the latest resolves', () => {
  refStore();
  // a copy of REF_STORE (the shared store stays as the other tests read it), with ref-t2's Outcome recorded again
  const dir = tmp();
  cpSync(REF_TRACE, join(dir, 'trace'), { recursive: true });
  const trace = join(dir, 'trace');
  const first = JSON.parse(readFileSync(join(trace, 'outcomes', 'ref-t2-3.json'), 'utf8'));
  const again = (value) => recordOutcome({ ...first, outcome: value }, { traceDir: trace, policyPath: HP5_OFF_PATH, now: LATE });
  const counted = () => {
    const c = rate({ traceDir: trace, policyPath: HP5_OFF_PATH, now: LATE }).stats.stats['cc-opus-high']['fix@T2'];
    return [c.accepted, c['verification-failed']];
  };
  assert.deepEqual(counted(), [1, 1], 'ref-t2 accepted, ref-fail verification-failed');
  assert.equal(again('verification-failed').detail, 'outcome verification-failed (dispatch seq 2)');
  const cannot = (line, why) => exit2(() => loadPolicy(withLine('cc-opus-high', line, dir)), new RegExp(`^invalid policy: profile cc-opus-high evidence '${esc(line)}' cannot be resolved: ${esc(why)}$`));
  cannot(REF_T2, 'trace/outcomes/ref-t2-3.json is superseded by outcome record ref-t2 seq 4 (verification-failed) for the same dispatch (seq 2)');
  // rate on the same store counts ref-t2's dispatch once, now as verification-failed: the resolver and the learning loop agree
  assert.deepEqual(counted(), [0, 2], 'ref-t2 and ref-fail both verification-failed');
  // accepted again: the latest record resolves; the first is superseded by it, whatever its value
  again('accepted');
  assert.ok(loadPolicy(withLine('cc-opus-high', 'outcome: ref-t2 fix@T2 accepted 2026-10-18 (trace/outcomes/ref-t2-5.json)', dir)));
  cannot(REF_T2, 'trace/outcomes/ref-t2-3.json is superseded by outcome record ref-t2 seq 5 (accepted) for the same dispatch (seq 2)');
  cannot('outcome: ref-t2 fix@T2 accepted 2026-10-18 (trace/outcomes/ref-t2-4.json)', 'trace/outcomes/ref-t2-4.json records outcome verification-failed, not accepted');
  // the shared store is untouched: REF_T2 still resolves beside it
  assert.ok(loadPolicy(withLine('cc-opus-high', REF_T2)));
});

test('README (F1): the calibration-first section says a reference\'s path cannot leave the policy file\'s directory, and the E7 bullets say rate offers nothing to paste for a store outside it', () => {
  const readme = readFileSync(join(HERE, 'README.md'), 'utf8').replace(/\s+/g, ' ');
  const start = readme.indexOf('## Calibration-first evidence (host-policy-6)');
  const section = readme.slice(start, readme.indexOf(' ## ', start + 1));
  for (const s of ["The path **cannot leave the policy file's directory**", "`<path> leaves the policy file's directory <dir>`", 'a store that is never committed with the policy, such as a temp trace, cannot back a qualification', "the file must lie inside the policy file's directory (F1)"]) {
    assert.ok(section.includes(s), `the calibration-first section lacks: ${s}`);
  }
  const note = "; no typed evidence to paste: the outcome store <dir> is outside the policy file's directory <dir>, and a reference cannot leave it (E1)";
  assert.equal(readme.split(note).length - 1, 2, 'the note in the applied E7 bullet and in the learning loop');
});

test('README (F2): the calibration-first section and the applied E1 bullet say a reference must be the latest outcome record of its dispatch', () => {
  const readme = readFileSync(join(HERE, 'README.md'), 'utf8').replace(/\s+/g, ' ');
  const start = readme.indexOf('## Calibration-first evidence (host-policy-6)');
  const section = readme.slice(start, readme.indexOf(' ## ', start + 1));
  for (const s of ['be the **latest outcome record of its dispatch**', 'spec-v2 §10.5 and decision-trace.md §4', '`<path> is superseded by outcome record <task> seq <n> (<value>) for the same dispatch (seq <d>)`']) {
    assert.ok(section.includes(s), `the calibration-first section lacks: ${s}`);
  }
  assert.ok(readme.includes('One from fix round 1 (F2): the outcome record must be the latest of its dispatch, as `rate` counts it.'), 'the applied E1 bullet');
});

// E2/E3: the adopting switch "evidence": "typed" (absent: the old behaviour) and the supported-entry rule
const typed = (p) => { p.evidence = 'typed'; };
const unsupported = (id, entry, cat, tier) => new RegExp(`^invalid policy: profile ${esc(id)} qualified-for '${esc(entry)}' has no typed evidence behind it \\(a PASS grade entry or an accepted outcome reference for ${esc(cat)}${tier ? ` at ${tier} or above` : ''}; free text supports nothing\\)$`);
// host-policy-5 made typed-valid in the smallest way: the entries free text alone held dropped, cc-opus-high's fix@T2
// backed by the ref-t2 reference
const typedHp5 = (p) => {
  typed(p);
  const opus = profileOf(p, 'cc-opus-high');
  opus['qualified-for'] = ['review@T1', 'fix@T2', 'pin-tests'];
  opus.evidence.push(REF_T2);
  profileOf(p, 'cc-fable-high')['qualified-for'] = ['review@T1', 'fix', 'pin-tests'];
  profileOf(p, 'cc-haiku-low')['qualified-for'] = ['pin-tests'];
};

test('E2: "evidence" is "typed" or absent (exit 2 otherwise); absent, an entry with nothing typed behind it loads as before; typed, it is refused naming the profile and the entry', () => {
  for (const bad of ['on', 'Typed', true, null, 1]) {
    exit2(() => loadPolicy(refPolicy((p) => { p.evidence = bad; })), new RegExp(`^invalid policy: evidence must be "typed" when present \\(absent: free-text evidence accepted\\); got ${esc(JSON.stringify(bad))}$`));
  }
  // host-policy-5 as it stands: absent, it loads; typed, its first entry held by free text alone is refused (cc-fable-high
  // fix@T2: its calibration fix PASSes are T1, the U5 fix-round line is prose)
  assert.ok(loadPolicy(HP5_OFF_PATH));
  exit2(() => loadPolicy(refPolicy(typed)), unsupported('cc-fable-high', 'fix@T2', 'fix', 'T2'));
  // made typed-valid, it loads
  assert.equal(loadPolicy(refPolicy(typedHp5)).evidence, 'typed');
  // free text supports nothing: cc-opus-high's build-core@T3 line of revision 5, and the 302-dispatches line
  exit2(() => loadPolicy(refPolicy((p) => { typedHp5(p); profileOf(p, 'cc-opus-high')['qualified-for'].unshift('build-core@T3'); })), unsupported('cc-opus-high', 'build-core@T3', 'build-core', 'T3'));
  // a profile with an entry and no evidence at all
  exit2(() => loadPolicy(refPolicy((p) => { typedHp5(p); profileOf(p, 'cc-sonnet-xhigh').evidence = []; })), unsupported('cc-sonnet-xhigh', 'review', 'review', 'T1'));
  // the onboarding state (proposal Item 1.2): present, priced, qualified-for [] - valid, and Gate 2 refuses it
  assert.ok(loadPolicy(refPolicy((p) => { typedHp5(p); const s = profileOf(p, 'cc-sonnet-xhigh'); s['qualified-for'] = []; s.evidence = []; })));
});

test('E2: a PASS grade entry or an accepted reference at the entry\'s tier or above supports it; PARTIAL and FAIL support nothing; a tierless grade is T1; untiered, the tier is ignored; extra references are the record', () => {
  const load = (mutate) => loadPolicy(refPolicy((p) => { typedHp5(p); mutate(p); }));
  const sonnetLow = (p) => profileOf(p, 'cc-sonnet-low');
  // cc-sonnet-low review: PASS, PARTIAL, PASS - without its PASS lines, the PARTIAL alone supports nothing; a FAIL alone neither
  exit2(() => load((p) => { sonnetLow(p).evidence = sonnetLow(p).evidence.filter((e) => !/: review PASS /.test(e)); }), unsupported('cc-sonnet-low', 'review', 'review', 'T1'));
  exit2(() => load((p) => { sonnetLow(p).evidence = sonnetLow(p).evidence.filter((e) => !/: review /.test(e)).concat('calibration-4: review FAIL (n=1)'); }), unsupported('cc-sonnet-low', 'review', 'review', 'T1'));
  // tiers: the reference at T2 supports fix@T2 and a bare fix (T1), not fix@T3; a tierless grade supports @T1, not @T2;
  // a grade at T2 supports @T2
  const opus = (p) => profileOf(p, 'cc-opus-high');
  exit2(() => load((p) => { opus(p)['qualified-for'] = ['review@T1', 'fix@T3', 'pin-tests']; }), unsupported('cc-opus-high', 'fix@T3', 'fix', 'T3'));
  assert.ok(load((p) => { opus(p)['qualified-for'] = ['review@T1', 'fix', 'pin-tests']; opus(p).evidence = opus(p).evidence.filter((e) => !/^calibration-\d: fix /.test(e)); }));
  exit2(() => load((p) => { opus(p).evidence = opus(p).evidence.filter((e) => e !== REF_T2); }), unsupported('cc-opus-high', 'fix@T2', 'fix', 'T2'));
  assert.ok(load((p) => { opus(p).evidence = opus(p).evidence.filter((e) => e !== REF_T2).concat('calibration-4: fix@T2 PASS (n=1)'); }));
  exit2(() => load((p) => { opus(p)['qualified-for'] = ['review@T2', 'fix@T2', 'pin-tests']; }), unsupported('cc-opus-high', 'review@T2', 'review', 'T2'));
  // untiered (no "difficulty-tiers"): an entry is supported by any PASS or reference of its category, whatever the tiers
  assert.ok(load((p) => { delete p['difficulty-tiers']; opus(p)['qualified-for'] = ['review@T3', 'fix@T3', 'pin-tests']; }));
  exit2(() => load((p) => { delete p['difficulty-tiers']; opus(p)['qualified-for'].push('build-core'); }), unsupported('cc-opus-high', 'build-core', 'build-core', null));
  // extra typed references that support no entry are allowed: cc-haiku-high's T3 pass (it holds a bare fix) and a
  // reference in a category the profile does not hold
  assert.ok(load((p) => { profileOf(p, 'cc-haiku-high').evidence.push('outcome: ref-pre fix@T3 accepted 2026-10-18 (trace/outcomes/ref-pre-3.json); would be T3 by the table'); }));
  assert.ok(load((p) => { opus(p)['qualified-for'] = ['review@T1', 'pin-tests']; }));
});

test('E3: the lead-direct profile (economics.lead-direct-profile) is exempt from E2 - its qualifications authorize the lead\'s own inline work; its references are still resolved, and another lead-direct profile moves the exemption', () => {
  const policy = loadPolicy(refPolicy(typedHp5));
  const lead = profileOf(policy, policy.economics['lead-direct-profile']);
  assert.equal(lead.id, 'cc-fable-xhigh');
  assert.ok(lead['qualified-for'].includes('build-core@T3') && lead.evidence.every((e) => !e.startsWith('outcome:')), 'held by prose and T1 grades alone');
  // the exemption follows the economics key: with cc-opus-high as the lead-direct profile, cc-fable-xhigh is checked
  exit2(() => loadPolicy(refPolicy((p) => { typedHp5(p); p.economics['lead-direct-profile'] = 'cc-opus-high'; })), unsupported('cc-fable-xhigh', 'build-core@T3', 'build-core', 'T3'));
  // ... and cc-opus-high, now exempt, may hold build-core@T3 on prose
  assert.ok(loadPolicy(refPolicy((p) => { typedHp5(p); p.economics['lead-direct-profile'] = 'cc-opus-high'; profileOf(p, 'cc-fable-xhigh')['qualified-for'] = ['review', 'fix', 'pin-tests']; profileOf(p, 'cc-opus-high')['qualified-for'].unshift('build-core@T3'); })));
  // E1 still applies to the exempt profile's typed lines
  exit2(() => loadPolicy(refPolicy((p) => { typedHp5(p); profileOf(p, 'cc-fable-xhigh').evidence.push(REF_T2); })), /^invalid policy: profile cc-fable-xhigh evidence '.*' cannot be resolved: trace\/outcomes\/ref-t2-3\.json is an outcome of cc-opus-high, not cc-fable-xhigh$/);
});

// ---------------------------------------------------------------------------------------------
// host-policy-6: the lead's table (E5) applied to the live policy, and its routing consequence (E6)
// ---------------------------------------------------------------------------------------------
const DROPPED = '; entry dropped in host-policy-6 (no outcome row to reference)';
const PRE_TIER = 'the decision predates revision 5 and carries no tier';
const HP6_HAIKU_HIGH_LINE = 'outcome: fix-x2-1 fix@T3 accepted 2026-10-18 (trace/outcomes/fix-x2-1-3.json); would be T3 by the table: one pass at T3, not a qualification';
const HP6_TABLE = {
  'cc-opus-high': {
    qualified: ['build-ui@T3', 'review@T1', 'fix@T2', 'pin-tests'],
    dropped: ['build-core@T3', 'build-tests@T3', 'research-collect@T2'],
    refs: [
      `outcome: sr-policy-2 build-ui@T3 accepted 2026-10-17 (trace/outcomes/sr-policy-2-3.json); would be T3 by the table (five permitted files; ${PRE_TIER})`,
      `outcome: sr-policy-3 build-ui@T3 accepted 2026-10-18 (trace/outcomes/sr-policy-3-5.json); would be T3 by the table (five permitted files; ${PRE_TIER})`,
      `outcome: sr-policy-4 build-ui@T3 accepted 2026-10-18 (trace/outcomes/sr-policy-4-4.json); would be T3 by the table (five permitted files; ${PRE_TIER})`,
      `outcome: sr-ci-item4 build-ui@T3 accepted 2026-10-18 (trace/outcomes/sr-ci-item4-3.json); would be T3 by the table (nine permitted files; ${PRE_TIER})`,
      `outcome: sr-policy-5 build-ui@T3 accepted 2026-10-18 (trace/outcomes/sr-policy-5-3.json); would be T3 by the table (six permitted files; ${PRE_TIER})`,
      `outcome: sr-host-review review@T1 accepted 2026-10-17 (trace/outcomes/sr-host-review-3.json); would be T1 by the table (one module against gates.md with the shipped tests; ${PRE_TIER})`,
      `outcome: sr-host-rereview1 review@T1 accepted 2026-10-17 (trace/outcomes/sr-host-rereview1-3.json); would be T1 by the table (one module against gates.md with the shipped tests; ${PRE_TIER})`,
      `outcome: sr-host-rereview2 review@T1 accepted 2026-10-17 (trace/outcomes/sr-host-rereview2-3.json); would be T1 by the table (one module against gates.md with the shipped tests; ${PRE_TIER})`,
      `outcome: sr-host-fix1 fix@T2 accepted 2026-10-17 (trace/outcomes/sr-host-fix1-4.json); would be T2 by the table (three files, one module, cause named by the findings; ${PRE_TIER})`,
      `outcome: sr-host-fix2 fix@T2 accepted 2026-10-17 (trace/outcomes/sr-host-fix2-4.json); would be T2 by the table (three files, one module, cause named by the findings; ${PRE_TIER})`
    ]
  },
  'cc-fable-high': {
    qualified: ['review@T1', 'fix', 'pin-tests'],
    dropped: ['fix@T2'],
    refs: [`outcome: gsi-u5-rereview4 review@T1 accepted 2026-10-17 (trace/outcomes/gsi-u5-rereview4-3.json); would be T1 by the table (one module with the shipped tests; ${PRE_TIER})`]
  },
  'cc-haiku-high': { rewritten: [HAIKU_HIGH_LINE, HP6_HAIKU_HIGH_LINE] },
  'cc-haiku-low': { qualified: ['pin-tests'], droppedLines: ['one completed mechanical extraction dispatch this session (91k tokens, done)'] }
};

test('host-policy-6: the lead\'s table applied - "evidence": "typed", revision 5\'s production-derived entries rewritten into references or dropped with their lines kept as prose, the lead-direct profile and the calibration-derived profiles unchanged; every reference resolves against the committed store', () => {
  const raw = JSON.parse(readFileSync(COMMITTED_POLICY_PATH, 'utf8'));
  const hp5 = JSON.parse(readFileSync(HP5_POLICY_PATH, 'utf8'));
  const live = loadPolicy(COMMITTED_POLICY_PATH);   // the validator resolves every reference against trace/ beside it
  assert.deepEqual([live['policy-revision'], live.evidence, live['difficulty-tiers']], ['host-policy-6', 'typed', 'enforced']);
  // the key sits after "difficulty-tiers"; nothing else at the top level changes
  const keys = Object.keys(hp5);
  keys.splice(keys.indexOf('difficulty-tiers') + 1, 0, 'evidence');
  assert.deepEqual(Object.keys(raw), keys);
  const rest = (p) => Object.fromEntries(Object.entries(p).filter(([k]) => !['policy-revision', 'evidence', 'profiles'].includes(k)));
  assert.deepEqual(rest(raw), rest(hp5), 'only the revision, the key and the profiles change');
  assert.deepEqual(raw.profiles.map((p) => p.id), hp5.profiles.map((p) => p.id), 'the fifteen profiles of host-policy-5, in order');
  const fixed = (p) => Object.fromEntries(Object.entries(p).filter(([k]) => !['qualified-for', 'evidence', 'qualified-at'].includes(k)));
  for (const after of raw.profiles) {
    const before = hp5.profiles.find((p) => p.id === after.id);
    const want = HP6_TABLE[after.id];
    if (!want) {
      assert.deepEqual(after, before, `${after.id}: unchanged (the lead-direct profile, E3, and every calibration-derived profile)`);
      continue;
    }
    // the headroom changes since the fixture: rate's proposals on the accepted sr-kit (1262204 tokens) and sr-evidence
    // (1491793) outcomes, each ratified by the lead at integration under the never-lowered rule; their lines close the
    // profile's evidence, in that order
    const rat = ({ 'cc-opus-high': { from: 1030000, to: 1492000, lines: [
      /^sr-kit outcome accepted .*: 1262204 tokens completed \(trace\/outcomes\/sr-kit-4\.json\); rate proposed headroom-tested 1030000 -> 1263000, ratified by the lead at integration/,
      /^sr-evidence outcome accepted .*: 1491793 tokens completed \(trace\/outcomes\/sr-evidence-3\.json\); rate proposed headroom-tested 1263000 -> 1492000, ratified by the lead at integration/
    ] } })[after.id];
    assert.deepEqual(fixed(after), { ...fixed(before), ...(rat ? { 'headroom-tested': rat.to } : {}) }, `${after.id}: model, effort, config, tools, vision, context, headroom (but the ratified raises), expires, reviewer unchanged`);
    if (rat) {
      assert.equal(before['headroom-tested'], rat.from, `${after.id} headroom before the raises`);
      const tail = after.evidence.slice(-rat.lines.length);
      rat.lines.forEach((re, i) => assert.match(tail[i], re, `${after.id}: ratification line ${i + 1} closes its evidence`));
    }
    const evidence = rat ? after.evidence.slice(0, -rat.lines.length) : after.evidence;
    assert.equal(after['qualified-at'], '2026-10-18', `${after.id} re-declared`);
    assert.deepEqual(after['qualified-for'], want.qualified ?? before['qualified-for'], `${after.id} qualified-for`);
    // the evidence: revision 5's lines in place (free text kept as prose, E4), each line of a dropped entry suffixed,
    // cc-haiku-high's line rewritten into form (b), then the references
    const droppedLine = (e) => (want.dropped ?? []).some((c) => e.startsWith(`${c}: `)) || (want.droppedLines ?? []).includes(e);
    const kept = before.evidence.map((e) => (droppedLine(e) ? `${e}${DROPPED}` : want.rewritten && e === want.rewritten[0] ? want.rewritten[1] : e));
    assert.deepEqual(evidence, [...kept, ...(want.refs ?? [])], `${after.id} evidence`);
    for (const c of want.dropped ?? []) assert.ok(before['qualified-for'].includes(c) && !after['qualified-for'].includes(c), `${after.id} drops ${c}`);
    assert.equal(before.evidence.filter(droppedLine).length, (want.dropped ?? []).length + (want.droppedLines ?? []).length, `${after.id}: one prose line per dropped entry`);
  }
  assert.ok(raw.profiles.find((p) => p.id === 'cc-haiku-high').evidence.includes(HP6_HAIKU_HIGH_LINE));
  assert.ok(!raw.profiles.find((p) => p.id === 'cc-haiku-high').evidence.includes(HAIKU_HIGH_LINE), 'rewritten, not duplicated');
  // no delegate holds build-core, build-tests, research-collect or docs-mechanical any more (E6)
  const lead = raw.economics['lead-direct-profile'];
  for (const cat of ['build-core', 'build-tests', 'research-collect', 'docs-mechanical']) {
    assert.deepEqual(raw.profiles.filter((p) => p.id !== lead && p['qualified-for'].some((c) => c.split('@')[0] === cat)).map((p) => p.id), [], cat);
  }
});

test('host-policy-6: every calibration-derived entry is supported by its own PASS grade entries (the validator checks each: without them it refuses the entry), and the production entries by their references', () => {
  const lead = COMMITTED_POLICY.economics['lead-direct-profile'];
  const beside = (mutate) => {
    const p = JSON.parse(readFileSync(LIVE_OFF_PATH, 'utf8'));
    mutate(p);
    const path = join(LIVE_OFF_DIR, `host-policy-hp6-${refN += 1}.json`);
    writeFileSync(path, JSON.stringify(p, null, 2));
    return path;
  };
  assert.ok(loadPolicy(LIVE_OFF_PATH));
  let checked = 0;
  for (const pr of COMMITTED_POLICY.profiles) {
    if (pr.id === lead) continue;
    for (const entry of pr['qualified-for']) {
      const [cat, tier] = entry.split('@');
      const hasRef = pr.evidence.some((e) => e.startsWith(`outcome: `) && e.split(' ')[2].split('@')[0] === cat);
      // strip every PASS grade of the category: an entry held on grades alone is now refused; one held at T2 or T3 on
      // references survives it (the grades are T1)
      const path = beside((p) => { const q = p.profiles.find((x) => x.id === pr.id); q.evidence = q.evidence.filter((e) => !new RegExp(`^calibration-\\d+: ${cat}(@T\\d)? PASS `).test(e)); });
      if (hasRef) assert.ok(loadPolicy(path), `${pr.id} ${entry} stands on its references`);
      else exit2(() => loadPolicy(path), unsupported(pr.id, entry, cat, tier ?? 'T1'));
      // and without its references, an entry above T1 is refused
      if (hasRef && tier && tier !== 'T1') {
        const noRefs = beside((p) => { const q = p.profiles.find((x) => x.id === pr.id); q.evidence = q.evidence.filter((e) => !(e.startsWith('outcome: ') && e.split(' ')[2].split('@')[0] === cat)); });
        exit2(() => loadPolicy(noRefs), unsupported(pr.id, entry, cat, tier));
      }
      checked += 1;
    }
  }
  assert.equal(checked, 30, 'every qualified-for entry of the fourteen delegate profiles');
});

const hp6Req = (category, over = {}) => reqFor(loadPolicy(LIVE_OFF_PATH), category, over);
test('host-policy-6 routing (E6): fix@T1 -> cc-haiku-high, fix@T2 -> cc-opus-high, review@T1 -> cc-sonnet-xhigh, undeclared build-ui -> cc-opus-high, pin-tests@T1 -> cc-haiku-low as under revision 5; build-core, build-tests, research-collect and docs-mechanical above direct-max-tokens blocked - no delegate holds them', () => {
  const live = loadPolicy(LIVE_OFF_PATH);
  const decideLive = (category, over) => computeDecision(hp6Req(category, over), live, []);
  const hp5 = loadPolicy(HP5_OFF_PATH);
  const decideHp5 = (category, over) => computeDecision(hp5Req(category, over), hp5, []);
  const pick = (d) => [d.route, d.profile, d['review-profile'], d['difficulty-tier'], d['all-in-bound-usd']];
  // the five routes of revision 5, unchanged
  for (const [category, over, want] of [
    ['fix', { difficultyTier: 'T1' }, ['delegate', 'cc-haiku-high', 'cc-sonnet-xhigh', 'T1', 3.1865]],
    ['fix', { difficultyTier: 'T2' }, ['delegate', 'cc-opus-high', 'cc-sonnet-xhigh', 'T2', 6.95]],
    ['review', { difficultyTier: 'T1' }, ['delegate', 'cc-sonnet-xhigh', null, 'T1', 3.09]],
    ['build-ui', { estimatedTokens: 250000 }, ['delegate', 'cc-opus-high', 'cc-sonnet-xhigh', 'T2', 8.09]],
    ['pin-tests', { difficultyTier: 'T1' }, ['delegate', 'cc-haiku-low', null, 'T1', 1.06]]
  ]) {
    assert.deepEqual(pick(decideLive(category, over)), want, `${category} ${JSON.stringify(over)}`);
    assert.deepEqual(pick(decideHp5(category, over)), want, `${category} ${JSON.stringify(over)} under host-policy-5`);
  }
  // fix@T1 keeps its eligible set (cc-fable-high's bare fix covers T1); fix@T2 loses cc-fable-high (fix dropped to bare)
  assert.deepEqual(decideLive('fix', { difficultyTier: 'T1' })['eligible-ordered'], ['cc-haiku-high', 'cc-opus-high', 'cc-opus-xhigh', 'cc-fable-high']);
  const t2 = decideLive('fix', { difficultyTier: 'T2' });
  assert.deepEqual(t2['eligible-ordered'], ['cc-opus-high']);
  assert.equal(t2.candidates['cc-fable-high'].reason, 'cc-fable-high not qualified for fix@T2 (holds fix@T1)');
  assert.deepEqual(decideLive('build-ui', { estimatedTokens: 250000 })['eligible-ordered'], ['cc-opus-high']);
  // the four categories no delegate holds: blocked at their medians, every delegate failing Gate 2 for holding nothing of
  // the category, the lead-direct profile failing Gate 5 on direct-max-tokens; nobody outside the candidates would pass
  for (const [category, over, tier, tokens] of [['build-core', {}, 'T3', 316000], ['build-tests', {}, 'T2', 250000], ['research-collect', {}, 'T2', 232000], ['docs-mechanical', {}, 'T2', 92000], ['docs-mechanical', { difficultyTier: 'T1' }, 'T1', 92000], ['build-core', { difficultyTier: 'T1', estimatedTokens: 16000 }, 'T1', 16000]]) {
    const d = decideLive(category, over);
    assert.deepEqual([d.route, d['difficulty-tier'], d['eligible-outside-candidates'], d['eligible-ordered']], ['blocked', tier, [], []], `${category} ${JSON.stringify(over)}`);
    for (const [id, c] of Object.entries(d.candidates)) {
      if (id === 'cc-fable-xhigh') assert.deepEqual([c['first-failing-gate'], c.reason], [5, `direct unsuitable: ${tokens} tokens > direct-max-tokens 15000`], `${category} ${id}`);
      else {
        // the Gate 2 reason leads with the qualification (a headroom shortfall may follow it, '; context: ...')
        assert.equal(c['first-failing-gate'], 2, `${category} ${id}`);
        assert.match(c.reason, new RegExp(`^${esc(id)} not qualified for ${category}(;|$)`), `${category} ${id}`);
      }
    }
    // at or below direct-max-tokens the lead takes it inline
    const small = decideLive(category, { ...over, estimatedTokens: 15000 });
    assert.deepEqual([small.route, small.profile], ['direct', 'cc-fable-xhigh'], `${category} at 15000`);
  }
  // under revision 5 the same requests delegated (cc-opus-high held build-core@T3, build-tests@T3, research-collect@T2;
  // cc-haiku-low docs-mechanical): the consequence of E4's drops
  for (const [category, profile] of [['build-core', 'cc-opus-high'], ['build-tests', 'cc-opus-high'], ['research-collect', 'cc-opus-high']]) {
    assert.deepEqual([decideHp5(category).route, decideHp5(category).profile], ['delegate', profile], `${category} under host-policy-5`);
  }
  assert.deepEqual([decideHp5('docs-mechanical', { difficultyTier: 'T1' }).route, decideHp5('docs-mechanical', { difficultyTier: 'T1' }).profile], ['delegate', 'cc-haiku-low']);
  // the CLI on the live policy agrees, and records the revision
  for (const [category, over, route, profile] of [['fix', { difficultyTier: 'T2' }, 'delegate', 'cc-opus-high'], ['build-ui', { estimatedTokens: 250000 }, 'delegate', 'cc-opus-high'], ['build-core', {}, 'blocked', null], ['docs-mechanical', { difficultyTier: 'T1' }, 'blocked', null]]) {
    const decided = cliDecide(hp6Req(category, { taskId: `hp6-${category}`, ...over }), LIVE_OFF_PATH);
    assert.deepEqual([decided.bindings['policy-revision'], decided.decision.route, decided.decision.profile], ['host-policy-6', route, profile], category);
  }
});

// E7: every command loads the policy through loadPolicy, so an unresolvable reference stops each of them (exit 2) before
// it reads or writes anything; no new command or flag
test('E7: decide, dispatch, outcome, status, rate and usage all validate the policy - an unresolvable reference is exit 2 with the reason, and nothing is written', () => {
  const bad = withLine('cc-opus-high', 'outcome: ref-fail fix@T2 accepted 2026-10-18 (trace/outcomes/ref-fail-3.json)');
  const reason = /^route\.mjs: invalid policy: profile cc-opus-high evidence 'outcome: ref-fail fix@T2 accepted 2026-10-18 \(trace\/outcomes\/ref-fail-3\.json\)' cannot be resolved: trace\/outcomes\/ref-fail-3\.json records outcome verification-failed, not accepted\n$/;
  // a task decided and dispatched under a valid policy, so every command has something to act on
  const trace = tmp();
  const good = withLine('cc-opus-high', REF_T2);
  const d = decide(hp5Req('fix', { taskId: 'e7-1', difficultyTier: 'T2' }), { traceDir: trace, policyPath: good });
  assert.equal(cli(['dispatch', 'e7-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--trace', trace, '--now', NOW, '--policy', good]).code, 0);
  const before = readFileSync(join(trace, 'ledger.jsonl'), 'utf8');
  const out = writeJson(outcome({ 'task-id': 'e7-1', outcome: 'accepted', 'original-brief-fingerprint': d.briefFingerprint }));
  for (const args of [
    ['decide', writeJson(hp5Req('fix', { taskId: 'e7-2', difficultyTier: 'T1' }))],
    ['dispatch', 'e7-1', 'cc-opus-high', '--project-stop', CLEAR_JSON, '--now', NOW],
    ['outcome', out, '--now', NOW],
    ['status', 'e7-1'],
    ['rate', '--now', NOW],
    ['usage', '--now', NOW]
  ]) {
    const r = cli([...args, '--trace', trace, '--policy', bad]);
    assert.equal(r.code, 2, `${args[0]}: ${r.stderr}`);
    assert.match(r.stderr, reason, args[0]);
  }
  assert.equal(readFileSync(join(trace, 'ledger.jsonl'), 'utf8'), before, 'nothing appended');
  assert.ok(!existsSync(join(trace, 'qualification-stats.json')), 'rate wrote nothing');
  assert.ok(!existsSync(join(trace, 'decisions', 'e7-2-1.json')) && !existsSync(join(trace, 'outcomes')), 'decide and outcome wrote nothing');
});

// E7: rate keeps proposing from outcomes as it does; a qualify proposal's PROPOSAL line now ends with the typed references
// the lead would paste (one per accepted outcome behind it, as JSON strings for the evidence array), each resolvable
// against the store beside the policy
test('E7: a qualify proposal ends with the typed reference lines the lead would paste - the decision\'s tier when it declares one, bare when it does not - and pasted, they resolve and the proposal is gone', () => {
  // tiered: the three hand-recorded T2 fixes on cc-haiku-high of the tiers D7 test, in a layout with the policy beside trace/
  const dir = tmp();
  const policyPath = join(dir, 'host-policy.json');
  writeFileSync(policyPath, readFileSync(TIERED_PATH));
  const q = join(dir, 'trace');
  const pol = loadPolicy(policyPath);
  for (const id of ['q-1', 'q-2', 'q-3']) {
    const d = decide(reqFor(pol, 'fix', { taskId: id, difficultyTier: 'T2', now: LATE }), { traceDir: q, policyPath });
    const h = profileOf(pol, 'cc-haiku-high');
    appendFileSync(join(q, 'ledger.jsonl'), `${JSON.stringify({ 'task-id': id, seq: 2, kind: 'dispatch', ts: LATE, profile: `(${h.id}, ${pol.harness.id}, anthropic, ${h.model}, ${h.effort}, ${h.config})`, counters: { 'calls-used': 1, 'calls-limit': 6, 'cash-spent': null, 'cash-cap': null, 'repairs-used': 0, 'repairs-allowed': 1 }, deadline: d.decision.deadline, 'brief-fingerprint': null, detail: 'host deviation: qualification run recorded by hand', 'outcome-ref': null, deviation: true, 'decision-seq': 1 })}\n`);
    recordOutcome(outcome({ 'task-id': id, outcome: 'accepted', 'owner-profile': 'cc-haiku-high', 'original-brief-fingerprint': d.briefFingerprint }), { traceDir: q, policyPath, now: LATE });
  }
  const lines = ['q-1', 'q-2', 'q-3'].map((id) => `outcome: ${id} fix@T2 accepted 2026-10-18 (trace/outcomes/${id}-3.json)`);
  const r = cli(['rate', '--trace', q, '--now', LATE, '--policy', policyPath]);
  assert.equal(r.code, 0, r.stderr);
  const want = `PROPOSAL qualify cc-haiku-high for fix@T2: 3 accepted while unqualified (host deviations: q-1, q-2, q-3); not applied — the lead ratifies by editing host-policy.json; typed evidence to paste: ${lines.map((l) => JSON.stringify(l)).join(', ')}`;
  assert.ok(r.stdout.split('\n').includes(want), r.stdout);
  const doc = JSON.parse(readFileSync(join(q, 'qualification-stats.json'), 'utf8'));
  assert.deepEqual(doc.proposals.map((p) => [p.kind, p.category, p.references]), [['qualify', 'fix@T2', lines]]);
  // pasted (the paste is valid JSON array elements) with the entry the lead would ratify, they resolve and back it
  const pasted = JSON.parse(readFileSync(policyPath, 'utf8'));
  const h = profileOf(pasted, 'cc-haiku-high');
  h['qualified-for'] = h['qualified-for'].map((c) => (c === 'fix' ? 'fix@T2' : c));
  h.evidence.push(...JSON.parse(`[${want.slice(want.indexOf('paste: ') + 'paste: '.length)}]`));
  writeFileSync(policyPath, JSON.stringify(pasted, null, 2));
  assert.ok(loadPolicy(policyPath));
  assert.ok(!rate({ traceDir: q, policyPath, now: LATE }).proposals.some((p) => p.kind === 'qualify'), 'qualified: no proposal');
  // untiered: the hand-recorded build-core runs on cc-fable-high (host-policy-1); the decisions carry no tier, so the lines are bare
  const dir2 = tmp();
  const policy2 = join(dir2, 'host-policy.json');
  writeFileSync(policy2, POLICY_TEXT);
  const t2 = join(dir2, 'trace');
  for (const id of ['u-1', 'u-2', 'u-3']) handQualificationRun(t2, id, 'build-core', 'cc-fable-high', 'accepted');
  const r2 = rate({ traceDir: t2, policyPath: policy2, now: NOW });
  const lines2 = ['u-1', 'u-2', 'u-3'].map((id) => `outcome: ${id} build-core accepted 2026-10-17 (trace/outcomes/${id}-3.json)`);
  assert.ok(r2.text.split('\n').includes(`PROPOSAL qualify cc-fable-high for build-core: 3 accepted while unqualified (host deviations: u-1, u-2, u-3); not applied — the lead ratifies by editing host-policy.json; typed evidence to paste: ${lines2.map((l) => JSON.stringify(l)).join(', ')}`), r2.text);
  const p2 = JSON.parse(POLICY_TEXT);
  profileOf(p2, 'cc-fable-high')['qualified-for'].push('build-core');
  profileOf(p2, 'cc-fable-high').evidence = [...(profileOf(p2, 'cc-fable-high').evidence ?? []), ...lines2];
  writeFileSync(policy2, JSON.stringify(p2, null, 2));
  assert.ok(loadPolicy(policy2));
  // demotion proposals carry no references (nothing to paste)
  assert.ok(rate({ traceDir: frozenTrace(FREEZE_HP3), policyPath: HP3_POLICY_PATH, now: LATE }).proposals.every((p) => p.kind !== 'demote' || p.references === undefined));
});

// deliverable E: the README's host-policy-6 qualification table is the live policy verbatim (P2-2)
test('README: the host-policy-6 qualification table matches host-policy.json row for row (15 rows), qualified-for in policy order, the three runs\' grades', () => {
  const readme = readFileSync(join(HERE, 'README.md'), 'utf8');
  const start = readme.indexOf('### The table (host-policy-6');
  assert.ok(start >= 0, 'the README carries the host-policy-6 table');
  const section = readme.slice(start, readme.indexOf('\n#', start + 1));
  const rows = section.split('\n').filter((l) => /^\| `cc-/.test(l)).map((l) => l.split('|').slice(1, -1).map((c) => c.trim()));
  assert.equal(rows.length, 15);
  assert.deepEqual(rows.map((r) => r[0]), COMMITTED_POLICY.profiles.map((p) => `\`${p.id}\``), 'one row per profile, in policy order');
  for (const p of COMMITTED_POLICY.profiles) {
    const [, , qual, headroom, run1, run2, run3, refs] = rows.find((r) => r[0] === `\`${p.id}\``);
    assert.equal(qual, p['qualified-for'].join(', ') || 'none', `${p.id} qualified-for`);
    assert.equal(headroom, `${p['headroom-tested'] / 1000}k`, `${p.id} headroom-tested`);
    const grade = (run, cat) => (p.evidence.find((e) => e.startsWith(`calibration-${run}: ${cat} `)) ?? '').split(' ')[2] ?? '-';
    for (const [run, cell] of [[1, run1], [2, run2], [3, run3]]) {
      assert.equal(cell, ['pin-tests', 'fix', 'review'].map((cat) => grade(run, cat) || '-').join(' / '), `${p.id} calibration-${run} grades`);
    }
    // the typed references column: '<task> <category>[@T<k>]' per reference, in evidence order
    const typedRefs = p.evidence.filter((e) => e.startsWith('outcome: ')).map((e) => e.split(' ').slice(1, 3).join(' '));
    assert.equal(refs, typedRefs.join(', ') || '-', `${p.id} references`);
  }
});

const ONBOARD_STATUS = 'Status: **draft proposal, not normative; revision 2 after the independent review of 2026-10-18 (Request Changes on c53cd77).** Nothing in `skills/` is amended by this document. If accepted after independent review (plan §15), the items below would become one additional host-policy validation rule, one new tools path holding the calibration kit, one evidence-folder contract with a CI check, and an additive host-policy field; until then hosts MUST NOT emit or require them.';
test('README: Calibration-first evidence (host-policy-6) - the two forms quoted, resolution, the supported-entry rule, the exemption, prose, the lead\'s table with every typed line, and the routing consequence as decide prints it with the remedy', () => {
  const readme = readFileSync(join(HERE, 'README.md'), 'utf8');
  const unquote = (s) => s.replace(/\n\s*>\s?/g, ' ').replace(/\s+/g, ' ');
  const start = readme.indexOf('## Calibration-first evidence (host-policy-6)');
  assert.ok(start >= 0, 'the README carries the section');
  const section = readme.slice(start, readme.indexOf('\n## ', start + 1));
  const flat = unquote(section);
  for (const s of [
    '`calibration-<n>: <category>[@T<k>] PASS|PARTIAL|FAIL (n=<k>)`',
    '`outcome: <task-id> <category>[@T<k>] accepted <ISO date> (<path>)`',
    ONBOARD_STATUS,
    '`| 1-5 (revision 2) | pending delta review | — | — |`',
    'relative to the policy file\'s directory, never to `--trace`',
    'A PARTIAL or FAIL grade entry supports nothing.',
    '`"evidence": "typed"`',
    'free text supports nothing',
    DROPPED.slice(2),
    'Run 4 gains one T1 host-pack cell for each of `build-core`, `build-tests`, `research-collect` and `docs-mechanical`'
  ]) assert.ok(flat.includes(s), `the section lacks: ${s}`);
  for (const line of [...Object.values(HP6_TABLE).flatMap((t) => t.refs ?? []), HP6_HAIKU_HIGH_LINE]) assert.ok(flat.includes(line), `the section lacks the line ${line}`);
  // the routing consequence: decide's own lines on the live policy (feature-off derivative)
  for (const [i, [category, over, walked]] of [['build-core', {}, true], ['docs-mechanical', { difficultyTier: 'T1' }, false], ['fix', { difficultyTier: 'T2' }, false]].entries()) {
    const r = cli(['decide', writeJson(hp6Req(category, { taskId: `readme6-${i}`, ...over })), '--trace', tmp(), '--policy', LIVE_OFF_PATH]);
    assert.equal(r.code, 0, r.stderr);
    const out = r.stdout.split('\n');
    const pickLine = (k) => out.find((l) => l.startsWith(`${k}:`));
    const profile = pickLine('Profile');
    const pr = COMMITTED_POLICY.profiles.find((p) => profile.includes(`(${p.id},`));
    const head = [pickLine('Difficulty'), pickLine('DifficultyTier'), pickLine('Route'), pr ? profile.replace(pr.model, '<model>') : profile, pickLine('Reservations')].join('\n');
    assert.ok(section.includes(`\n${head}\n`), `${category}: the section lacks\n${head}`);
    if (walked) {
      const walk = out.slice(out.findIndex((l) => l.startsWith('Gate walk')), out.findIndex((l, j) => j > 0 && (l.startsWith('Brief') || l === '')));
      assert.equal(walk.length, 1 + COMMITTED_POLICY.profiles.length);
      assert.ok(section.includes(`\n${walk.join('\n')}\n`), `${category}: the section lacks the gate walk`);
    }
  }
});

test('README: How the onboarding proposal was applied (host-policy-6) names E1-E7; policy findings (host-policy-6); friction items 23 (the lead-direct exemption) and 24 (the reference form carries no tier)', () => {
  const readme = readFileSync(join(HERE, 'README.md'), 'utf8');
  const start = readme.indexOf('### How the onboarding proposal was applied (host-policy-6)');
  assert.ok(start >= 0);
  const applied = readme.slice(start, readme.indexOf('\n### ', start + 1));
  for (const e of ['E1', 'E2', 'E3', 'E4', 'E5', 'E6', 'E7']) assert.match(applied, new RegExp(`\\n- \\*\\*${e}\\.\\*\\*`), e);
  const fStart = readme.indexOf('## Policy findings (host-policy-6)');
  assert.ok(fStart >= 0 && fStart < readme.indexOf('## Policy findings (host-policy-5)'), 'the revision-6 findings come first');
  const findings = readme.slice(fStart, readme.indexOf('\n## ', fStart + 1)).replace(/\s+/g, ' ');
  // the next revision's fixture problem and the owner check beyond E1 are on record
  for (const s of ['trace/policies/host-policy-6.json', 'owner-profile']) assert.ok(findings.includes(s), `the findings lack: ${s}`);
  const friction = readme.slice(readme.indexOf('## Friction log for SmartRouter upstream'));
  assert.match(friction, /\n23\. \*\*The proposal has no clause for the lead's own profile\.\*\*/);
  assert.match(friction, /\n24\. \*\*The proposal's `outcome:` form carries no tier\.\*\*/);
  const f24 = friction.slice(friction.indexOf('\n24. **')).replace(/\s+/g, ' ');
  assert.ok(f24.includes('`[@T<k>]`'), 'item 24 names the tier this host added');
});
