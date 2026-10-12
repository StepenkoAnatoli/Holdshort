#!/usr/bin/env python3
"""Credential-store hygiene — orphaned gh keyring tokens and stale stored credentials.

Why this exists: credentials outlive the tool that stored them. A gh session can be
removed (or never persisted) while its tokens stay in the OS credential store; a git
credential-helper chain can be re-pointed — `gh auth setup-git` writes a URL-scoped
`credential.https://github.com.helper =` reset that clears every inherited helper —
while the previous store's entry stays behind. Nothing reports either: git silently
never reads the entry again, and `gh auth status` says "not logged in" without
mentioning the tokens gh still holds. This check rides the pre-commit gate
(tools/run_regression.py), so the next commit is refused while an untriaged entry
exists.

Classes (each a real observed state on this machine, 2026-10-12):
  * orphaned-gh-keyring-token — a stored `gh:<host>[:<user>]` target whose <host> has
    no entry in gh's hosts.yml (or there is no hosts.yml at all): a LIVE credential that
    no session manages. `gh auth status` cannot see it, so nothing reports or rotates it,
    while gh's own git-credential helper still serves it to git (verified on this machine
    2026-10-12: with no hosts.yml, `gh auth git-credential get` returns a full credential,
    which is how this clone's fetches authenticate). `gh` stores the active token in an
    empty-username slot (`gh:<host>:`) beside the per-user entry, so BOTH are orphans when
    the host is absent, and expected when it is present.
  * stale-gh-keyring-token — a `gh:<host>:<user>` target for a user gh no longer lists
    for that host (token for an account that is not configured anywhere).
  * stale-git-credential — a stored `git:<url>` target whose effective credential-helper
    chain for <url> contains no OS-store helper (`manager`, i.e. Git Credential
    Manager, which owns `git:` targets): git will never read that entry again. The
    helper chain is computed from `git config --list --show-origin` in file order with
    gitcredentials(7) reset semantics (an empty `helper` value clears the accumulated
    list) — the same rule `gh auth setup-git` relies on.
  * stale-hosts-entry — a hosts.yml host with no stored `gh:` token and no inline
    token: gh believes it is logged in and holds nothing to authenticate with.
  * stale-plaintext-credential — a `~/.git-credentials` line whose host's chain does not
    include the `store` helper (git will never read it), plus an informational line when
    such a file IS in use (plaintext at rest, by the operator's own choice).

Surfaces and resolution (each overridable for tests, matching the app_db precedent):
  * OS store: `cmdkey /list` on Windows. On other platforms the surface does not exist
    (POSIX has no Windows Credential Manager) and is reported as N/A — CI runners must
    not fail on that; a `store_available=False` machine also skips token-presence
    judgements rather than guessing.
  * gh config dir, single resolution exactly as gh does it: GH_CONFIG_DIR, else
    %APPDATA%/GitHub CLI, else $XDG_CONFIG_HOME/gh, else <home>/.config/gh.
  * git's plaintext store: <home>/.git-credentials.
  * user home for git config: USERPROFILE wins over HOME, because the pre-commit hook
    exports HOME=<repo root> and a machine config read through that HOME would silently
    miss the user's real credential config.

Output discipline: target names, hosts, usernames and helper names only — never a
secret. hosts.yml `oauth_token` is inspected only as "present or placeholder", the
password part of a .git-credentials URL is never retained, and no credential helper is
ever executed (the chain comes from config; `git credential fill` is not run, so this
check cannot prompt for or emit a credential).

Exit codes (stop-the-line, matching check_secrets.py / check_app_db_secrets.py):
  0  clean, or every finding is already in the baseline (triaged)
  1  NEW finding(s) — refuse the commit; clean the store, or record the subject in the
     baseline after triage: `--update-baseline --note "<why this one is known>"`
  2  fail-closed — a surface could not be read or parsed, or the baseline is malformed;
     an unreadable hosts.yml could be hiding an orphan, so it is never "clean"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parent
BASELINE_DEFAULT = TOOLS / "credential_hygiene_baseline.json"
GH_CONFIG_ENV = "GH_CONFIG_DIR"
CREDENTIALS_FILE_NAME = ".git-credentials"

# Helpers that read from a store this check can see. Matching is by the family name a
# helper is written as (`manager`, a path to git-credential-manager, `!`-commands, ...).
MANAGER_MARKERS = ("credential-manager", "git-credential-manager", "manager")
STORE_MARKERS = ("credential-store", "store")

TARGET_RE = re.compile(r"^\s*Target:\s*(?:LegacyGeneric:target=)?(.+?)\s*$")
USER_RE = re.compile(r"^\s*User:\s*(.*?)\s*$")
HOST_KEY_RE = re.compile(r"^([^\s:#][^:]*):\s*$")
OAUTH_TOKEN_RE = re.compile(r"^\s*oauth_token:\s*(.*?)\s*$")
# gh writes `oauth_token: !!!` when the token lives in the keyring instead of the file.
TOKEN_PLACEHOLDERS = {"!!!", "", "''", '""'}


class FailClosed(Exception):
    """A surface could not be read or parsed — never report this as clean."""


# ---------------------------------------------------------------- decoding

def decode(raw: bytes) -> str:
    """Decode command/file bytes: utf-8 (no NULs), else utf-16 by BOM/parity, else latin-1."""
    if b"\x00" not in raw[:4096]:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    even = sum(1 for i in range(0, len(raw) - 1, 2) if raw[i] == 0)
    odd = sum(1 for i in range(1, len(raw), 2) if raw[i] == 0)
    if even or odd:
        for enc in (("utf-16-be" if even > odd else "utf-16-le"), "utf-16-le", "utf-16-be"):
            try:
                text = raw.decode(enc)
            except UnicodeDecodeError:
                continue
            if "\x00" not in text:
                return text
    return raw.decode("latin-1")


# ---------------------------------------------------------------- OS store

@dataclass(frozen=True)
class StoreEntry:
    target: str
    user: str = ""


def parse_store_listing(text: str) -> list[StoreEntry]:
    """Target/User pairs from `cmdkey /list` output (names only, never values)."""
    entries: list[StoreEntry] = []
    current: StoreEntry | None = None
    for line in text.splitlines():
        m = TARGET_RE.match(line)
        if m:
            if current:
                entries.append(current)
            current = StoreEntry(target=m.group(1), user="")
            continue
        if current:
            u = USER_RE.match(line)
            if u:
                current = StoreEntry(target=current.target, user=u.group(1))
    if current:
        entries.append(current)
    return entries


def store_listing(override: Path | None, platform: str | None = None) -> tuple[list[StoreEntry], str]:
    """(entries, surface description). POSIX has no such store: N/A, not fail-closed."""
    if override is not None:
        if not override.is_file():
            raise FailClosed(f"--store-listing {override} is not a readable file")
        return parse_store_listing(decode(override.read_bytes())), f"listing file {override}"
    if (platform or os.name) != "nt":
        return [], "N/A on this platform (no Windows Credential Manager)"
    try:
        proc = subprocess.run(["cmdkey", "/list"], capture_output=True, timeout=60)
    except OSError as e:
        raise FailClosed(f"cmdkey /list could not run ({e})") from e
    if proc.returncode != 0:
        raise FailClosed(f"cmdkey /list failed (exit {proc.returncode}) — the OS store listing "
                         "is unavailable, so orphaned tokens cannot be ruled out")
    return parse_store_listing(decode(proc.stdout)), "cmdkey /list"


# ---------------------------------------------------------------- gh config

@dataclass
class HostInfo:
    host: str
    users: set[str] = field(default_factory=set)
    inline_token: bool = False      # a real oauth_token value sits in hosts.yml


def resolve_gh_config_dir(override: Path | None) -> Path | None:
    """gh's own single-resolution order (GH_CONFIG_DIR, %APPDATA%, XDG, ~/.config)."""
    if override is not None:
        return override
    env = os.environ
    if env.get(GH_CONFIG_ENV):
        return Path(env[GH_CONFIG_ENV])
    if env.get("APPDATA"):
        return Path(env["APPDATA"]) / "GitHub CLI"
    if env.get("XDG_CONFIG_HOME"):
        return Path(env["XDG_CONFIG_HOME"]) / "gh"
    for var in ("USERPROFILE", "HOME"):
        if env.get(var):
            return Path(env[var]) / ".config" / "gh"
    return None


