#!/usr/bin/env python3
"""Pre-write redaction filter — strip credential-shaped strings BEFORE they reach the app store.

Why this exists: `tools/check_app_db_secrets.py` refuses the next commit and
`tools/watch_app_db_secrets.py` alerts on change, but both are *detection* — by the
time either fires, the value is already in `desktop-v2.db*` (the app owns that
sqlite store, is usually running, and must not be edited in place — see
docs/CREDENTIAL_ROTATION_RUNBOOK.md §4). This tool is the *prevention* half: run
any text through it BEFORE pasting/typing it into the Desktop app (or before
saving a transcript file), so token-shaped strings never reach the store.

Scope, honestly stated:

  * This filter cannot intercept the app's SQLite writes. It sanitizes the text
    you give it (stdin, files, or the `redact()` import) — the operator must
    route text through it. Detection layers stay in place for everything that
    bypasses the filter.
  * The pattern set is reused from `tools/check_app_db_secrets.py` by import,
    never copied, so redaction and detection cannot drift apart.
  * Output discipline matches the check/watch: reports name class + count only.
    A value is never printed, logged, or stored by this tool.

Usage:
    echo "$TEXT" | python tools/redact_text.py > clean.txt
    python tools/redact_text.py --file notes.md > notes.clean.md
    python tools/redact_text.py --check --file notes.md   # exit 1 if redaction would fire
    python tools/redact_text.py --stats < draft.txt        # classes+counts on stderr

Exit codes: 0 clean (or redacted output written); 1 --check found shapes;
2 configuration error (missing file). Plain filter mode always exits 0.
Placeholders look like `[REDACTED-github-pat-fine-grained]` — the class is kept
so triage can tell a GitHub token from an sk- shape without the value.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent


def _load_check():
    spec = importlib.util.spec_from_file_location("cads_redact", TOOLS / "check_app_db_secrets.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


cads = _load_check()

PLACEHOLDER_FMT = "[REDACTED-{cls}]"


def redact(text: str) -> tuple[str, list[tuple[str, int]]]:
    """Return (redacted_text, [(class, count), ...]) for one string.

    One pass per audited pattern, in pattern order; each match is replaced by
    its class placeholder. Placeholders contain no credential-shaped text, so
    the result is stable (redact(redact(x)) == redact(x)).
    """
    counts: dict[str, int] = {}
    out = text
    for name, pat in cads.PATTERNS:
        def _repl(_m, _name=name):
            counts[_name] = counts.get(_name, 0) + 1
            return PLACEHOLDER_FMT.format(cls=_name)
        out = pat.sub(_repl, out)
    hits = [(n, counts[n]) for n, _ in cads.PATTERNS if n in counts]
    return out, hits


def total_hits(hits: list[tuple[str, int]]) -> int:
    return sum(c for _, c in hits)


def parse_args(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(description="Strip credential-shaped strings before they reach the app transcript store.")
    ap.add_argument("--file", type=Path, default=None, help="redact this file instead of stdin")
    ap.add_argument("--check", action="store_true", help="do not print redacted text; exit 1 if any shape found")
    ap.add_argument("--stats", action="store_true", help="print class+count summary to stderr (never values)")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.file is not None:
            text = args.file.read_text(encoding="utf-8", errors="strict")
        else:
            text = sys.stdin.read()
    except OSError as e:
        print(f"redact_text: cannot read input ({e})", file=sys.stderr)
        return 2
    except UnicodeDecodeError as e:
        print(f"redact_text: input is not decodable text ({e})", file=sys.stderr)
        return 2
    redacted, hits = redact(text)
    if args.stats:
        n = total_hits(hits)
        if n:
            summary = ", ".join(f"{name}x{cnt}" for name, cnt in hits)
            print(f"redact_text: redacted {n} hit(s) [{summary}]", file=sys.stderr)
        else:
            print("redact_text: clean (0 hits)", file=sys.stderr)
    if args.check:
        if hits:
            summary = ", ".join(f"{name}x{cnt}" for name, cnt in hits)
            print(f"redact_text: would redact {total_hits(hits)} hit(s) [{summary}]", file=sys.stderr)
            return 1
        print("redact_text: clean (0 hits)", file=sys.stderr)
        return 0
    sys.stdout.write(redacted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
