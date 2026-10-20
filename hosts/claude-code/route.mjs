#!/usr/bin/env node
// Holdshort host adapter for the MoonAliza build process.
//
// Holdshort (StepenkoAnatoli/Holdshort @ fbe7bca, skill 3.0.0) is advisory and stateless; this
// adapter is the host side: it collects the inputs from host-policy.json and the request, walks the
// five ordered gates for every candidate (references/gates.md, tests/holdshort_decisions.py
// run_gates/choose_route), prints the Required output format block plus the Brief (spec-v2 §10.1),
// and keeps the append-only Outcome Ledger (spec-v2 §10.5). It never dispatches anything itself.
//
// CLI:  decide <request.json> | dispatch <task-id> <profile-id> --project-stop <json> | outcome <outcome.json>
//       | status <task-id> | rate | usage [<reading.json>]
//       options: --trace <dir> --policy <file> --now <iso> --deviation <reason>
// Exit: 0 done (any decided route, blocked included), 2 invalid input, 3 refused, 4 ledger integrity.
import { createHash } from 'node:crypto';
import { appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, writeFileSync } from 'node:fs';
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
export const DEFAULT_POLICY = join(HERE, 'host-policy.json');
export const DEFAULT_TRACE = join(HERE, 'trace');
export const CASH_UNCERTAINTY = 'cash: estimate only, no host accounting (subscription); not a strict cap';
export const ADVISORY_TEXT = 'recommendation only — no dispatch performed or claimed';
export const ADVISORY = `Advisory: ${ADVISORY_TEXT}`;
export const PROVIDER = 'anthropic';
export const USAGE_OFF = 'usage windows: not configured';

const ISOLATION = ['none', 'directory', 'worktree+branch', 'ephemeral-container'];
const HUMAN_GATES = ['none', 'review-before-dispatch', 'review-before-merge', 'approval-required'];
const OUTCOMES = ['accepted', 'verification-failed', 'partial', 'cost-overrun', 'cancelled', 'blocked', 'escalated'];
const KINDS = ['decision', 'dispatch', 'outcome', 'spend', 'escalation'];
const TASK_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const FINGERPRINT = /^[0-9a-f]{64}$/;
const TUPLE = /^\([^,()]+(, [^,()]+){5}\)$/;
const EXPIRY_WARN_DAYS = 14;
// a calibration grade in a profile's evidence: 'calibration-<run>: <category>[@T<k>] PASS|PARTIAL|FAIL (n=<count>)'.
// PARTIAL (host-policy-3) is calibration-2's third review grade: one of the two ground-truth findings, no false blocking
// one. The tier (difficulty tiers, proposal 2.6) is optional: a tierless entry reads @T1
const CALIBRATION_ENTRY = /^calibration-([1-9]\d*): ([^\s@]+)(?:@(T[1-3]))? (PASS|PARTIAL|FAIL) \(n=([1-9]\d*)\)$/;
// difficulty tiers (Holdshort docs/proposals/difficulty-tiers.md, the lead's decisions D1-D9 in briefs/policy5-builder.md).
// A policy turns them on with "difficulty-tiers": "enforced" (D1); absent, the policy is untiered and behaves as before
export const TIERS = ['T1', 'T2', 'T3'];
export const TIERS_ENFORCED = 'enforced';
export const TIERS_OFF = 'difficulty tiers: not enforced by this policy';
const tierRank = (t) => TIERS.indexOf(t) + 1;
const tiersEnforced = (policy) => policy['difficulty-tiers'] === TIERS_ENFORCED;
// a qualified-for entry is '<category>' or '<category>@T1|T2|T3' (D2)
const QUALIFICATION = /^([^\s@]+)(?:@(T[1-3]))?$/;
// calibration-first evidence (Holdshort docs/proposals/calibration-first-onboarding.md Item 1, the lead's decisions
// E1-E7 in briefs/policy6-builder.md). E1: the typed production reference, 'outcome: <task-id> <category>[@T<k>] accepted
// <YYYY-MM-DD> (<path>)', optionally followed by '; <note>'. <path> is the outcome file the host writes
// (trace/outcomes/<task>-<seq>.json), relative to the policy file's directory; its form is checked from the policy alone,
// then it is resolved against the store it names (resolveReference)
const OUTCOME_REFERENCE = /^outcome: (\S+) ([^\s@]+)(?:@(T([1-9])))? accepted (\S+) \(([^()]+)\)(?:; (.+))?$/;
const REFERENCE_FORM = "'outcome: <task-id> <category>[@T<k>] accepted <YYYY-MM-DD> (<path>)'";
// E2: a policy adopts the supported-entry rule with the top-level key "evidence": "typed" (the shape of "difficulty-tiers");
// absent, free-text evidence is accepted as before
export const EVIDENCE_TYPED = 'typed';
function parseQualification(entry) {
  const m = QUALIFICATION.exec(entry);
  return m ? { category: m[1], tier: m[2] ?? null } : null;
}
// the tier at which a profile holds a category: 1-3, or 0 when it holds nothing of it. A bare entry reads @T1 (proposal
// 2.2); under an untiered policy only "holds it or not" is read (D1: the form is checked, the tier ignored)
function heldTier(pr, category) {
  for (const e of pr['qualified-for']) {
    const q = parseQualification(e);
    if (q && q.category === category) return q.tier ? tierRank(q.tier) : 1;
  }
  return 0;
}

export class RouterError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

const invalid = (m) => new RouterError(2, m);
const refused = (m) => new RouterError(3, m);

// ---------------------------------------------------------------------------------------------
// small helpers
// ---------------------------------------------------------------------------------------------
function sortKeys(v) {
  if (Array.isArray(v)) return v.map(sortKeys);
  if (v && typeof v === 'object') return Object.fromEntries(Object.keys(v).sort().map((k) => [k, sortKeys(v[k])]));
  return v;
}
export function canonicalJson(v) { return JSON.stringify(sortKeys(v)); }
const sha256 = (s) => createHash('sha256').update(s).digest('hex');
export function briefFingerprint(brief) { return sha256(canonicalJson(brief)); }
const round4 = (x) => Math.round(x * 1e4) / 1e4;
const round6 = (x) => Math.round(x * 1e6) / 1e6;
const usd = (x) => `$${x.toFixed(2)}`;
const isStr = (v) => typeof v === 'string' && v.length > 0;
const isStrArray = (v) => Array.isArray(v) && v.every((x) => typeof x === 'string');
const isInt = (v, min = 0) => Number.isInteger(v) && v >= min;
// the project stop rules' state, from the request at decide and from the lead at dispatch (Gate 1)
const isProjectStop = (ps) => Boolean(ps) && typeof ps === 'object' && !Array.isArray(ps)
  && ['redSuite', 'gateOff', 'researchGateFailing'].every((k) => typeof ps[k] === 'boolean');
const PROJECT_STOP_USAGE = '--project-stop \'{"redSuite":false,"gateOff":false,"researchGateFailing":false}\'';

function isoMs(v) {
  if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/.test(v)) return null;
  const ms = Date.parse(v);
  return Number.isNaN(ms) ? null : ms;
}
function dayMs(v) {
  if (typeof v !== 'string') return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return Date.parse(`${v}T00:00:00Z`);
  return isoMs(v);
}
const isoOf = (ms) => new Date(ms).toISOString().replace('.000Z', 'Z');
function slug(s) {
  return String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'unit';
}
function readJsonFile(path, what) {
  let text;
  try { text = readFileSync(path, 'utf8'); } catch (e) { throw invalid(`cannot read ${what} ${path}: ${e.message}`); }
  try { return JSON.parse(text); } catch (e) { throw invalid(`${what} ${path} is not JSON: ${e.message}`); }
}

// ---------------------------------------------------------------------------------------------
// policy
// ---------------------------------------------------------------------------------------------
// the directory a policy file's typed references resolve against (E1): the file's own directory, except that a
// fixture copy under <root>/trace/policies/ (where every revision's goldens are pinned) resolves against <root>, the
// directory holding that trace; the two directory names are the rule, so <root>/policies/ resolves against itself
export function policyRoot(path) {
  const dir = dirname(resolve(path));
  return basename(dir) === 'policies' && basename(dirname(dir)) === 'trace' ? dirname(dirname(dir)) : dir;
}

export function loadPolicy(path = DEFAULT_POLICY) {
  const p = readJsonFile(path, 'policy');
  // typed production references resolve against the policy file's directory, never against --trace (E1)
  validatePolicy(p, policyRoot(path));
  return p;
}