def parse_hosts(text: str) -> dict[str, HostInfo]:
    """Hosts and usernames from gh's hosts.yml. Token values are never retained.

    Tolerates gh's `users:` map (nested per-account blocks) by indent tracking, so an
    account named there counts as configured for its host.
    """
    hosts: dict[str, HostInfo] = {}
    current: HostInfo | None = None
    users_indent: int | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if indent == 0:
            m = HOST_KEY_RE.match(line)
            if not m:
                raise FailClosed(f"unrecognized hosts.yml structure at indent 0: {line[:40]!r} "
                                 "— refusing to guess whether a host is configured")
            current = hosts.setdefault(m.group(1), HostInfo(host=m.group(1)))
            users_indent = None
            continue
        if current is None:
            raise FailClosed("hosts.yml has indented content before any host key — malformed")
        if users_indent is not None and indent > users_indent and line.endswith(":"):
            current.users.add(line[:-1].strip())      # an account named under `users:`
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key == "users":
            users_indent = indent
        elif key == "user" and value:
            current.users.add(value)
            users_indent = None
        elif key == "oauth_token":
            users_indent = None
            if value not in TOKEN_PLACEHOLDERS:
                current.inline_token = True   # value itself is never kept or printed
        else:
            users_indent = None
    return hosts


def read_hosts(config_dir: Path | None) -> tuple[dict[str, HostInfo] | None, str]:
    """(hosts or None when no session file exists, description)."""
    if config_dir is None:
        return None, "no gh config dir resolvable"
    hosts_file = config_dir / "hosts.yml"
    if not hosts_file.is_file():
        return None, f"no hosts.yml at {config_dir} (no persisted gh session)"
    try:
        text = decode(hosts_file.read_bytes())
    except OSError as e:
        raise FailClosed(f"{hosts_file} is unreadable ({e})") from e
    return parse_hosts(text), f"{hosts_file}"


