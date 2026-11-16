# Gemini comparison adapter (offline preparation)

Status: **offline preparation only** (issue #59). No Gemini destination, model id,
price configuration or accounting scope is authorized in this repository. The
adapter ships no network transport (only the offline `MockTransport`), the
checked-in authorization record is `unqualified`, and every test is mock-only —
`provider_calls: 0`. A live
comparison is a separate, explicitly authorized change (see *Bindings* below).

Files: `tools/gemini_adapter.py` (mapping, gates and a `MockTransport` for dry
runs and tests), `tools/gemini_comparison_authorization.json` (the unqualified
host record), `tools/test_gemini_adapter.py` (38 mock tests, in the regression
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
| `promptFeedback.blockReason` | checked first: a blocked prompt returns no candidates and may not name its model | prompt blocked |
| `modelVersion` | must equal the qualified model | any other id (never a fallback) |
| `candidates` | exactly one, with non-empty text for a `STOP` answer; a part holding only a `thoughtSignature` adds no text | zero or several candidates, a `STOP` answer with no text or only empty text, a part with any other payload, even beside text, or with a signature that is not a string |
| `finishReason` | must be `STOP` for a graded answer | `MAX_TOKENS`, `SAFETY`, `RECITATION`, `OTHER`, missing — the cell is void |
| `usageMetadata` absent | `(None, None)` — usage stays **null**, never zero | — |
| `promptTokenCount`, `candidatesTokenCount` | billable totals; an omitted `candidatesTokenCount` is a zero only when `totalTokenCount` proves it | prompt count missing; candidate count missing with no total; negative or non-integer; a zero candidate count beside generated text (output unknown, prompt kept) |
| `cachedContentTokenCount` | kept **inside** the prompt total (it is already included there) and priced at the full input rate, a conservative upper bound | exceeds the prompt total |
| `thoughtsTokenCount` | **added** to the candidate total: thinking is separate from `candidatesTokenCount` and billed as output | negative or non-integer |
| `totalTokenCount` | must equal `prompt + candidates + thoughts` | any other total |
| `promptTokensDetails`, `cacheTokensDetails`, `candidatesTokensDetails` | per-modality breakdowns: each must hold only `TEXT` entries that add up to its counter | another modality (priced at its own rate), a sum that disagrees, a malformed entry |
| billed output (`candidates + thoughts`) | must fit the declared `maxOutputTokens` | above the ceiling |
| any other usage field (`toolUsePromptTokenCount`, `toolUsePromptTokensDetails`, `serviceTier`, …) | — | unmodeled usage (charge unknown) |

Provider facts behind these rows: `promptTokenCount` "is still the total effective
prompt size" when content is cached, and `totalTokenCount` is the sum of prompt,
tool-use prompt, thoughts and candidates (https://ai.google.dev/api/generate-content,
`UsageMetadata`); output is priced "including thinking tokens" and cached tokens at
a reduced, nonzero rate, and audio input at a higher rate than text, image or video
(https://ai.google.dev/gemini-api/docs/pricing). The dispatcher prices only
`(input, output)` at two rates, so subtracting either subset would bill real tokens
at $0, and a modality other than text would be priced at the wrong rate.
`max_output_tokens` "applies to the combined total of thinking tokens and output
tokens", and a response cut there still bills its thinking
(https://ai.google.dev/gemini-api/docs/thinking), so the ceiling row is a sanity
check on a cap the provider enforces.

The API omits a counter whose value is zero (the proto3 JSON mapping,
https://protobuf.dev/programming-guides/json/). A thinking model that spends its
whole budget therefore answers `MAX_TOKENS` with no `candidatesTokenCount` and no
text part, as in googleapis/python-genai#782 (`prompt_token_count=1674`,
`prompt_tokens_details=[TEXT 1674]`, `thoughts_token_count=2000`,
`total_token_count=3674`); the reported total proves the omitted zero. A usage
block with no total proves nothing, so a missing candidate count there stays
unknown.

Every refusal raised after a response from the qualified model carries the parsed
counts as `err.input_tokens` / `err.output_tokens`, the attributes
`tools/live_dispatcher.py` reads from a failed send. That covers a partial finish
reason (which may carry no text at all), a `STOP` answer with only empty text,
a malformed candidate and output above the ceiling, so the dispatcher records the
spend without grading a truncated or filtered answer as capability. A blocked
prompt carries its counts only when the response names the qualified model and its
usage is known. When the counts are unknown (no `usageMetadata`, a total that
disagrees with its parts, a missing candidate count with no total, a detail list
that disagrees or is not text, an unmodeled field, a different or unnamed model)
both stay `None`, and the dispatcher holds the whole reservation instead of
settling a guess. Text is not generated in zero tokens, so text beside a zero
candidate count (reported or omitted), in any candidate, leaves only the output
unknown, and this holds before every other refusal: the prompt count is carried,
the output is `None`, and the dispatcher keeps the prompt as a cost floor and
stops the pilot for review. A refusal before anything is sent (a
changed authorization record, an unknown profile, a ceiling above the profile's
maximum, an invalid request, an exhausted `MockTransport`) carries a known zero,
`(0, 0)`, so the dispatcher settles it at $0 instead of halting with nothing to
reconcile.

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
  transport is implemented. The dispatcher's pre-send reservation therefore
  blocks rather than pricing a prompt at zero, even if a record names a
  `count_endpoint`.

The record's keys are exact: `schema_version`, `issue`, `status`, `destination`,
`profiles`, `accounting`, `count_endpoint` and `notes` (a list of strings). An
unmodeled key refuses, because a field this adapter does not understand may be
the one that authorizes spend.

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
