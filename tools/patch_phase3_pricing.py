#!/usr/bin/env python3
"""One-shot patcher: inserts §3.3 (pricing revision skeleton) after §3.2 in
docs/PHASE3_PREREGISTRATION.md. Idempotent."""
from __future__ import annotations
import sys
from pathlib import Path

DOC = Path("docs/PHASE3_PREREGISTRATION.md")

ANCHOR_SECTION_4 = "## 4. Numerical thresholds — status per value"

PRICING_BLOCK = """### 3.3 Pricing revision skeleton — structure RATIFIED, numbers PENDING-owner-ratification

Per plan §11 ("Fill approved numerical values ... Blanks mean not ready") and §5 of the
holdshort-eval-prep checklist, a pilot cannot start without a pinned price list. The structure
below is **RATIFIED** (it mirrors plan §10's default `prices-1` shape and plan §8's budget,
reservation, and receipt rules); the **unit numbers are PENDING** explicit owner ratification before
Phase 4 starts. No number is author-ratified.

**Structure (RATIFIED):** the Phase 4 pilot uses a `prices-<label>` record naming, per profile in
§2's catalog:

| Field | What it carries | Source of value |
| --- | --- | --- |
| `profile_id` | match one of the §2 catalogue tuples exactly | host provider |
| `input_rate` | per-token (or per-call, if the provider is flat) price for input/context tokens | provider pubublished rate sheet at the pinned revision |
| `output_rate` | per-token (or per-call) price for generated tokens | same |
| `currency` | exact minor-unit identifier (e.g. `USD-1000` for thousandths; no converted quota) | provider |
| `bounds_source` | which provider-side file/page/hash the rate came from, with revision reference | provider |
| `uncertainty_class` | `known` / `unknown` / `flat-rate-capped` | operator observation |
| `effective_at` | timestamp the bound was read | operator |
| `revision_hash` | SHA-256 of the pricing record itself, so price-revision changes (S15b) are detectable | recomputed at freeze |

**Fill-out rule (RATIFIED as a structure):** a `prices-<label>` record is complete only when every
row carries a value for every field. Units are **minor units** of the stated currency, not dollar
approximations; converting from provider's unit (token, call, per-minute, per-image) to minor units
must show the arithmetic in-line. Any field that cannot be filled leaves the record incomplete;
the pilot then treats the profile's cost as **unknown/unbounded** for Gate 4 purposes (S06/S08).

**PENDING explicit owner-provided fill:** the provider's actual rate sheet content, its source
URL/hash, the provider's exact currency/decimal rule, and any flat-rate minimums. Filling these is
an owner action in §10 (row 4's prerequisite). Author-side provision not permitted this turn.

**Local-model exception (structural, `L` in the §10 catalogue):** the §10 L profile is local and
free of per-token billing, so its `input_rate`/`output_rate` are **0**, only its `resource
cost` (wall-clock/energy, per plan §8 "Local work has resource/time cost") is a real number to
record. This structural note is RATIFIED as-to-method; any specific number owner supplies stays
PENDING.

**Status of §3.3: binning of cost-model cell-level values.** Structure is RATIFIED; concrete rates
stay **PENDING** until the named owner supplies a verifiable price source (plan §11 rule: "Blanks
mean not ready"). This is an explicitly documented outstanding item, not a silent assumption.

## 4. Numerical thresholds — status per value"""

def main() -> int:
    if not DOC.is_file():
        print(f"missing {DOC}", file=sys.stderr)
        return 1
    t = DOC.read_text(encoding="utf-8")
    if "### 3.3 Pricing revision skeleton" in t:
        print("already patched; skipping")
        return 0
    if ANCHOR_SECTION_4 not in t:
        print("§4 header anchor not found", file=sys.stderr)
        return 1
    t = t.replace(ANCHOR_SECTION_4, PRICING_BLOCK, 1)
    DOC.write_text(t, encoding="utf-8")
    print("inserted §3.3")
    return 0

if __name__ == "__main__":
    sys.exit(main())