# ---------------------------------------------------------------- git config

@dataclass(frozen=True)
class ConfigEntry:
    origin: str
    key: str
    value: str


def user_home(env: dict | None = None) -> Path | None:
    """The real user home: USERPROFILE wins over HOME (the hook exports HOME=<repo>)."""
    env = env if env is not None else os.environ
    for var in ("USERPROFILE", "HOME"):
        if env.get(var):
            return Path(env[var])
    try:
        return Path.home()
    except (RuntimeError, ValueError):
        return None


def git_env() -> dict:
    """os.environ with HOME pinned to the real user home, so a hook-exported HOME
    cannot hide the user's credential config from the chain computation."""
    env = dict(os.environ)
    home = user_home(env)
    if home is not None:
        env["HOME"] = str(home)
    return env


def config_entries(env: dict) -> list[ConfigEntry]:
    """All git config entries in file order (`--show-origin`), for chain computation."""
    try:
        proc = subprocess.run(["git", "config", "--list", "--show-origin"], env=env,
                              capture_output=True, timeout=60)
    except OSError as e:
        raise FailClosed(f"git config could not run ({e})") from e
    if proc.returncode != 0:
        raise FailClosed(f"git config --list failed (exit {proc.returncode}): "
                         f"{decode(proc.stderr)[:200]}")
    out: list[ConfigEntry] = []
    for line in decode(proc.stdout).splitlines():
        if "\t" not in line or "=" not in line:
            continue
        origin, rest = line.split("\t", 1)
        key, value = rest.split("=", 1)
        out.append(ConfigEntry(origin.strip(), key.strip(), value))
    return out


def _normalize_url(url: str) -> str:
    return url.strip().rstrip("/").lower()