// the form of a typed production reference (E1), from the policy alone: null when the line is well formed, else the reason
function referenceForm(e, categories) {
  const m = OUTCOME_REFERENCE.exec(e);
  if (!m || (m[3] && !TIERS.includes(m[3])) || !/^\d{4}-\d{2}-\d{2}$/.test(m[5])) return { why: `is not ${REFERENCE_FORM}` };
  const [, task, category, tier, , date, path, note] = m;
  if (!TASK_ID.test(task)) return { why: `is not ${REFERENCE_FORM} (task-id ${task})` };
  if (!Object.hasOwn(categories, category)) return { why: `names unknown category '${category}'` };
  if (Number.isNaN(Date.parse(`${date}T00:00:00Z`)) || new Date(`${date}T00:00:00Z`).toISOString().slice(0, 10) !== date) return { why: `date ${date} is not a calendar day` };
  // relative (an absolute path would not travel with the policy and its trace), '/'-separated, and naming the file the
  // host writes for this task: the store is the directory that holds outcomes/, the seq finds the outcome record
  const seq = new RegExp(`(?:^|/)outcomes/${task.replace(/[.]/g, '\\.')}-([1-9]\\d*)\\.json$`).exec(path)?.[1];
  if (/^([A-Za-z]:)?\//.test(path) || path.includes('\\') || !seq) return { why: `path ${path} must be relative to the policy file's directory and name the outcome file outcomes/${task}-<seq>.json` };
  return { ref: { task, category, tier: tier ?? null, date, path, note: note ?? '', seq: Number(seq) } };
}

// whether `path` lies inside the directory `dir`, by its spelling and, when both exist, after symlinks. A reference
// cannot leave the policy file's directory (E1, sr-policy-6 F1): a store never committed with the policy (a temp
// trace) could otherwise back a qualification
function inside(dir, path) {
  const under = (d, p) => {
    const r = relative(d, p);
    return !isAbsolute(r) && r !== '..' && !r.startsWith(`..${sep}`);
  };
  if (!under(resolve(dir), resolve(path))) return false;
  return !(existsSync(dir) && existsSync(path)) || under(realpathSync(dir), realpathSync(path));
}

// one outcome store (a trace directory: ledger.jsonl, decisions/), read once per validation
function storeOf(stores, dir) {
  if (!stores.has(dir)) {
    try { stores.set(dir, { records: readLedger(dir), catMap: categoryMap(dir) }); } catch (e) { stores.set(dir, { error: e.message }); }
  }
  return stores.get(dir);
}

// E1: resolve a well-formed reference against the store it names, relative to the policy file's directory: null when it
// resolves, else the reason. The file must lie inside that directory (F1: no '..' out of it, no symlink out of it), be
// the latest outcome record of its dispatch (F2), be an Outcome of that task, owned by the referencing profile, `accepted`,
// recorded on the date (its own ts, else its outcome record's), and the task decided in the reference's category; the
// tier must be the decision's when the decision carries one, and a tier declared on a pre-tier decision must be the
// host's stated reading ('would be T<k> by the table')
function resolveReference(ref, pr, baseDir, stores) {
  const file = resolve(baseDir, ref.path);
  if (!inside(baseDir, file)) return `${ref.path} leaves the policy file's directory ${baseDir}: a reference names an outcome file under it`;
  if (!existsSync(file)) return `${ref.path} does not exist (resolved against the policy file's directory ${baseDir})`;
  let o;
  try { o = JSON.parse(readFileSync(file, 'utf8')); } catch { return `${ref.path} is not JSON`; }
  try { validateOutcome(o); } catch (e) { return `${ref.path} is not an Outcome (${e.message})`; }
  if (o['task-id'] !== ref.task) return `${ref.path} is the outcome of ${o['task-id']}, not ${ref.task}`;
  if (o.outcome !== 'accepted') return `${ref.path} records outcome ${o.outcome}, not accepted`;
  if (tupleId(o['owner-profile']) !== pr.id) return `${ref.path} is an outcome of ${tupleId(o['owner-profile'])}, not ${pr.id}`;
  const dir = dirname(dirname(file));
  const store = storeOf(stores, dir);
  if (store.error) return `the outcome store ${dir} is unreadable (${store.error})`;
  const rec = store.records.find((r) => r.kind === 'outcome' && r['task-id'] === ref.task && r.seq === ref.seq);
  // one outcome per dispatch (spec-v2 §10.5, decision-trace.md §4), the rule rate counts by (latestOutcomes): a later
  // outcome record for the same dispatch supersedes this one, whatever its value (F2)
  const last = rec && latestOutcomes(store.records).find((r) => outcomeKey(r) === outcomeKey(rec));
  if (last && last !== rec) return `${ref.path} is superseded by outcome record ${ref.task} seq ${last.seq} (${outcomeValue(last) ?? last.detail}) for the same dispatch (seq ${rec['dispatch-seq']})`;
  const ts = isoMs(o.ts) !== null ? o.ts : rec?.ts;
  if (isoMs(ts) === null) return `${ref.path} has no recorded time (no ts in the Outcome, no outcome record ${ref.task} seq ${ref.seq} in ${ledgerPath(dir)})`;
  if (isoOf(isoMs(ts)).slice(0, 10) !== ref.date) return `${ref.path} was recorded ${ts}, not on ${ref.date}`;
  const m = store.catMap[ref.task];
  if (!m) return `no decision file for ${ref.task} in ${join(dir, 'decisions')}`;
  if (m.category !== ref.category) return `${ref.task} was decided as ${m.category}, not ${ref.category}`;
  // the tier of the decision the outcome's dispatch was made under (as learn() counts it), else the task's latest
  const disp = rec && store.records.find((r) => r.kind === 'dispatch' && r['task-id'] === ref.task && r.seq === rec['dispatch-seq']);
  const declared = disp && Object.hasOwn(m.declared, disp['decision-seq']) ? m.declared[disp['decision-seq']] : m.latestDeclared;
  const tier = ref.tier ?? 'T1';
  if (declared) {
    if (declared !== tier) return `${ref.task} was decided at ${declared}, not ${tier}`;
  } else if (ref.tier && !new RegExp(`(^|[^\\w])would be ${ref.tier} by the table`).test(ref.note)) {
    return `the decision of ${ref.task} carries no difficulty tier, so the line must say 'would be ${ref.tier} by the table'`;
  }
  return null;
}

function validatePolicy(p, baseDir) {
  const fail = (m) => { throw invalid(`invalid policy: ${m}`); };
  if (!p || typeof p !== 'object') fail('not an object');
  if (!isStr(p.harness?.id)) fail('harness.id missing');
  // ADR-0003: the upstream block is `holdshort`. Only the archived host-policy-1..5 keep the old key; a later policy
  // carrying it has not migrated and would bind `holdshort: null` into every decision without a word
  if (p.smartrouter !== undefined && !/^host-policy-[1-5]$/.test(p['policy-revision'] ?? '')) fail('the upstream block is named smartrouter; rename it holdshort (ADR-0003; only the archived host-policy-1..5 keep the old name)');
  const a = p.authorization;
  if (!a || !isStrArray(a['data-classes-permitted']) || !isStrArray(a['data-classes-forbidden']) || !isStrArray(a.destinations)) fail('authorization data classes or destinations missing');
  if (!isStrArray(a['project-stop-rules']) || a['project-stop-rules'].length < 3) fail('authorization.project-stop-rules needs the red-suite, gate-off and research-gate rules');
  if (!ISOLATION.includes(p.isolation?.capability)) fail('isolation.capability is not on the lattice');
  const s = p.accounting?.strict;
  if (!s || !isInt(s['calls-per-task'], 1) || !isInt(s['same-profile-repairs-per-task']) || !(s['deadline-per-task-hours'] > 0)) fail('accounting.strict incomplete');
  if (!p.prices || typeof p.prices !== 'object') fail('prices missing');
  if (!p.categories || typeof p.categories !== 'object') fail('categories missing');
  if (p['difficulty-tiers'] !== undefined && p['difficulty-tiers'] !== TIERS_ENFORCED) fail(`difficulty-tiers must be "${TIERS_ENFORCED}" when present (absent: untiered); got ${JSON.stringify(p['difficulty-tiers'])}`);
  if (p.evidence !== undefined && p.evidence !== EVIDENCE_TYPED) fail(`evidence must be "${EVIDENCE_TYPED}" when present (absent: free-text evidence accepted); got ${JSON.stringify(p.evidence)}`);
  for (const [id, c] of Object.entries(p.categories)) {
    if (!isStrArray(c.verification) || !isStrArray(c['required-tools']) || !isInt(c['median-tokens'], 1) || !isStr(c.risk)) fail(`category ${id} incomplete`);
  }
  if (!Array.isArray(p.profiles) || p.profiles.length === 0) fail('profiles missing');
  const ids = new Set();
  const stores = new Map();
  // per profile, what its typed evidence supports (E2): PASS grade entries and resolved references, by category and tier
  const supports = new Map();
  for (const pr of p.profiles) {
    if (!isStr(pr.id) || !isStr(pr.model) || !isStr(pr.effort) || !isStr(pr.config) || !isStrArray(pr['qualified-for'])) fail(`profile ${pr.id} incomplete`);
    if (ids.has(pr.id)) fail(`duplicate profile ${pr.id}`);
    ids.add(pr.id);
    // a qualification names a category the policy has: a misspelt one would silently never qualify. An entry may carry
    // a tier (D2), and a category is held once: two entries for it (bare and tiered, or two tiers) would make the tier ambiguous
    const held = new Map();
    for (const c of pr['qualified-for']) {
      const q = parseQualification(c);
      if (!q) fail(`profile ${pr.id} qualified-for entry '${c}' is not '<category>' or '<category>@T1|T2|T3'`);
      if (!Object.hasOwn(p.categories, q.category)) fail(`profile ${pr.id} qualified-for names unknown category '${q.category}'`);
      if (held.has(q.category)) fail(`profile ${pr.id} qualified-for names ${q.category} twice ('${held.get(q.category)}', '${c}'): one entry per category`);
      held.set(q.category, c);
    }
    if (pr.evidence !== undefined && !isStrArray(pr.evidence)) fail(`profile ${pr.id} evidence must be an array of strings`);
    // a calibration grade entry (host-policy-2) is counted by the lead's qualification rules, so its form is fixed; a
    // typed production reference (E1, a line starting 'outcome:') is checked for form, then resolved against its store
    const typedSupport = [];
    supports.set(pr.id, typedSupport);
    for (const e of pr.evidence ?? []) {
      if (e.startsWith('outcome:')) {
        const { ref, why } = referenceForm(e, p.categories);
        if (why) fail(`profile ${pr.id} evidence '${e}' ${why}`);
        const unresolved = resolveReference(ref, pr, baseDir, stores);
        if (unresolved) fail(`profile ${pr.id} evidence '${e}' cannot be resolved: ${unresolved}`);
        typedSupport.push({ category: ref.category, tier: tierRank(ref.tier ?? 'T1') });
        continue;
      }
      if (!e.startsWith('calibration-')) continue;
      const m = CALIBRATION_ENTRY.exec(e);
      if (!m) fail(`profile ${pr.id} evidence '${e}' is not 'calibration-<n>: <category> PASS|PARTIAL|FAIL (n=<k>)'`);
      if (!Object.hasOwn(p.categories, m[2])) fail(`profile ${pr.id} evidence '${e}' names unknown category '${m[2]}'`);
      // a PARTIAL or FAIL grade supports nothing (E2); a tierless grade is T1
      if (m[4] === 'PASS') typedSupport.push({ category: m[2], tier: tierRank(m[3] ?? 'T1') });
    }
  }
  const e = p.economics;
  if (!e || !ids.has(e['lead-direct-profile']) || !isInt(e['direct-max-tokens']) || !isInt(e['delegate-overhead-tokens'])) fail('economics incomplete');
  const lead = p.profiles.find((x) => x.id === e['lead-direct-profile']);
  if (!(p.prices[lead.model]?.output_rate_per_mtok >= 0)) fail('the lead-direct profile has no price; brief overhead cannot be bounded');
  // E2: under "evidence": "typed" every qualified-for entry needs a PASS grade entry or an accepted reference for its
  // category at its tier or above (untiered: of its category). The validator counts no passes; the lead's rules do.
  // E3: the lead-direct profile is exempt - its qualifications are the operator's authorization of the lead's own inline
  // work, not a capability claim about a delegate (policy finding and friction item 23 of host-policy-6)
  if (p.evidence === EVIDENCE_TYPED) {
    const tiered = tiersEnforced(p);
    for (const pr of p.profiles) {
      if (pr.id === e['lead-direct-profile']) continue;
      for (const c of pr['qualified-for']) {
        const q = parseQualification(c);
        const k = tiered ? tierRank(q.tier ?? 'T1') : 0;
        if (supports.get(pr.id).some((s) => s.category === q.category && s.tier >= k)) continue;
        fail(`profile ${pr.id} qualified-for '${c}' has no typed evidence behind it (a PASS grade entry or an accepted outcome reference for ${q.category}${tiered ? ` at T${Math.max(k, 1)} or above` : ''}; free text supports nothing)`);
      }
    }
  }
  if (p['usage-windows'] !== undefined) validateUsageWindows(p['usage-windows'], fail);
}

// the optional usage-windows block: when present it is required whole. Unknown is not allowed for a coefficient: a
// window with no coefficient cannot be projected, so the lead declares one with its basis rather than gate blind
function validateUsageWindows(u, fail) {
  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
  if (!u || typeof u !== 'object' || Array.isArray(u)) fail('usage-windows must be an object');
  if (!isStr(u.source)) fail('usage-windows.source missing (where the reading comes from)');
  if (!(isNum(u['reading-max-age-minutes']) && u['reading-max-age-minutes'] > 0)) fail('usage-windows.reading-max-age-minutes must be a number > 0');
  if (!isStr(u['coefficient-basis'])) fail('usage-windows.coefficient-basis missing (the basis of the declared coefficients)');
  const ws = u.windows;
  if (!ws || typeof ws !== 'object' || Array.isArray(ws) || Object.keys(ws).length === 0) fail('usage-windows.windows must name at least one window');
  for (const [name, w] of Object.entries(ws)) {
    const at = `usage-windows.windows.${name}`;
    if (!w || typeof w !== 'object') fail(`${at} must be an object`);
    if (!isInt(w['length-seconds'], 1)) fail(`${at}.length-seconds must be a positive integer`);
    if (!(isNum(w['stop-at']) && w['stop-at'] > 0 && w['stop-at'] <= 1)) fail(`${at}.stop-at must be in (0, 1]`);
    if (!(isNum(w['lead-reserve']) && w['lead-reserve'] >= 0 && w['lead-reserve'] < w['stop-at'])) fail(`${at}.lead-reserve must be in [0, stop-at) (lead-reserve ${w['lead-reserve']}, stop-at ${w['stop-at']})`);
    if (!(isNum(w['utilization-per-mtok']) && w['utilization-per-mtok'] > 0)) fail(`${at}.utilization-per-mtok must be a finite number > 0 (a window with no coefficient cannot be projected; declare one with its basis)`);
    if (w['ratified-at'] !== undefined && w['ratified-at'] !== null && isoMs(w['ratified-at']) === null) fail(`${at}.ratified-at must be ISO-8601 when present (the time the current coefficient was ratified; rate considers only observations after it)`);
  }
}

function profileTuple(policy, pr) {
  return `(${pr.id}, ${policy.harness.id}, ${PROVIDER}, ${pr.model}, ${pr.effort}, ${pr.config})`;
}
// same-profile identity for repairs: the tuple without the host id, so a renamed profile with the same
// harness, provider, model, effort and config is still the same profile (spec-v2 §11.9, brief-and-result.md)
function sameKey(tuple) {
  return typeof tuple === 'string' ? tuple.replace(/^\([^,]+, /, '(') : null;
}
function tupleId(tuple) {
  if (typeof tuple !== 'string') return null;
  const m = /^\(([^,]+),/.exec(tuple);
  return m ? m[1].trim() : tuple;
}
const outRate = (policy, pr) => {
  const r = policy.prices[pr.model]?.output_rate_per_mtok;
  return typeof r === 'number' && r >= 0 ? r : null;
};
function optInsOf(policy, override) {
  const o = { ...policy['host-opt-ins'], ...(override ?? {}) };
  if (typeof o.speculative !== 'boolean') throw invalid('host opt-in speculative must be boolean');
  if (typeof o['nested-allowed'] !== 'boolean') throw invalid('host opt-in nested-allowed must be boolean');
  if (![0, 1, 2].includes(o['max-nesting-depth'])) throw invalid('host opt-in max-nesting-depth must be 0, 1 or 2');
  if (!HUMAN_GATES.includes(o['human-gate'])) throw invalid(`host opt-in human-gate must be one of ${HUMAN_GATES.join(', ')}`);
  return o;
}

// ---------------------------------------------------------------------------------------------
// validation of §10 objects and of the request
// ---------------------------------------------------------------------------------------------
export function validateOutcome(o) {
  const fail = (m) => { throw invalid(`invalid Outcome (spec-v2 §10.3): ${m}`); };
  if (!o || typeof o !== 'object' || Array.isArray(o)) fail('not an object');
  if (!isStr(o['task-id']) || !TASK_ID.test(o['task-id'])) fail('task-id');
  if (!OUTCOMES.includes(o.outcome)) fail(`outcome must be one of ${OUTCOMES.join(' | ')}`);
  const ev = o.evidence;
  if (!ev || typeof ev !== 'object') fail('evidence');
  if (!Array.isArray(ev.checks) || !ev.checks.every((c) => c && typeof c.command === 'string' && Number.isInteger(c['exit-code']) && typeof c['output-ref'] === 'string')) fail('evidence.checks');
  // estimate-only host: actual spend is unknown, so null is the honest value (decision-trace.md §1)
  if (!(ev['actual-spend'] === null || (typeof ev['actual-spend'] === 'number' && ev['actual-spend'] >= 0))) fail('evidence.actual-spend');
  // additive (spec-v2 §13): the tokens the unit actually used, for the usage-window learning in rate
  if (!(ev['actual-tokens'] === undefined || ev['actual-tokens'] === null || isInt(ev['actual-tokens']))) fail('evidence.actual-tokens (an integer >= 0, or null = unknown)');
  // Holdshort Item 4: a basis other than "estimate-only" is a violation upstream (conform_spec.py); null = no basis
  if (!(ev['actual-spend-basis'] == null || ev['actual-spend-basis'] === ESTIMATE_ONLY)) fail(`evidence.actual-spend-basis must be "${ESTIMATE_ONLY}" when present (Holdshort Item 4)`);
  if (!isStrArray(ev['files-touched'])) fail('evidence.files-touched');
  if (typeof ev.notes !== 'string') fail('evidence.notes');
  if (typeof o['original-brief-fingerprint'] !== 'string') fail('original-brief-fingerprint');
  if (!isStr(o['owner-profile'])) fail('owner-profile');
  return o;
}

export function validateBrief(b, { callsRemaining, repairsAllowed, now }) {
  const fail = (m) => { throw new RouterError(2, `refusing to emit an invalid Brief (spec-v2 §10.1, §14): ${m}`); };
  if (!isStr(b.objective)) fail('objective');
  if (!Array.isArray(b.acceptance?.checks) || b.acceptance.checks.length === 0 || !b.acceptance.checks.every((c) => isStr(c.command) && isStr(c.expect))) fail('acceptance.checks');
  for (const k of ['sources', 'permitted-effects', 'non-goals', 'stop-triggers']) if (!isStrArray(b[k])) fail(k);
  if (!ISOLATION.includes(b.isolation)) fail('isolation');
  if (!isStr(b['branch-hint'])) fail('branch-hint');
  const al = b.allowance;
  if (!al || typeof al.cash !== 'number' || al.cash < 0) fail('allowance.cash');
  if (!isInt(al.calls, 1) || al.calls > callsRemaining) fail(`allowance.calls ${al?.calls} exceeds the ${callsRemaining} remaining call slots`);
  const dl = isoMs(al.deadline);
  if (dl === null || !(Date.parse(now) < dl)) fail('allowance.deadline');
  if (!isInt(b.attempts) || b.attempts > repairsAllowed) fail('attempts');
  if (b.ownership !== 'worker') fail('ownership');
  if (b['nested-allowed'] !== false) fail('nested-allowed: this host cannot produce or enforce a NestedBrief');
  if (b['max-nesting-depth'] !== 1) fail('max-nesting-depth');
  return b;
}

function validateSpeculativeSet(s, { callsRemaining }) {
  const fail = (m) => { throw new RouterError(2, `refusing to emit an invalid SpeculativeSet (spec-v2 §10.2): ${m}`); };
  if (!Array.isArray(s.candidates) || s.candidates.length < 2 || !s.candidates.every((c) => isStr(c.profile) && typeof c.weight === 'number')) fail('candidates');
  if (!isInt(s['max-parallel'], 2) || s['max-parallel'] > s.candidates.length) fail('max-parallel');
  if (typeof s['shared-budget']?.cash !== 'number' || !isInt(s['shared-budget'].calls, 2) || s['shared-budget'].calls > callsRemaining) fail('shared-budget');
  if (!['first-success', 'budget-exhausted', 'all-fail'].includes(s['cancel-policy'])) fail('cancel-policy');
  if (s['winner-owns'] !== true) fail('winner-owns');
  return s;
}

function validateLedgerRecord(r) {
  if (!r || typeof r !== 'object' || Array.isArray(r)) return 'not an object';
  if (!isStr(r['task-id'])) return 'task-id';
  if (!isInt(r.seq, 1)) return 'seq';
  if (!KINDS.includes(r.kind)) return 'kind';
  if (isoMs(r.ts) === null) return 'ts';
  if (!(r.profile === null || isStr(r.profile))) return 'profile';
  const c = r.counters;
  if (!c || !isInt(c['calls-used']) || !isInt(c['calls-limit']) || c['calls-used'] > c['calls-limit']) return 'counters.calls';
  if (!isInt(c['repairs-used']) || !isInt(c['repairs-allowed']) || c['repairs-used'] > c['repairs-allowed']) return 'counters.repairs';
  for (const k of ['cash-spent', 'cash-cap']) if (!(c[k] === null || typeof c[k] === 'number')) return `counters.${k}`;
  if (!(r.deadline === null || isoMs(r.deadline) !== null)) return 'deadline';
  if (!(r['brief-fingerprint'] === null || FINGERPRINT.test(r['brief-fingerprint']))) return 'brief-fingerprint';
  if (typeof r.detail !== 'string') return 'detail';
  if (!(r['outcome-ref'] === null || isStr(r['outcome-ref']))) return 'outcome-ref';
  return null;
}

function validateRequest(r, policy) {
  const fail = (m) => { throw invalid(`invalid request: ${m}`); };
  if (!r || typeof r !== 'object' || Array.isArray(r)) fail('not an object');
  if (!isStr(r.taskId) || !TASK_ID.test(r.taskId)) fail('taskId must match [A-Za-z0-9][A-Za-z0-9._-]*');
  for (const k of ['objective', 'category', 'unit']) if (!isStr(r[k])) fail(k);
  for (const k of ['permittedEffects', 'sources', 'nonGoals', 'dataClasses']) if (!isStrArray(r[k])) fail(`${k} must be an array of strings`);
  // Gate 1 is default-deny and a read-only call still transmits prompt bytes (gates.md Gate 1): every dispatch
  // sends at least the objective and sources, so a request that declares no data has nothing Gate 1 can permit
  if (r.dataClasses.length === 0) fail('declare at least one data class');
  if (!Array.isArray(r.acceptanceChecks) || !r.acceptanceChecks.every((c) => c && isStr(c.command) && isStr(c.expect))) fail('acceptanceChecks must be [{command, expect}]');
  if (r.estimatedTokens !== undefined && !isInt(r.estimatedTokens, 1)) fail('estimatedTokens');
  if (r.requiredTools !== undefined && !isStrArray(r.requiredTools)) fail('requiredTools');
  if (typeof r.needsVision !== 'boolean') fail('needsVision must be boolean');
  const ps = r.projectStop;
  if (!isProjectStop(ps)) fail('projectStop needs boolean redSuite, gateOff, researchGateFailing');
  if (r.previousResult !== null && r.previousResult !== undefined) {
    validateOutcome(r.previousResult);
    if (r.previousResult['task-id'] !== r.taskId) fail('previousResult.task-id differs from taskId');
    const owner = r.previousResult['owner-profile'];
    if (!TUPLE.test(owner) && !policy.profiles.some((p) => p.id === owner)) fail('previousResult.owner-profile is neither a policy profile id nor an identity tuple');
  }
  if (isoMs(r.deadline) === null) fail('deadline must be ISO-8601');
  if (isoMs(r.now) === null) fail('now must be ISO-8601');
  if (r.candidates !== undefined && (!isStrArray(r.candidates) || r.candidates.length === 0 || new Set(r.candidates).size !== r.candidates.length)) fail('candidates must be a non-empty list of distinct ids');
  if (r.allowDirect !== undefined && typeof r.allowDirect !== 'boolean') fail('allowDirect');
  if (r.hostOptIns !== undefined && (typeof r.hostOptIns !== 'object' || r.hostOptIns === null)) fail('hostOptIns');
  if (r.uncertainty !== undefined && typeof r.uncertainty !== 'string') fail('uncertainty');
  if (r.requiredIsolation !== undefined && !ISOLATION.includes(r.requiredIsolation)) fail('requiredIsolation');
  // D3: the form is checked under any policy; the floor only under an enforced one (requestTier)
  if (r.difficultyTier !== undefined && !TIERS.includes(r.difficultyTier)) fail(`difficultyTier must be "T1", "T2" or "T3" when present (got ${JSON.stringify(r.difficultyTier)})`);
}

// the floor (D3, proposal Item 1 rule 1): the mechanical part of the tier predicates, from the request's structural
// fields only. The edit set is permittedEffects without the architecture map; docs-mechanical is always T1
function tierFloor(r) {
  if (r.category === 'docs-mechanical') return { tier: 'T1', reason: 'docs-mechanical is always T1' };
  const edits = r.permittedEffects.filter((p) => !p.endsWith('ARCHITECTURE.md')).length;
  const t3 = [];
  if (r.uncertainty === 'high') t3.push('uncertainty high');
  if (edits > 3) t3.push(`edit set of ${edits} files, more than three`);
  if (t3.length) return { tier: 'T3', reason: t3.join('; ') };
  if (edits === 3) return { tier: 'T2', reason: 'edit set of exactly three files' };
  return { tier: 'T1', reason: `edit set of ${edits} file${edits === 1 ? '' : 's'}` };
}

// the request's difficulty tier under the policy (D3). Untiered: tier null, nothing enforced. Enforced: a declared tier
// below the floor is an invalid request; at or above it, it is accepted as given; undeclared reads the proposal's
// default (T3 for a high-risk category - an unknown one counts as high, as Difficulty does - T2 otherwise), raised to the floor
export function requestTier(r, policy) {
  const declared = r.difficultyTier ?? null;
  if (!tiersEnforced(policy)) return { tier: null, declared, floor: null, default: null };
  const floor = tierFloor(r);
  if (declared && tierRank(declared) < tierRank(floor.tier)) {
    throw invalid(`invalid request: difficultyTier ${declared} is below the floor ${floor.tier} (${floor.reason}); a declared tier above the floor is accepted as given, one below it never`);
  }
  const category = Object.hasOwn(policy.categories, r.category) ? policy.categories[r.category] : null;
  const def = !category || category.risk === 'high' ? 'T3' : 'T2';
  const tier = declared ?? (tierRank(floor.tier) > tierRank(def) ? floor.tier : def);
  return { tier, declared, floor: floor.tier, default: def };
}

// ---------------------------------------------------------------------------------------------
// ledger
// ---------------------------------------------------------------------------------------------
const ledgerPath = (traceDir) => join(traceDir, 'ledger.jsonl');

export function readLedger(traceDir = DEFAULT_TRACE) {
  const path = ledgerPath(traceDir);
  if (!existsSync(path)) return [];
  const text = readFileSync(path, 'utf8');
  // an append onto an unterminated last line would itself write an unparseable line, repairable only by a rewrite
  if (text.length && !text.endsWith('\n')) throw new RouterError(4, `ledger does not end with a newline (last line unterminated, probably hand-written); refusing to read or append (${path}); the lead terminates the last line, which changes no record`);
  const lines = text.split('\n');
  lines.pop();
  const lastSeq = new Map();
  return lines.map((line, i) => {
    let rec;
    try { rec = JSON.parse(line); } catch { throw new RouterError(4, `ledger line ${i + 1} is unparseable; refusing to read or append (${path})`); }
    const why = validateLedgerRecord(rec);
    if (why) throw new RouterError(4, `ledger line ${i + 1} is not a §10.5 LedgerRecord (${why}); refusing to read or append`);
    const prev = lastSeq.get(rec['task-id']) ?? 0;
    if (rec.seq !== prev + 1) throw new RouterError(4, `ledger line ${i + 1}: seq ${rec.seq} for ${rec['task-id']} does not follow ${prev}; refusing to read or append`);
    lastSeq.set(rec['task-id'], rec.seq);
    return rec;
  });
}

// Holdshort Item 4 (docs/proposals/usage-windows-gate4.md, accepted upstream 2026-10-18): §10.5's null cash counters
// conform only beside counters["cash-basis"] == "estimate-only", and §10.3's null actual-spend only beside
// evidence["actual-spend-basis"] == "estimate-only". The policy's accounting.mode says whether this host is estimate-only
export const ESTIMATE_ONLY = 'estimate-only';
const estimateOnly = (policy) => policy.accounting?.mode === ESTIMATE_ONLY;

// every record goes through here, so every record of an estimate-only host carries the marker; decision files and
// status keep §10.5's six counters (the marker is additive to records, spec-v2 §13). Lines already in the ledger are
// never rewritten: those written before Item 4 stay unmarked
function appendRecord(traceDir, policy, rec) {
  const marked = estimateOnly(policy) ? { ...rec, counters: { ...rec.counters, 'cash-basis': ESTIMATE_ONLY } } : rec;
  const why = validateLedgerRecord(marked);
  if (why) throw new RouterError(2, `refusing to append an invalid LedgerRecord (${why})`);
  mkdirSync(traceDir, { recursive: true });
  appendFileSync(ledgerPath(traceDir), `${JSON.stringify(marked)}\n`);
  return marked;
}

const isDeviation = (r) => r.deviation === true || /^host deviation/.test(r.detail);

// ---------------------------------------------------------------------------------------------
// usage windows: the subscription's rolling limits (rate_limit_event -> rate_limit_info.unifiedWindows), pasted by
// the lead into trace/usage.jsonl (append-only, separate from the ledger) and projected in Gate 4
// ---------------------------------------------------------------------------------------------
const usagePath = (traceDir) => join(traceDir, 'usage.jsonl');
const USAGE_REFRESH = 'refresh with route.mjs usage';
const minutesOf = (ms) => Math.round(ms / 600) / 100;

function usageConfig(policy) {
  const u = policy['usage-windows'];
  if (u === undefined) throw invalid('usage windows are not configured in the policy (no usage-windows block)');
  return u;
}

export function readUsage(traceDir = DEFAULT_TRACE) {
  const path = usagePath(traceDir);
  if (!existsSync(path)) return [];
  const text = readFileSync(path, 'utf8');
  if (text.length && !text.endsWith('\n')) throw new RouterError(4, `usage.jsonl does not end with a newline (last line unterminated); refusing to read or append (${path})`);
  const lines = text.split('\n');
  lines.pop();
  return lines.map((line, i) => {
    let rec;
    try { rec = JSON.parse(line); } catch { throw new RouterError(4, `usage.jsonl line ${i + 1} is unparseable; refusing to read or append (${path})`); }
    const ok = rec && isoMs(rec.ts) !== null && rec.windows && typeof rec.windows === 'object'
      && Object.values(rec.windows).every((w) => w && typeof w.utilization === 'number' && isoMs(w['resets-at']) !== null);
    if (!ok) throw new RouterError(4, `usage.jsonl line ${i + 1} is not a usage reading; refusing to read or append (${path})`);
    return rec;
  });
}

// the three accepted forms: rate_limit_info, its bare unifiedWindows, or { windows: { <w>: { utilization, resets-at } }, note }
function normaliseReading(raw, cfg, ts) {
  const fail = (m) => { throw invalid(`invalid usage reading: ${m}`); };
  const isObj = (v) => Boolean(v) && typeof v === 'object' && !Array.isArray(v);
  if (!isObj(raw)) fail('expected rate_limit_info, its unifiedWindows, or { windows: { <name>: { utilization, resets-at } } }');
  let src = raw;
  let note = null;
  if (isObj(raw.unifiedWindows)) src = raw.unifiedWindows;
  else if (isObj(raw.windows)) { src = raw.windows; note = isStr(raw.note) ? raw.note : null; }
  const tsMs = isoMs(ts);
  const windows = {};
  // only the windows the policy names are recorded: the policy decides which windows bind
  for (const [name, w] of Object.entries(cfg.windows)) {
    const e = src[name];
    if (!isObj(e)) fail(`window ${name} (named in the policy) is missing`);
    const u = e.utilization;
    if (!(typeof u === 'number' && Number.isFinite(u) && u >= 0 && u <= 1)) fail(`${name} utilization ${JSON.stringify(u)} is not a number in [0, 1]`);
    let rMs = null;
    if (typeof e.resetsAt === 'number' && Number.isFinite(e.resetsAt) && e.resetsAt > 0) rMs = e.resetsAt * 1000;
    else if (isoMs(e['resets-at']) !== null) rMs = isoMs(e['resets-at']);
    if (rMs === null) fail(`${name} resets-at missing or not a time (resetsAt in epoch seconds, or resets-at ISO-8601)`);
    const shown = typeof e.resetsAt === 'number' ? `${e.resetsAt} (epoch seconds)` : e['resets-at'];
    if (!(rMs > tsMs)) fail(`${name} resets-at ${rMs > 0 && rMs < 8.64e15 ? isoOf(rMs) : shown} is not strictly after the reading ts ${ts}`);
    // a rolling window resets within one window length of any moment in it (catches milliseconds pasted as seconds)
    if (rMs - tsMs > w['length-seconds'] * 1000) fail(`${name} resets-at ${shown} is more than one window length (${w['length-seconds']} s) after the reading ts ${ts}`);
    windows[name] = { utilization: u, 'resets-at': typeof e.resetsAt === 'number' ? isoOf(rMs) : e['resets-at'] };
  }
  return { windows, note };
}

export function recordUsage(raw, { policyPath = DEFAULT_POLICY, traceDir = DEFAULT_TRACE, now = new Date().toISOString() } = {}) {
  if (isoMs(now) === null) throw invalid('--now must be ISO-8601');
  const cfg = usageConfig(loadPolicy(policyPath));
  const readings = readUsage(traceDir);
  const prev = readings[readings.length - 1];
  // readings are monotonic, like the ledger clock
  if (prev && !(isoMs(now) > isoMs(prev.ts))) throw invalid(`invalid usage reading: ts ${now} does not follow the previous reading's ts ${prev.ts} (readings are monotonic)`);
  const { windows, note } = normaliseReading(raw, cfg, now);
  const rec = { ts: now, windows, source: 'rate_limit_event', note };
  mkdirSync(traceDir, { recursive: true });
  appendFileSync(usagePath(traceDir), `${JSON.stringify(rec)}\n`);
  return rec;
}

// the latest reading taken at or before `now`: a later reading says nothing about an earlier decision
function latestReading(readings, nowMs) {
  let best = null;
  for (const r of readings) if (isoMs(r.ts) <= nowMs && (!best || isoMs(r.ts) > isoMs(best.ts))) best = r;
  return best;
}

const usageLimit = (w) => w['stop-at'] - w['lead-reserve'];
const headroomMtok = (w, u, since = 0) => round4((usageLimit(w) - u) / w['utilization-per-mtok'] - since / 1e6);

// the tokens committed and not in the reading (SW-2, SW-7): every dispatch, of any task, recorded at or before `now`
// that the reading cannot hold in full. That is (a) a dispatch recorded after the reading's ts, finished or not, and
// (b) a dispatch recorded at or before it with no outcome at or before it: a unit in flight when the reading was
// taken keeps consuming after it, so it counts at its full usage-tokens (an over-count of the part the reading
// already holds, the safe direction) until a reading taken at or after its outcome. `exclude` drops the dispatches a
// decision's own sum already covers (the other members of a speculative set). A dispatch with no usage-tokens
// (recorded with the feature off) is unknown.
function dispatchedSince(records, reading, nowMs, exclude = () => false) {
  const since = { tokens: 0, after: 0, inFlight: 0, unknown: null };
  if (!reading) return since;
  const fromMs = isoMs(reading.ts);
  const closedBy = (d) => records.some((o) => o.kind === 'outcome' && o['task-id'] === d['task-id'] && o.seq > d.seq
    && o['dispatch-seq'] === d.seq && isoMs(o.ts) <= fromMs);
  for (const r of records) {
    if (r.kind !== 'dispatch' || exclude(r)) continue;
    const ms = isoMs(r.ts);
    if (!(ms <= nowMs)) continue;
    const after = ms > fromMs;
    if (!after && closedBy(r)) continue;
    if (!isInt(r['usage-tokens'])) { since.unknown ??= { ...r, inFlight: !after }; continue; }
    since.tokens += r['usage-tokens'];
    if (after) since.after += r['usage-tokens']; else since.inFlight += r['usage-tokens'];
  }
  return since;
}

const unknownReason = (reading, d) => (d.inFlight
  ? `usage reading ${reading.ts} does not hold dispatch seq ${d.seq} of ${d['task-id']} (in flight since ${d.ts}, no outcome before the reading), whose usage-tokens are unknown; record its outcome, then ${USAGE_REFRESH}`
  : `usage reading ${reading.ts} predates dispatch seq ${d.seq} of ${d['task-id']}, whose usage-tokens are unknown; ${USAGE_REFRESH}`);

// Gate 4's usage steps, in order: (1) a fresh reading, (2) no window reset since it, (3) every window's projection
// within stop-at - lead-reserve, counting the tokens dispatched and not in the reading. Returns { reason } on the first
// failure, else each window's projection and the binding one
function usageWalk(cfg, reading, nowMs, tokens, deadlineMs, since = { tokens: 0, unknown: null }) {
  if (!reading) return { reason: 'usage reading missing' };
  const age = nowMs - isoMs(reading.ts);
  if (age > cfg['reading-max-age-minutes'] * 60000) return { reason: `usage reading stale: age ${minutesOf(age)} min > ${cfg['reading-max-age-minutes']}; ${USAGE_REFRESH}` };
  for (const name of Object.keys(cfg.windows)) {
    const r = reading.windows[name];
    if (!r) return { reason: `usage reading has no window ${name}; ${USAGE_REFRESH}` };
    if (!(nowMs < isoMs(r['resets-at']))) return { reason: `usage window ${name} reset at ${r['resets-at']} after the reading; ${USAGE_REFRESH}` };
  }
  if (since.unknown) return { reason: unknownReason(reading, since.unknown) };
  const projected = {};
  let binding = null;
  for (const [name, w] of Object.entries(cfg.windows)) {
    const r = reading.windows[name];
    const p = r.utilization + ((since.tokens + tokens) / 1e6) * w['utilization-per-mtok'];
    const limit = usageLimit(w);
    if (p - limit > 1e-12) {
      const defer = isoMs(r['resets-at']) < deadlineMs ? '; defer until the reset' : '';
      const with_ = since.tokens ? ` (with ${since.tokens} tokens dispatched and not in the reading)` : '';
      return { reason: `usage window ${name}: projected ${round4(p)}${with_} > ${round4(limit)} (stop-at ${w['stop-at']} - lead-reserve ${w['lead-reserve']}); resets ${r['resets-at']}${defer}` };
    }
    projected[name] = p;
    if (!binding || limit - p < binding.slack) binding = { name, slack: limit - p, projected: p, limit };
  }
  return { reason: null, projected, binding };
}

// the decision's usage block: the reading, its age, and per window the projection for the chosen profile (null if blocked)
function usageBlock(cfg, reading, nowMs, chosenProjected, since) {
  if (!reading) return { 'reading-ts': null, 'reading-age-minutes': null, 'dispatched-not-in-reading-tokens': null, windows: {} };
  const windows = {};
  for (const [name, w] of Object.entries(cfg.windows)) {
    const r = reading.windows[name];
    if (!r) continue;
    windows[name] = { utilization: r.utilization, 'resets-at': r['resets-at'], projected: chosenProjected ? round4(chosenProjected[name]) : null, 'headroom-mtok': headroomMtok(w, r.utilization, since.tokens) };
  }
  return { 'reading-ts': reading.ts, 'reading-age-minutes': minutesOf(nowMs - isoMs(reading.ts)), 'dispatched-not-in-reading-tokens': since.unknown ? null : since.tokens, windows };
}

export function usageSummary({ policyPath = DEFAULT_POLICY, traceDir = DEFAULT_TRACE, now = new Date().toISOString() } = {}) {
  const nowMs = isoMs(now);
  if (nowMs === null) throw invalid('--now must be ISO-8601');
  const cfg = usageConfig(loadPolicy(policyPath));
  const readings = readUsage(traceDir);
  const r = latestReading(readings, nowMs);
  if (!r) return { reading: null, text: `no usage reading recorded in ${usagePath(traceDir)}; paste one with route.mjs usage <reading.json>\n` };
  const age = nowMs - isoMs(r.ts);
  const max = cfg['reading-max-age-minutes'];
  const lines = [`latest usage reading ${r.ts} (age ${minutesOf(age)} min, max ${max})${age > max * 60000 ? `: stale; ${USAGE_REFRESH}` : ''}`];
  const since = dispatchedSince(readLedger(traceDir), r, nowMs);
  if (since.unknown) lines.push(`  dispatched and not in the reading: unknown (${unknownReason(r, since.unknown)})`);
  else if (since.tokens) lines.push(`  dispatched and not in the reading: ${since.tokens} tokens (${since.after} since the reading, ${since.inFlight} in flight from before it)`);
  const minus = since.tokens ? ` - ${round6(since.tokens / 1e6)} dispatched and not in the reading` : '';
  for (const [name, w] of Object.entries(cfg.windows)) {
    const x = r.windows[name];
    if (!x) { lines.push(`  ${name}: not in the reading; ${USAGE_REFRESH}`); continue; }
    if (!(nowMs < isoMs(x['resets-at']))) { lines.push(`  ${name}: utilization ${x.utilization}, resets ${x['resets-at']}: reset since the reading; ${USAGE_REFRESH}`); continue; }
    lines.push(`  ${name}: utilization ${x.utilization}, resets ${x['resets-at']}, headroom ${headroomMtok(w, x.utilization, since.tokens)} Mtok ((${w['stop-at']} - ${w['lead-reserve']} - ${x.utilization}) / ${w['utilization-per-mtok']}${minus})`);
  }
  return { reading: r, text: `${lines.join('\n')}\n` };
}

function taskState(records, taskId, policy) {
  const recs = records.filter((r) => r['task-id'] === taskId);
  const strict = policy.accounting.strict;
  const st = {
    records: recs, lastSeq: recs.length ? recs[recs.length - 1].seq : 0, callsUsed: 0, repairsUsed: 0,
    callsLimit: strict['calls-per-task'], repairsAllowed: strict['same-profile-repairs-per-task'],
    dispatched: new Map(), dispatchedKeys: new Map(), startMs: null, latestMs: null, latestTs: null, lastDecision: null, lastOutcomeSeq: 0, fingerprints: new Set()
  };
  for (const r of recs) {
    const ms = isoMs(r.ts);
    if (st.startMs === null || ms < st.startMs) st.startMs = ms;
    if (st.latestMs === null || ms > st.latestMs) { st.latestMs = ms; st.latestTs = r.ts; }
    if (r['brief-fingerprint']) st.fingerprints.add(r['brief-fingerprint']);
    if (r.kind === 'decision') st.lastDecision = r;
    if (r.kind === 'outcome') st.lastOutcomeSeq = r.seq;
    if (r.kind === 'dispatch') {
      st.callsUsed += 1;
      const key = sameKey(r.profile);
      if (st.dispatchedKeys.has(key)) st.repairsUsed += 1;
      st.dispatchedKeys.set(key, r);
      st.dispatched.set(tupleId(r.profile), r);
    }
  }
  return st;
}

// the task clock is monotonic (decision-trace.md §1): a stale `now` could otherwise dodge deadline expiry
function assertClock(st, now, taskId) {
  if (st.latestMs !== null && isoMs(now) < st.latestMs) throw invalid(`now ${now} precedes the latest ledger event for ${taskId} (${st.latestTs}); the task clock is monotonic`);
}

function counters(st, calls = st.callsUsed, repairs = st.repairsUsed) {
  return { 'calls-used': calls, 'calls-limit': st.callsLimit, 'cash-spent': null, 'cash-cap': null, 'repairs-used': repairs, 'repairs-allowed': st.repairsAllowed };
}

// per task: the category and the difficulty tier from its decision files (D7), and the tier of each decision by its ledger
// seq, so an outcome counts at the tier of the decision its dispatch was made under. A decision without a tier (every
// one before host-policy-5, or under an untiered policy) counts at T1
function categoryMap(traceDir) {
  const dir = join(traceDir, 'decisions');
  const map = {};
  if (!existsSync(dir)) return map;
  for (const f of readdirSync(dir).filter((x) => x.endsWith('.json')).sort()) {
    let j;
    try { j = JSON.parse(readFileSync(join(dir, f), 'utf8')); } catch { throw new RouterError(4, `decision file ${f} is unparseable`); }
    if (!(isStr(j?.request?.taskId) && isStr(j.request.category))) continue;
    const t = j.decision?.['difficulty-tier'];
    if (t !== undefined && !TIERS.includes(t)) throw new RouterError(4, `decision file ${f}: difficulty-tier ${JSON.stringify(t)} is not T1, T2 or T3`);
    const tier = t ?? 'T1';
    const entry = (map[j.request.taskId] ??= { tiers: {}, declared: {} });
    entry.category = j.request.category;
    entry.tier = tier;
    // the tier as the decision declares it, null for none (E1: a reference's tier is checked against a declared one only)
    entry.latestDeclared = t ?? null;
    if (isInt(j['ledger-seq'], 1)) {
      entry.tiers[j['ledger-seq']] = tier;
      entry.declared[j['ledger-seq']] = t ?? null;
    }
  }
  return map;
}

// ---------------------------------------------------------------------------------------------
// learning: outcome statistics and proposals (never applied; the lead edits host-policy.json)
// ---------------------------------------------------------------------------------------------
function outcomeValue(r) {
  const m = /^outcome ([a-z-]+)/.exec(r.detail);
  return m && OUTCOMES.includes(m[1]) ? m[1] : null;
}

// one outcome per dispatch: a later outcome for the same (task, dispatch seq) supersedes the earlier one
// (spec-v2 §10.5, decision-trace.md §4), so streams count dispatches, not records
// the dispatch an outcome record answers (a record without dispatch-seq stands alone)
const outcomeKey = (r) => `${r['task-id']}#${isInt(r['dispatch-seq'], 1) ? r['dispatch-seq'] : `record-${r.seq}`}`;
function latestOutcomes(records) {
  const latest = new Map();
  for (const r of records) {
    if (r.kind !== 'outcome') continue;
    const key = outcomeKey(r);
    latest.delete(key); // re-inserted at the superseding record's place in ledger order
    latest.set(key, r);
  }
  return [...latest.values()];
}

// under an enforced policy the streams are per (profile, category, tier) (D7, proposal 2.3-2.4): stats keys and proposals
// read '<category>@T<k>'; a profile is qualified at tier k when it holds the category at k or above. Untiered: per
// (profile, category), as before
function learn(policy, records, catMap, reference = () => null) {
  const tiered = tiersEnforced(policy);
  const stats = {};
  const streams = {};
  const dispatchBySeq = new Map(records.filter((r) => r.kind === 'dispatch').map((r) => [`${r['task-id']}#${r.seq}`, r]));
  for (const r of latestOutcomes(records)) {
    const value = outcomeValue(r);
    const pid = tupleId(r.profile);
    if (!value || !pid) continue;
    const m = catMap[r['task-id']];
    const entry = typeof m === 'string' ? { category: m, tier: 'T1', tiers: {}, declared: {}, latestDeclared: null } : m;
    const cat = entry?.category ?? 'unknown';
    const d = dispatchBySeq.get(`${r['task-id']}#${r['dispatch-seq']}`);
    // the tier of the decision the dispatch was made under, else the task's (a dispatch recorded without decision-seq)
    const tier = (d && entry?.tiers?.[d['decision-seq']]) || entry?.tier || 'T1';
    // the tier that decision declares, null for none: a typed reference to this outcome carries it, or none (E1, E7)
    const declared = (d && entry?.declared && Object.hasOwn(entry.declared, d['decision-seq']) ? entry.declared[d['decision-seq']] : entry?.latestDeclared) ?? null;
    const label = tiered && cat !== 'unknown' ? `${cat}@${tier}` : cat;
    stats[pid] ??= {};
    stats[pid][label] ??= { ...Object.fromEntries(OUTCOMES.map((o) => [o, 0])), deviations: 0 };
    const s = stats[pid][label];
    s[value] += 1;
    if (d && isDeviation(d)) s.deviations += 1;
    streams[pid] ??= {};
    streams[pid][label] ??= { cat, tier, list: [] };
    streams[pid][label].list.push({ value, task: r['task-id'], ms: isoMs(r.ts), seq: r.seq, declared });
  }
  const proposals = [];
  for (const pid of Object.keys(streams).sort()) {
    const pr = policy.profiles.find((p) => p.id === pid);
    if (!pr) continue;
    for (const label of Object.keys(streams[pid]).sort()) {
      const { cat, tier } = streams[pid][label];
      if (cat === 'unknown') continue;
      const qualified = tiered ? heldTier(pr, cat) >= tierRank(tier) : heldTier(pr, cat) > 0;
      const since = dayMs(pr['qualified-at']);
      const list = streams[pid][label].list.filter((o) => since === null || o.ms >= since);
      if (qualified) {
        let run = [];
        let hit = null;
        for (const o of list) {
          run = o.value === 'verification-failed' ? [...run, o.task] : [];
          if (run.length >= 2 && !hit) hit = run.slice(-2);
        }
        const overrun = list.filter((o) => o.value === 'cost-overrun').map((o) => o.task);
        if (hit) proposals.push({ kind: 'demote', profile: pid, category: label, reason: `2 consecutive verification-failed (${hit.join(', ')})` });
        else if (overrun.length) proposals.push({ kind: 'demote', profile: pid, category: label, reason: `cost-overrun (${overrun.join(', ')})` });
      } else {
        const accepted = list.filter((o) => o.value === 'accepted');
        const acc = accepted.map((o) => o.task);
        // E7: the typed references the lead would paste, one per accepted outcome behind the proposal
        const references = accepted.map((o) => reference(o, cat)).filter(Boolean);
        if (acc.length >= 3) proposals.push({ kind: 'qualify', profile: pid, category: label, reason: `${acc.length} accepted while unqualified (host deviations: ${acc.join(', ')})`, ...(references.length ? { references } : {}) });
      }
    }
  }
  return { stats, proposals };
}

// headroom-tested is the largest completed run, rounded up to the next thousand, never lowered: an accepted outcome
// (one per dispatch, the latest) whose recorded tokens exceed the profile's current value proposes the raise to them,
// rounded up. Unknown tokens (null) and other outcome values propose nothing. One proposal per profile, from its largest
// accepted run; never applied (deliverable F of sr-policy-3: the stale cc-opus-high headroom blocked its seq-1 decision)
function headroomProposals(policy, records) {
  const best = new Map();
  for (const r of latestOutcomes(records)) {
    if (outcomeValue(r) !== 'accepted' || !isInt(r.tokens)) continue;
    const pr = policy.profiles.find((p) => p.id === tupleId(r.profile));
    if (!pr || !isInt(pr['headroom-tested']) || !(r.tokens > pr['headroom-tested'])) continue;
    const prev = best.get(pr.id);
    if (!prev || r.tokens > prev.tokens) best.set(pr.id, { profile: pr.id, from: pr['headroom-tested'], to: Math.ceil(r.tokens / 1000) * 1000, tokens: r.tokens, task: r['task-id'] });
  }
  return [...best.values()].sort((a, b) => (a.profile < b.profile ? -1 : 1));
}

function expiryFlags(policy, nowMs) {
  const flags = [];
  for (const pr of policy.profiles) {
    const ex = dayMs(pr.expires);
    if (ex === null) continue;
    if (ex - nowMs <= EXPIRY_WARN_DAYS * 86400000) flags.push({ kind: 'expiry', profile: pr.id, reason: `qualification expires ${pr.expires} (within ${EXPIRY_WARN_DAYS} days of ${isoOf(nowMs)}); re-qualify with fresh evidence` });
  }
  return flags;
}

function proposalText(p) {
  const head = p.kind === 'demote' ? `demote ${p.profile} from ${p.category}` : p.kind === 'qualify' ? `qualify ${p.profile} for ${p.category}` : `re-qualify ${p.profile}`;
  return `${head}: ${p.reason}`;
}

// ---------------------------------------------------------------------------------------------
// the five gates
// ---------------------------------------------------------------------------------------------
function requiredIsolation(ctx, kind) {
  if (ctx.req.requiredIsolation) return ctx.req.requiredIsolation;
  return kind === 'direct' && ctx.category?.risk === 'low' ? 'none' : 'worktree+branch';
}

function gate1(ctx, pr, id, kind) {
  const a = ctx.policy.authorization;
  for (const c of ctx.req.dataClasses) {
    if (a['data-classes-forbidden'].includes(c)) return `data class '${c}' is forbidden (${a['data-classes-forbidden'].join(', ')}); denied before any transmission to ${PROVIDER}`;
  }
  for (const c of ctx.req.dataClasses) {
    if (!a['data-classes-permitted'].includes(c)) return `data class '${c}' not covered by authorization (default deny)`;
  }
  if (!pr) return `unknown profile '${id}' (default deny)`;
  if (!ctx.category) return `unknown category '${ctx.req.category}' (default deny)`;
  if (!a.destinations.some((d) => d.split(/\s/)[0] === PROVIDER)) return `destination ${PROVIDER} not covered by authorization`;
  for (const p of ctx.req.permittedEffects) {
    if (!isStr(p) || p.startsWith('/') || /^[A-Za-z]:/.test(p) || p.split(/[\\/]/).includes('..')) return `permitted effect '${p}' is outside the repository (unknown path, default deny)`;
  }
  const rules = a['project-stop-rules'];
  const stop = ctx.req.projectStop;
  if (stop.redSuite) return `project stop: ${rules[0]}`;
  if (stop.gateOff) return `project stop: ${rules[1]}`;
  if (stop.researchGateFailing) return `project stop: ${rules[2]}`;
  const need = requiredIsolation(ctx, kind);
  const cap = ctx.policy.isolation.capability;
  if (ISOLATION.indexOf(need) > ISOLATION.indexOf(cap)) return `isolation ${need} required; host provides at most ${cap}`;
  return null;
}

function fingerprintProblem(nowMs, pr) {
  if (!pr['qualified-at'] || !pr.expires) return `missing or stale capability fingerprint (${!pr['qualified-at'] ? 'qualified-at null' : 'expires null'})`;
  const ex = dayMs(pr.expires);
  if (ex === null || nowMs >= ex) return `missing or stale capability fingerprint (expired ${pr.expires})`;
  return null;
}

// the capability walk for one role: the work itself, or the required review (category 'review', its median, its tools).
// tier: the tier the role needs under an enforced policy (D4: held at that tier or above), null when untiered
function capabilities(ctx, pr, id, { category, tokens, tools, tier }) {
  // collect every capability reason, then fail once (run_gates in the fixture runner)
  const reasons = [];
  const fp = fingerprintProblem(ctx.nowMs, pr);
  if (fp) reasons.push(fp);
  const held = heldTier(pr, category);
  if (held === 0) reasons.push(`${id} not qualified for ${category}`);
  else if (tier && held < tierRank(tier)) reasons.push(`${id} not qualified for ${category}@${tier} (holds ${category}@T${held})`);
  const missing = pr.tools === true ? [] : Array.isArray(pr.tools) ? tools.filter((t) => !pr.tools.includes(t)) : tools;
  if (missing.length) reasons.push(`required tools missing on ${id}: ${missing.join(', ')}`);
  if (ctx.req.needsVision && pr.vision !== true) reasons.push(`vision required, ${id} lacks it`);
  const h = pr['headroom-tested'];
  if (!isInt(h, 1)) reasons.push(`context headroom untested on ${id}`);
  else if (!(tokens < h)) reasons.push(`context: ${tokens} tokens not below headroom-tested ${h} on ${id}`);
  return reasons.length ? reasons.join('; ') : null;
}

function gate2(ctx, pr, id) {
  return capabilities(ctx, pr, id, { category: ctx.req.category, tokens: ctx.tokens, tools: ctx.requiredTools, tier: ctx.tier });
}

function gate3(ctx) {
  const checks = ctx.req.acceptanceChecks;
  const has = (name) => checks.some((c) => c.command.toLowerCase().includes(name.toLowerCase()) || c.expect.toLowerCase().includes(name.toLowerCase()));
  const missing = ctx.category.verification.filter((n) => !has(n));
  if (missing.length) return `verification prerequisite missing: ${missing.join(', ')} (blocked before start)`;
  if (ctx.reviewName && !ctx.reviewer) {
    const why = Object.entries(ctx.reviewWalk).map(([rid, r]) => `${rid}: ${r}`).join('; ') || 'no candidate other than the lead';
    return `verification prerequisite missing: no candidate passes Gates 1-2 as reviewer for '${ctx.reviewName}' (${why}) (blocked before start)`;
  }
  return null;
}

function bounds(ctx, pr, kind) {
  const rate = outRate(ctx.policy, pr);
  if (rate === null) return null;
  const work = (ctx.tokens * rate) / 1e6;
  if (kind === 'direct') return { work, review: 0, overhead: 0, allIn: work, rate };
  const review = ctx.reviewer ? ctx.reviewer.bound : 0;
  const overhead = (ctx.policy.economics['delegate-overhead-tokens'] * ctx.leadRate) / 1e6;
  return { work, review, overhead, allIn: work + review + overhead, rate };
}

function isRepair(ctx, pr) {
  const key = sameKey(profileTuple(ctx.policy, pr));
  const owner = ctx.req.previousResult?.['owner-profile'];
  const ownerPr = owner && ctx.policy.profiles.find((p) => p.id === owner);
  const ownerKey = owner ? (TUPLE.test(owner) ? sameKey(owner) : ownerPr ? sameKey(profileTuple(ctx.policy, ownerPr)) : null) : null;
  return ownerKey === key || ctx.st.dispatchedKeys.has(key);
}

function gate4(ctx, pr, id, kind, out) {
  const st = ctx.st;
  if (!(st.callsUsed + 1 <= st.callsLimit)) return `call slots exhausted: ${st.callsUsed} used + 1 > ${st.callsLimit} calls-per-task`;
  if (isRepair(ctx, pr) && !(st.repairsUsed + 1 <= st.repairsAllowed)) return `same-profile repairs exhausted: ${st.repairsUsed} used + 1 > ${st.repairsAllowed} allowed (R01-R03); a different profile needs a fresh decision`;
  if (!(ctx.nowMs < ctx.deadlineMs)) return `deadline expired: now ${ctx.req.now} not strictly before ${ctx.deadlineIso}`;
  const b = bounds(ctx, pr, kind);
  if (!b) return `unknown price for ${pr.model}: the bound cannot be computed (no silent zero)`;
  out.bounds = b;
  out.note = `cash estimate ${usd(b.allIn)}: estimate only, never a strict cap in this host`;
  if (ctx.usage) {
    // the usage windows are this host's finite resource: a fresh reading, no reset since, and a projection within
    // stop-at - lead-reserve for every window, over the same tokens the cash bound counts
    const tokens = usageTokens(ctx, kind);
    const u = usageWalk(ctx.usage.cfg, ctx.usage.reading, ctx.nowMs, tokens, ctx.deadlineMs, ctx.usage.since);
    if (u.reason) return u.reason;
    out.usage = { tokens, projected: u.projected };
    out.note += `; usage window ${u.binding.name} binds: projected ${round4(u.binding.projected)} <= ${round4(u.binding.limit)}`;
  }
  return null;
}

// the tokens Gate 4 projects: the work for direct; work + the required reviewer's (the review median) + the brief
// overhead for a delegate - the same count the cash bound uses
function usageTokens(ctx, kind) {
  if (kind === 'direct') return ctx.tokens;
  const review = ctx.reviewer ? ctx.policy.categories.review['median-tokens'] : 0;
  return ctx.tokens + review + ctx.policy.economics['delegate-overhead-tokens'];
}

function gate5(ctx, pr, id, kind) {
  if (kind !== 'direct') return null;
  if (ctx.req.allowDirect === false) return 'direct unsuitable: allowDirect is false';
  const max = ctx.policy.economics['direct-max-tokens'];
  if (ctx.tokens > max) return `direct unsuitable: ${ctx.tokens} tokens > direct-max-tokens ${max}`;
  return null;
}

function evaluate(ctx, id, kind) {
  const pr = ctx.policy.profiles.find((p) => p.id === id) ?? null;
  const walkthrough = [];
  const out = {};
  let fail = null;
  const gates = [gate1, gate2, gate3, gate4, gate5];
  gates.forEach((g, i) => {
    if (fail) { walkthrough.push({ gate: i + 1, result: 'not-reached' }); return; }
    const reason = g(ctx, pr, id, kind, out);
    if (reason) {
      fail = { gate: i + 1, reason };
      walkthrough.push({ gate: i + 1, result: 'fail', reason });
    } else {
      walkthrough.push(i === 3 ? { gate: 4, result: 'pass', note: out.note } : { gate: i + 1, result: 'pass' });
    }
  });
  if (fail) return { id, kind, eligible: false, 'first-failing-gate': fail.gate, reason: fail.reason, walkthrough };
  const b = out.bounds;
  return {
    id, kind, eligible: true, 'all-in-bound-usd': round4(b.allIn), 'work-bound-usd': round4(b.work),
    'review-bound-usd': round4(b.review), 'overhead-bound-usd': round4(b.overhead), walkthrough, _allIn: b.allIn, _rate: b.rate,
    _effort: effortRank(pr.effort), _usage: out.usage ?? null
  };
}

// ties of the all-in bound go to the lower output rate, then the lower effort, then the alphabetical id. The bound
// prices every profile on the same token estimate, but at one model a lower effort spends fewer tokens: calibration-1
// measured it for every model on every task (12 model-task pairs, 36 runs; trace/calibration-1/tokens-and-estimates.md). An unknown effort ranks last
const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max'];
function effortRank(effort) {
  const i = EFFORTS.indexOf(effort);
  return i === -1 ? EFFORTS.length : i;
}
const byEconomics = (a, b) => a._allIn - b._allIn || a._rate - b._rate || a._effort - b._effort || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);

// gates.md: the gates apply to every profile under consideration, the reviewer included. The required reviewer is
// drawn from the request's candidates (never the lead-direct profile) and walked through Gate 1 and Gate 2 for the
// review category, with headroom against the review median; an unpriced reviewer cannot bound the review. Under an
// enforced policy the walk requires review@T1 (D5): the review of a unit is its own request when the lead dispatches it,
// with its own declared tier, so the unit's tier is not the reviewer's
function reviewerFor(ctx, ids, leadId) {
  const rev = ctx.policy.categories.review;
  const walk = {};
  const pool = [];
  for (const id of ids) {
    if (id === leadId) continue;
    const pr = ctx.policy.profiles.find((p) => p.id === id);
    if (!pr) continue;
    const g1 = gate1(ctx, pr, id, 'delegate');
    const g2 = g1 || !rev ? null : capabilities(ctx, pr, id, { category: 'review', tokens: rev['median-tokens'], tools: rev['required-tools'], tier: ctx.tier ? 'T1' : null });
    const why = g1 ? `gate 1: ${g1}` : !rev ? 'gate 2: the policy has no review category' : g2 ? `gate 2: ${g2}` : outRate(ctx.policy, pr) === null ? `gate 4: unknown price for ${pr.model}` : null;
    walk[id] = why;
    if (!why) pool.push(pr);
  }
  pool.sort((a, b) => outRate(ctx.policy, a) - outRate(ctx.policy, b) || (a.id < b.id ? -1 : 1));
  const reviewer = pool.length ? { id: pool[0].id, bound: (rev['median-tokens'] * outRate(ctx.policy, pool[0])) / 1e6 } : null;
  return { reviewer, walk };
}

// ---------------------------------------------------------------------------------------------
// decision
// ---------------------------------------------------------------------------------------------
export function computeDecision(req, policy, records = [], catMap = {}, { probe = null, readings = [] } = {}) {
  validateRequest(req, policy);
  const tiering = requestTier(req, policy);
  const optIns = optInsOf(policy, req.hostOptIns);
  const category = Object.hasOwn(policy.categories, req.category) ? policy.categories[req.category] : null;
  const leadId = policy.economics['lead-direct-profile'];
  const leadRate = outRate(policy, policy.profiles.find((p) => p.id === leadId));
  const st = taskState(records, req.taskId, policy);
  assertClock(st, req.now, req.taskId);
  const nowMs = isoMs(req.now);
  const startMs = st.startMs === null ? nowMs : Math.min(st.startMs, nowMs);
  const capMs = startMs + policy.accounting.strict['deadline-per-task-hours'] * 3600000;
  const reqDeadlineMs = isoMs(req.deadline);
  const capped = capMs < reqDeadlineMs;
  const deadlineMs = capped ? capMs : reqDeadlineMs;
  const deadlineIso = capped ? isoOf(capMs) : req.deadline;
  const reviewName = category ? category.verification.find((v) => /review/i.test(v)) ?? null : null;
  const ctx = {
    req, policy, category, st, nowMs, deadlineMs, deadlineIso, leadRate, reviewName,
    tokens: req.estimatedTokens ?? category?.['median-tokens'] ?? 0,
    requiredTools: req.requiredTools ?? category?.['required-tools'] ?? [],
    reviewer: null, reviewWalk: {},
    usage: null, tier: tiering.tier
  };
  if (policy['usage-windows']) {
    const reading = latestReading(readings, nowMs);
    ctx.usage = { cfg: policy['usage-windows'], reading, since: dispatchedSince(records, reading, nowMs) };
  }
  const ids = req.candidates ?? policy.profiles.map((p) => p.id);
  if (reviewName) ({ reviewer: ctx.reviewer, walk: ctx.reviewWalk } = reviewerFor(ctx, ids, leadId));
  const results = ids.map((id) => evaluate(ctx, id, id === leadId ? 'direct' : 'delegate'));
  // a profile walked as a delegate without joining the route choice (the pre-dispatch recheck of a host deviation)
  const probed = probe ? evaluate(ctx, probe, 'delegate') : null;
  const eligible = results.filter((r) => r.eligible).sort(byEconomics);

  let route;
  let chosen = null;
  let specSet = null;
  // the speculative set's members run at once, so Gate 4 projects their summed tokens, as the shared cash bound
  // sums their cash (SW-1); a set that does not fit is not routed speculative
  let specUsage = null;
  let specMiss = null;
  // no eligible candidate => blocked (SKILL.md decision flow step 3, 'No empty-set resurrection'; fixture E01).
  // A profile outside the candidates that would pass is named in Uncertainty as a hint, never routed to.
  let outside = [];
  if (!eligible.length) {
    route = 'blocked';
    outside = policy.profiles.filter((p) => p.id !== leadId && !ids.includes(p.id))
      .map((p) => evaluate(ctx, p.id, 'delegate')).filter((r) => r.eligible).sort(byEconomics).map((r) => r.id);
  } else {
    const delegates = eligible.filter((r) => r.kind === 'delegate');
    const slots = st.callsLimit - st.callsUsed;
    const speculate = optIns.speculative && req.uncertainty === 'high' && delegates.length >= 2 && slots >= 2;
    const set = delegates.slice(0, 2);
    if (speculate && ctx.usage) {
      const sum = set.reduce((s, r) => s + r._usage.tokens, 0);
      const u = usageWalk(ctx.usage.cfg, ctx.usage.reading, nowMs, sum, deadlineMs, ctx.usage.since);
      if (u.reason) specMiss = `the set's summed usage projection, ${sum} tokens, does not fit: ${u.reason}`;
      else specUsage = { tokens: sum, projected: u.projected };
    }
    if (speculate && !specMiss) {
      route = 'speculative';
      chosen = set[0];
      specSet = {
        candidates: set.map((r) => ({ profile: r.id, weight: 1.0 })), 'max-parallel': set.length,
        'shared-budget': { cash: round4(set.reduce((s, r) => s + r._allIn, 0)), calls: set.length, 'cash-basis': 'estimate-only' },
        'cancel-policy': 'first-success', 'winner-owns': true
      };
      validateSpeculativeSet(specSet, { callsRemaining: slots });
    } else {
      chosen = eligible[0];
      route = chosen.kind === 'direct' ? 'direct' : 'delegate';
    }
  }

  const pr = chosen ? policy.profiles.find((p) => p.id === chosen.id) : null;
  const uncertainty = [CASH_UNCERTAINTY];
  uncertainty.push(ctx.usage ? `usage windows: coefficients host-declared (${ctx.usage.cfg['coefficient-basis']})` : USAGE_OFF);
  if (optIns['nested-allowed']) uncertainty.push('nested-allowed opt-in refused: this host cannot produce or enforce a NestedBrief (spec-v2 §14)');
  if (req.uncertainty === 'high' && route !== 'speculative') uncertainty.push(`uncertainty high; speculative not used (${specMiss ?? (optIns.speculative ? 'fewer than two eligible delegates or call slots' : 'no host opt-in')})`);
  if (outside.length) uncertainty.push(`not among candidates: ${outside.join(', ')} would pass all five gates (hint only; the route stays blocked, and a fresh decision must list it as a candidate)`);
  const { proposals } = learn(policy, records, catMap);
  const pending = [...proposals, ...expiryFlags(policy, nowMs)].filter((p) => chosen && p.profile === chosen.id);
  for (const p of pending) uncertainty.push(`pending proposal (not applied): ${proposalText(p)}`);
  // D3: a declared tier against an untiered policy has no effect, and says so
  if (tiering.tier === null && tiering.declared) uncertainty.push(TIERS_OFF);

  const isolation = route === 'blocked' ? 'none' : requiredIsolation(ctx, route === 'direct' ? 'direct' : 'delegate');
  const isolationReason = {
    blocked: 'blocked: nothing is dispatched, nothing to isolate',
    direct: isolation === 'none' ? 'Gate 5: the lead works inline on a low-risk bounded task (<= direct-max-tokens)' : `Gate 1/3: ${category?.risk}-risk work; the lead keeps a ${isolation} even inline`,
    delegate: `Gate 1: concurrent workers in this host never share a tree; Gate 5: the delegated unit owns its ${isolation} (host capability ${policy.isolation.capability})`,
    speculative: `Gate 5: each speculative candidate owns its ${isolation}; losers are cancelled`
  }[route];

  let brief = null;
  let fingerprint = null;
  if (route === 'delegate' || route === 'speculative') {
    const repair = isRepair(ctx, pr) ? 1 : 0;
    const nonGoals = [...req.nonGoals];
    if (!nonGoals.some((g) => /nest|recursive/i.test(g))) nonGoals.push('no recursive delegation (nested-allowed: false)');
    brief = {
      objective: req.objective,
      acceptance: { checks: req.acceptanceChecks.map((c) => ({ command: c.command, expect: c.expect })) },
      sources: [...req.sources],
      'permitted-effects': [...req.permittedEffects],
      'non-goals': nonGoals,
      isolation,
      'branch-hint': `build/${slug(req.unit)}`,
      allowance: { cash: route === 'speculative' ? specSet['shared-budget'].cash : chosen['all-in-bound-usd'], calls: st.callsLimit - st.callsUsed, deadline: deadlineIso, 'cash-basis': 'estimate-only' },
      attempts: st.repairsAllowed - st.repairsUsed - repair,
      'stop-triggers': [
        `verification failure -> outcome record, then a fresh decision; at most ${st.repairsAllowed} same-profile repair per task`,
        'repairs exhausted -> fresh Holdshort decision (no ownership transfer without it)',
        `call slots exhausted (${st.callsLimit} per task) -> blocked`,
        `deadline ${deadlineIso} reached -> blocked`,
        'project stop rule -> blocked'
      ],
      ownership: 'worker',
      'nested-allowed': false,
      'max-nesting-depth': 1,
      // D6: additive (spec-v2 §13); the recheck recomputes it, so the fingerprint binds the tier
      ...(tiering.tier ? { 'difficulty-tier': tiering.tier } : {})
    };
    validateBrief(brief, { callsRemaining: st.callsLimit - st.callsUsed, repairsAllowed: st.repairsAllowed, now: req.now });
    fingerprint = briefFingerprint(brief);
  }

  const risk = category?.risk;
  const difficulty = !category || risk === 'high' || req.uncertainty === 'high' ? 'high-or-ambiguous' : risk === 'low' ? 'trivial' : 'moderate';
  const owner = { direct: 'orchestrator', delegate: 'worker', speculative: 'worker', blocked: 'none' }[route];
  let profileLine = 'none — blocked';
  if (route === 'speculative') profileLine = specSet.candidates.map((c) => profileTuple(policy, policy.profiles.find((p) => p.id === c.profile))).join(' | ');
  else if (route !== 'blocked') profileLine = profileTuple(policy, pr);
  let allIn = null;
  if (route === 'speculative') allIn = specSet['shared-budget'].cash;
  else if (route !== 'blocked') allIn = chosen['all-in-bound-usd'];
  const reservations = allIn === null ? 'unknown/blocked'
    : `${usd(allIn)} conservative all-in bound, estimate only (work ${usd(chosen['work-bound-usd'])} + review ${usd(chosen['review-bound-usd'])} + brief overhead ${usd(chosen['overhead-bound-usd'])}${route === 'speculative' ? ', first candidate; the set sums its candidates' : ''})`;
  const left = deadlineMs - nowMs;
  const capNote = capped ? `; capped by deadline-per-task-hours ${policy.accounting.strict['deadline-per-task-hours']}` : '';
  const deadlineLine = left > 0
    ? `open until ${deadlineIso} (${Math.floor(left / 3600000)}h ${Math.floor((left % 3600000) / 60000)}m left${capNote})`
    : `expired at ${deadlineIso} (now ${req.now} is not strictly before it)`;
  const maxDepth = optIns['nested-allowed'] ? 0 : optIns['max-nesting-depth'];

  const lines = [
    ['Difficulty', difficulty], ...(tiering.tier ? [['DifficultyTier', tiering.tier]] : []), ['Route', route], ['Profile', profileLine], ['Isolation', isolation],
    ['IsolationReason', isolationReason], ['Owner', owner], ['HumanGate', optIns['human-gate']], ['NestedAllowed', 'no'],
    ['MaxNestingDepth', String(maxDepth)], ['Reservations', reservations],
    ['Calls', `${st.callsUsed} / ${st.callsLimit}`], ['Deadline', deadlineLine], ['Uncertainty', uncertainty.join('; ')]
  ].map(([k, v]) => `${`${k}:`.padEnd(19)}${v}`);
  const idWidth = Math.max(16, ...results.map((r) => r.id.length + 1));   // a space after the longest id (P2-4)
  const walk = results.map((r) => `  ${r.id.padEnd(idWidth)}${r.kind.padEnd(10)}${r.eligible ? `eligible, all-in ${usd(r._allIn)}` : `gate ${r['first-failing-gate']}: ${r.reason}`}`);
  let text = `${lines.join('\n')}\n${ADVISORY}\nGate walk (${route === 'blocked' ? 'first failing gate and reason per candidate' : 'per candidate'}):\n${walk.join('\n')}\n`;
  if (specSet) text += `SpeculativeSet:\n${JSON.stringify(specSet, null, 2)}\n`;
  if (brief) text += `Brief:\n${JSON.stringify(brief, null, 2)}\n`;

  const strip = (r) => Object.fromEntries(Object.entries(r).filter(([k]) => !k.startsWith('_') && k !== 'id'));
  const chosenUsage = route === 'speculative' ? specUsage : chosen?._usage;
  const usage = ctx.usage ? usageBlock(ctx.usage.cfg, ctx.usage.reading, nowMs, chosenUsage?.projected ?? null, ctx.usage.since) : null;
  const usageFields = ctx.usage ? { 'usage-tokens': chosenUsage?.tokens ?? null } : {};
  return {
    route, profile: route === 'blocked' ? null : chosen.id, 'profile-tuple': route === 'blocked' ? null : profileTuple(policy, pr),
    isolation, 'isolation-reason': isolationReason, owner, 'human-gate': optIns['human-gate'], 'nested-allowed': false,
    'max-nesting-depth': maxDepth, difficulty, ...(tiering.tier ? { 'difficulty-tier': tiering.tier } : {}), 'estimated-tokens': ctx.tokens,
    'all-in-bound-usd': allIn, candidates: Object.fromEntries(results.map((r) => [r.id, strip(r)])),
    'eligible-ordered': eligible.map((r) => r.id), 'eligible-outside-candidates': outside, 'speculative-set': specSet, uncertainty,
    advisory: ADVISORY_TEXT, 'pending-proposals': pending, deadline: deadlineIso, 'deadline-capped': capped,
    'review-profile': ctx.reviewer?.id ?? null, 'review-candidates': ctx.reviewWalk, brief, 'brief-fingerprint': fingerprint, text,
    counters: counters(st), usage, ...usageFields, ...(probed ? { probe: strip(probed) } : {})
  };
}

function policyBindings(policy, policyPath) {
  return {
    'policy-revision': policy['policy-revision'] ?? null, 'policy-sha256': sha256(readFileSync(policyPath)),
    holdshort: policy.holdshort ?? null, harness: `${policy.harness.id}@${policy.harness.version ?? 'unknown'}`
  };
}

export function decide(req, { policyPath = DEFAULT_POLICY, traceDir = DEFAULT_TRACE } = {}) {
  const policy = loadPolicy(policyPath);
  const records = readLedger(traceDir);
  const readings = policy['usage-windows'] ? readUsage(traceDir) : [];
  const d = computeDecision(req, policy, records, categoryMap(traceDir), { readings });
  const st = taskState(records, req.taskId, policy);
  const seq = st.lastSeq + 1;
  const { text, brief, 'brief-fingerprint': fp, counters: ctr, ...decision } = d;
  const file = {
    request: req,
    'inputs-sha256': sha256(canonicalJson(req)),
    bindings: policyBindings(policy, policyPath),
    'ledger-before': { 'last-seq': st.lastSeq, ...ctr },
    decision,
    estimates: { basis: 'estimate-only', 'cost-bound-rule': policy.accounting['cost-bound-rule'] ?? null, 'all-in-bound-usd': d['all-in-bound-usd'] },
    accounting: { mode: policy.accounting.mode, 'cash-spent': null, 'cash-cap': null, note: 'no per-call USD accounting in this host; spend is unknown, never zero' },
    brief,
    'brief-fingerprint': fp,
    'ledger-seq': seq
  };
  const dir = join(traceDir, 'decisions');
  mkdirSync(dir, { recursive: true });
  const decisionPath = join(dir, `${req.taskId}-${seq}.json`);
  writeFileSync(decisionPath, `${JSON.stringify(file, null, 1)}\n`, { flag: 'wx' });
  const record = appendRecord(traceDir, policy, {
    'task-id': req.taskId, seq, kind: 'decision', ts: req.now, profile: d['profile-tuple'], counters: ctr,
    deadline: d.deadline, 'brief-fingerprint': fp, detail: `route ${d.route}`,
    'outcome-ref': null,
    // additive (spec-v2 §13, D6): the request's difficulty tier under an enforced policy
    ...('difficulty-tier' in d ? { 'difficulty-tier': d['difficulty-tier'] } : {}),
    // additive (spec-v2 §13): the tokens Gate 4 projected for the chosen profile, so dispatch re-checks that count
    ...('usage-tokens' in d ? { 'usage-tokens': d['usage-tokens'] } : {}),
    ...(d['speculative-set'] ? { 'speculative-profiles': d['speculative-set'].candidates.map((c) => c.profile), 'speculative-calls': d['speculative-set']['shared-budget'].calls } : {})
  });
  return { route: d.route, text, decision: d, brief, briefFingerprint: fp, decisionPath, record };
}

// ---------------------------------------------------------------------------------------------
// dispatch, outcome, status, rate
// ---------------------------------------------------------------------------------------------
// the decision file behind a ledger decision record: the stored request is what the recheck re-walks
function storedDecision(traceDir, taskId, dec) {
  const path = join(traceDir, 'decisions', `${taskId}-${dec.seq}.json`);
  if (!existsSync(path)) throw refused(`decision file ${taskId}-${dec.seq}.json is missing: the route cannot be rechecked before dispatch, and unknown evidence invalidates it (gates.md 'Qualification, freshness and pre-dispatch binding' item 3); decide again`);
  let j;
  try { j = JSON.parse(readFileSync(path, 'utf8')); } catch { throw new RouterError(4, `decision file ${taskId}-${dec.seq}.json is unparseable`); }
  if (j?.['ledger-seq'] !== dec.seq || j.request?.taskId !== taskId || (j['brief-fingerprint'] ?? null) !== dec['brief-fingerprint']) {
    throw new RouterError(4, `decision file ${taskId}-${dec.seq}.json does not match ledger decision seq ${dec.seq}`);
  }
  return j;
}

// gates.md 'Qualification, freshness and pre-dispatch binding' items 3-4: immediately before dispatch, re-walk the
// stored request against the current policy, ledger and clock. Changed, expired or revoked evidence invalidates
// the route; revocation always wins over the stored decision.
function recheck({ traceDir, policy, records, readings, taskId, dec, route, profileId, now, projectStop, deviation }) {
  const stored = storedDecision(traceDir, taskId, dec);
  // the re-walk sees the ledger as the decision did: the dispatches made under this same decision (the other members
  // of a speculative set) are its own consumption, not changed evidence; dispatch counts them against the slots itself
  const own = (r) => r['task-id'] === taskId && r.kind === 'dispatch' && r['decision-seq'] === dec.seq;
  // the stop rules are re-walked with the lead's current state, never the snapshot taken at decide time
  const again = computeDecision({ ...stored.request, now, projectStop }, policy, records.filter((r) => !own(r)), {}, { probe: deviation ? profileId : null, readings });
  if (deviation) {
    // a deviation is allowed only to a profile that passes Gates 1-4 on the same request (spec-v2 §11.2, §11.10, §12)
    const p = again.probe;
    if (!p.eligible) throw refused(`pre-dispatch recheck refused deviation ${profileId} (decision seq ${dec.seq}): gate ${p['first-failing-gate']}: ${p.reason}; a host deviation must still pass Gates 1-4 (spec-v2 §11.2)`);
    // the deviating worker is handed the decided Brief too (README step 2), so it is bound the same way (R3-1)
    assertBriefUnchanged(stored, again, dec);
    return;
  }
  const c = again.candidates[profileId];
  if (!c?.eligible) {
    const why = c ? `gate ${c['first-failing-gate']}: ${c.reason}` : 'not among the request\'s candidates';
    throw refused(`pre-dispatch recheck refused ${profileId} (decision seq ${dec.seq}): ${why}; changed, expired or revoked evidence invalidates the route (gates.md pre-dispatch binding); decide again`);
  }
  const choice = route === 'speculative'
    ? again['eligible-ordered'].filter((id) => again.candidates[id].kind === 'delegate').slice(0, 2)
    : again.route === 'delegate' ? [again.profile] : [];
  if (!choice.includes(profileId)) {
    throw refused(`pre-dispatch recheck: the route changed since decision seq ${dec.seq} (now ${again.route}${again.profile ? ` ${again.profile}` : ''}); decide again`);
  }
  assertBriefUnchanged(stored, again, dec);
}

// gates.md binding item 3: the worker is handed the decided Brief, so its allowance (calls, deadline, attempts,
// cash) must still be what the current policy, ledger and clock give; a changed Brief invalidates the route
function assertBriefUnchanged(stored, again, dec) {
  if (again['brief-fingerprint'] !== stored['brief-fingerprint']) {
    const changed = Object.keys({ ...stored.brief, ...again.brief }).sort()
      .filter((k) => canonicalJson(stored.brief?.[k] ?? null) !== canonicalJson(again.brief?.[k] ?? null));
    throw refused(`pre-dispatch recheck: the Brief changed since decision seq ${dec.seq}; decide again (changed: ${changed.join(', ') || 'fingerprint'})`);
  }
}

export function dispatch(taskId, profileId, { policyPath = DEFAULT_POLICY, traceDir = DEFAULT_TRACE, now = new Date().toISOString(), deviation = null, projectStop = null } = {}) {
  if (!isStr(taskId) || !TASK_ID.test(taskId)) throw invalid(`invalid task id ${taskId}`);
  if (isoMs(now) === null) throw invalid('--now must be ISO-8601');
  // gates.md binding item 3 rechecks current permission: Gate 1's project stops are part of it, so no default
  if (!isProjectStop(projectStop)) throw invalid(`dispatch needs the current project-stop state: ${PROJECT_STOP_USAGE} (missing or malformed; each of redSuite, gateOff, researchGateFailing a boolean)`);
  const policy = loadPolicy(policyPath);
  const pr = policy.profiles.find((p) => p.id === profileId);
  if (!pr) throw invalid(`unknown profile ${profileId}`);
  const records = readLedger(traceDir);
  const st = taskState(records, taskId, policy);
  assertClock(st, now, taskId);
  const dec = st.lastDecision;
  if (!dec) throw refused(`no decision recorded for task ${taskId}; run decide first`);
  const route = /^route (\S+)/.exec(dec.detail)?.[1] ?? 'unknown';
  if (route === 'blocked') throw refused(`latest decision for ${taskId} is blocked (seq ${dec.seq}); a blocked result is never overridden (spec-v2 §11.2)`);
  if (route !== 'delegate' && route !== 'speculative') throw refused(`latest decision for ${taskId} is ${route}; nothing to dispatch without a fresh decision`);
  if (st.lastOutcomeSeq > dec.seq) throw refused(`an outcome (seq ${st.lastOutcomeSeq}) follows the latest decision (seq ${dec.seq}); decide again with previousResult first`);
  const decided = route === 'speculative' ? dec['speculative-profiles'] ?? [tupleId(dec.profile)] : [tupleId(dec.profile)];
  const after = st.records.filter((r) => r.kind === 'dispatch' && r.seq > dec.seq);
  if (route === 'delegate' && after.length) throw refused(`decision seq ${dec.seq} for ${taskId} was already dispatched (seq ${after[0].seq}); decide again`);
  if (after.some((r) => tupleId(r.profile) === profileId)) throw refused(`decision seq ${dec.seq} already dispatched ${profileId}`);
  const asDecided = decided.includes(profileId);
  if (route === 'speculative') {
    // spec-v2 §8.4: the shared budget is a hard ceiling across the entire set; a record without the ceiling
    // (written before it was stored) is held to the set's size, which is what the adapter emits as calls
    const ceiling = isInt(dec['speculative-calls'], 1) ? dec['speculative-calls'] : decided.length;
    if (after.length >= ceiling) throw refused(`speculative set of decision seq ${dec.seq} has used its shared budget: ${after.length} of ${ceiling} calls dispatched; the shared budget is a hard ceiling across the set (spec-v2 §8.4); decide again`);
    if (!asDecided) throw refused(`decision seq ${dec.seq} is speculative: dispatching ${profileId} outside its set (${decided.join(', ')}) is refused; a speculative route admits no host deviation (its shared budget is a hard ceiling, spec-v2 §8.4); decide again`);
  }
  // the lead-direct profile is walked only as `direct` (Gate 5's direct-max-tokens bound); a deviation probe walks
  // every profile as a delegate, so without this the lead could be dispatched as a worker past that bound
  const leadId = policy.economics['lead-direct-profile'];
  if (!asDecided && profileId === leadId) throw refused(`${profileId} is the lead-direct profile (economics.lead-direct-profile): it works direct only, up to direct-max-tokens ${policy.economics['direct-max-tokens']}, and is never dispatched as a delegated worker, --deviation or not (Gate 5); decide again`);
  if (!asDecided && !isStr(deviation)) throw refused(`decided ${decided.join(', ')}; dispatching ${profileId} is a host deviation: pass --deviation <reason> to record it`);
  if (!(isoMs(now) < isoMs(dec.deadline))) throw refused(`deadline ${dec.deadline} reached: now ${now} is not strictly before it`);
  if (!(st.callsUsed + 1 <= st.callsLimit)) throw refused(`call slots exhausted: ${st.callsUsed} used + 1 > ${st.callsLimit} calls-per-task`);
  const key = sameKey(profileTuple(policy, pr));
  const prior = st.dispatchedKeys.get(key);
  const repair = Boolean(prior);
  if (repair && !(st.repairsUsed + 1 <= st.repairsAllowed)) throw refused(`same-profile repairs exhausted for ${taskId}: ${st.repairsUsed} used + 1 > ${st.repairsAllowed} allowed (R01-R03)`);
  // the decided Brief's attempts assume the decided profile's repair status; a deviation that would be a repair
  // under a Brief decided for a fresh profile (or the reverse) hands the worker the wrong attempts (R3-1)
  if (!asDecided) {
    const decidedRepair = decided.some((id) => { const dp = policy.profiles.find((p) => p.id === id); return dp ? st.dispatchedKeys.has(sameKey(profileTuple(policy, dp))) : false; });
    if (repair !== decidedRepair) {
      const attempts = st.repairsAllowed - st.repairsUsed - (decidedRepair ? 1 : 0);
      throw refused(repair
        ? `deviation to ${profileId} would be a same-profile repair under a Brief decided for a fresh profile (attempts ${attempts}); decide again with ${profileId} among the candidates`
        : `deviation to ${profileId} would be a fresh dispatch under a Brief decided for a same-profile repair (attempts ${attempts}); decide again with ${profileId} among the candidates`);
    }
  }
  // reconcile first (SKILL.md 'Hard prohibitions', spec-v2 §7 and §12): any earlier dispatch of the task, of any
  // profile, whose acceptance is unknown (no later outcome naming its dispatch-seq) holds every further dispatch;
  // the one exception is the other members of the same speculative decision, which run side by side by design
  const reconciled = (d) => st.records.some((o) => o.kind === 'outcome' && o.seq > d.seq && o['dispatch-seq'] === d.seq);
  const sibling = (d) => route === 'speculative' && asDecided && d['decision-seq'] === dec.seq;
  const open = st.records.find((d) => d.kind === 'dispatch' && !reconciled(d) && !sibling(d));
  if (open) throw refused(`previous dispatch of ${tupleId(open.profile)} (seq ${open.seq}) has no outcome; reconcile before any re-dispatch (spec-v2 §12)`);
  // the usage windows at dispatch time, against the token count the decision projected: a decision taken minutes
  // earlier can be stale by now, or the window can have filled since (the recheck below walks Gate 4 again too)
  const readings = policy['usage-windows'] ? readUsage(traceDir) : [];
  let usageFields = {};
  if (policy['usage-windows']) {
    // each dispatch records the tokens it commits, so later decisions and dispatches count it until a reading taken
    // at or after its outcome (SW-2, SW-7): a speculative member commits its share of the set's sum
    usageFields = { 'usage-tokens': isInt(dec['usage-tokens']) ? dec['usage-tokens'] / decided.length : null };
  }
  if (policy['usage-windows'] && isInt(dec['usage-tokens'])) {
    const reading = latestReading(readings, isoMs(now));
    // the decision's own sum covers the other members of its speculative set; every other dispatch the reading does not hold counts
    const since = dispatchedSince(records, reading, isoMs(now), (r) => r['task-id'] === taskId && r['decision-seq'] === dec.seq);
    const u = usageWalk(policy['usage-windows'], reading, isoMs(now), dec['usage-tokens'], isoMs(dec.deadline), since);
    if (u.reason) throw refused(`usage check refused ${profileId} (decision seq ${dec.seq}, usage-tokens ${dec['usage-tokens']}): ${u.reason}`);
  }
  recheck({ traceDir, policy, records, readings, taskId, dec, route, profileId, now, projectStop, deviation: !asDecided });
  const detail = asDecided ? `${repair ? 'same-profile repair dispatch' : 'dispatch'} as decided (decision seq ${dec.seq})` : `host deviation: ${deviation}; route said ${decided.join(', ')}`;
  return appendRecord(traceDir, policy, {
    'task-id': taskId, seq: st.lastSeq + 1, kind: 'dispatch', ts: now, profile: profileTuple(policy, pr),
    counters: counters(st, st.callsUsed + 1, st.repairsUsed + (repair ? 1 : 0)), deadline: dec.deadline,
    'brief-fingerprint': dec['brief-fingerprint'], detail, 'outcome-ref': null,
    'decision-seq': dec.seq, repair, deviation: !asDecided, ...usageFields
  });
}

export function recordOutcome(o, { policyPath = DEFAULT_POLICY, traceDir = DEFAULT_TRACE, now = new Date().toISOString() } = {}) {
  validateOutcome(o);
  if (isoMs(now) === null) throw invalid('--now must be ISO-8601');
  const policy = loadPolicy(policyPath);
  const ownerId = tupleId(o['owner-profile']);
  const pr = policy.profiles.find((p) => p.id === ownerId);
  if (!pr) throw invalid(`owner-profile ${o['owner-profile']} is not a policy profile`);
  const records = readLedger(traceDir);
  const st = taskState(records, o['task-id'], policy);
  if (!st.records.length) throw refused(`unknown task ${o['task-id']}: no ledger records`);
  assertClock(st, now, o['task-id']);
  const disp = st.dispatched.get(ownerId);
  if (!disp) throw refused(`no dispatch of ${ownerId} recorded for task ${o['task-id']}; an outcome must reference a dispatch`);
  const fp = o['original-brief-fingerprint'];
  if (st.fingerprints.size && !st.fingerprints.has(fp)) throw refused(`original-brief-fingerprint does not match any Brief recorded for ${o['task-id']}`);
  const seq = st.lastSeq + 1;
  // Item 4: an estimate-only host's unknown spend (null) is stored with the basis that makes it conformant (§10.3);
  // a supplied "estimate-only" is kept (validateOutcome refuses any other), a null basis is no basis - defaulted like
  // an absent one, or dropped where none applies - and a known spend needs none. The caller's object is not changed
  const { 'actual-spend-basis': supplied, ...unbased } = o.evidence;
  const basis = supplied ?? (estimateOnly(policy) && o.evidence['actual-spend'] === null ? ESTIMATE_ONLY : undefined);
  const stored = basis === supplied ? o : { ...o, evidence: basis === undefined ? unbased : { ...unbased, 'actual-spend-basis': basis } };
  const dir = join(traceDir, 'outcomes');
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, `${o['task-id']}-${seq}.json`), `${JSON.stringify(stored, null, 1)}\n`, { flag: 'wx' });
  return appendRecord(traceDir, policy, {
    'task-id': o['task-id'], seq, kind: 'outcome', ts: now, profile: profileTuple(policy, pr), counters: counters(st),
    deadline: st.lastDecision?.deadline ?? null, 'brief-fingerprint': FINGERPRINT.test(fp) ? fp : null,
    detail: `outcome ${o.outcome} (dispatch seq ${disp.seq})`, 'outcome-ref': o['task-id'], 'dispatch-seq': disp.seq,
    tokens: isInt(o.evidence['actual-tokens']) ? o.evidence['actual-tokens'] : null,
    // derived from the stored Outcome, like tokens: the basis of its actual-spend, when it has one
    ...(basis !== undefined ? { 'actual-spend-basis': basis } : {})
  });
}

