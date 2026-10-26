# Run-level usage and latency attribution

Status: **first slice** of issue #61 (`tools/usage_attribution.py`, 34 synthetic
tests in the regression gate). The record schema, validation, export whitelist,
per-model aggregation and cost function exist and are pinned; the dispatcher
does not emit these records yet, so no issue claim rests on a live run.

## Why a record per task

The native Codex comparison reported requested settings and final answers, but
not per-agent tokens, an immutable deployment revision or precise completion
times. A parent-session aggregate cannot be allocated to individual models, so
every observation here is bound to one task:

| Field | Meaning | Rule |
| --- | --- | --- |
| `run_id`, `task_id` | the run and the unit of work | 1-200 visible ASCII characters, no spaces (any other character refuses: controls, zero-width, bidi, combining marks, variation selectors and blank-looking letters or symbols can hide text in what looks like one token) |
| `policy_sha256` | the policy/packet digest in force | lowercase sha256 |
| `requested_model` / `observed_model` | what was asked for / what the host reported | same rule as the ids; both recorded; `model_match` is derived, never guessed |
| `settings` | `effort`, `reasoning`, `max_output_tokens` | only these keys; each value is null, a boolean, a finite number within 2**53 or a short lowercase token (`[a-z0-9][a-z0-9._-]{0,31}`, e.g. `high`); `max_output_tokens` is a positive integer; anything else refuses |
| `started_at`, `completed_at` | UTC instants; `observation()` accepts a trailing `Z`, records hold the `+00:00` form | timezone required; completion before start, or an instant with no UTC form, refuses |
| `latency_ms` | derived from the instants | null for an interrupted run, never 0 |
| `clock` | `utc` or `utc+monotonic` | names what produced the instants |
| `boundary` | `transport`, `provider-request`, `harness-cell` | names the span the interval covers |
| `interrupted` | the run did not complete | a completion time with this set refuses |
| `counters` | `input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_output_tokens` | integers from 0 to 2**53 or **null** |

`clock` and `boundary` exist so two hosts cannot compare different spans by
accident: a wall-clock interval around a harness cell is not the same
measurement as a monotonic interval around one transport call.

## Nulls and subsets

- A counter the host does not expose is `null`. Nothing is zero-filled, and an
  aggregate over any unknown value reports `null` plus `*_unknown` counts.
- `cached_input_tokens <= input_tokens` and
  `reasoning_output_tokens <= output_tokens`. They are recorded as subsets and
  are never added to their totals a second time.

## Export

`export()` is a whitelist, not a redaction pass: a record carrying any field
outside the schema (a prompt, an answer, a key) refuses instead of being
scrubbed. Only selected metadata leaves the host.

The whitelist covers values, not only key names. Records the CLI reads from
JSONL were never built by `observation()`, so `export()` rebuilds each one
through `observation()` from its own fields and refuses the whole export when
the result differs in any field, compared as JSON so `1`, `1.0` and `true` stay
distinct. That refuses free text inside `settings`, an invalid digest, clock or
boundary, a non-boolean `interrupted`, a subset larger than its total, a
`latency_ms` or `model_match` that disagrees with its inputs, and a
non-canonical instant (export expects the UTC `+00:00` form `observation()`
writes). The CLI also refuses a JSON object that repeats a key (`json.loads`
keeps only the last copy, so an earlier one would stay in the file unchecked)
and a line nested too deeply to parse.

The CLI reads only canonical lines: each line must be exactly the JSON
`to_jsonl()` writes for its record (sorted keys, the default `", "` and `": "`
separators, non-ASCII escaped) and end in a newline. A file whose every line
ends in CRLF, as a checkout that converts line endings writes it, reads as its
LF form; a lone CR or a mix of endings refuses.
The checks and the digest cover the parsed records, so without this any text a
parse discards would stay in the file unchecked behind a clean digest: float
digits past the 17 a double keeps (a `1.5` followed by 100,000 digits parsed as
`1.5`), padding, escapes, key order, blank lines and a line ending chosen per
line. With it, the file holds nothing the checks do not see beyond that one
whole-file conversion. `python tools/usage_attribution.py records.jsonl`
exits 2 on any of these. Refusals name schema fields and count unknown keys,
never echoing a value or an unknown key name. `estimate_cost` re-checks the
counters it prices the same way and bounds its rates, so a cost is always a
finite number or a refusal.

Every number in a record is bounded by 2**53, the largest integer JSON readers
keep exact, so a field cannot carry kilobytes of arbitrary bytes as digits. The
per-model totals the CLI prints are sums of those numbers and can exceed 2**53.

What the rules cannot see: an identifier is a free token, so a credential
shaped like an id (visible ASCII, no spaces, at most 200 characters) would still pass. The
secret scan (`tools/check_secrets.py`) on tracked evidence is the layer for
that.

## Dollars

`estimate_cost(record, rates, price_revision=...)` always returns the price
revision, the currency, the unit and the billing assumptions it applied. It
returns `cost_usd: null` when the counters it needs are unknown. Cached input is
billed at the cached-input rate and not again as uncached input; reasoning is
billed at the reasoning rate when the sheet prices it separately, otherwise as
output.

An unknown subset is never split by guess: if the cached-input count is null and
the sheet prices cached input separately, or the reasoning count is null and the
sheet prices reasoning separately, the cost is `null` with that reason. When the
sheet has no separate rate, the assumption says so explicitly (all input billed
at the input rate; any reasoning billed as output), so the figure carries the
approximation instead of hiding it. An account-wide usage percentage is not
accepted as a per-run measurement.

## What remains for #61

1. **Emit from the dispatcher.** `tools/live_dispatcher.py` knows the send
   boundary (`transport_started_at`/`transport_finished_at` in its ledger) and
   the profile, but not the model the adapter resolved; the adapter's
   `dispatch_fn` must expose it so `observed_model` is not inferred.
2. **Store per run.** An append-only JSONL next to the pilot ledger, written
   with `to_jsonl()`, with the export digest, so a rerun cannot silently replace
   a record.
3. **Wire into the report.** `tools/pilot_report.py` and the calibration
   `observations.json` usage block should read the attributed records instead of
   the parent-session aggregate.
4. **Price binding.** Point `estimate_cost` at a frozen price sheet revision
   (the pilot's `prices-2.json` shape) and record that revision per run.