def _subsection_matches(subsection: str, url: str) -> bool:
    sub, u = _normalize_url(subsection), _normalize_url(url)
    return bool(sub) and (u == sub or u.startswith(sub + "/"))


def helper_chain(url: str, entries: list[ConfigEntry]) -> list[str]:
    """Effective credential helper list for `url` (gitcredentials(7) reset semantics:
    an empty value clears the accumulated list; entries apply in config file order)."""
    subs = [e.key[len("credential."):-len(".helper")]
            for e in entries
            if e.key.startswith("credential.") and e.key.endswith(".helper")
            and e.key != "credential.helper"]
    best = ""
    for sub in subs:
        if _subsection_matches(sub, url) and len(sub) > len(best):
            best = sub
    chain: list[str] = []
    for e in entries:
        if e.key == "credential.helper":
            value = e.value
        elif e.key == f"credential.{best}.helper" and best:
            value = e.value
        else:
            continue
        if value.strip():
            chain.append(value.strip())
        else:
            chain = []          # the documented reset
    return chain


def helper_kind(helper: str) -> str:
    low = helper.lower().lstrip("!").strip().strip("'\"")
    if any(m in low for m in MANAGER_MARKERS):
        return "manager"
    if any(m in low for m in STORE_MARKERS):
        return "store"
    if "gh" in low and "auth" in low:
        return "gh"
    if low.startswith("!"):
        return "custom"
    return low or "empty"


# ---------------------------------------------------------------- .git-credentials

@dataclass(frozen=True)
class CredentialFileEntry:
    line: int
    host: str
    user: str


@dataclass(frozen=True)
class MalformedCredentialLine:
    line: int
    reason: str


def parse_credentials_file(text: str) -> tuple[list[CredentialFileEntry], list[MalformedCredentialLine]]:
    """Parse git's store-file format. Only host and username are returned: the
    password part of the URL is never retained."""
    good: list[CredentialFileEntry] = []
    bad: list[MalformedCredentialLine] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "://" not in line or "@" not in line.split("://", 1)[1].split("/", 1)[0]:
            bad.append(MalformedCredentialLine(n, "not a scheme://user@host URL"))
            continue
        scheme, _, rest = line.partition("://")
        userinfo, _, hostpart = rest.partition("@")
        host = hostpart.split("/", 1)[0].split(":", 1)[0]
        if not host or not scheme:
            bad.append(MalformedCredentialLine(n, "missing scheme or host"))
            continue
        user = userinfo.split(":", 1)[0]
        good.append(CredentialFileEntry(n, host, user))
    return good, bad


# ---------------------------------------------------------------- findings

@dataclass
class Finding:
    cls: str
    subject: str        # stable baseline key: a store target, or file:<host>/hosts:<host>
    reason: str
    fix: str

    def render(self) -> list[str]:
        return [f"  - {self.cls}: {self.subject}", f"      {self.reason}", f"      fix: {self.fix}"]