export function status(taskId, { policyPath = DEFAULT_POLICY, traceDir = DEFAULT_TRACE } = {}) {
  const policy = loadPolicy(policyPath);
  const st = taskState(readLedger(traceDir), taskId, policy);
  if (!st.records.length) throw invalid(`unknown task ${taskId}: no ledger records`);
  const dec = st.lastDecision;
  const disp = st.records.filter((r) => r.kind === 'dispatch');
  const outs = st.records.filter((r) => r.kind === 'outcome');
  const text = [
    `task: ${taskId}`, `last seq: ${st.lastSeq}`, `calls: ${st.callsUsed} / ${st.callsLimit}`, `repairs: ${st.repairsUsed} / ${st.repairsAllowed}`,
    `deadline: ${dec?.deadline ?? 'none'}`, `latest decision: ${dec ? `seq ${dec.seq} ${dec.detail} ${dec.profile ?? ''}`.trim() : 'none'}`,
    `dispatches: ${disp.length} (deviations: ${disp.filter(isDeviation).length})`,
    `outcomes: ${outs.length ? outs.map((r) => `seq ${r.seq} ${r.detail}`).join('; ') : 'none'}`
  ].join('\n');
  return { text: `${text}\n`, counters: counters(st) };
}


// observed coefficients: for consecutive readings with no reset of the window between them (same resets-at, not
// passed by the later reading), (u2 - u1) / (T / 1e6) where T sums the outcome tokens recorded in (ts1, ts2] - one
// outcome per dispatch, as the qualification streams count. Pairs with unknown tokens or T = 0 are skipped and counted.
// Proposals: upward at once when the max observed exceeds the current by more than 10 % (the conservative direction);
// downward only when the last three observations are all below 90 % of the current, to the highest of the three.
function usageLearning(cfg, readings, records) {
  const outs = latestOutcomes(records).map((r) => ({ ms: isoMs(r.ts), tokens: isInt(r.tokens) ? r.tokens : null }));
  // a unit's tokens are recorded whole at its outcome, so a pair of readings says what they cost only when
  // no unit was in flight at either reading: a dispatch at or before the reading whose first outcome is
  // absent or later than it (SW-8); such pairs are skipped and counted
  const dispatches = records.filter((r) => r.kind === 'dispatch');
  const firstOutcome = (d) => records.find((o) => o.kind === 'outcome' && o['task-id'] === d['task-id'] && o.seq > d.seq && o['dispatch-seq'] === d.seq);
  const inFlightAt = (ms) => dispatches.some((d) => isoMs(d.ts) <= ms && (() => { const o = firstOutcome(d); return !o || isoMs(o.ts) > ms; })());
  const usage = {};
  const proposals = [];
  for (const [name, w] of Object.entries(cfg.windows)) {
    const observed = [];
    const skipped = { reset: 0, spanning: 0, 'unknown-tokens': 0, 'zero-tokens': 0, 'negative-delta': 0 };
    for (let i = 1; i < readings.length; i += 1) {
      const a = readings[i - 1];
      const b = readings[i];
      const ra = a.windows[name];
      const rb = b.windows[name];
      if (!ra || !rb || ra['resets-at'] !== rb['resets-at'] || isoMs(ra['resets-at']) <= isoMs(b.ts)) { skipped.reset += 1; continue; }
      if (inFlightAt(isoMs(a.ts)) || inFlightAt(isoMs(b.ts))) { skipped.spanning += 1; continue; }
      const inside = outs.filter((o) => o.ms > isoMs(a.ts) && o.ms <= isoMs(b.ts));
      if (inside.some((o) => o.tokens === null)) { skipped['unknown-tokens'] += 1; continue; }
      const tokens = inside.reduce((sum, o) => sum + o.tokens, 0);
      if (tokens === 0) { skipped['zero-tokens'] += 1; continue; }
      const delta = rb.utilization - ra.utilization;
      // utilization that fell under one resets-at (a rolling window shedding old usage, or a mistaken paste) says
      // nothing about what the tokens cost: skipped and counted, never a negative coefficient (SW-3)
      if (delta < 0) { skipped['negative-delta'] += 1; continue; }
      observed.push({ from: a.ts, to: b.ts, delta: round6(delta), tokens, coefficient: round6(delta / (tokens / 1e6)) });
    }
    const current = w['utilization-per-mtok'];
    // only observations after the last ratification bear on the current coefficient: the all-history maximum
    // would propose going straight back up after a ratified downward change (SW-5)
    const ratMs = w['ratified-at'] ? isoMs(w['ratified-at']) : null;
    const considered = ratMs === null ? observed : observed.filter((o) => isoMs(o.to) > ratMs);
    const max = considered.length ? Math.max(...considered.map((o) => o.coefficient)) : null;
    usage[name] = { observed, considered: considered.length, 'ratified-at': w['ratified-at'] ?? null, 'max-observed': max, current, skipped };
    const last = considered.slice(-3);
    if (max !== null && max > current * 1.1) {
      proposals.push({ window: name, from: current, to: max, direction: 'up', reason: 'max observed exceeds the current by more than 10 %; upward at once' });
    } else if (last.length === 3 && last.every((o) => o.coefficient < current * 0.9) && Math.max(...last.map((o) => o.coefficient)) > 0) {
      // validatePolicy refuses a coefficient <= 0, so none is ever proposed (SW-3)
      proposals.push({ window: name, from: current, to: Math.max(...last.map((o) => o.coefficient)), direction: 'down', reason: 'the last three observations are all below 90 % of the current; downward slowly' });
    }
  }
  return { usage, proposals };
}

