// Lineage: the accepted journey test of the host pack moonaliza-x2-1 (tools/calibration/subject-pack/host/moonaliza-x2-1); make-repo.sh
// adds it to the accepted commit at tests/zz_accepted_x2_1.test.ts and grade.sh places it in a candidate's checkout, where it runs against
// the candidate's source. It names only what the base already has (Vault, GitHubAccountStore and the startup statements of src/main/index.ts),
// never a name the accepted fix added, so a different correct fix passes it too.
import { afterEach, describe, expect, test, vi } from 'vitest';
import { createCipheriv, createDecipheriv, randomBytes } from 'node:crypto';
import fs, { cpSync, existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import fsp, { mkdtemp, rm } from 'node:fs/promises';
import { syncBuiltinESMExports } from 'node:module';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { transformSync } from 'esbuild';
import ts from 'typescript';
import * as vaultModule from '../src/main/vault';
import * as storeModule from '../src/main/github-account-store';
import { Vault } from '../src/main/vault';
import { GitHubAccountStore, type GitHubAccount } from '../src/main/github-account-store';

// X2-1: a crash after the account file names a new pair but before the pair is committed leaves the pair staged in the vault. If the next
// start cannot read the file (an I/O error, not a missing file), the store knows no references, and the startup reconcile must not delete
// the staged pair the file names; the next start that reads the file then finds the pair and commits it. The start is driven as the app
// runs it: the store's open(), then the statements src/main/index.ts runs between the engine's references and the supervisor (the reconcile
// and both finishStartup calls), taken from the candidate's own index.ts, so the test holds whatever names that wiring uses. A later start
// runs with the wall clock moved ten years past the crash, so no age limit on a kept pair can pass for a start after a long time away.

const KEY = randomBytes(32);
const cryptor = {
  isEncryptionAvailable: () => true,
  encryptString(value: string) {
    const iv = randomBytes(12); const cipher = createCipheriv('aes-256-gcm', KEY, iv);
    const data = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]); return Buffer.concat([iv, cipher.getAuthTag(), data]);
  },
  decryptString(value: Buffer) {
    const decipher = createDecipheriv('aes-256-gcm', KEY, value.subarray(0, 12)); decipher.setAuthTag(value.subarray(12, 28));
    return Buffer.concat([decipher.update(value.subarray(28)), decipher.final()]).toString('utf8');
  },
};
const CLIENT = 'Iv1.u2-store-test';
const T0 = Date.UTC(2026, 9, 13, 10, 0, 0);
// Token stand-ins: the vault and the store treat a token as an opaque string, so no provider-shaped value is needed.
const tokens = () => ({ access: `x2-access-${randomBytes(16).toString('hex')}`, refresh: `x2-refresh-${randomBytes(16).toString('hex')}`,
  accessExpiresInS: 28_800, refreshExpiresInS: 15_897_600 });
const refsOf = (account: { accessRef: string; refreshRef: string | null } | null | undefined): string[] =>
  !account ? [] : account.refreshRef === null ? [account.accessRef] : [account.accessRef, account.refreshRef];

const roots: string[] = [];
afterEach(async () => { vi.useRealTimers(); for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true }); });

const DAY = 86_400_000;
/** Moves the wall clock (Date alone; timers stay real) `days` past now: the vault stamps a staged entry with Date.now(), and a start may
 *  come long after the crash, so nothing about the kept pair may depend on how recent it is. The rows move it ten years (3650 days), far
 *  past any age a keep could be limited to (a day, a month, a year); the store's clock is injected and fixed, so only the vault sees it. */
function later(days: number): void { vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(Date.now() + days * DAY); }

/** Every read of one path fails with `code` (EACCES, EBUSY, EIO) until the returned function runs: lstat, stat, open and readFile in
 *  node:fs/promises and their synchronous forms in node:fs, synced to every importer (the node project runs without isolation, so no
 *  module mock). A retry inside the start fails too, as it would while another process holds the file. */