def hygiene_findings(entries: list[StoreEntry], store_available: bool,
                     hosts: dict[str, HostInfo] | None,
                     cred_entries: list[CredentialFileEntry],
                     malformed: list[MalformedCredentialLine],
                     config: list[ConfigEntry]) -> tuple[list[Finding], list[str], list[str]]:
    """(findings, informational lines, other (unjudged) store targets)."""
    findings: list[Finding] = []
    info: list[str] = []
    other: list[str] = []
    hosts = hosts or {}

    def chain_for(url: str) -> list[str]:
        return helper_chain(url, config)

    for e in entries:
        target = e.target
        if target.startswith("gh:"):
            rest = target[len("gh:"):]
            host, _, user = rest.partition(":")
            user = user.strip()
            if host not in hosts:
                where = ("no hosts.yml at all (no persisted gh session)" if hosts == {}
                         else f"gh's hosts.yml has no entry for {host}")
                findings.append(Finding(
                    "orphaned-gh-keyring-token", target,
                    f"{where}: a live credential no gh session manages — `gh auth status` "
                    "cannot see it, yet gh's git-credential helper still serves it to git",
                    f'adopt it (`gh auth login`) or delete it (`cmdkey /delete:"{target}"`)'))
            elif user and hosts[host].users and user not in hosts[host].users:
                findings.append(Finding(
                    "stale-gh-keyring-token", target,
                    f"token for account '{user}', which hosts.yml does not list for {host} "
                    f"(configured: {', '.join(sorted(hosts[host].users)) or 'none'})",
                    f'cmdkey /delete:"{target}"  (or `gh auth logout --hostname {host}`)'))
        elif target.startswith("git:"):
            url = target[len("git:"):]
            chain = chain_for(url)
            kinds = [helper_kind(h) for h in chain]
            if "manager" not in kinds:
                shown = ", ".join(chain) if chain else "(none)"
                findings.append(Finding(
                    "stale-git-credential", target,
                    f"no OS-store helper reads this entry for {url} — effective chain: "
                    f"{shown}",
                    f'cmdkey /delete:"{target}"  (restore Git Credential Manager for '
                    "this URL only if the entry should be live)"))
        else:
            other.append(target)

    if store_available and hosts:
        targets = [e.target for e in entries]
        for host, hinfo in sorted(hosts.items()):
            has_token = any(t.startswith(f"gh:{host}:") or t == f"gh:{host}" for t in targets)
            if not has_token and not hinfo.inline_token:
                findings.append(Finding(
                    "stale-hosts-entry", f"hosts.yml:{host}",
                    f"hosts.yml lists {host} but the OS store holds no gh token for it and "
                    "hosts.yml has no inline token — gh believes it is logged in and has "
                    "nothing to authenticate with",
                    f"`gh auth login --hostname {host}`  (or `gh auth logout --hostname {host}`)"))
            elif hinfo.inline_token:
                info.append(f"hosts.yml lists {host} with an inline oauth_token (plaintext "
                            "at rest by the operator's choice) — the OS store would be safer")

    for entry in cred_entries:
        chain = chain_for(f"https://{entry.host}")
        if "store" not in [helper_kind(h) for h in chain]:
            findings.append(Finding(
                "stale-plaintext-credential", f"store-file:{entry.host}",
                f"{CREDENTIALS_FILE_NAME} line {entry.line} holds a credential for "
                f"{entry.host}, whose helper chain does not include the `store` helper — "
                "git will never read it",
                f"remove that line (or configure credential.helper=store if it is intended)"))
        else:
            info.append(f"{CREDENTIALS_FILE_NAME} is in use for {entry.host} "
                        "(plaintext at rest, by the operator's own helper choice)")
    for bad in malformed:
        findings.append(Finding(
            "stale-plaintext-credential", f"store-file:line-{bad.line}",
            f"{CREDENTIALS_FILE_NAME} line {bad.line} is not a usable entry ({bad.reason})",
            "fix or remove that line"))

    return findings, info, other


# ---------------------------------------------------------------- baseline

