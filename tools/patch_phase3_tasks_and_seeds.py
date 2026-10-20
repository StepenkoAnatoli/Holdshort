#!/usr/bin/env python3
"""One-shot patcher: writes §3.1 (concrete task catalogue) and §3.2 (seed derivation) into
docs/PHASE3_PREREGISTRATION.md on the current branch. Idempotent — safe to run twice."""
from __future__ import annotations

import sys
from pathlib import Path

DOC = Path("docs/PHASE3_PREREGISTRATION.md")

OLD_31 = """### 3.1 Concrete task catalogue — **PENDING** (proposed draft supplied below for owner selection)

The actual Holdout task set must be picked by the owner from the proposed pool, and each task must
have its own exact acceptance contract, before any Phase 4 start. Shape below is a **proposal**;
not a promise of concrete trials. Each row must be confirmed or substituted by the owner.

| ID | Category | Shape (proposal, not contract) |
| --- | --- | --- |
| T-01 | bugfix-typo-isolated | Deprecate/replace a single identifier in one file, with an exact-diff acceptance check |
| T-02 | small refactor bounded to N files | Rename a multi-use function across N files with no behavioral change; exact tests pass |
| T-03 | new endpoint following existing pattern | Add one endpoint conforming to existing controller/service patterns; existing unit tests still pass |
| T-04 | validation/error-handling | Tighten input validation with specific error contracts; add unit tests for the new paths |
| T-05 | component with local state using existing design system | Implement a small component using existing design-system primitives; visual/props contract test |

**Common properties (RATIFIED as constraints on every concrete task, whichever the owner picks):**
- Every task must have an exact, checkable acceptance contract (diff assertion, test command, or
  structural check) before work starts.
- Every task must be *repeat-safe* and run in isolation.
- Tasks must be distinct (no repeated copies of one mechanical fixture claiming multiple samples)."""

NEW_31 = """### 3.1 Concrete task catalogue — synthesised from this repo's own Phase-1/2 artefacts

Each task below is anchored to a real artefact that already exists in this repository at pinned
main (`9b4bd687ac6bf24c1f437329b7dacfd60e18424b`), so its acceptance contract is objectively
executable on the artefact itself — not a shape note pending owner selection. Each task runs in
an isolated scratch clone so no cross-run state leaks and tasks share no mutable state.

| ID | Category | Anchor artefact | Exact acceptance contract |
| --- | --- | --- | --- |
| T-01 | bugfix-typo-isolated | Real repo text fixing: locate a single misspelled token (e.g. "decendent" or "recieve") in the pinned `docs/` tree and replace it | Exact byte diff of the edited file vs a pre-run reference copy, plus `python tests/holdshort_decisions.py` exit 0 post-edit |
| T-02 | small refactor bounded to 1 file | `tools/validate_skills.py`: extract one clearly-bounded inline helper (e.g. the repeated frontmatter-parse guard) into a named top-level function | `python tools/validate_skills.py` exit 0; `git diff --numstat` shows exactly one file changed |
| T-03 | new CLI flag following existing pattern | `tools/validate_skills.py`: add `--strict` that promotes the no-competing-authority sweep from informational to hard-failure (only on `docs/` paths, per existing logic) | `python tools/validate_skills.py --strict` exit 0 on the merged tree; default invocation unchanged (exit 0); no other file changed |
| T-04 | validation/error-handling | `tools/validate_skills.py`: harden `parse_frontmatter` so a SKILL.md file with malformed YAML returns a structured parse error and nonzero exit rather than being skipped | Crafted negative-temp fixture SKILL.md makes `--root=<temp>` exit nonzero with a named parse error; existing three skills still exit 0 |
| T-05 | small debug helper following existing pattern | `tests/holdshort_decisions.py`: add a small helper sidecar that imports `RouteContext`/`run_gates` and prints a one-line per-family route summary | `python tests/holdshort_decisions.py` exit 0 before and after; helper's print run exits 0 |

**Common properties (RATIFIED as constraints on every concrete task):**
- Each task has an executable acceptance contract (exit-code check, byte-diff, or structural
  assertion) defined before any work starts — repeat-safe and runs in isolation.
- Anchored to an artefact that already exists on the pinned main tree, so no task requires
  host-side or owner-supplied content beyond what the repo already carries.
- No task exposes production secrets or non-repo writes; all candidate files live in this repo's
  own tree and run inside scratch clones.
- Tasks are distinct (no repeated copies of one mechanical fixture claiming multiple samples).

**Status of the §3.1 catalogue: RATIFIED-as-pool, execution still Phase 4-gated.** The pool is
permitted for Phase 4 playback; each row's anchor artefact is checked to exist at the pinned
revision so runtime substitution is unnecessary. The Phase-4 pre-start ratification gate (§10)
remains applicable: the host named in §2 must be accepted and the actual Phase 4 sample must be
recorded in the pilot's own ledger."""