// calibration evidence (host-policy-2): graded calibration runs in <trace>/calibration-<n>/observations.json, counted per
// (profile, category) apart from the outcomes. They never enter the ledger and never make a proposal: proposals stay
// outcome-based, and qualification from calibration is the lead's, under the qualification rules (README).
// The tasks and the categories they represent: the pin task is pin-tests (rule 4), the fix task fix, the review task review.
// Each reads a grade: 'pass' | 'partial' | 'fail' | 'ungraded', or null when the observation does not carry the task (not
// run: calibration-2's review-only profiles have pin and fix null). Pin and fix carry a boolean score in both runs; the
// review grade is calibration-1's boolean review-grade.score or calibration-2's three-valued review-grade.result
// (PASS | PARTIAL | FAIL, its preregistered protocol), the result read first. Anything else is ungraded, never a pass.
const isObject = (v) => Boolean(v) && typeof v === 'object' && !Array.isArray(v);
const scoreGrade = (task) => (!isObject(task) ? null : task.score === true ? 'pass' : task.score === false ? 'fail' : 'ungraded');
function reviewGrade(o) {
  const g = o?.['review-grade'];
  if (!isObject(g)) return null;
  if (g.result !== undefined) return ['PASS', 'PARTIAL', 'FAIL'].includes(g.result) ? g.result.toLowerCase() : 'ungraded';
  return scoreGrade(g);
}
// D8: a task object (pin, fix, review) may carry "tier": "T2" | "T3" (run 4 will); absent or T1 counts as today, a tier
// counts apart under '<category>@T<k>'
const CALIBRATION_TASKS = [['pin-tests', (o) => scoreGrade(o?.pin), (o) => o?.pin?.tier], ['fix', (o) => scoreGrade(o?.fix), (o) => o?.fix?.tier], ['review', reviewGrade, (o) => o?.review?.tier]];
const CALIBRATION_SUFFIXES = ['', '@T2', '@T3'];

