# Handoff note — Moonzila owner

**To:** StepenkoAnatoli (Moonzila owner)
**From:** Holdshort project, via the codebuff agent, 2026-10-10
**Subject:** v1.0.0-pilot is released — your Phase 6/7 entry points

## Release

> The project was renamed Holdshort on 2026-10-20 (ADR-0003). This release and its zip keep the
> old names: the asset file, the `smart-router` skill and `tests/smart_router_decisions.py`.

- **Tag:** `v1.0.0-pilot` (annotated, at `b6e04fd`)
- **Release page:** https://github.com/StepenkoAnatoli/Holdshort/releases/tag/v1.0.0-pilot
- **Asset:** https://github.com/StepenkoAnatoli/Holdshort/releases/download/v1.0.0-pilot/SmartRouter-v1.0.0-pilot.zip
  (90,260 bytes, 31 entries, MIT; contains the validated `skills/` tree, the 79-assertion decision
  suite, the sidecar helper, the hardened validator, and all canonical docs)
- **Quickstart verified from a clean unpack** — all four commands exit 0 (see `RELEASE_NOTES.md` in the zip)

## What this release already contains for Moonzila

- `docs/MOONZILA_ADVISORY_UI.md` — the Phase 6 "first advisory UI" design note (stored-preview
  display vs. generate-path separation, plan §13). It needs **your approval** before any Moonzila
  implementation work starts.
- The `smart-router` skill (now `holdshort`) — advisory-only by design; it **recommends** route decisions but never
  performs dispatch, spend, or model switching itself. All performative enforcement is Moonzila-side.

## Gate you own (per plan §13/§16 — not started in this project by design)

1. **Phase 6 first advisory UI** — approve the design note (`docs/MOONZILA_ADVISORY_UI.md`) as-is
   or with changes, then implement on the Moonzila side. Stored-preview display requires **zero
   new model calls**; the generate path is separately gated.
2. **Phase 7 full integration** — a separate approval, not bundled with Phase 6.

## Where the harness is already on your side

The release zip contains everything needed to validate the skill tree on the Moonzila host
without any additional repo work — `tools/validate_skills.py` (supports `--strict`) and
`tests/smart_router_decisions.py` (79 assertions / 52 fixture IDs, exit 0 expected) are both
pre-run and reported clean at `b6e04fd`.

## Contact / provenance

- Pinned plan revision: `d7c00f96a17c35e6c47c5ba1f7e3a9160c966042` (what every skill references)
- Completed non-live evaluation: `docs/PHASE4_PILOT_REPORT.md` (in the zip / on `main`)
- Outstanding P02 strict independence: `docs/P02_REVIEW_RECORD.md` §5 countersignature block
