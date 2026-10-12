#!/usr/bin/env python3
"""App-DB secrets scan — flag credential-shaped strings that land in the
Freebuff Desktop app's transcript database.

Why this exists (the hole it closes): the app persists thread transcripts in
sqlite stores under `~/.config/freebuff-desktop/projects/*/desktop-v2.db*`.
A token echoed into a chat/transcript is written there and is NOT a repo file,
so tools/check_secrets.py — whose corpus is exactly `git ls-files` — can never
see it. This check rides the same pre-commit gate (tools/run_regression.py),
so the next commit is refused while an untriaged token-shaped string sits in
those stores.

Exit codes (stop-the-line, matching check_secrets.py):
  0  clean, or every hit is already in the baseline (triaged)
  1  NEW token-shaped hit(s) — refuse the commit; remove the leak source, or
     record the digest in the baseline after triage:
     `--update-baseline --note "<why this one is known/acceptable>"`
  2  fail-closed — the scan corpus is incomplete: a store is unreadable or
     oversized, or the baseline file is unreadable/malformed

Path resolution — ordering matters: the pre-commit hook exports
`HOME="$REPO_ROOT"` (`.githooks/pre-commit`), so HOME alone would resolve to
the repo checkout and silently SKIP on every real hook run. Order:
  1. FREEBUFF_APP_DB_DIR       explicit override (tests / other machines);
                               if set, it must exist or the run fails closed
  2. USERPROFILE, then HOME    -> <root>/.config/freebuff-desktop
  3. Path.home()               -> same suffix
A machine with no app directory (CI runners, fresh clones) exits 0 with SKIP.

Matching: stores are binary; each file is decoded latin-1 (1 char == 1 byte,
lossless) so the audited str patterns from tools/check_secrets.py can be
reused and every reported offset is a true byte offset.

Output discipline: only class, byte offset and a sha256 DIGEST of a hit are
printed — never the value — so triaging a leak cannot echo the secret into yet
another transcript.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import check_secrets as cs  # noqa: E402  (reuse the audited pattern definitions)

APP_DIR_ENV = "FREEBUFF_APP_DB_DIR"
STORE_GLOB = "desktop-v2.*"
BASELINE_DEFAULT = TOOLS / "app_db_secrets_baseline.json"
MAX_BYTES = 512 * 1024 * 1024  # a store bigger than this is fail-closed, not skipped

# GitHub credential families — the classes that genuinely leak through git/gh
# workflows. `check_secrets.py`'s noisy generic matchers (key-assignment,
# bearer-token) are deliberately NOT reused here: on opaque transcript blobs
# they produce triage noise, and this check must stay fail-closed but precise.
GITHUB_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("github-pat-fine-grained", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("github-pat-classic", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("github-oauth", re.compile(r"gho_[A-Za-z0-9]{36}")),
    ("github-user-to-server", re.compile(r"ghu_[A-Za-z0-9]{36}")),
    ("github-server-to-server", re.compile(r"ghs_[A-Za-z0-9]{36}")),
    ("github-refresh", re.compile(r"ghr_[A-Za-z0-9]{36}")),
]
REUSED_FROM_CHECK_SECRETS = ("anthropic-key", "openai-style-key", "generic-sk-key")
PATTERNS: list[tuple[str, re.Pattern[str]]] = GITHUB_PATTERNS + [
    p for p in cs.PATTERNS if p[0] in REUSED_FROM_CHECK_SECRETS
]


class FailClosed(Exception):
    """The scan corpus is incomplete — never report this as clean."""


def candidate_app_dirs() -> list[Path]:
    """App-root candidates in resolution order (deduplicated)."""
    cands: list[Path] = []
    override = os.environ.get(APP_DIR_ENV)
    if override:
        cands.append(Path(override))
    for var in ("USERPROFILE", "HOME"):
        root = os.environ.get(var)
        if root:
            cands.append(Path(root) / ".config" / "freebuff-desktop")
    try:
        cands.append(Path.home() / ".config" / "freebuff-desktop")
    except (RuntimeError, ValueError):
        pass
    seen: set[str] = set()
    out: list[Path] = []
    for c in cands:
        key = str(c).lower() if os.name == "nt" else str(c)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def resolve_app_dir() -> Path | None:
    """First existing candidate; None when the machine has no app store."""
    cands = candidate_app_dirs()
    if os.environ.get(APP_DIR_ENV):
        override = cands[0]
        if not override.is_dir():
            raise FailClosed(f"{APP_DIR_ENV}={override} is set but is not a directory")
        return override
    for c in cands:
        if c.is_dir():
            return c
    return None


def store_files(app_dir: Path) -> list[Path]:
    """Every desktop-v2.* store under the app root (sorted, deterministic)."""
    return sorted(app_dir.rglob(STORE_GLOB))


def scan_store(path: Path) -> list[tuple[str, int, str]]:
    """(class, byte-offset, sha256-of-match) for one store. Value never returned."""
    try:
        size = path.stat().st_size
    except OSError as e:
        raise FailClosed(f"{path} cannot be stat'ed ({e})") from e
    if size > MAX_BYTES:
        raise FailClosed(f"{path} is {size} bytes (> {MAX_BYTES}) — refusing to skip it silently")
    try:
        data = path.read_bytes()
    except OSError as e:
        raise FailClosed(f"{path} is unreadable ({e}) — close the app and retry") from e
    text = data.decode("latin-1")  # lossless bytes<->chars: offsets are byte offsets
    hits: list[tuple[str, int, str]] = []
    for name, pat in PATTERNS:
        for m in pat.finditer(text):
            digest = hashlib.sha256(m.group(0).encode("latin-1")).hexdigest()
            hits.append((name, m.start(), digest))
    return hits


def load_baseline(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        digests = doc.get("digests", {})
        if not isinstance(digests, dict):
            raise ValueError("'digests' must be an object")
        return {str(k).lower(): str(v) for k, v in digests.items()}
    except Exception as e:  # malformed baseline must fail closed, not disable checks
        raise FailClosed(f"baseline {path} is unreadable/malformed: {e}") from e


def save_baseline(path: Path, digests: dict[str, str], note: str) -> None:
    doc = {
        "note": ("Known, triaged token-shaped strings already present in the Freebuff app "
                 "DB stores. Keyed by sha256 of the matched string, never the string itself. "
                 "Remove entries once the underlying secret is revoked and the store cleaned. "
                 "Add new ones only after triage: --update-baseline --note \"...\""),
        "digests": {k: digests[k] for k in sorted(digests)},
    }
    if note:
        doc["last_update_note"] = note
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(
        description="Scan the Freebuff Desktop app stores for credential-shaped strings.")
    ap.add_argument("--db-dir", type=Path, default=None,
                    help=f"app root to scan (overrides {APP_DIR_ENV})")
    ap.add_argument("--baseline", type=Path, default=BASELINE_DEFAULT,
                    help=f"baseline allowlist (default: {BASELINE_DEFAULT.name})")
    ap.add_argument("--update-baseline", action="store_true",
                    help="record the digests of all current hits, then exit 0 (use after triage)")
    ap.add_argument("--note", default="", help="note to store alongside an --update-baseline run")
    return ap.parse_args(argv)


def run(args) -> int:
    if args.db_dir is not None:
        os.environ[APP_DIR_ENV] = str(args.db_dir)
    try:
        app_dir = resolve_app_dir()
        if app_dir is None:
            print("app_db_secrets: SKIP — no Freebuff app dir on this machine "
                  "(expected on CI runners and fresh clones)")
            return 0
        stores = store_files(app_dir)
        if not stores:
            print(f"app_db_secrets: SKIP — {app_dir} has no {STORE_GLOB} stores")
            return 0
        baseline = load_baseline(args.baseline)
        new_hits: list[tuple[Path, str, int, str]] = []
        baselined = 0
        for store in stores:
            for name, offset, digest in scan_store(store):
                if digest in baseline:
                    baselined += 1
                else:
                    new_hits.append((store, name, offset, digest))
        if args.update_baseline:
            added = 0
            for _store, name, _offset, digest in new_hits:
                if digest not in baseline:
                    # the class is recorded with every digest so triage can tell
                    # a GitHub token from an Anthropic/sk- shape without re-scanning
                    label = f"class={name}"
                    baseline[digest] = f"{label}; {args.note}" if args.note else label
                    added += 1
            save_baseline(args.baseline, baseline, args.note)
            print(f"app_db_secrets: baseline updated — {added} digest(s) recorded in {args.baseline}")
            return 0
        if new_hits:
            print(f"app_db_secrets: {len(new_hits)} NEW token-shaped hit(s) — DO NOT COMMIT "
                  f"until triaged (app dir: {app_dir}):")
            for store, name, offset, digest in new_hits[:20]:
                print(f"  {store}: {name} @0x{offset:x} sha256={digest[:16]}...")
            if len(new_hits) > 20:
                print(f"  ... and {len(new_hits) - 20} more")
            print("  triage: remove the leak source; if the string is known/acceptable, run")
            print("          python tools/check_app_db_secrets.py --update-baseline --note \"...\"")
            return 1
        print(f"app_db_secrets: clean (0 new hits; {baselined} baselined in "
              f"{len(stores)} store(s), app dir: {app_dir})")
        return 0
    except FailClosed as e:
        print(f"app_db_secrets: FAIL-CLOSED — {e}", file=sys.stderr)
        return 2


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    sys.exit(main())
