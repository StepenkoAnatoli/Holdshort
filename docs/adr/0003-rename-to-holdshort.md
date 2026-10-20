# ADR-0003 — The project is renamed Holdshort; frozen records and other projects' names keep the old spelling

- **Date:** 2026-10-20
- **Status:** accepted
- **Area:** the repository name, `skills/holdshort*`, `tests/holdshort_decisions.py`, the worker Brief file name, the credential custody folder, the host policy's upstream block, every document

## Context

"SmartRouter" is a generic name. On 2026-10-20, `smartrouter` was taken on PyPI and `smart-router` on npm,
several unrelated GitHub repositories used it (among them `A-new/SmartRouter`, an LLM API switcher), and
the US register held eight dead SMARTROUTER filings. "Router" also undersells the project: its point is
that permissions, capabilities, verification and budget are checked before price, and that a failed
check is a recorded stop.

On 2026-10-20 the owner picked **Holdshort** from a checked shortlist. In air traffic control, "hold short"
means stop at the line and do not enter the runway until cleared. The name was free on PyPI, npm and
GitHub, and neither the USPTO nor the Israeli register held a mark for it, as one word or as "hold
short" (searched 2026-10-20; a first screen, not legal clearance). The owner's instruction: "change the name of the repo and all
files, change all files that says: smart router into Holdshort as suggested".

## Decision

1. **Spellings.** `SmartRouter`, `Smart Router`, `smartrouter`, `smart-router`, `smart_router` become
   `Holdshort` or `holdshort`, and `SMARTROUTER` becomes `HOLDSHORT`. Paths move with them:
   `skills/smart-router{,-review,-eval-prep}/` → `skills/holdshort{,-review,-eval-prep}/`,
   `tests/smart_router_decisions.py` → `tests/holdshort_decisions.py`,
   `docs/SMARTROUTER_USAGE_REVIEW_2026-10-13.md` → `docs/HOLDSHORT_USAGE_REVIEW_2026-10-13.md`,
   `docs/assets/smartrouter-preview.svg` → `docs/assets/holdshort-preview.svg`.
2. **Dated prose records are renamed too** (reviews, records, the CHANGELOG, ADRs, the host README), as
   the owner chose the same day for the identical Research-Kit → Fetchproof rename.
3. **Clean break, no fallbacks**, also following that same-day choice: the worker Brief is
   `HOLDSHORT_BRIEF.json`, the custody folder is `~/.secrets/holdshort`, the skills are `holdshort`,
   `holdshort-review` and `holdshort-eval-prep`, the host policy's upstream block and the decision field
   written by `hosts/claude-code/route.mjs` are `holdshort`, and the canary's User-Agent and temporary
   prefixes use the new name. Nothing reads the old names any more. Two checks make a missed migration loud
   instead of silent; they detect the old names and never read through them: the custody checks
   (`tools/check_credential_hygiene.py`, also with `--secrets-dir`, and `tools/check_custody_acl.py` on Windows)
   fail closed while `~/.secrets/smart-router` exists, and `route.mjs` refuses a policy that still names its
   upstream block `smartrouter`. The exceptions are the archived host-policy-1..5, and host-policy-6 as its frozen
   copy under `trace/policies/`: it was live at the rename, and the next revision freezes it byte for byte. Under
   the pre-commit hook on Linux or macOS `HOME` is the repo, so there the custody checks do not see the old folder.
4. **Kept as written**, because changing them would make a record false or point at something that does
   not exist:
   - `hosts/claude-code/trace/**`: the host's real ledger (decisions with Brief fingerprints, usage,
     outcomes). Old decision records keep their `smartrouter` field.
   - `docs/evidence/**`: packets as sent to models, frozen protocols, observations.
   - The frozen evaluation pool id `smartrouter-prospective-v1` and the trial ids built from it
     (`tests/fixtures/prospective-eval/pool-v1.json`, `tools/eval_pool.py`, the Phase 3
     pre-registration and the pilot-readiness review). The id names a pre-registered pool, and the
     evidence refers to it.
   - Other projects' names: `BJFinancial/Smart-router` (and `src/smart_router/` inside its URLs),
     `beettlle/pi-smart-router`, `Magma-Devs/smart-router`, `ginsonko/newapi-smart-router`.
   - MoonAliza's folder `docs/orchestration/smartrouter/`. It is the host's real path;
     `hosts/claude-code/` was copied from it and differs from it since this rename.
   - Facts about things that exist under the old name outside this tree: paths inside other projects' URLs
     (`protocol/rpcsmartrouter/`, `core/smartrouter/`), the published release assets
     (`SmartRouter-v1.0.0-pilot.zip`, `SmartRouter-v1.0.1.zip`) and the zip's contents as the MoonAliza handoff
     names them, the copy of the published v1.0.1 release body (`tools/release/RELEASE_NOTES_v1.0.1.md`), git
     branch names (`docs/corrected-smartrouter-development-plan`, `skills/smart-router-v1`), paths pinned to a
     commit before the rename (`tests/smart_router_decisions.py` at `fbe7bca` and `2f4b141`), commands recorded
     as run before it, and a path quoted from a brief (`/home/user/smartrouter`).
   - The social video `docs/assets/social/local-first-look.mp4` until it is re-rendered; the two social PNGs
     were re-exported from their renamed sources.
   - One verbatim chat quote in `hosts/claude-code/README.md` ("focus on smartrouter for now").
5. The GitHub repository is renamed `StepenkoAnatoli/Holdshort` when this change merges. GitHub
   redirects the old URLs until a new repository takes the old name.

## Rejected alternatives

- **Keep the old names working** (read `SMARTROUTER_BRIEF.json` and `~/.secrets/smart-router` as
  fallbacks, alias the old skill names). Rejected: the owner chose a clean break for the same-day
  Research-Kit rename, and two names for one thing would stay in the code indefinitely. Hosts and
  machines move once (CHANGELOG, migration steps).
- **Leave dated records unchanged.** Rejected for prose records, for the same reason. It still holds for
  frozen records (Decision 4), where editing would falsify what was sent, captured or fingerprinted.
- **Rewrite the ledger and evidence too.** Rejected: they record what happened under the old name,
  and Brief fingerprints and pre-registered identifiers would no longer match.
- **Other names.** Fivebar (stops fitting if a sixth check is added) and Tokenblock (can be read as
  "blocks tokens") were the other finalists. Switchyard, Pointsman, Interlock, Remit and Idonea were
  taken in the AI field.

## Trigger to revisit

- MoonAliza renames `docs/orchestration/smartrouter/`: update the references kept in Decision 4.
- A host still writes `SMARTROUTER_BRIEF.json` or reads `~/.secrets/smart-router` after migrating, and
  cannot change: then decide on a fallback with a removal date.
- A new pool version (`v2`) is frozen: it takes the new name.
