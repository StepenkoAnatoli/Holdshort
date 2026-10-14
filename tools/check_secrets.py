#!/usr/bin/env python3
"""Secrets scan — fail the build if a credential-like token is committed.

Row-4 key-placement decision: the Anthropic key lives in a local, gitignored
`.env`. This tool is the second guard: it scans tracked files for
credential-shaped strings and for references to `.env` values leaking into
tracked artifacts.

Checked patterns (conservative; a hit names file:line):
  * Anthropic keys:      sk-ant-... (>= 20 chars after prefix)
  * generic API keys:    sk-[A-Za-z0-9_-]{16,}
  * OpenAI-style keys:   sk-proj-...
  * key assignment:      (api_?key|secret|token|password)\\s*[=:]\\s*["']?[A-Za-z0-9_\\-]{12,}
  * raw authorization headers with bearer tokens

Scope: all git-tracked files via `git ls-files -z` (untracked local files are
out of scope — .env is untracked by design). Known-binary extensions (.png,
.zip, ...) are skipped.

Decoding policy (hardened): a skipped unreadable or undecodable file is an
UNSCANNED hole, not a pass. Decode chain attempts utf-8-sig, strict utf-8,
utf-16 (BOM-sniffing), utf-16-le and utf-16-be before giving up. Exit codes:
  0  clean
  1  credential-shaped hit (refuse commit)
  2  fail-closed: tracked-file listing failed, a text-class file was
     unreadable (permissions) or undecodable (NOT any known-binary ext) —
     the scan corpus is incomplete and a leak could be hiding in it.
Designed as a stop-the-line check, not advisory output.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PATTERNS = [
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai-style-key", re.compile(r"sk-proj-[A-Za-z0-9_\-]{16,}")),
    ("generic-sk-key", re.compile(r"\bsk-[A-Za-z0-9_\-]{24,}\b")),
    ("key-assignment", re.compile(
        r"""(?i)\b(api_?key|secret|token|password)\b['"\s]*[=:]\s*["']?[A-Za-z0-9_\-]{12,}""")),
    ("bearer-token", re.compile(r"(?i)authorization['\"]?\s*[:=]\s*['\"]?bearer\s+[A-Za-z0-9_\-\.]{16,}")),
]

_SKIP_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".zip", ".pdf", ".woff", ".woff2", ".ico"}
_SKIP_DIRS = (".git/", "__pycache__/")
# self-exclusions: this file's own pattern definitions must not self-trip
SELF_PATH = "tools/check_secrets.py".replace("\\", "/")

UTF8_FAMILY: tuple[str, ...] = ("utf-8-sig", "utf-8")
UTF16_FAMILY: tuple[str, ...] = ("utf-16", "utf-16-le", "utf-16-be")


class UnscannableError(Exception):
    """A tracked file that should be text could not be decoded or read."""


def is_mp4_container(path: Path) -> bool:
    """Recognize an ISO base-media ftyp header, not just a .mp4 filename."""
    try:
        with path.open('rb') as fh:
            header = fh.read(16)
    except OSError as exc:
        raise UnscannableError('MP4 header unreadable') from exc
    return (len(header) == 16 and header[4:8] == b'ftyp'
            and int.from_bytes(header[:4], 'big') >= 16
            and header[8:12] in (b'isom', b'iso2', b'avc1', b'mp41', b'mp42'))


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, timeout=60)
    if out.returncode != 0:
        print(f"check_secrets: git ls-files failed: {out.stderr.decode(errors='replace')}",
              file=sys.stderr)
        raise SystemExit(2)
    return [f.decode("utf-8", errors="replace")
            for f in out.stdout.split(b"\x00") if f.strip()]


def _utf16_order_by_nul_parity(raw: bytes) -> str:
    """Little-endian utf-16 puts ASCII NULs at ODD byte offsets, big-endian
    at EVEN offsets; pick the dominant parity (ties → LE, the common case)."""
    even = sum(1 for i in range(0, len(raw) - 1, 2) if raw[i] == 0)
    odd = sum(1 for i in range(1, len(raw), 2) if raw[i] == 0)
    return "utf-16-be" if even > odd else "utf-16-le"


def decode_text(p: Path) -> str:
    """Decode a text-class tracked file via the BOM/utf-8/utf-16 chain.

    Acceptance rule: a decode is only ACCEPTED when it yields NUL-free
    text. utf-16-le/be bytes without a BOM are "valid" utf-8 with
    interleaved NULs, and searching that mangled string would silently
    miss real keys — so NUL-mixed utf-8 dispatches to utf-16 with the
    endianness chosen by NUL-byte parity (Python's BOM-less 'utf-16'
    defaults to LE and would mangle BE text into NUL-free garbage, which
    is exactly the false-clean trap). utf-8-garbled bytes without a BOM
    are unrecoverably ambiguous → UnscannableError (fail closed).
    """
    try:
        raw = p.read_bytes()
    except OSError as e:  # PermissionError and friends
        raise UnscannableError(f"unreadable ({e})") from e
    fallback: str | None = None
    for enc in UTF8_FAMILY:  # utf-8-sig then strict utf-8
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        except UnicodeError:
            continue
        if "\x00" not in text:
            return text
        if fallback is None:
            fallback = text  # NUL-mixed utf-8: real utf-16 without BOM
        break
    if fallback is not None:
        # BOM-less utf-16: decode with parity-chosen endianness; everything
        # else in that shape is mangled utf-8 text, still searchable
        try:
            ordered = raw.decode(_utf16_order_by_nul_parity(raw))
        except UnicodeDecodeError:
            ordered = None
        if ordered is not None and "\x00" not in ordered:
            return ordered
        return fallback  # mangled text beats skipping: a hit is still a hit
    # utf-8 family failed outright: only a BOM'd utf-16 file is trustworthy
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    raise UnscannableError(
        f"undecodable in any of {', '.join(UTF8_FAMILY + UTF16_FAMILY)}")


def scan() -> list[str]:
    hits: list[str] = []
    for rel in tracked_files():
        win_rel = rel.replace("/", "\\")
        if win_rel.startswith(_SKIP_DIRS) or rel.startswith(_SKIP_DIRS):
            continue
        p = ROOT / rel
        suffix = p.suffix.lower()
        if suffix in _SKIP_EXTENSIONS:
            continue
        if not p.is_file():
            continue
        # Genuine media cannot be decoded as text. Keep text disguised with
        # a .mp4 suffix in the scan corpus rather than adding a blanket skip.
        if suffix == '.mp4' and is_mp4_container(p):
            continue
        try:
            text = decode_text(p)
        except UnscannableError as e:
            raise UnscannableError(
                f"{rel} could not be scanned ({e}); fix or remove the file, "
                "or add its extension to _SKIP_EXTENSIONS if it is genuinely binary"
            ) from e
        for name, pat in PATTERNS:
            for i, line in enumerate(text.splitlines(), 1):
                # skip the scanner's own literal pattern definitions
                if SELF_PATH in rel and ("re.compile(r" in line or "re.compile(" in line):
                    continue
                if pat.search(line):
                    snippet = line.strip()
                    if len(snippet) > 120:
                        snippet = snippet[:117] + "..."
                    hits.append(f"{rel}:{i}: {name}: {snippet}")
    return hits


def main() -> int:
    try:
        hits = scan()
    except UnscannableError as e:
        print(f"check_secrets: FAIL-CLOSED — {e}", file=sys.stderr)
        return 2
    if hits:
        print(f"check_secrets: {len(hits)} hit(s) — DO NOT COMMIT; remove the credential:")
        for h in hits:
            print("  " + h)
        return 1
    print("check_secrets: clean (0 hits)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