function failingReads(path: string, code: string): () => void {
  const target = resolve(path);
  const swapped: Array<[Record<string, unknown>, string, unknown]> = [];
  const swap = (module: Record<string, unknown>, name: string, sync: boolean) => {
    const real = module[name] as (...args: unknown[]) => unknown; swapped.push([module, name, real]);
    module[name] = (...args: unknown[]) => {
      if (typeof args[0] === 'string' && resolve(args[0]) === target) {
        const error = Object.assign(new Error(`${code}: the account file cannot be read`), { code });
        if (sync) throw error;
        return Promise.reject(error);
      }
      return real(...args);
    };
  };
  for (const name of ['lstat', 'stat', 'open', 'readFile']) swap(fsp as unknown as Record<string, unknown>, name, false);
  for (const name of ['lstatSync', 'statSync', 'openSync', 'readFileSync']) swap(fs as unknown as Record<string, unknown>, name, true);
  syncBuiltinESMExports();
  return () => { for (const [module, name, real] of swapped.reverse()) module[name] = real; syncBuiltinESMExports(); };
}

type Wiring = (vault: Vault, references: string[], collectorSettings: unknown, githubStore: GitHubAccountStore) => Promise<void>;
const START = ['vault', 'references', 'collectorSettings', 'githubStore'];
// The two other modules in scope, as the candidate's source exports them: a name index.ts imports from one of them is in scope in the
// startup statements, so it is bound here to the same export (a helper the wiring calls, say).
const MODULES: Record<string, Record<string, unknown>> = { './github-account-store': storeModule, './vault': vaultModule };
/** The names src/main/index.ts imports from the modules in scope (named, renamed with `as`, a default or a namespace), each with its
 *  export, read from the parsed file, so comments and line breaks inside an import do not matter; type-only imports bind nothing. */
function imported(file: ts.SourceFile): Map<string, unknown> {
  const names = new Map<string, unknown>();
  for (const statement of file.statements) {
    if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier)) continue;
    const module = MODULES[statement.moduleSpecifier.text]; const clause = statement.importClause;
    if (!module || !clause || clause.isTypeOnly) continue;
    if (clause.name) names.set(clause.name.text, module.default);
    const bindings = clause.namedBindings;
    if (bindings && ts.isNamespaceImport(bindings)) names.set(bindings.name.text, module);
    if (bindings && ts.isNamedImports(bindings)) {
      for (const element of bindings.elements) if (!element.isTypeOnly) names.set(element.name.text, module[(element.propertyName ?? element.name).text]);
    }
  }
  for (const name of START) names.delete(name);
  return names;
}
/** The first node under `node` (itself included) that passes `test`, depth first. */
function find(node: ts.Node, test: (node: ts.Node) => boolean): ts.Node | undefined {
  return test(node) ? node : ts.forEachChild(node, child => find(child, test));
}
/** The engine call that reads the references: a call with an object argument whose `method` is the string 'vault.references'. */
const isEngineCall = (node: ts.Node): boolean => ts.isCallExpression(node) && node.arguments.some(arg => ts.isObjectLiteralExpression(arg)
  && arg.properties.some(p => ts.isPropertyAssignment(p) && (ts.isIdentifier(p.name) || ts.isStringLiteral(p.name)) && p.name.text === 'method'
    && ts.isStringLiteralLike(p.initializer) && p.initializer.text === 'vault.references'));
const isAttach = (node: ts.Node): boolean => ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)
  && node.expression.name.text === 'attach' && ts.isIdentifier(node.expression.expression) && node.expression.expression.text === 'supervisor';
const declaresReferences = (statement: ts.Statement): boolean => ts.isVariableStatement(statement)
  && statement.declarationList.declarations.some(d => ts.isIdentifier(d.name) && d.name.text === 'references');
/** The startup statements of the candidate's src/main/index.ts, found in the file as TypeScript parses it (so no comment, string, regex
 *  literal, line break or missing `;` moves them): in the block that holds the statement with the engine call, every statement after that
 *  one (or after a later one that declares `references`, when the call's result is parsed in a statement of its own) up to the statement
 *  that calls supervisor.attach(), run with the start's vault, store and engine references, a collector with no token, and what index.ts
 *  imports from the modules in scope. No other name of index.ts reaches them here. */