def load_baseline(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        entries = doc.get("entries", {})
        if not isinstance(entries, dict):
            raise ValueError("'entries' must be an object")
        return {str(k): str(v) for k, v in entries.items()}
    except Exception as e:
        raise FailClosed(f"baseline {path} is unreadable/malformed: {e}") from e


def save_baseline(path: Path, entries: dict[str, str], note: str) -> None:
    doc = {
        "note": ("Known, triaged credential-store entries (orphaned gh keyring tokens, stale "
                 "git credentials). Keyed by store target / finding subject — never a secret "
                 "value. Remove an entry once the store entry is deleted (or adopted); add "
                 "new ones only after triage: --update-baseline --note \"...\""),
        "entries": {k: entries[k] for k in sorted(entries)},
    }
    if note:
        doc["last_update_note"] = note
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- run

def parse_args(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(
        description="Credential-store hygiene: orphaned gh keyring tokens, stale stored "
                    "credentials. Read-only; no helper is ever executed and no secret is "
                    "ever printed.")
    ap.add_argument("--store-listing", type=Path, default=None,
                    help="file holding `cmdkey /list` output (tests/other machines); "
                         "default: run cmdkey on Windows, N/A elsewhere")
    ap.add_argument("--gh-config-dir", type=Path, default=None,
                    help=f"gh config dir (overrides {GH_CONFIG_ENV} and the default order)")
    ap.add_argument("--credentials-file", type=Path, default=None,
                    help=f"git store file to inspect (default: <home>/{CREDENTIALS_FILE_NAME})")
    ap.add_argument("--baseline", type=Path, default=BASELINE_DEFAULT,
                    help=f"baseline allowlist (default: {BASELINE_DEFAULT.name})")
    ap.add_argument("--update-baseline", action="store_true",
                    help="record the subjects of all current findings, then exit 0 "
                         "(use after triage)")
    ap.add_argument("--note", default="", help="note to store alongside an --update-baseline run")
    return ap.parse_args(argv)


def inspect(store_path: Path | None = None, gh_config_override: Path | None = None,
            credentials_file: Path | None = None, platform: str | None = None,
            config: list[ConfigEntry] | None = None):
    """Gather every surface once, for the CLI and for tests.
    Returns (entries, store_desc, store_available, hosts, hosts_desc, creds, malformed, config)."""
    entries, store_desc = store_listing(store_path, platform)
    store_available = (store_path is not None) or (platform or os.name) == "nt"
    config_dir = resolve_gh_config_dir(gh_config_override)
    hosts, hosts_desc = read_hosts(config_dir)
    home = user_home()
    creds_path = credentials_file if credentials_file is not None else (
        home / CREDENTIALS_FILE_NAME if home else None)
    creds: list[CredentialFileEntry] = []
    malformed: list[MalformedCredentialLine] = []
    if creds_path is not None and creds_path.is_file():
        try:
            creds, malformed = parse_credentials_file(decode(creds_path.read_bytes()))
        except OSError as e:
            raise FailClosed(f"{creds_path} is unreadable ({e})") from e
    if config is None:
        config = config_entries(git_env())
    return entries, store_desc, store_available, hosts, hosts_desc, creds, malformed, config


def run(args) -> int:
    try:
        (entries, store_desc, store_available, hosts, hosts_desc,
         creds, malformed, config) = inspect(
            store_path=args.store_listing, gh_config_override=args.gh_config_dir,
            credentials_file=args.credentials_file)
        baseline = load_baseline(args.baseline)
        findings, info, other = hygiene_findings(
            entries, store_available, hosts, creds, malformed, config)
        new = [f for f in findings if f.subject not in baseline]
        known = [f for f in findings if f.subject in baseline]
        if args.update_baseline:
            added = 0
            for f in new:
                if f.subject not in baseline:
                    baseline[f.subject] = (f"class={f.cls}; {args.note}" if args.note
                                           else f"class={f.cls}")
                    added += 1
            save_baseline(args.baseline, baseline, args.note)
            print(f"credential_hygiene: baseline updated — {added} entry(ies) recorded in "
                  f"{args.baseline}")
            return 0
        if new:
            print(f"credential_hygiene: {len(new)} NEW finding(s) — DO NOT COMMIT until "
                  f"triaged (store: {store_desc}; gh config: {hosts_desc}):")
            for f in new:
                for line in f.render():
                    print(line)
            print("  triage: delete/adopt the entry; if it is known and acceptable, run")
            print("          python tools/check_credential_hygiene.py --update-baseline "
                  "--note \"...\"")
            return 1
        summary = (f"credential_hygiene: clean (0 new findings; {len(known)} baselined; "
                   f"store: {store_desc}; gh config: {hosts_desc})")
        print(summary)
        for line in info:
            print(f"  info: {line}")
        if other:
            shown = ", ".join(other[:3]) + (" ..." if len(other) > 3 else "")
            print(f"  info: {len(other)} other store entr(ies) not judged (not git:/gh: "
                  f"targets): {shown}")
        return 0
    except FailClosed as e:
        print(f"credential_hygiene: FAIL-CLOSED — {e}", file=sys.stderr)
        return 2


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    sys.exit(main())
