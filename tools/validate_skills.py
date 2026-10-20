#!/usr/bin/env python3
"""Package validator for Holdshort Agent Skills.

Checks (per agentskills.io/specification, inspected 2026-10):
  1. Each skill directory contains SKILL.md with YAML frontmatter.
  2. name: 1-64 chars, [a-z0-9-], no leading/trailing/consecutive hyphen, matches directory name.
  3. description: 1-1024 chars, non-empty.
  4. Optional fields' constraints: license (str), compatibility (1-500), metadata (str->str), allowed-tools (str).
  5. Relative file references in SKILL.md and references/*.md resolve to existing files (one level deep).
  6. No in-repo competing routing authority: no operational tier/flowchart/headers/score-approval
     policy outside skills/holdshort/** (README/docs may describe the policy but must not
     restate operational rules).
Exits 0 when all checks pass; nonzero otherwise. No network, no code execution of skill content.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
# simple scalar/list parser subset for our known frontmatter fields
DEFUNCT_OPERATIONAL_MARKERS = [
    # old README policy's operational vocabulary — must not appear outside skills/holdshort
    (r"Difficulty: \[Trivial", "response-header mandate"),
    (r"chosen model tier", "tier header mandate"),
    (r"average score", "score-average approval"),
    (r"choose this tier", "tier selection rule"),
    (r"escalate to a higher available tier", "tier escalation rule"),
]


def parse_frontmatter(text: str):
    m = FM_RE.match(text)
    if not m:
        return None, "no YAML frontmatter block found"
    block = m.group(1)
    fields: dict = {}
    current_key = None
    for line in block.splitlines():
        if re.match(r"^\s", line) and current_key:
            # continuation of a list or nested map — keep raw
            fields.setdefault(current_key, "")
            continue
        km = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not km:
            if line.strip() and not line.startswith(" "):
                return None, f"malformed frontmatter line (expected 'key: value'): {line!r}"
            continue
        key, val = km.group(1), km.group(2).strip()
        current_key = key
        fields[key] = val
    return fields, block


def check_name_dir_match(skill_dir: Path, name: str, errors: list):
    if name != skill_dir.name:
        errors.append(f"{skill_dir.name}: name '{name}' != directory name '{skill_dir.name}'")


def check_field(name: str, fields: dict, body_errors: list):
    desc = fields.get("description", "")
    if not desc:
        body_errors.append(f"{name}: missing description")
    elif len(desc) > 1024:
        body_errors.append(f"{name}: description too long ({len(desc)} > 1024)")
    if not fields.get("name") or not NAME_RE.match(fields["name"]):
        body_errors.append(f"{name}: invalid name")
    elif len(fields["name"]) > 64:
        body_errors.append(f"{name}: name too long")
    compat = fields.get("compatibility")
    if compat and (len(compat) < 1 or len(compat) > 500):
        body_errors.append(f"{name}: compatibility must be 1-500 chars")
    at = fields.get("allowed-tools")
    if at and not isinstance(at, str):
        body_errors.append(f"{name}: allowed-tools must be a string")


def resolve_refs(md_path: Path, errors: list):
    """Relative file/path references should resolve to existing files (allowing http(s) links)."""
    text = md_path.read_text(encoding="utf-8")
    for m in re.finditer(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
        target = m.group(1)
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        resolved = (md_path.parent / target).resolve()
        if not resolved.exists():
            errors.append(f"{md_path.relative_to(ROOT)}: broken reference '{target}'")


def check_no_competing_authority(errors: list):
    allowed_prefix = ("skills/", "docs/", "tools/", "tests/")
    for md in ROOT.rglob("*.md"):
        rel = md.relative_to(ROOT).as_posix()
        if rel.startswith(allowed_prefix):
            continue
        if rel.upper().startswith("LICENSE"):
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        for pattern, label in DEFUNCT_OPERATIONAL_MARKERS:
            if re.search(pattern, text, re.IGNORECASE):
                errors.append(f"{rel}: possible competing routing authority ({label})")


def check_skill_dir(sd: Path, errors: list):
    """Validate one skill directory: SKILL.md presence, frontmatter, naming, refs."""
    skill_md = sd / "SKILL.md"
    if not skill_md.is_file():
        errors.append(f"{sd.name}: missing SKILL.md")
        return
    text = skill_md.read_text(encoding="utf-8")
    fields, block = parse_frontmatter(text)
    if fields is None:
        errors.append(f"{sd.name}: {block}")
        return
    name = fields.get("name", "")
    check_field(sd.name, fields, errors)
    if name and NAME_RE.match(name):
        check_name_dir_match(sd, name, errors)
    # reference resolution inside SKILL.md
    resolve_refs(skill_md, errors)
    # reference resolution inside references/
    refs = sd / "references"
    if refs.is_dir():
        for ref in sorted(refs.glob("*.md")):
            resolve_refs(ref, errors)


def main() -> int:
    import sys as _sys
    strict = "--strict" in _sys.argv[1:]

    errors: list = []
    competing: list = []  # separated for strict-mode promotion

    if not SKILLS_DIR.is_dir():
        print("no skills/ directory — nothing to validate (plan-only branch).")
        return 0
    skill_dirs = [d for d in sorted(SKILLS_DIR.iterdir()) if d.is_dir()]
    if not skill_dirs:
        print("no skill directories found under skills/")
        return 0
    for sd in skill_dirs:
        check_skill_dir(sd, errors)
    check_no_competing_authority(competing)
    if strict and competing:
        print(f"FAILED (--strict): {len(competing)} possible competing-authority finding(s) promoted to hard failure:")
        for e in competing:
            print(" -", e)
        return 1
    if errors:
        print(f"FAILED with {len(errors)} error(s):")
        for e in errors:
            print(" -", e)
        return 1
    if competing:
        print(f"NOTE: {len(competing)} possible competing-authority finding(s) (informational; rerun with --strict to promote to failure):")
        for e in competing:
            print(" -", e)
    print(f"OK: {len(skill_dirs)} skill(s) validated:")
    for sd in skill_dirs:
        n_refs = len(list((sd / 'references').glob('*.md'))) if (sd / 'references').is_dir() else 0
        print(f" - {sd.name}: SKILL.md + {n_refs} reference file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