function wiring(): Wiring {
  const source = readFileSync(new URL('../src/main/index.ts', import.meta.url), 'utf8').replace(/\r\n/g, '\n');
  const file = ts.createSourceFile('index.ts', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  let statement = find(file, isEngineCall);
  while (statement && !ts.isBlock(statement.parent) && !ts.isSourceFile(statement.parent)) statement = statement.parent;
  const statements: readonly ts.Statement[] = statement ? (statement.parent as ts.Block | ts.SourceFile).statements : [];
  const call = statements.indexOf(statement as ts.Statement);
  const to = call < 0 ? -1 : statements.findIndex((s, index) => index > call && find(s, isAttach) !== undefined);
  if (call < 0 || to < 0) throw new Error('the startup statements of src/main/index.ts were not found');
  const declared = statements.findIndex((s, index) => index > call && index < to && declaresReferences(s));
  const from = call >= 0 && !declaresReferences(statements[call]!) && declared >= 0 ? declared : call;
  const body = source.slice(statements[from]!.end, statements[to]!.getStart(file));
  const extra = imported(file);
  const { code } = transformSync(`(async (${[...START, ...extra.keys()].join(', ')}) => {\n${body}\n});`, { loader: 'ts' });
  const run = new Function(`return ${code.trim().replace(/;$/, '')}`)() as (...args: unknown[]) => Promise<void>;
  return (vault, references, collectorSettings, githubStore) => run(vault, references, collectorSettings, githubStore, ...extra.values());
}
const noCollectorToken = { references: (): string[] => [], finishStartup: async () => {} };

interface Hooks { beforeCommit?: (count: number) => void; afterStaged?: (count: number) => void; failRemove?: boolean }
/** The real vault, with hooks on the calls the store makes: a commit about to run, a staged entry just saved, a removal that fails. */
function recorded(real: Vault, hooks: Hooks): Vault {
  let commits = 0; let staged = 0;
  return new Proxy(real, {
    get(target, key) {
      const value = Reflect.get(target, key, target) as unknown;
      if (typeof value !== 'function') return value;
      const call = (...args: unknown[]) => (value as (...a: unknown[]) => unknown).apply(target, args);
      if (key === 'commit') return (ref: string) => { const count = ++commits; hooks.beforeCommit?.(count); return call(ref); };
      if (key === 'saveStaged') return async (secret: string) => { const ref = await call(secret); const count = ++staged; hooks.afterStaged?.(count); return ref; };
      if (key === 'remove' && hooks.failRemove) return async () => { throw Object.assign(new Error('EBUSY'), { code: 'EBUSY' }); };
      return call;
    },
  });
}

/** A first session: the real vault behind the hooks, and a snapshot of the data directory as a crash at that moment leaves it. */
async function firstSession() {
  const root = await mkdtemp(join(tmpdir(), 'x2-1-journey-')); roots.push(root);
  const data = join(root, 'data'); const file = join(data, 'github', 'account.json');
  const vault = new Vault(join(data, 'vault'), cryptor); await vault.initialize('epoch-1');
  const hooks: Hooks = {};
  const store = new GitHubAccountStore(file, recorded(vault, hooks), CLIENT, () => T0);
  await store.open();
  let snapshots = 0;
  return {
    vault, store, hooks,
    signIn: () => store.replace(tokens(), T0, 'sign-in', () => true),
    refresh: (from: GitHubAccount) => store.replace(tokens(), T0 + 60_000, 'refresh', live => live?.accessRef === from.accessRef),
    snapshot() { const dir = join(root, `crash-${++snapshots}`); cpSync(data, dir, { recursive: true }); return dir; },
  };
}

/** A later start as the app runs it: a new vault and store on `dir`, open(), then index.ts's startup statements. With `unread`, every read of
 *  the account file fails with that code for the whole start. */
async function start(dir: string, options: { unread?: string; clientId?: string; engine?: string[] } = {}) {
  const file = join(dir, 'github', 'account.json');
  const vault = new Vault(join(dir, 'vault'), cryptor); await vault.initialize('epoch-2');
  const store = new GitHubAccountStore(file, vault, options.clientId ?? CLIENT, () => T0 + 3_600_000);
  const run = wiring();
  const restore = options.unread ? failingReads(file, options.unread) : () => {};
  try { await store.open(); await run(vault, options.engine ?? [], noCollectorToken, store); }
  finally { restore(); }
  return { vault, store };
}

const fileAt = (dir: string) => join(dir, 'github', 'account.json');
const accountFile = (dir: string) => existsSync(fileAt(dir))
  ? JSON.parse(readFileSync(fileAt(dir), 'utf8')) as { account: { accessRef: string; refreshRef: string | null } | null; retiredRefs: string[] }
  : null;
const entries = (dir: string) => (JSON.parse(readFileSync(join(dir, 'vault', 'index.json'), 'utf8')) as { entries: Record<string, { state: string }> }).entries;
const bins = (dir: string) => readdirSync(join(dir, 'vault')).filter(name => name.endsWith('.bin')).sort();

/** The start reads `expected` as the account, and the file, the vault index and the encrypted files agree with it, nothing else left. */
async function expectAlone(dir: string, next: { vault: Vault; store: GitHubAccountStore }, expected: string[]) {
  expect(refsOf(next.store.current())).toEqual(expected);
  expect(refsOf(accountFile(dir)?.account)).toEqual(expected);
  expect(accountFile(dir)?.retiredRefs ?? []).toEqual([]);
  const index = entries(dir);
  expect(Object.keys(index).sort()).toEqual([...expected].sort());
  expect(Object.values(index).every(entry => entry.state === 'committed')).toBe(true);
  expect(bins(dir)).toEqual(expected.map(ref => `${ref}.bin`).sort());
  for (const ref of expected) expect(await next.vault.has(ref)).toBe(true);
}

type Kind = 'first sign-in' | 'sign-in' | 'refresh';
/** The data directory as a crash leaves it just before commit `at` runs during a replace: the file already names the new pair. A first
 *  sign-in's commits are 1 and 2; after a sign-in, the replace's commits are 3 and 4. */
async function crashBeforeCommit(kind: Kind, at: number) {
  const session = await firstSession();
  const old = kind === 'first sign-in' ? null : await session.signIn();
  let dir: string | undefined;
  session.hooks.beforeCommit = count => { if (count === at) dir = session.snapshot(); };
  const next = kind === 'refresh' ? await session.refresh(old!) : await session.signIn();
  expect(dir).toBeDefined();
  return { dir: dir!, pair: refsOf(next), old: refsOf(old) };
}

// A row runs two or three starts and takes seconds; under a loaded host it can pass the subject's 15 s testTimeout, and a
// timeout here would fail a correct fix, so every row has its own.
const ROW = { timeout: 120_000 };

describe('X2-1 journey: a crash leaves the new pair staged, the next start cannot read the account file, the start after it can', ROW, () => {
  const crashes: Array<[Kind, number, string[]]> = [
    ['first sign-in', 1, ['staged', 'staged']],
    ['sign-in', 3, ['staged', 'staged']],
    ['refresh', 3, ['staged', 'staged']],
    ['refresh', 4, ['committed', 'staged']],
  ];
  for (const [kind, at, states] of crashes) for (const code of ['EACCES', 'EBUSY', 'EIO']) {
    test(`${kind}, crash before commit ${at}, ${code} at the next start: the pair survives that start and is live and committed after the next`, async () => {
      const { dir, pair } = await crashBeforeCommit(kind, at);
      expect(refsOf(accountFile(dir)?.account)).toEqual(pair);                 // the crash came after the file named the pair
      expect(pair.map(ref => entries(dir)[ref]?.state)).toEqual(states);
      const before = readFileSync(fileAt(dir), 'utf8');

      later(3650);                                                             // the next start comes ten years after the crash
      const unread = await start(dir, { unread: code });
      expect(unread.store.current()).toBeNull();                               // that start reads no account
      expect(readFileSync(fileAt(dir), 'utf8')).toBe(before);                  // and leaves the file as it was
      expect(pair.map(ref => entries(dir)[ref]?.state)).toEqual(states);       // the pair is still in the vault, in the crash's states,
      for (const ref of pair) expect(bins(dir)).toContain(`${ref}.bin`);       // with its encrypted files

      await expectAlone(dir, await start(dir), pair);                          // the next start reads the file and commits the pair
      await expectAlone(dir, await start(dir), pair);                          // and a further start finds the same
    });
  }

  // A file that stays unreadable (a bad permission, a lock held for days) gives several such starts in a row, and the promise does not
  // depend on how many: so no limit on the number of unreadable starts a kept pair survives can pass for four of them, and the
  // same code twice in a row (a lasting permission error) is no sign the pair was abandoned.
  test('first sign-in before commit 1 and refresh before commit 4, then EACCES, EACCES again, EBUSY and EIO at four starts in a row, ten years apart: the pair survives all four and is live and committed after the next', async () => {
    const forms: Array<[Kind, number, string[]]> = [['first sign-in', 1, ['staged', 'staged']], ['refresh', 4, ['committed', 'staged']]];
    for (const [kind, at, states] of forms) {
      vi.useRealTimers();
      const { dir, pair } = await crashBeforeCommit(kind, at);
      expect(pair.map(ref => entries(dir)[ref]?.state), kind).toEqual(states);
      const before = readFileSync(fileAt(dir), 'utf8');

      for (const [index, code] of ['EACCES', 'EACCES', 'EBUSY', 'EIO'].entries()) {
        const step = `${kind}, start ${index + 1} (${code})`;
        vi.useRealTimers(); later(3650 * (index + 1));                        // each start ten years after the one before it
        const unread = await start(dir, { unread: code });
        expect(unread.store.current(), step).toBeNull();
        expect(readFileSync(fileAt(dir), 'utf8'), step).toBe(before);
        expect(pair.map(ref => entries(dir)[ref]?.state), step).toEqual(states);
        for (const ref of pair) expect(bins(dir), step).toContain(`${ref}.bin`);
      }

      vi.useRealTimers(); later(3650 * 5);
      await expectAlone(dir, await start(dir), pair);                          // the next start reads the file and commits the pair
    }
  });
});

describe('what an unreadable start still deletes, and what a readable start deletes after it', ROW, () => {
  test('a sign-out whose removals failed: a start that cannot read the file still deletes the tombstoned pair and commits a referenced staged entry', async () => {
    const session = await firstSession();
    const a = refsOf(await session.signIn());
    const engineRef = await session.vault.saveStaged(`x2-engine-${randomBytes(16).toString('hex')}`);
    session.hooks.failRemove = true;
    expect(await session.store.clear(() => true)).toBe('durable');
    const dir = session.snapshot();
    expect(a.map(ref => entries(dir)[ref]?.state)).toEqual(['tombstoned', 'tombstoned']);

    await start(dir, { unread: 'EBUSY', engine: [engineRef] });
    expect(Object.keys(entries(dir))).toEqual([engineRef]);
    expect(entries(dir)[engineRef]?.state).toBe('committed');
    expect(bins(dir)).toEqual([`${engineRef}.bin`]);
  });

  test('a crash after staging, before the file write: after four starts in a row that cannot read the file, the next readable start deletes the orphan pair', async () => {
    const session = await firstSession();
    const a = refsOf(await session.signIn());
    let dir: string | undefined;
    session.hooks.afterStaged = count => { if (count === 4) dir = session.snapshot(); };
    await session.signIn();
    expect(dir).toBeDefined();
    expect(Object.values(entries(dir!)).filter(entry => entry.state === 'staged')).toHaveLength(2);

    for (const [index, code] of ['EACCES', 'EACCES', 'EBUSY', 'EIO'].entries()) {  // no run of them makes the orphan pair one to keep
      vi.useRealTimers(); later(3650 * (index + 1));
      await start(dir!, { unread: code });
    }
    vi.useRealTimers(); later(3650 * 5);
    await expectAlone(dir!, await start(dir!), a);
  });

  test('a sign-out, then a sign-in that crashed after staging, before the file write: the next readable start deletes the orphan pair (a file naming no account is read)', async () => {
    const session = await firstSession();
    await session.signIn();
    expect(await session.store.clear(() => true)).toBe('durable');
    let dir: string | undefined;
    session.hooks.afterStaged = count => { if (count === 4) dir = session.snapshot(); };
    await session.signIn();
    expect(dir).toBeDefined();
    expect(accountFile(dir!)?.account).toBeNull();                             // the file reads as signed out
    expect(Object.values(entries(dir!)).map(entry => entry.state)).toEqual(['staged', 'staged']);

    const next = await start(dir!);                                            // a readable start: the orphan pair goes, files and all
    expect(next.store.current()).toBeNull();
    expect(entries(dir!)).toEqual({});
    expect(bins(dir!)).toEqual([]);
    expect(accountFile(dir!)?.account).toBeNull();
  });

  test('a sign-out, a sign-in that crashed after staging, then a refused file (invalid JSON, over 64 KiB, an extra key, version 2): the start deletes the orphan pair and rewrites the file (a refused file is read)', async () => {
    const session = await firstSession();
    await session.signIn();
    expect(await session.store.clear(() => true)).toBe('durable');
    let crash: string | undefined;
    session.hooks.afterStaged = count => { if (count === 4) crash = session.snapshot(); };
    await session.signIn();
    expect(crash).toBeDefined();
    const valid = readFileSync(fileAt(crash!), 'utf8');                        // the file the sign-out wrote, naming no account
    const signedOut = JSON.parse(valid) as Record<string, unknown>;
    expect(signedOut.account).toBeNull();
    expect(Object.values(entries(crash!)).map(entry => entry.state)).toEqual(['staged', 'staged']);

    // Spec 4.4: a missing, invalid, oversized or extra-key file reads as no account. Unlike a file that cannot be read (an errno
    // code), a refused one was read: it names no reference, so the start deletes the orphan pair and finishStartup rewrites it.
    const refused: Array<[string, string]> = [
      ['invalid JSON', valid.slice(0, valid.lastIndexOf('}'))],
      ['over 64 KiB', valid + ' '.repeat(64 * 1024)],                         // valid JSON, refused for its size alone
      ['an extra key', JSON.stringify({ ...signedOut, extra: true })],
      ['version 2', JSON.stringify({ ...signedOut, version: 2 })],            // a value the schema refuses, beside the key it refuses
    ];
    for (const [index, [name, text]] of refused.entries()) {
      const dir = `${crash!}-refused-${index + 1}`;
      cpSync(crash!, dir, { recursive: true });
      writeFileSync(fileAt(dir), text);
      const next = await start(dir);
      expect(next.store.current(), name).toBeNull();
      expect(entries(dir), name).toEqual({});
      expect(bins(dir), name).toEqual([]);
      expect(readFileSync(fileAt(dir), 'utf8'), name).not.toBe(text);         // rewritten
      expect(Object.keys(accountFile(dir) ?? {}).sort(), name).toEqual(Object.keys(signedOut).sort());
      expect(accountFile(dir)?.account, name).toBeNull();
    }
  });

  test('a first sign-in that crashed before commit 1, then the file naming the pair is refused (invalid JSON, over 64 KiB, an extra key, version 2): the start deletes the pair and rewrites the file (a refused file names no reference)', async () => {
    const { dir: crash, pair } = await crashBeforeCommit('first sign-in', 1);
    const valid = readFileSync(fileAt(crash), 'utf8');                         // the file the sign-in wrote, naming the staged pair
    const named = JSON.parse(valid) as Record<string, unknown>;
    expect(refsOf(accountFile(crash)?.account)).toEqual(pair);
    expect(pair.map(ref => entries(crash)[ref]?.state)).toEqual(['staged', 'staged']);

    // Spec 4.4 again, for a file that still names an account (a newer app's file, say): what a refused file names is not read,
    // so it names no reference whatever it holds, and the start deletes the pair it names as it deletes any unreferenced one.
    const refused: Array<[string, string]> = [
      ['invalid JSON', valid.slice(0, valid.lastIndexOf('}'))],
      ['over 64 KiB', valid + ' '.repeat(64 * 1024)],
      ['an extra key', JSON.stringify({ ...named, extra: true })],
      ['version 2', JSON.stringify({ ...named, version: 2 })],
    ];
    for (const [index, [name, text]] of refused.entries()) {
      const dir = `${crash}-refused-${index + 1}`;
      cpSync(crash, dir, { recursive: true });
      writeFileSync(fileAt(dir), text);
      const next = await start(dir);
      expect(next.store.current(), name).toBeNull();
      expect(entries(dir), name).toEqual({});
      expect(bins(dir), name).toEqual([]);
      expect(readFileSync(fileAt(dir), 'utf8'), name).not.toBe(text);         // rewritten
      expect(Object.keys(accountFile(dir) ?? {}).sort(), name).toEqual(Object.keys(named).sort());
      expect(accountFile(dir)?.account, name).toBeNull();
    }
  });

  test('a first sign-in that crashed after staging, before any file existed: a start deletes the staged pair (a missing file is no account)', async () => {
    const session = await firstSession();
    let dir: string | undefined;
    session.hooks.afterStaged = count => { if (count === 2) dir = session.snapshot(); };
    await session.signIn();
    expect(dir).toBeDefined();
    expect(existsSync(fileAt(dir!))).toBe(false);
    expect(Object.values(entries(dir!)).filter(entry => entry.state === 'staged')).toHaveLength(2);

    const next = await start(dir!);
    expect(next.store.current()).toBeNull();
    expect(entries(dir!)).toEqual({});
    expect(bins(dir!)).toEqual([]);
  });

  test('a file issued to another app, with an orphan pair beside it: the start deletes the account and the orphan', async () => {
    const session = await firstSession();
    await session.signIn();
    let dir: string | undefined;
    session.hooks.afterStaged = count => { if (count === 4) dir = session.snapshot(); };
    await session.signIn();
    expect(dir).toBeDefined();

    const next = await start(dir!, { clientId: 'Iv1.another-app' });
    expect(next.store.current()).toBeNull();
    expect(next.store.openedAppChanged()).toBe(true);
    expect(entries(dir!)).toEqual({});
    expect(bins(dir!)).toEqual([]);
    expect(accountFile(dir!)?.account).toBeNull();
  });

  test('the vault reconcile with only the references deletes unreferenced staged and tombstoned entries and commits referenced ones', async () => {
    const root = await mkdtemp(join(tmpdir(), 'x2-1-journey-')); roots.push(root);
    const dir = join(root, 'vault');
    const vault = new Vault(dir, cryptor); await vault.initialize('epoch-1');
    const unreferenced = await vault.saveStaged('x2-unreferenced');
    const referenced = await vault.saveStaged('x2-referenced');
    const tombstoned = await vault.saveStaged('x2-tombstoned'); await vault.commit(tombstoned); await vault.tombstone(tombstoned);
    await vault.reconcile(new Set([referenced]));
    const index = (JSON.parse(readFileSync(join(dir, 'index.json'), 'utf8')) as { entries: Record<string, { state: string }> }).entries;
    expect(Object.keys(index)).toEqual([referenced]);
    expect(index[referenced]?.state).toBe('committed');
    expect(readdirSync(dir).filter(name => name.endsWith('.bin'))).toEqual([`${referenced}.bin`]);
    expect([unreferenced, tombstoned].some(ref => existsSync(join(dir, `${ref}.bin`)))).toBe(false);
  });
});