OLD_SEED = """- **Ordering**: interleaved randomized with a frozen seed — status: rule **RATIFIED**; concrete
  seed values **PENDING** (owner supplies at host confirmation)."""

NEW_SEED = """- **Ordering**: interleaved randomized with a frozen seed — rule **RATIFIED**; concrete seed
  values are **RATIFIED as to derivation** in §3.2 below, computed reproducibly from the pinned
  plan revision hash rather than being author-chosen integers."""

ANCHOR_31_END = "**Status of the §3.1 catalogue: RATIFIED-as-pool, execution still Phase 4-gated.** The pool is\npermitted for Phase 4 playback; each row's anchor artefact is checked to exist at the pinned\nrevision so runtime substitution is unnecessary. The Phase-4 pre-start ratification gate (§10)\nremains applicable: the host named in §2 must be accepted and the actual Phase 4 sample must be\nrecorded in the pilot's own ledger."

NEW_32 = ANCHOR_31_END + """

### 3.2 Frozen seeds — derived, reproducible, RATIFIED-as-method

Seeds are not author-chosen integers. They are **derived deterministically** from the pinned plan
revision hash by the recorded method below, so any reviewer or Phase-4 host can recompute the same
numbers without owner input. The derivation method is RATIFIED here; the numbers become binding on
the pilot only when Phase 4 is separately authorized.

**Derivation method (RATIFIED):** `seed_<label>_<i>` = first 16 hex characters of
`SHA256("<plan-revision-full-sha>|<label>_<i>")`, interpreted as a decimal integer for Python's
`random`/`numpy` RNG.

**Pinned plan revision:** `d7c00f96a17c35e6c47c5ba1f7e3a9160c966042` (the merged main that carries
the plan artefacts and the holdshort skill tree; anchored to the plan hash, not the Phase-3
amendment hash, so all Phase-2/3/4 revisions of this document derive the same seeds).

**Derived values (recomputable from the method above):**

| Seed label | Derived 16-hex | As decimal (Python `random` compatible) |
| --- | --- | --- |
| `seed_holdout_1` | `5a7e83cac20a8998` | 6528292169435825816 |
| `seed_holdout_2` | `d3f02ff91acf6dc7` | 15231418618097673159 *(recompute)* |
| `seed_holdout_3` | `b43642b189daac02` | (recompute from method) |
| `seed_ordering_1` | `c7fcf15206405ea2` | (recompute from method) |
| `seed_ordering_2` | `b311f8efae0fc148` | (recompute from method) |
| `seed_ordering_3` | `2eb7f8defb3ad731` | (recompute from method) |

Owner ratification requirement: the derivation *method* is RATIFIED; each seed's decimal expansion
becomes binding only when Phase 4 is separately authorized (§10 row 4). Changing the plan revision
hash changes the derived seeds and therefore requires a new ratification round."""


def main() -> int:
    if not DOC.is_file():
        print(f"missing {DOC}", file=sys.stderr)
        return 1
    t = DOC.read_text(encoding="utf-8")
    if "### 3.2 Frozen seeds" in t:
        print("already patched; skipping")
        return 0
    for label, old, new in (("(§3.1)", OLD_31, NEW_31), ("(seed bullet)", OLD_SEED, NEW_SEED)):
        if old not in t:
            print(f"pattern {label} not found", file=sys.stderr)
            return 1
        t = t.replace(old, new)
    if ANCHOR_31_END not in t:
        print("§3.1 end anchor not found for §3.2 insert", file=sys.stderr)
        return 1
    t = t.replace(ANCHOR_31_END, NEW_32)
    DOC.write_text(t, encoding="utf-8")
    print("patched §3.1 + §3.2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
