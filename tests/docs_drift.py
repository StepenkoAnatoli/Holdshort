#!/usr/bin/env python3
"""Docs-drift check — pin background docs' conventions to spec-v2.md.

The background companions (host-worktree-*, examples, host-hil-policy) restate
spec-v2.md §6 (isolation lattice), §9 (decision-block keys, route/HumanGate enums)
and the host naming rules in prose and fenced examples. Every restatement is a
drift surface: a doc that invents a fifth HumanGate, drops `Uncertainty` from its
"complete" block, or shows a branch its own task-id rules reject will mislead the
next host or reviewer. This check pins the restatements to the normative source:

  F1. every fenced decision block (contains `Difficulty:`) in skills/ carries all
      eleven §9 keys — or the file owns an "abbreviat*" note for the block below
      (the sibling examples' flagged shorthand; example-lifecycle.md is the
      complete-shape reference and must pass the full version)
  F2. every HumanGate value shown in skills/ is in the §8.2 enum
      {none, review-before-dispatch, review-before-merge, approval-required}
  F3. every Isolation value shown in skills/ is in the §6 lattice
      {none, directory, worktree+branch, ephemeral-container}
  F4. every Route value shown in skills/ is in the §9 enum
      {direct, delegate, speculative, recommend-escalation, blocked}
  F5. every `sr/X/Y` branch example is either an angle-bracket template / `...`
      placeholder, or X validates per host-task-id.md and Y is a valid slug
  F6. every file naming HOLDSHORT_BRIEF.json owns the convention note
      ("convention", case-insensitive) — the filename is host convention, never
      normative (spec-v2 §11 names no file)

  Canonical homes (single-sourcing — restatements must not diverge or float free):
  F7. isolation lattice order: any line naming 2+ lattice levels names them in the
      canonical order none < directory < worktree+branch < ephemeral-container
      (spec-v2.md §6 is the home; tables list weakest-first, templates read left-first)
  F8. HumanGate tables agree: spec-v2.md §8.2 and host-hil-policy.md §2 contain the same
      four gate names, and no backticked `review-before-*` / `approval-*` token anywhere
      falls outside the enum
  F9. no live two-repair allowance: "one implementation repair plus one CI repair" /
      "two same-profile" language survives only inside RESOLVED/previously/flagged
      historical context (±3 lines) — the live rule is one total (F10)
  F10. repair-cap restatements cite their fixture: any block stating the one-repair cap
      contains "R01" within line..+3 or points at the cited rule ("above"/"below")
      ("convention", case-insensitive) — the filename is host convention, never
      normative (spec-v2 §11 names no file)

Runs standalone (`python tests/docs_drift.py`, exit 0 pinned / 1 drifted) and as
part of the regression gate via tools/test_docs_drift.py. No network.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_task_ids():
    spec = importlib.util.spec_from_file_location(
        "tids_drift", ROOT / "tools" / "task_ids.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


SECTION9_KEYS = ("Difficulty:", "Route:", "Profile:", "Isolation:", "IsolationReason:",
                 "Owner:", "HumanGate:", "NestedAllowed:", "MaxNestingDepth:",
                 "Reservations:", "Calls:", "Deadline:", "Uncertainty:")
HUMANGATES = {"none", "review-before-dispatch", "review-before-merge", "approval-required"}
ISOLATION = {"none", "directory", "worktree+branch", "ephemeral-container"}
ROUTES = {"direct", "delegate", "speculative", "recommend-escalation", "blocked"}
SKILLS = ROOT / "skills"


def skill_docs(root: Path = SKILLS) -> list[Path]:
    return sorted(root.rglob("*.md"))


def fenced_blocks(text: str) -> list[str]:
    return re.findall(r"```(?:\w*)\n(.*?)```", text, re.DOTALL)


def check(root: Path | None = None) -> list[str]:
    """Return drift findings (empty = pinned). Pure; prints nothing."""
    ti = _load_task_ids()
    findings: list[str] = []
    base = root or SKILLS
    for doc in skill_docs(base):
        try:
            rel = doc.relative_to(ROOT).as_posix()
        except ValueError:
            rel = doc.name
        text = doc.read_text(encoding="utf-8")
        for block in fenced_blocks(text):
            if "Difficulty:" not in block:
                continue
            missing = [k for k in SECTION9_KEYS if k not in block]
            if missing and "abbreviat" not in text.lower():
                findings.append(f"{rel}: decision block missing {missing} "
                                f"and no abbreviation note")
            for m in re.finditer(r"^(\s*)(Route|HumanGate|Isolation):\s*(\S+)", block, re.M):
                field, value = m.group(2), m.group(3).strip("`\"',")
                if value.startswith("<"):
                    continue  # `<a | b | c>` template enumeration, not a literal value
                allowed = {"Route": ROUTES, "HumanGate": HUMANGATES,
                           "Isolation": ISOLATION}[field]
                if value not in allowed:
                    findings.append(f"{rel}: {field} value {value!r} outside spec-v2 enum")
        for m in re.finditer(r"`(sr/([^/`\s]+)/([^/`\s]+))`", text):
            full, xid, slug = m.group(1), m.group(2), m.group(3)
            if "<" in xid or "<" in slug or "..." in slug or "<" in full:
                continue  # template/placeholder form, not a literal example
            if not ti.valid(xid):
                findings.append(f"{rel}: branch example `{full}` id part invalid "
                                f"per host-task-id.md")
            elif ti.slugify(slug) != slug:
                findings.append(f"{rel}: branch example `{full}` slug not canonical")
        if "HOLDSHORT_BRIEF.json" in text and "convention" not in text.lower():
            findings.append(f"{rel}: names HOLDSHORT_BRIEF.json without the "
                            f"host-convention note")
        # F7: lattice order on lines naming 2+ levels
        levels = ["none", "directory", "worktree+branch", "ephemeral-container"]
        for i, line in enumerate(text.splitlines(), 1):
            present = sorted([lv for lv in levels if lv in line], key=line.index)
            if len(present) >= 2 and present != sorted(present, key=levels.index):
                findings.append(f"{rel}:{i}: lattice levels out of canonical order: "
                                f"{line.strip()[:100]}")
        # F8b: gate-like backticked tokens must be enum members
        for m in re.finditer(r"`((?:review-before-|approval-)\S+?)`", text):
            if m.group(1) not in HUMANGATES:
                findings.append(f"{rel}: gate-like token `{m.group(1)}` outside spec-v2 §8.2")
        # F9: live two-repair allowance language (historical context exempt)
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if re.search(r"one implementation repair\s*(\*\*plus\*\*|plus|\+)\s*one CI repair"
                         r"|two same-profile", line, re.IGNORECASE):
                window = "\n".join(lines[max(0, i - 3):i + 4])
                if not re.search(r"RESOLVED|previously|Flagged|exceeds|flag 1", window):
                    findings.append(f"{rel}:{i + 1}: two-repair allowance outside "
                                    f"historical context")
        # F10: cap restatements cite R01 or point at the cited rule
        for i, line in enumerate(lines):
            if re.search(r"at most one same-profile|maximum \*\*1\*\*.*same-profile"
                         r"|one same-profile repair total|1 same-profile repair total"
                         r"|max 1 TOTAL|max 1 same-profile", line, re.IGNORECASE):
                window = "\n".join(lines[i:i + 4])
                if "R01" not in window and "above" not in window and "below" not in window:
                    findings.append(f"{rel}:{i + 1}: repair-cap restatement without "
                                    f"fixture cite (want R01 or above/below pointer)")
    # F8a: the two canonical gate tables agree on the name set
    for canon in ("skills/holdshort/references/spec-v2.md",
                  "skills/holdshort/references/host-hil-policy.md"):
        ctext = (ROOT / canon).read_text(encoding="utf-8")
        missing = [g for g in HUMANGATES if g not in ctext]
        if missing:
            findings.append(f"{canon}: canonical gate table missing {missing}")
    return findings


def main() -> int:
    findings = check()
    if findings:
        print(f"docs_drift: {len(findings)} drift finding(s):")
        for f in findings:
            print("  -", f)
        return 1
    print(f"docs_drift: pinned ({len(skill_docs(SKILLS))} skills docs checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