function calibrationEvidence(policy, traceDir) {
  if (!existsSync(traceDir)) return null;
  const dirs = readdirSync(traceDir).map((d) => [d, /^calibration-([1-9]\d*)$/.exec(d)]).filter(([d, m]) => m && existsSync(join(traceDir, d, 'observations.json')))
    .sort((a, b) => Number(a[1][1]) - Number(b[1][1])).map(([d]) => d);
  if (!dirs.length) return null;
  const runs = [];
  const profiles = {};
  const seen = {};
  for (const run of dirs) {
    const path = join(traceDir, run, 'observations.json');
    // a read error (a directory, no permission) refuses the run like an unparseable file: exit 4, never a stack trace (P2-1)
    let bytes;
    try { bytes = readFileSync(path); } catch (e) { throw new RouterError(4, `${run}/observations.json is unreadable (${e.code ?? e.message}); refusing to rate (${path})`); }
    let obs;
    try { obs = JSON.parse(bytes); } catch { throw new RouterError(4, `${run}/observations.json is unparseable; refusing to rate (${path})`); }
    if (!obs || typeof obs !== 'object' || Array.isArray(obs)) throw new RouterError(4, `${run}/observations.json is not an object of observations (${path})`);
    for (const [key, o] of Object.entries(obs)) {
      if (!o || typeof o !== 'object' || Array.isArray(o)) throw new RouterError(4, `${run}/observations.json: observation ${JSON.stringify(key)} is not an object; refusing to rate (${path})`);
    }
    runs.push({ run, 'observations-sha256': sha256(bytes) });
    for (const [key, o] of Object.entries(obs)) {
      // an observation is a profile's model (any of its own tasks' usage, never the grader's) at the effort its name ends in
      const model = Object.entries(o?.usage ?? {}).filter(([t]) => t !== 'grade').map(([, u]) => u).find((u) => isStr(u?.model))?.model;
      const name = isStr(o?.profile) ? o.profile : key;
      const pr = policy.profiles.find((p) => p.model === model && p.effort === name.split('-').pop());
      const label = pr ? pr.id : `${name} (no policy profile)`;
      for (const [cat, grade, tierOf] of CALIBRATION_TASKS) {
        const g = grade(o);
        if (g === null) continue; // the task was not run for this profile: nothing to count
        const t = tierOf(o);
        if (t !== undefined && !TIERS.includes(t)) throw new RouterError(4, `${run}/observations.json: observation ${JSON.stringify(key)} ${cat} tier ${JSON.stringify(t)} is not T1, T2 or T3; refusing to rate (${path})`);
        const k = t === undefined || t === 'T1' ? cat : `${cat}@${t}`;
        const c = ((profiles[label] ??= {})[k] ??= { pass: 0, partial: 0, fail: 0, ungraded: 0 });
        c[g] += 1;
        const r = ((seen[label] ??= {})[k] ??= []);
        if (!r.includes(run)) r.push(run);
      }
    }
  }
  const lines = [];
  for (const label of Object.keys(profiles).sort()) {
    for (const [cat] of CALIBRATION_TASKS) {
      for (const suffix of CALIBRATION_SUFFIXES) {
        const k = `${cat}${suffix}`;
        const c = profiles[label][k];
        if (!c) continue;
        lines.push(`CALIBRATION ${label} ${k}: ${c.pass} pass, ${c.partial} partial, ${c.fail} fail${c.ungraded ? `, ${c.ungraded} ungraded` : ''} (${seen[label][k].join(', ')})`);
      }
    }
  }
  return { doc: { runs, profiles }, lines };
}

