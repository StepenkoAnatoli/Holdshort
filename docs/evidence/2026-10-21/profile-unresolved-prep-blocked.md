# Superseded: model-routing prep blocked, target profile not supplied

> **Superseded 2026-10-21.** This note records the state before the target identity was supplied. The
> current target is DeepSeek V4.1 Flash Free at effort `max`. The target-specific preparation, tests,
> launch refusals and remaining blockers are in
> [`deepseek-v4.1-flash-free-max-prep.md`](deepseek-v4.1-flash-free-max-prep.md). The body below is
> retained only as history. No model was qualified in either note.

- Date: 2026-10-21
- Repository: `https://github.com/StepenkoAnatoli/Holdshort.git`
- Base commit: `0a6d341beab0e7d4b0448fe30a7b0949e16680c2`
- Mode: offline only. No model/provider request was made.
- Status: **BLOCKED before profile preparation. Nothing in this session qualifies any model for routing, spend, or live use.**

## Why this is blocked

The supplied task uses a `TARGET PROFILE` template, but none of its fields were filled:

- display name
- canonical model ID / artifact
- provider / endpoint family
- effort / reasoning setting
- official documentation URLs
- context / max output limits
- vendor list input / cached input / output prices
- capability notes and ambiguities

Those fields are inputs to the profile definition, the price-bound files, the mock transport, and the
calibration protocol. Guessing them would produce fabricated evidence. The profile-specific work in Steps
1 and 2 therefore did not start, and no `{{MODEL_SLUG}}-{{EFFORT}}-prep.md` file can be named until the
slug and effort are supplied.

## What ran locally, and exact outcomes

All commands were run in the author's Holdshort checkout at the commit above.

| Command | Exit | Observed result |
|---|---:|---|
| `python tools/validate_skills.py --strict` | 0 | 3 skills validated: `holdshort` (24 references), `holdshort-eval-prep` (1), `holdshort-review` (2) |
| `python tests/holdshort_decisions.py` | 0 | 94/94 assertions passed; 57/57 distinct fixture IDs exercised |
| `python tools/eval_pool.py self-check` | 0 | All 10 fixtures (PE-01 to PE-10) passed baseline-rejected and reference-accepted; `provider_calls: 0`; `live_model_qualification: pending`; manifest SHA-256 `c6efcd0a114c9a07c1a565f31a0ac5efa518fdd182c03b629168954aa55effd4` |
| `python tools/check_calibration_evidence.py` | 0 | 3 existing folders; 0 failures; 14 limitations (all legacy-run limitations, not new evidence) |
| `python tools/qualification_table.py --check` | 0 | `docs/evidence/qualification-table.md` matches the generated table |
| `python -m unittest tools.test_calibration_kit.RunTemplate -v` | 0 | 11/11 tests passed, including launch refusals for unfrozen protocols, placeholder qualifications, leftover placeholders, path sharing, and unrecorded relayed text. No agents were launched. |
| `python tools/dispatch_adapter.py --check key` | 2 | Refused: no `ANTHROPIC_API_KEY` in the local `.env`. This is the expected fail-closed result and no egress occurred. |
| `python tools/dispatch_adapter.py --check endpoint` | 0 | The current adapter's hard-coded endpoint (`api.anthropic.com`) passes its own consistency check. This is not approval for a new target profile. |

The `RunTemplate` test suite uses only synthetic fixtures and a stub harness. Its passing result proves
the gate behaviour, not a model's capability.

## Prepared offline

- Baseline test evidence was collected at the pinned commit.
- The calibration launch refusals were re-verified locally, including:
  - an unfrozen protocol is refused;
  - a placeholder qualification is treated as no qualification;
  - any remaining `{{placeholder}}` in the protocol is refused;
  - a judging profile without either a real qualification or the exact bootstrap limitation line is
    refused.
- No target profile definition, price-bound file, mock transport, filled `protocol.json`, history-less
  checkouts, or calibration evidence folder was created. Those all require the missing target values.

## Blocked prerequisites (user/host actions)

| Blocker | Current state | Artifact that must be supplied or authorized |
|---|---|---|
| Target profile identity and vendor facts | Not supplied; template placeholders remain | A completed `TARGET PROFILE` block, plus the cited vendor docs for limits and prices |
| (a) Credential | Local adapter refuses with exit 2: no `ANTHROPIC_API_KEY` | The host's secret store / gitignored `.env` entry for the actual provider. The owner places it; it must never be committed or pasted into chat. |
| (b) Endpoint allow-list | The adapter has one hard-coded approved endpoint and `tools/prices-2.json` lists only `api.anthropic.com` as approved (`api.openai.com` is conditional) | A host-reviewed adapter/allow-list change for the target provider, with tests. This cannot be inferred from the target profile. |
| (c) Billing qualification | `tools/live_billing_qualification.json` is deliberately unqualified (`qualified: false`, no profiles, no evidence) | A host-reviewed qualification record binding the model, request mode, exact price bytes/hash, enforced input and output token ceilings, and captured local evidence. Hashes prove integrity, not truth; the record must be authorized by the host. |
| (d) Judging profile | No independently qualified review profile for the new target; rule 3 bootstrap only | A qualified judging profile in host policy, or the protocol's exact limitation line: `judging profile not independently qualified, host-declared by <reviewer>` |
| (e) Spend allowance | No authorization for the target profile; current pilot caps are for an unrelated approved scope | A host-authorized spend/expiry/allowance record. A cheaper model does not bypass any failed gate. |

## Explicit non-claims

- No live model or provider call was made by this session.
- No token counts, costs, latency, usage observations, or qualification evidence were invented.
- No model is qualified, eligible, approved, or recommended for routing, spend, or live use.
- The passing local checks are regression and gate tests only; they are not model qualification.
- Steps 1-4 remain incomplete for the target profile because the profile inputs are missing.
