// Lineage: the accepted journey test of the host pack moonaliza-x2-1 (tools/calibration/subject-pack/host/moonaliza-x2-1); make-repo.sh
// adds it to the accepted commit at tests/zz_accepted_x2_1.test.ts and grade.sh places it in a candidate's checkout, where it runs against
// the candidate's source. It names only what the base already has (Vault, GitHubAccountStore and the startup statements of src/main/index.ts),
// never a name the accepted fix added, so a different correct fix passes it too.
import { afterAll, afterEach, describe, expect, test, vi } from 'vitest';
import { spawn } from 'node:child_process';
import { createCipheriv, createDecipheriv, randomBytes } from 'node:crypto';
import fs, { cpSync, existsSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { buildSync, transformSync } from 'esbuild';
import ts from 'typescript';
import type * as VaultModule from '../src/main/vault';
import type * as StoreModule from '../src/main/github-account-store';
import type { GitHubAccount } from '../src/main/github-account-store';

// X2-1: a crash after the account file names a new pair but before the pair is committed leaves the pair staged in the vault. If the next
// start cannot read the file (an I/O error, not a missing file), the store knows no references, and the startup reconcile must not delete
// the staged pair the file names; the next start that reads the file then finds the pair and commits it. The start is driven as the app
// runs it: the store's open(), then the statements src/main/index.ts runs between the engine's references and the supervisor (the reconcile
// and both finishStartup calls), taken from the candidate's own index.ts, so the test holds whatever names that wiring uses. Each later
// start runs in a new process of its own, as the app's next start does, so nothing the first session or an earlier start kept in memory
// reaches it, and a start that cannot read the file fails every node:fs read of that file, by whatever name and path form it is reached,
// at the open or at the read, with an error shaped as a real one (code, errno, syscall, path). A later start runs with every clock it reads
// moved ten years past the crash and the data directory's file times moved back by as much, so no age limit on a kept pair can pass for a
// start after a long time away.

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
 *  past any age a keep could be limited to (a day, a month, a year); the store's clock is injected and fixed, so only the vault sees it. A
 *  start's own process runs with every clock it reads moved by as much (Date, performance's origin, Intl's default date and
 *  process.hrtime; the system's uptime stays, as the system has booted since), and before it runs, the times of every file and
 *  directory in the data directory are moved back by as much as the clock moved since they were written (`aged`), so a file's age by
 *  the real clock (a file the start writes, against the crash's) is as old as the start is late. */
function later(days: number): void { vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(Date.now() + days * DAY); }

// A start's process gets an empty environment, as the app's next process gets none of what this one set: so nothing the first
// session put in this process's environment reaches a later start, and no preload (NODE_OPTIONS) runs before the start's own.
const NO_ENV: Record<string, string> = {};

/** The subject's two modules, loaded afresh after a reset (the node project shares its module cache between files), for a first session
 *  and the vault-default row. A later start never runs here: it runs in a process of its own (`start`). */
async function load() {
  vi.resetModules();
  const vault: typeof VaultModule = await import('../src/main/vault');
  const store: typeof StoreModule = await import('../src/main/github-account-store');
  return { Vault: vault.Vault, GitHubAccountStore: store.GitHubAccountStore };
}
const { Vault } = await load(); type Vault = InstanceType<typeof Vault>;

// A later start's process: node running START_RUNNER, which loads the candidate's two modules from SUBJECT (esbuild bundles them once
// per run of this file, from the candidate's own source), drives the start and writes what the rows ask of it to a result file. An
// unreadable file is one every read fails on, as a file another process holds or a permission denies: a second read of it, through
// whatever node:fs function and by whatever name, meets the same error. A start's fault is set for its whole process, from before the
// subject's modules load, and it fails where a real one does (`at`), on the faulted file:
//  - at the stat (a directory on the way that may not be searched): every node:fs function that reads a file by its path fails: open,
//    readFile, stat, lstat, access, copyFile and cp (cp also from a directory that holds the file), each in its promise, callback and
//    synchronous form, and openAsBlob, and so does the module loader (an import or a require of it);
//  - at the open (a file another process opened without sharing it, a permission on the file): its stat, lstat and access succeed, and
//    open, readFile, copyFile, cp, openAsBlob and the module loader fail;
//  - at the read (a byte-range lock, a failing disk): its stat, lstat, access and open succeed, and every read of what the open gave
//    fails (read and readv of the descriptor, and a FileHandle's read, readv, readFile, readLines, stream and web stream), as do
//    readFile, copyFile, cp, openAsBlob and the module loader by the file's path.
// A stream (createReadStream) opens and reads its file through the callback open and read, so it meets the error too, as its 'error'
// event. The error has a real one's shape: the code, the errno and the message libuv gives for that code, the syscall that failed and the
// path. The faulted file is known by its identity (its device and file index, which a hard link shares), not by its path, so a hard
// link, a rename, a symlink, a junction or another spelling of the path reaches the same error; the path is taken in whatever form
// node:fs takes one (a string, a Buffer or another Uint8Array, a file: URL or an object node:fs reads as one), because node:fs itself
// reads it: the fault hands the argument to the real stat, so no form a read accepts is missed (only a descriptor or a FileHandle
// names no path, and those come from an open that met the fault). A read function the subject takes as it loads (promisify(fs.readFile),
// say) is a wrapper too: the wrappers are synced to every importer before the subject loads. A later start also runs with every clock
// the process reads moved by as much as the test's (see `later`).
const START_RUNNER = String.raw`
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import { createCipheriv, createDecipheriv, randomBytes } from 'node:crypto';
import { registerHooks, syncBuiltinESMExports } from 'node:module';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { getSystemErrorMap } from 'node:util';

const [subjectUrl, jobFile] = process.argv.slice(2);
const real = { statSync: fs.statSync, readdirSync: fs.readdirSync, readFileSync: fs.readFileSync, writeFileSync: fs.writeFileSync,
  realpathSync: fs.realpathSync.native };
const job = JSON.parse(real.readFileSync(jobFile, 'utf8'));
const report = value => { real.writeFileSync(job.result, JSON.stringify(value)); process.exit(0); };

/** A file's identity: its device and file index (a hard link, a rename, a symlink to it and every spelling of its path share them),
 *  or its real path where the file system gives no index. path is anything node:fs takes as a path: the real stat reads it, so every
 *  form it accepts is read as it reads it; anything else (a descriptor, a FileHandle, a value no read accepts) is no file. */
function identity(path) {
  if (typeof path === 'number') return null;
  try {
    const stats = real.statSync(path, { bigint: true });
    if (stats.ino !== 0n) return stats.dev + ':' + stats.ino;
    const full = real.realpathSync(path);
    return 'path:' + (process.platform === 'win32' ? full.toLowerCase() : full);
  } catch { return null; }
}
/** The path an argument names, as a string, for the error's message (the real path when node:fs can resolve it). */
function pathText(arg) { try { return real.realpathSync(arg); } catch { return String(arg); } }
let fault = null;
const SYSTEM_ERRORS = getSystemErrorMap();
/** The error a real failure of syscall gives for the start's code: libuv's errno and message for it, the syscall and the path. */
function failure(syscall, arg) {
  const code = job.unread;
  let errno; let text = 'unknown error';
  for (const [number, [name, description]] of SYSTEM_ERRORS) if (name === code) { errno = number; text = description; break; }
  const path = arg === undefined ? undefined : pathText(arg);
  const error = new Error(code + ': ' + text + ', ' + syscall + (path === undefined ? '' : " '" + path + "'"));
  return Object.assign(error, { errno, code, syscall }, path === undefined ? {} : { path });
}
/** Whether the directory tree at dir holds the faulted file, by any name. */
function holds(dir, depth) {
  let names; try { names = real.readdirSync(dir); } catch { return false; }
  for (const name of names) {
    const path = join(dir, name);
    if (identity(path) === fault) return true;
    let directory = false; try { directory = real.statSync(path).isDirectory(); } catch { /* gone or unreadable: no tree */ }
    if (directory && depth < 16 && holds(path, depth + 1)) return true;
  }
  return false;
}
/** Whether a read of arg meets the fault: arg is the faulted file (or, with tree, a directory that holds it). */
function hit(arg, tree) {
  if (fault === null) return false;
  if (identity(arg) === fault) return true;
  if (!tree) return false;
  try { return real.statSync(arg).isDirectory() && holds(real.realpathSync(arg), 0); } catch { return false; }
}
const PHASE = job.at; const AT_READ = PHASE === 'read';
// what an open at the read gave: the descriptors (until they are closed) and the FileHandles
const openFds = new Set(); const openHandles = new WeakSet();
const faultedFd = fd => typeof fd === 'number' && openFds.has(fd);
const faultedHandle = handle => handle !== null && typeof handle === 'object' && openHandles.has(handle);
/** Replaces module[name] with a function that fails as the fault says, in the function's form; when(args) gives the failing syscall
 *  (or null to call through) and after(result, args) sees what a call through returned. */
function wrap(module, name, form, when, after) {
  const original = module[name];
  if (typeof original !== 'function') return;
  module[name] = function (...args) {
    const syscall = when(args);
    if (syscall === null) {
      if (!after) return original.apply(this, args);
      if (form === 'callback' && typeof args[args.length - 1] === 'function') {
        const callback = args[args.length - 1];
        return original.apply(this, [...args.slice(0, -1), (error, ...rest) => { if (!error) after(rest[0], args); callback(error, ...rest); }]);
      }
      const result = original.apply(this, args);
      if (form === 'promise') return result.then(value => { after(value, args); return value; });
      after(result, args); return result;
    }
    const error = failure(syscall, typeof args[0] === 'number' || faultedHandle(args[0]) ? undefined : args[0]);
    if (form === 'promise') return Promise.reject(error);
    const callback = args[args.length - 1];
    if (form === 'callback' && typeof callback === 'function') { process.nextTick(callback, error); return undefined; }
    throw error;
  };
}
const FORMS = [[fsp, '', 'promise'], [fs, '', 'callback'], [fs, 'Sync', 'sync']];
const opened = (fd, args) => { if (hit(args[0], false)) (typeof fd === 'number' ? openFds.add(fd) : openHandles.add(fd)); };
for (const [module, suffix, form] of FORMS) {
  if (AT_READ) {
    // the open, the stat and the access succeed; the open's descriptor or FileHandle is remembered, and every read of it fails
    wrap(module, 'open' + suffix, form, () => null, opened);
    wrap(module, 'readFile' + suffix, form, args => faultedFd(args[0]) || faultedHandle(args[0]) || hit(args[0], false) ? 'read' : null);
    wrap(module, 'copyFile' + suffix, form, args => hit(args[0], false) ? 'copyfile' : null);
    wrap(module, 'cp' + suffix, form, args => hit(args[0], true) ? 'copyfile' : null);
  } else {
    // at the stat every call by the path fails, each with its own syscall; at the open the stat, lstat and access succeed
    const calls = [['open', 'open'], ['readFile', 'open'], ['copyFile', 'copyfile'], ['cp', 'copyfile']];
    if (PHASE === 'stat') calls.push(['stat', 'stat'], ['lstat', 'lstat'], ['access', 'access']);
    for (const [name, syscall] of calls) {
      const tree = name === 'cp';
      wrap(module, name + suffix, form, args => hit(args[0], tree) ? syscall : null);
    }
  }
}
if (AT_READ) {
  for (const name of ['read', 'readv']) {
    wrap(fs, name, 'callback', args => faultedFd(args[0]) ? 'read' : null);
    wrap(fs, name + 'Sync', 'sync', args => faultedFd(args[0]) ? 'read' : null);
  }
  for (const [name, form] of [['close', 'callback'], ['closeSync', 'sync']]) {
    wrap(fs, name, form, args => { openFds.delete(args[0]); return null; });
  }
}
wrap(fs, 'openAsBlob', 'promise', args => hit(args[0], false) ? (AT_READ ? 'read' : 'open') : null);
syncBuiltinESMExports();
if (AT_READ) {
  // a FileHandle's own reads (its stream, readLines and web stream read through its read)
  const handle = await fsp.open(jobFile, 'r'); const prototype = Object.getPrototypeOf(handle); await handle.close();
  for (const name of ['read', 'readv', 'readFile', 'readLines', 'createReadStream', 'readableWebStream']) {
    const original = prototype[name];
    if (typeof original !== 'function') continue;
    const returnsPromise = name === 'read' || name === 'readv' || name === 'readFile';
    prototype[name] = function (...args) {
      if (!faultedHandle(this)) return original.apply(this, args);
      const error = failure('read');
      if (returnsPromise) return Promise.reject(error);
      throw error;
    };
  }
}
registerHooks({
  load(url, context, nextLoad) {
    let path = null;
    if (fault !== null && url.startsWith('file:')) { try { path = fileURLToPath(url); } catch { path = null; } }
    if (path !== null && identity(path) === fault) throw failure(AT_READ ? 'read' : 'open', path);
    return nextLoad(url, context);
  },
});
if (job.unread) {
  fault = identity(job.file);
  if (fault === null) report({ error: 'the account file to fail is missing: ' + job.file });
}
if (job.shift) {
  // every clock the process reads moves by job.shift: Date (now, new Date() and Date() as a string), performance's origin (so
  // timeOrigin + now() is the moved wall clock), Intl's date formats with no date given (which read V8's own clock, not Date) and
  // process.hrtime (counted from the same point as the crash's, as on the same boot). The system's uptime stays: ten years on, the
  // system has booted since the crash, so a boot time it gives is after the crash.
  const RealDate = Date; const now = () => RealDate.now() + job.shift;
  globalThis.Date = new Proxy(RealDate, {
    construct: (target, args, newTarget) => Reflect.construct(target, args.length > 0 ? args : [now()], newTarget),
    apply: () => new RealDate(now()).toString(),
    get: (target, key, receiver) => key === 'now' ? now : Reflect.get(target, key, receiver),
  });
  const origin = performance.timeOrigin + job.shift;
  Object.defineProperty(performance, 'timeOrigin', { get: () => origin, configurable: true });
  const formats = Intl.DateTimeFormat.prototype; const format = Object.getOwnPropertyDescriptor(formats, 'format');
  Object.defineProperty(formats, 'format', { ...format, get() { const bound = format.get.call(this); return date => bound(date === undefined ? now() : date); } });
  const toParts = formats.formatToParts;
  formats.formatToParts = function (date) { return toParts.call(this, date === undefined ? now() : date); };
  const shiftNs = BigInt(job.shift) * 1_000_000n; const bigint = process.hrtime.bigint;
  const hrtime = previous => {
    const at = bigint() + shiftNs; const seconds = Number(at / 1_000_000_000n); const nanos = Number(at % 1_000_000_000n);
    if (!previous) return [seconds, nanos];
    let s = seconds - previous[0]; let n = nanos - previous[1]; if (n < 0) { s -= 1; n += 1e9; } return [s, n];
  };
  hrtime.bigint = () => bigint() + shiftNs;
  process.hrtime = hrtime;
  syncBuiltinESMExports();
}

const key = Buffer.from(job.key, 'hex');
const cryptor = {
  isEncryptionAvailable: () => true,
  encryptString(value) {
    const iv = randomBytes(12); const cipher = createCipheriv('aes-256-gcm', key, iv);
    const data = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]); return Buffer.concat([iv, cipher.getAuthTag(), data]);
  },
  decryptString(value) {
    const decipher = createDecipheriv('aes-256-gcm', key, value.subarray(0, 12)); decipher.setAuthTag(value.subarray(12, 28));
    return Buffer.concat([decipher.update(value.subarray(28)), decipher.final()]).toString('utf8');
  },
};
try {
  const subject = await import(subjectUrl);
  const modules = { './github-account-store': subject.store, './vault': subject.vault };
  const vault = new subject.vault.Vault(join(job.dir, 'vault'), cryptor); await vault.initialize('epoch-2');
  const store = new subject.store.GitHubAccountStore(job.file, vault, job.clientId, () => job.clock);
  const run = new Function('return ' + job.wiring.code)();
  const extra = job.wiring.binds.map(([specifier, name]) => name === '*' ? modules[specifier] : modules[specifier]?.[name]);
  await store.open();
  await run(vault, job.engine, { references: () => [], finishStartup: async () => {} }, store, ...extra);
  const current = store.current();
  let entries = {};
  try { entries = JSON.parse(real.readFileSync(join(job.dir, 'vault', 'index.json'), 'utf8')).entries ?? {}; } catch { entries = {}; }
  const has = {};
  for (const ref of new Set([...Object.keys(entries), ...(current ? [current.accessRef, current.refreshRef] : [])])) {
    if (typeof ref === 'string') has[ref] = await vault.has(ref);
  }
  report({ current, appChanged: store.openedAppChanged(), has });
} catch (error) { report({ error: String(error?.stack ?? error) }); }
`;
const HERE = dirname(fileURLToPath(import.meta.url));
const PROCESSES = mkdtempSync(join(tmpdir(), 'x2-1-starts-'));
afterAll(() => rm(PROCESSES, { recursive: true, force: true }));
const RUNNER_FILE = join(PROCESSES, 'start.mjs');
writeFileSync(RUNNER_FILE, START_RUNNER);
const SUBJECT_FILE = join(PROCESSES, 'subject.mjs');
const bundle = buildSync({
  stdin: { contents: "export * as vault from '../src/main/vault';\nexport * as store from '../src/main/github-account-store';\n",
    resolveDir: HERE, sourcefile: 'x2-1-subject.ts', loader: 'ts' },
  bundle: true, platform: 'node', format: 'esm', target: 'node24', write: false, logLevel: 'silent',
  banner: { js: "import { createRequire as x2CreateRequire } from 'node:module'; const require = x2CreateRequire(import.meta.url);" },
});
writeFileSync(SUBJECT_FILE, bundle.outputFiles[0]!.contents);

const START = ['vault', 'references', 'collectorSettings', 'githubStore'];
const IN_SCOPE = ['./github-account-store', './vault'];
/** The names src/main/index.ts imports from the two other modules in scope (named, renamed with `as`, a default or a namespace), each
 *  bound in the start's process to the same export of that start's own load of them (a helper the wiring calls, say): the module and the
 *  export's name (`*` for a namespace), read from the parsed file, so comments and line breaks inside an import do not matter; type-only
 *  imports bind nothing. */
function imported(file: ts.SourceFile): Map<string, [string, string]> {
  const names = new Map<string, [string, string]>();
  for (const statement of file.statements) {
    if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier)) continue;
    const module = statement.moduleSpecifier.text; const clause = statement.importClause;
    if (!IN_SCOPE.includes(module) || !clause || clause.isTypeOnly) continue;
    if (clause.name) names.set(clause.name.text, [module, 'default']);
    const bindings = clause.namedBindings;
    if (bindings && ts.isNamespaceImport(bindings)) names.set(bindings.name.text, [module, '*']);
    if (bindings && ts.isNamedImports(bindings)) {
      for (const element of bindings.elements) if (!element.isTypeOnly) names.set(element.name.text, [module, (element.propertyName ?? element.name).text]);
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
 *  that calls supervisor.attach(), transpiled to a function the start's process runs with the start's vault, store and engine
 *  references, a collector with no token, and what index.ts imports from the modules in scope. No other name of index.ts reaches them. */
function wiring(): { code: string; binds: Array<[string, string]> } {
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
  return { code: code.trim().replace(/;$/, ''), binds: [...extra.values()] };
}

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
  const subject = await load();
  const vault = new subject.Vault(join(data, 'vault'), cryptor); await vault.initialize('epoch-1');
  const hooks: Hooks = {};
  const store = new subject.GitHubAccountStore(file, recorded(vault, hooks), CLIENT, () => T0);
  await store.open();
  let snapshots = 0;
  return {
    vault, store, hooks,
    signIn: () => store.replace(tokens(), T0, 'sign-in', () => true),
    refresh: (from: GitHubAccount) => store.replace(tokens(), T0 + 60_000, 'refresh', live => live?.accessRef === from.accessRef),
    snapshot() { const dir = join(root, `crash-${++snapshots}`); cpSync(data, dir, { recursive: true }); return dir; },
  };
}

/** What a later start left: the account it read, whether it found the file issued to another app, and which refs its vault holds. */
interface Started { store: { current(): GitHubAccount | null; openedAppChanged(): boolean }; vault: { has(ref: string): Promise<boolean> } }
let starts = 0;
/** Where a start's fault fails: at the stat of the account file (and every call after it), at its open, or at the read of what the
 *  open gave. A real one fails at any of them (a directory that may not be searched at the stat; a file held without sharing or a
 *  permission on it at the open; a byte-range lock or a failing disk at the read), with the same code from each. */
type Phase = 'stat' | 'open' | 'read';
const PHASES: Phase[] = ['stat', 'open', 'read'];
/** A later start as the app runs it, in a new process of its own: a new vault and store on `dir`, open(), then index.ts's startup
 *  statements. With `unread`, every read of the account file fails with that code for the whole start, where `at` says (the
 *  stat by default). */
async function start(dir: string, options: { unread?: string; at?: Phase; clientId?: string; engine?: string[] } = {}): Promise<Started> {
  const n = ++starts;
  const shift = Date.now() - vi.getRealSystemTime();
  aged(dir, shift);
  const job = {
    dir, file: join(dir, 'github', 'account.json'), unread: options.unread ?? null, at: options.at ?? 'stat',
    clientId: options.clientId ?? CLIENT, clock: T0 + 3_600_000, engine: options.engine ?? [], shift, key: KEY.toString('hex'),
    wiring: wiring(), result: join(PROCESSES, `start-${n}.result.json`),
  };
  const jobFile = join(PROCESSES, `start-${n}.job.json`);
  writeFileSync(jobFile, JSON.stringify(job));
  const { status, output } = await new Promise<{ status: number | null; output: string }>(resolve => {
    const child = spawn(process.execPath, [RUNNER_FILE, pathToFileURL(SUBJECT_FILE).href, jobFile], { env: NO_ENV, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
    let output = '';
    child.stdout.on('data', (chunk: Buffer) => { output += chunk.toString('utf8'); });
    child.stderr.on('data', (chunk: Buffer) => { output += chunk.toString('utf8'); });
    const timer = setTimeout(() => child.kill(), 90_000);
    child.on('error', error => { clearTimeout(timer); resolve({ status: null, output: output + String(error) }); });
    child.on('close', code => { clearTimeout(timer); resolve({ status: code, output }); });
  });
  const result = existsSync(job.result)
    ? JSON.parse(readFileSync(job.result, 'utf8')) as { error?: string; current: GitHubAccount | null; appChanged: boolean; has: Record<string, boolean> }
    : null;
  if (status !== 0 || !result || result.error !== undefined) throw new Error(`the start's process failed (exit ${status}): ${result?.error ?? ''}\n${output.slice(-4000)}`);
  return { store: { current: () => result.current, openedAppChanged: () => result.appChanged }, vault: { has: async ref => result.has[ref] === true } };
}

/** How far back each data directory's file times have been moved: a start moved by `shift` finds every file and directory in it
 *  (the crash's and an earlier start's) moved back by what the clock moved since, so the real clock reads them as old as the start is
 *  late; only the times a program can set (access and modification) move. */
const agedBy = new Map<string, number>();
function aged(dir: string, shift: number): void {
  const by = shift - (agedBy.get(dir) ?? 0);
  agedBy.set(dir, shift);
  if (by === 0) return;
  const move = (path: string) => {
    const stats = fs.lstatSync(path);
    if (stats.isDirectory()) for (const name of readdirSync(path)) move(join(path, name));
    if (!stats.isSymbolicLink()) fs.utimesSync(path, (stats.atimeMs - by) / 1000, (stats.mtimeMs - by) / 1000);
  };
  move(dir);
}

const fileAt = (dir: string) => join(dir, 'github', 'account.json');
const accountFile = (dir: string) => existsSync(fileAt(dir))
  ? JSON.parse(readFileSync(fileAt(dir), 'utf8')) as { account: { accessRef: string; refreshRef: string | null } | null; retiredRefs: string[] }
  : null;
const entries = (dir: string) => (JSON.parse(readFileSync(join(dir, 'vault', 'index.json'), 'utf8')) as { entries: Record<string, { state: string }> }).entries;
const bins = (dir: string) => readdirSync(join(dir, 'vault')).filter(name => name.endsWith('.bin')).sort();

/** The start reads `expected` as the account, and the file, the vault index and the encrypted files agree with it, nothing else left. */
async function expectAlone(dir: string, next: Started, expected: string[]) {
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
    test(`${kind}, crash before commit ${at}, ${code} at the next three starts (at the stat, the open, then the read): the pair survives all three and is live and committed after the next`, async () => {
      const { dir, pair } = await crashBeforeCommit(kind, at);
      expect(refsOf(accountFile(dir)?.account)).toEqual(pair);                 // the crash came after the file named the pair
      expect(pair.map(ref => entries(dir)[ref]?.state)).toEqual(states);
      const before = readFileSync(fileAt(dir), 'utf8');

      for (const [index, phase] of PHASES.entries()) {                         // ten years after the crash, then ten more, twice
        vi.useRealTimers(); later(3650 * (index + 1));
        const unread = await start(dir, { unread: code, at: phase });
        expect(unread.store.current(), phase).toBeNull();                      // that start reads no account
        expect(readFileSync(fileAt(dir), 'utf8'), phase).toBe(before);         // and leaves the file as it was
        expect(pair.map(ref => entries(dir)[ref]?.state), phase).toEqual(states); // the pair is still in the vault, in the crash's states,
        for (const ref of pair) expect(bins(dir), phase).toContain(`${ref}.bin`); // with its encrypted files
      }

      await expectAlone(dir, await start(dir), pair);                          // the next start reads the file and commits the pair
      await expectAlone(dir, await start(dir), pair);                          // and a further start finds the same
    });
  }

  // Only a missing file (ENOENT) reads as no account: every other errno code makes a start that cannot read the file. The rows above
  // use EACCES, EBUSY and EIO, so a keep keyed on a list of codes taken for passing ones that holds those three would pass them all. This
  // row's next start fails with codes such a list is unlikely to hold: EPERM, EMFILE (too many open files), EINVAL and UNKNOWN (libuv's
  // code for an error it does not map, as a Windows error can be), each at the four crash points, at the stat, the open and the read.
  test('first sign-in before commit 1, sign-in or refresh before commit 3 and refresh before commit 4, then EPERM, EMFILE, EINVAL or UNKNOWN at the next three starts (at the stat, the open, then the read): the pair survives all three and is live and committed after the next', async () => {
    for (const [kind, at, states] of crashes) for (const code of ['EPERM', 'EMFILE', 'EINVAL', 'UNKNOWN']) {
      const step = `${kind}, crash before commit ${at}, ${code}`;
      vi.useRealTimers();
      const { dir, pair } = await crashBeforeCommit(kind, at);
      expect(pair.map(ref => entries(dir)[ref]?.state), step).toEqual(states);
      const before = readFileSync(fileAt(dir), 'utf8');

      for (const [index, phase] of PHASES.entries()) {                         // ten, twenty and thirty years after the crash, as above
        const at = `${step} at the ${phase}`;
        vi.useRealTimers(); later(3650 * (index + 1));
        const unread = await start(dir, { unread: code, at: phase });
        expect(unread.store.current(), at).toBeNull();
        expect(readFileSync(fileAt(dir), 'utf8'), at).toBe(before);
        expect(pair.map(ref => entries(dir)[ref]?.state), at).toEqual(states);
        for (const ref of pair) expect(bins(dir), at).toContain(`${ref}.bin`);
      }

      await expectAlone(dir, await start(dir), pair);                          // the next start reads the file and commits the pair
    }
  });

  // A file that stays unreadable (a bad permission, a lock held for days) gives several such starts in a row, and the promise does not
  // depend on how many: so no limit on the number of unreadable starts a kept pair survives can pass for four of them, and the
  // same code twice in a row (a lasting permission error) is no sign the pair was abandoned.
  test('first sign-in before commit 1 and refresh before commit 4, then EACCES, EACCES again, EBUSY and EIO at four starts in a row, ten years apart, at the stat, the open and the read in turn: the pair survives all four and is live and committed after the next', async () => {
    const forms: Array<[Kind, number, string[]]> = [['first sign-in', 1, ['staged', 'staged']], ['refresh', 4, ['committed', 'staged']]];
    for (const [kind, at, states] of forms) {
      vi.useRealTimers();
      const { dir, pair } = await crashBeforeCommit(kind, at);
      expect(pair.map(ref => entries(dir)[ref]?.state), kind).toEqual(states);
      const before = readFileSync(fileAt(dir), 'utf8');

      for (const [index, code] of ['EACCES', 'EACCES', 'EBUSY', 'EIO'].entries()) {
        const step = `${kind}, start ${index + 1} (${code} at the ${PHASES[index % 3]})`;
        vi.useRealTimers(); later(3650 * (index + 1));                        // each start ten years after the one before it
        const unread = await start(dir, { unread: code, at: PHASES[index % 3] });
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
      await start(dir!, { unread: code, at: PHASES[index % 3] });
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

  test('a first sign-in that crashed before commit 1, a sign-in or a refresh before commit 3 and a refresh before commit 4, then the file naming the new pair is refused (invalid JSON, over 64 KiB, an extra key, version 2): the start deletes the staged entries and rewrites the file (a refused file names no reference, beside a committed account too)', async () => {
    // Spec 4.4 again, for a file that still names an account (a newer app's file, say): what a refused file names is not read,
    // so it names no reference whatever it holds, and the start deletes the staged entries it names as it deletes any unreferenced
    // one. After a sign-in the old account's pair is committed beside the new one (a downgrade finds a signed-in vault), so a keep
    // that holds while the vault has a committed entry beside a refused file fails here too.
    const crashes: Array<[Kind, number, string[]]> = [
      ['first sign-in', 1, ['staged', 'staged']],
      ['sign-in', 3, ['staged', 'staged']],
      ['refresh', 3, ['staged', 'staged']],
      ['refresh', 4, ['committed', 'staged']],
    ];
    for (const [kind, at, states] of crashes) {
      const { dir: crash, pair, old } = await crashBeforeCommit(kind, at);
      const valid = readFileSync(fileAt(crash), 'utf8');                       // the file the replace wrote, naming the new pair
      const named = JSON.parse(valid) as Record<string, unknown>;
      expect(refsOf(accountFile(crash)?.account), kind).toEqual(pair);
      expect(pair.map(ref => entries(crash)[ref]?.state), kind).toEqual(states);
      expect(old.map(ref => entries(crash)[ref]?.state), kind).toEqual(old.map(() => 'committed'));
      const committed = Object.keys(entries(crash)).filter(ref => entries(crash)[ref]?.state === 'committed');

      const refused: Array<[string, string]> = [
        ['invalid JSON', valid.slice(0, valid.lastIndexOf('}'))],
        ['over 64 KiB', valid + ' '.repeat(64 * 1024)],
        ['an extra key', JSON.stringify({ ...named, extra: true })],
        ['version 2', JSON.stringify({ ...named, version: 2 })],
      ];
      for (const [index, [name, text]] of refused.entries()) {
        const step = `${kind} before commit ${at}, ${name}`;
        const dir = `${crash}-refused-${index + 1}`;
        cpSync(crash, dir, { recursive: true });
        writeFileSync(fileAt(dir), text);
        const next = await start(dir);
        expect(next.store.current(), step).toBeNull();
        // every staged entry goes, files and all; only entries committed at the crash may stay
        expect(Object.keys(entries(dir)).filter(ref => !committed.includes(ref)), step).toEqual([]);
        expect(bins(dir).filter(bin => !committed.some(ref => bin === `${ref}.bin`)), step).toEqual([]);
        expect(readFileSync(fileAt(dir), 'utf8'), step).not.toBe(text);       // rewritten
        expect(Object.keys(accountFile(dir) ?? {}).sort(), step).toEqual(Object.keys(named).sort());
        expect(accountFile(dir)?.account, step).toBeNull();
      }
    }
  });

  test('a first sign-in that crashed after staging, before any file existed, and a sign-in that crashed after staging or a refresh before commit 3 beside a committed account, its file then lost: a start deletes the staged entries (a missing file is no account)', async () => {
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

    // A missing file beside a committed account: the file is gone, not unreadable, so it names no reference and the start deletes
    // the staged entries all the same; only entries committed at the crash may stay.
    const signedIn = await firstSession();
    await signedIn.signIn();
    let orphan: string | undefined;
    signedIn.hooks.afterStaged = count => { if (count === 4) orphan = signedIn.snapshot(); };
    await signedIn.signIn();
    expect(orphan).toBeDefined();
    const lost: Array<[string, string]> = [['a sign-in after staging', orphan!], ['a refresh before commit 3', (await crashBeforeCommit('refresh', 3)).dir]];
    for (const [name, crash] of lost) {
      const committed = Object.keys(entries(crash)).filter(ref => entries(crash)[ref]?.state === 'committed');
      expect(committed, name).toHaveLength(2);
      expect(Object.values(entries(crash)).filter(entry => entry.state === 'staged'), name).toHaveLength(2);
      fs.rmSync(fileAt(crash));
      const after = await start(crash);
      expect(after.store.current(), name).toBeNull();
      expect(Object.keys(entries(crash)).filter(ref => !committed.includes(ref)), name).toEqual([]);
      expect(bins(crash).filter(bin => !committed.some(ref => bin === `${ref}.bin`)), name).toEqual([]);
    }
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