export function rate({ policyPath = DEFAULT_POLICY, traceDir = DEFAULT_TRACE, now = new Date().toISOString() } = {}) {
  if (isoMs(now) === null) throw invalid('--now must be ISO-8601');
  const policy = loadPolicy(policyPath);
  const records = readLedger(traceDir);
  // E7: a typed reference to an outcome record, its path relative to the policy file's directory (where E1 resolves it)
  const policyDir = dirname(resolve(policyPath));
  // F1: an outcome store outside the policy file's directory cannot be referenced, so nothing is offered to paste
  const storeInside = inside(policyDir, traceDir);
  const reference = (o, category) => {
    if (!storeInside || !isInt(o.seq, 1) || o.ms === null) return null;
    const path = relative(policyDir, join(resolve(traceDir), 'outcomes', `${o.task}-${o.seq}.json`)).split(sep).join('/');
    return `outcome: ${o.task} ${category}${o.declared ? `@${o.declared}` : ''} accepted ${isoOf(o.ms).slice(0, 10)} (${path})`;
  };
  const { stats, proposals } = learn(policy, records, categoryMap(traceDir), reference);
  const learned = policy['usage-windows'] ? usageLearning(policy['usage-windows'], readUsage(traceDir), records) : null;
  const usageProposals = learned ? learned.proposals : [];
  const calibration = calibrationEvidence(policy, traceDir);
  const headroom = headroomProposals(policy, records);
  const path = ledgerPath(traceDir);
  const doc = {
    _comment: 'derived by route.mjs rate from ledger.jsonl and the decision files; regenerated on every run, never hand-edited',
    'policy-revision': policy['policy-revision'] ?? null,
    'ledger-sha256': existsSync(path) ? sha256(readFileSync(path)) : null,
    'outcomes-counted': latestOutcomes(records).length,
    'outcome-records': records.filter((r) => r.kind === 'outcome').length,
    stats,
    proposals,
    'headroom-proposals': headroom,
    ...(learned ? { usage: learned.usage, 'usage-proposals': usageProposals, 'usage-sha256': existsSync(usagePath(traceDir)) ? sha256(readFileSync(usagePath(traceDir))) : null } : {}),
    ...(calibration ? { calibration: calibration.doc } : {})
  };
  mkdirSync(traceDir, { recursive: true });
  const statsPath = join(traceDir, 'qualification-stats.json');
  writeFileSync(statsPath, `${JSON.stringify(sortKeys(doc), null, 2)}\n`);
  const flags = expiryFlags(policy, isoMs(now));
  const lines = [`${statsPath} regenerated (${doc['outcomes-counted']} outcomes)`];
  if (calibration) lines.push(...calibration.lines);
  const paste = (p) => {
    if (p.references) return `; typed evidence to paste: ${p.references.map((x) => JSON.stringify(x)).join(', ')}`;
    return p.kind === 'qualify' && !storeInside ? `; no typed evidence to paste: the outcome store ${resolve(traceDir)} is outside the policy file's directory ${policyDir}, and a reference cannot leave it (E1)` : '';
  };
  for (const p of proposals) lines.push(`PROPOSAL ${proposalText(p)}; not applied — the lead ratifies by editing host-policy.json${paste(p)}`);
  for (const h of headroom) lines.push(`PROPOSAL profiles.${h.profile}.headroom-tested: ${h.from} -> ${h.to} (accepted outcome ${h.task} completed ${h.tokens} tokens); not applied — the lead ratifies by editing host-policy.json`);
  for (const p of usageProposals) lines.push(`PROPOSAL usage-windows.windows.${p.window}.utilization-per-mtok: ${p.from} -> ${p.to} (${p.reason}); not applied — the lead ratifies by editing host-policy.json`);
  for (const f of flags) lines.push(`FLAG ${f.profile}: ${f.reason}`);
  if (!proposals.length && !headroom.length && !usageProposals.length && !flags.length) lines.push('no proposals');
  return { stats: doc, proposals, headroomProposals: headroom, usageProposals, flags, statsPath, text: `${lines.join('\n')}\n` };
}

