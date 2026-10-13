#!/usr/bin/env python3
"""Transcript redaction layer — strip credential-shaped strings BEFORE any
content is written to a transcript-bound store.

Why this exists (the hole it closes): the Freebuff Desktop app persists thread
transcripts to sqlite stores under `~/.config/freebuff-desktop/projects/*/
desktop-v2.db*`. Anything this repo renders or persists — pilot ledger lines,
per-task state, host-watchdog escalation packages, tool output echoed into a
thread — can land there. `tools/check_app_db_secrets.py` and
`tools/watch_app_db_secrets.py` DETECT such strings after they are already
written; this layer PREVENTS them at the source: every writer that produces
transcript-bound content passes it through `redact_text` / `redact_obj` first.
(The app's own write path is not ours to hook; stripping at every boundary we
do control is what keeps credential-shaped strings from ever reaching it.)

Invariant: coverage is the union of both audited scanners —
`check_secrets.PATTERNS` plus the GitHub families from
`check_app_db_secrets` — so anything the gate would flag is stripped before it
can be written. Overlapping matches resolve to the most specific class
(anthropic beats generic-sk).

Output discipline (same as the scanners): a match is replaced by
`[REDACTED:<class>:sha256=<first-16-hex>]` — class plus a digest, never the
value. Digests are safe to print; values are not. Redaction is idempotent:
the markers themselves never re-trigger any pattern.

Library:
    redact_text(text)   -> (redacted_text, findings)
    redact_bytes(data)  -> (redacted_bytes, findings)
    redact_obj(obj)     -> (redacted_obj, findings)   # dict/list/tuple/str
    findings entries are {"class": ..., "digest": sha256-hex of the value}

CLI (a pre-write filter for any pipeline):
    python tools/redaction.py [--in P] [--out P] [--fail-on-hit] [--quiet]

Exit codes:
    0  ran (redactions, if any, are reported on stderr as class+digest only)
    1  --fail-on-hit and at least one credential-shaped string was stripped
    2  I/O failure (fail-closed: unredacted content is never passed through)
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any, List, Tuple

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import check_secrets as cs  # noqa: E402  (audited pattern definitions)
import check_app_db_secrets as appdb  # noqa: E402  (GitHub families + reuse)

# The single source of truth for what "credential-shaped" means here:
# appdb.PATTERNS (GitHub families + anthropic/openai/generic-sk, specific
# first) plus the two audited classes appdb deliberately skips for blob-scan
# precision. A redaction false positive costs a transcript a few characters;
# a missed class costs a live credential.
PATTERNS: List[Tuple[str, Any]] = list(appdb.PATTERNS) + [
    p for p in cs.PATTERNS if p[0] not in {n for n, _ in appdb.PATTERNS}
]

MARKER = "[REDACTED:{cls}:sha256={digest}]"


def _find_matches(text: str) -> List[Tuple[int, int, str]]:
    """Non-overlapping (start, end, class) spans, most specific class first."""
    spans: List[Tuple[int, int, int, str]] = []
    for idx, (name, pat) in enumerate(PATTERNS):
        for m in pat.finditer(text):
            spans.append((m.start(), m.end(), idx, name))
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0]), s[2]))
    picked: List[Tuple[int, int, str]] = []
    last_end = -1
    for start, end, _idx, name in spans:
        if start < last_end:  # overlap: the earlier/longer/more specific won
            continue
        picked.append((start, end, name))
        last_end = end
    return picked


def _digest(value: str) -> str:
    # Matches check_app_db_secrets' digest exactly (the matched strings are
    # pure [A-Za-z0-9_-] ASCII, so utf-8 == latin-1 here).
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def redact_text(text: str) -> Tuple[str, List[dict]]:
    """Strip credential-shaped substrings; return (redacted, findings)."""
    if not isinstance(text, str):
        raise TypeError(f"redact_text expects str, got {type(text).__name__}")
    matches = _find_matches(text)
    if not matches:
        return text, []
    out: List[str] = []
    findings: List[dict] = []
    pos = 0
    for start, end, name in matches:
        value = text[start:end]
        digest = _digest(value)
        out.append(text[pos:start])
        out.append(MARKER.format(cls=name, digest=digest[:16]))
        findings.append({"class": name, "digest": digest})
        pos = end
    out.append(text[pos:])
    return "".join(out), findings


def redact_bytes(data: bytes) -> Tuple[bytes, List[dict]]:
    """Byte-level redaction via a lossless latin-1 round trip (scanner style)."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError(f"redact_bytes expects bytes, got {type(data).__name__}")
    redacted, findings = redact_text(data.decode("latin-1"))
    return redacted.encode("latin-1"), findings


def redact_obj(obj: Any) -> Tuple[Any, List[dict]]:
    """Recursively redact strings inside dict/list/tuple structures."""
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        out = {}
        findings: List[dict] = []
        for k, v in obj.items():
            rk, fk = redact_text(k) if isinstance(k, str) else (k, [])
            rv, fv = redact_obj(v)
            out[rk] = rv
            findings.extend(fk)
            findings.extend(fv)
        return out, findings
    if isinstance(obj, list):
        out_l: List[Any] = []
        findings_l: List[dict] = []
        for item in obj:
            ri, fi = redact_obj(item)
            out_l.append(ri)
            findings_l.extend(fi)
        return out_l, findings_l
    if isinstance(obj, tuple):
        out_t = []
        findings_t: List[dict] = []
        for item in obj:
            ri, fi = redact_obj(item)
            out_t.append(ri)
            findings_t.extend(fi)
        return tuple(out_t), findings_t
    return obj, []  # numbers, bools, None: nothing to strip


def parse_args(argv: List[str] | None = None):
    ap = argparse.ArgumentParser(
        description="Pre-write redaction filter: strip credential-shaped "
                    "strings before content reaches a transcript-bound store.")
    ap.add_argument("--in", dest="in_path", type=Path, default=None,
                    help="input file (default: stdin)")
    ap.add_argument("--out", dest="out_path", type=Path, default=None,
                    help="output file (default: stdout)")
    ap.add_argument("--fail-on-hit", action="store_true",
                    help="exit 1 when anything was stripped (gating mode)")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress the stderr findings summary")
    return ap.parse_args(argv)


def run(args) -> int:
    try:
        raw = args.in_path.read_bytes() if args.in_path else sys.stdin.buffer.read()
    except OSError as e:
        print(f"redaction: FAIL-CLOSED — cannot read input ({e})", file=sys.stderr)
        return 2
    redacted, findings = redact_bytes(raw)
    try:
        if args.out_path:
            args.out_path.write_bytes(redacted)
        else:
            sys.stdout.buffer.write(redacted)
            sys.stdout.buffer.flush()
    except OSError as e:
        print(f"redaction: FAIL-CLOSED — cannot write output ({e})", file=sys.stderr)
        return 2
    if findings and not args.quiet:
        print(f"redaction: stripped {len(findings)} credential-shaped string(s); "
              f"classes: {sorted({f['class'] for f in findings})}", file=sys.stderr)
        for f in findings:
            print(f"  {f['class']} sha256={f['digest'][:16]}...", file=sys.stderr)
    if findings and args.fail_on_hit:
        return 1
    return 0


def main(argv: List[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
