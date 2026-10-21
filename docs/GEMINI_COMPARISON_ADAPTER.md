# Gemini comparison adapter (offline preparation)

Status: **offline preparation only** (issue #59). No Gemini destination, model id,
price configuration or accounting scope is authorized in this repository. The
adapter ships no network transport (only the offline `MockTransport`), the
checked-in authorization record is `unqualified`, and every test is mock-only —
`provider_calls: 0`. A live
comparison is a separate, explicitly authorized change (see *Bindings* below).

Files: `tools/gemini_adapter.py` (mapping, gates and a `MockTransport` for dry
runs and tests), `tools/gemini_comparison_authorization.json` (the unqualified
host record), `tools/test_gemini_adapter.py` (25 mock tests, in the regression
gate).

## What it maps

Requests are provider-neutral; the adapter shapes them for Gemini's
`generateContent` and refuses any setting it does not model rather than dropping
it, because a dropped tool declaration or safety override silently compares a
different configuration.

| Neutral input | Gemini body | Refusal |
| --- | --- | --- |
| the task text | `contents[0].parts[0].text` (role `user`) | empty text |
| `max_output_tokens` | `generationConfig.maxOutputTokens` | not a positive integer |
| `response_schema` (JSON Schema object with a `type`) | `generationConfig.responseMimeType = "application/json"` + `responseSchema` | schema without a `type` |
| `system_instruction` | `systemInstruction.parts[0].text` | empty or non-string |
| `temperature` (0–2, finite, not `bool`) | `generationConfig.temperature` | out of range, NaN, boolean |
| anything else (`tools`, `safetySettings`, `cachedContent`, `thinkingConfig`, `stream`, …) | — | refused by name |

Responses map back to text and billable usage:

| Response field | Use | Refusal |
| --- | --- | --- |
| `promptFeedback.blockReason` | — | prompt blocked |
| `modelVersion` | must equal the qualified model | any other id (never a fallback) |
| `candidates` | exactly one, with non-empty text parts | zero or several candidates, missing text |
| `finishReason` | must be `STOP` for a graded answer | `MAX_TOKENS`, `SAFETY`, `RECITATION`, `OTHER`, missing — the cell is void |
| `usageMetadata` absent | `(None, None)` — usage stays **null**, never zero | — |
| `promptTokenCount`, `candidatesTokenCount` | billable totals | missing, negative or non-integer |
| `cachedContentTokenCount` | **subtracted** from the prompt total | exceeds the prompt total |
| `thoughtsTokenCount` | **subtracted** from the candidate total | exceeds the candidate total |
| `totalTokenCount` | must equal `prompt + candidates` | any other total |
| any other usage field | — | unmodeled usage (charge unknown) |

A partial finish reason refuses the answer but carries the parsed counts on the
exception (`err.usage`), so a future host can record spend without grading a
truncated or filtered answer as capability.

## Fail-closed gates

`build_dispatch_fn` refuses when any of these is unknown or unqualified:

- **destination** — not one of the endpoints this adapter can shape, or `null`;
- **profile** — unknown profile id at call time (no model substitution);
- **capability** — an unsupported setting, an invalid value, more than one
  candidate, a non-`STOP` finish reason;
- **price and accounting** — the record lacks `price_revision` or the sha256 of
  the price configuration, or its scope/currency is not
  `provider-reported-tokens` / `USD`;
- **transport** — none supplied (this module has no network path);
- **change during a run** — the record's sha256 is recompared before every call,
  so an edited qualification stops the adapter instead of being half-honored;
- **token counting** — `count_tokens` always refuses, because no counting
  endpoint is authorized. The dispatcher's pre-send reservation therefore
  blocks rather than pricing a prompt at zero.

## Frozen trial plan

`frozen_trial_plan()` reads `tools/calibration/subject-pack/shared/manifest.json`
(the kit's shared packet), verifies the pinned manifest sha256 **and** every
`source_hashes` entry, and emits one trial per case (`fix`, `pin`, `review`)
with the manifest's base commit and tier. The oracle hash covers the manifest's
`findings`, `commands`, `paths`, `accepted_fix`, `checkout`, `commit_rule` and
`isolation` — the packet and oracle every host running the shared pack uses, so a
later Gemini result is comparable rather than a new task set.

The historical calibration runs (`docs/evidence/2026-10-17`, `2026-10-18`) used a
host pack (`MoonAliza`), not the shared pack: the shared pack is the
cross-host packet this kit defines, so the Gemini arm is comparable to any host
that runs it, not retroactively to those host-pack runs. Any change to the pack
files or the manifest refuses: a new pack version needs a new pinned plan and a
new cohort, never a silent substitution.

Harness differences, recorded in the plan:

| Aspect | Cohort (Claude Code workflow) | Gemini arm |
| --- | --- | --- |
| Transport | workflow cells inside the host harness | one direct API call per cell |
| Repository access | candidate works in a history-less checkout | the same checkout, driven by the host around the call |
| Grading | `grade.sh` for pin/fix, kit grader + cluster + lenses for review | identical; the arm supplies only the answer |
| Retries | retry limit 0, harness retries recorded | identical |
| Readings | protocol before/after usage-window readings | identical (host duty) |

## Bindings required for a future live comparison

Issue #59 does not authorize spend or a new network destination. Before a live
run, the host must supply and review:

1. **Destination authorization** — an approval record naming one endpoint (the
   adapter knows `https://generativelanguage.googleapis.com`), in the same form
   as row 4 of the Phase 4 packet for Anthropic.
2. **Model ids and configuration** — resolved from current provider
   documentation at implementation time, one profile per model, each with its
   output ceiling and input token ceiling.
3. **Price configuration** — a rate sheet with a revision and a sha256 that the
   record carries, so price drift is detectable; no price, no execution.
4. **Accounting scope** — `provider-reported-tokens` in USD, with the same
   "unknown is not zero" rule as the pilot ledger.
5. **A counting endpoint or a conservative ceiling** — the dispatcher requires
   `max_tokens` and `count_tokens` before egress; `count_tokens` refuses today.
6. **A dispatcher change** — `tools/live_dispatcher.py` returns integer token
   counts from `dispatch_fn`; recording a `null` usage row (the issue's rule for
   providers without counters) needs an explicit unknown-usage path rather than
   a zero fill.
7. **Protocol and evidence** — the calibration protocol's freeze, run id,
   judging profile and readings, plus a spend allowance recorded before launch.

Until all seven exist, `tools/gemini_adapter.py status` and
`build_dispatch_fn` refuse, and the regression gate runs only the mock tests.