// ---------------------------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------------------------
function parseArgs(argv) {
  const pos = [];
  const opt = {};
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const v = argv[i + 1];
      if (v === undefined || v.startsWith('--')) throw invalid(`${a} needs a value`);
      opt[a.slice(2)] = v;
      i += 1;
    } else pos.push(a);
  }
  return { pos, opt };
}

export function main(argv = process.argv.slice(2)) {
  try {
    const { pos, opt } = parseArgs(argv);
    const unknown = Object.keys(opt).filter((k) => !['trace', 'policy', 'now', 'deviation', 'project-stop'].includes(k));
    if (unknown.length) throw invalid(`unknown option --${unknown[0]}`);
    const base = { traceDir: opt.trace ? resolve(opt.trace) : DEFAULT_TRACE, policyPath: opt.policy ? resolve(opt.policy) : DEFAULT_POLICY };
    const now = opt.now ?? new Date().toISOString();
    const [cmd, a, b] = pos;
    if (cmd === 'decide' && a) {
      process.stdout.write(decide(readJsonFile(a, 'request'), base).text);
    } else if (cmd === 'dispatch' && a && b) {
      let projectStop = null;
      if (opt['project-stop'] !== undefined) {
        try { projectStop = JSON.parse(opt['project-stop']); } catch (e) { throw invalid(`--project-stop is not JSON (${e.message}); expected ${PROJECT_STOP_USAGE}`); }
      }
      const r = dispatch(a, b, { ...base, now, deviation: opt.deviation ?? null, projectStop });
      process.stdout.write(`dispatch recorded: ${r['task-id']} seq ${r.seq} ${r.profile} (calls ${r.counters['calls-used']} / ${r.counters['calls-limit']}, repairs ${r.counters['repairs-used']} / ${r.counters['repairs-allowed']})\n${r.detail}\n`);
    } else if (cmd === 'outcome' && a) {
      const r = recordOutcome(readJsonFile(a, 'outcome'), { ...base, now });
      process.stdout.write(`outcome recorded: ${r['task-id']} seq ${r.seq} ${r.detail}\n`);
    } else if (cmd === 'status' && a) {
      process.stdout.write(status(a, base).text);
    } else if (cmd === 'rate') {
      process.stdout.write(rate({ ...base, now }).text);
    } else if (cmd === 'usage' && a) {
      const r = recordUsage(readJsonFile(a, 'usage reading'), { ...base, now });
      process.stdout.write(`usage reading recorded: ${r.ts} ${Object.entries(r.windows).map(([w, x]) => `${w} ${x.utilization} (resets ${x['resets-at']})`).join(', ')}\n`);
      // ts is the observation time staleness is measured from; the paste can come long after the event (SW-4)
      if (opt.now === undefined) process.stderr.write(`route.mjs: note: no --now, so the reading's ts is the clock (${r.ts}); pass --now <the rate_limit_event's own timestamp>, because staleness is measured from ts\n`);
    } else if (cmd === 'usage') {
      process.stdout.write(usageSummary({ ...base, now }).text);
    } else {
      throw invalid('usage: route.mjs decide <request.json> | dispatch <task-id> <profile-id> --project-stop <json> | outcome <outcome.json> | status <task-id> | rate | usage [<reading.json>]  [--trace <dir>] [--policy <file>] [--now <iso>] [--deviation <reason>]');
    }
    return 0;
  } catch (e) {
    if (e instanceof RouterError) {
      process.stderr.write(`route.mjs: ${e.message}\n`);
      return e.code;
    }
    if (e?.code === 'EEXIST') {
      process.stderr.write(`route.mjs: refusing to overwrite ${e.path}\n`);
      return 4;
    }
    throw e;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main();
}
