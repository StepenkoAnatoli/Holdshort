# Export and interpret usage telemetry

Holdshort's usage exporter reads one explicitly supplied Codex session JSONL
file and writes a summary of observed metadata. It makes no provider request.
The summary can help you inspect token counters; it does not calculate a bill,
attribute spending to individual tasks, or establish savings.

Run commands from the repository root with Python 3. To start with entirely
synthetic data:

```bash
python tools/usage_snapshot.py --session tests/fixtures/usage-telemetry/synthetic-session.jsonl --out .local/usage-demo/snapshot.json
```

Exit `0` means the export succeeded. Open `.local/usage-demo/snapshot.json` in a
text editor. `.local/` is ignored by Git. The fixture contains invented model
labels, timestamps and counters; it is not an actual account or session export.

For a session file you are authorized to inspect, replace the `--session` value
with its path. Quote paths that contain spaces:

```bash
python tools/usage_snapshot.py --session "/path/to/your/session.jsonl" --out .local/usage-review/snapshot.json
```

On Windows, that input could be `"C:/path/to/your/session.jsonl"`. The exporter
does not search for other sessions. Without `--out`, it prints the summary to
the terminal. An unreadable or malformed source returns exit `2` without
printing source contents or inferring usage; inspect its format before retrying.

## Read the counters

The synthetic example produces these cumulative values:

```json
{
  "input_tokens": 100,
  "cached_input_tokens": 60,
  "cache_write_input_tokens": null,
  "output_tokens": 20,
  "reasoning_output_tokens": 5,
  "total_tokens": 120
}
```

| Field | Interpretation |
| --- | --- |
| `input_tokens` | Observed input total, including cached input. |
| `cached_input_tokens` | A subset of input. The example's 60 cached tokens are already in its 100 input tokens. |
| `cache_write_input_tokens` | A separately reported counter, if supplied. This exporter does not infer its pricing or add it to a total. |
| `output_tokens` | Observed output total, including reasoning output. |
| `reasoning_output_tokens` | A subset of output. The example's 5 reasoning tokens are already in its 20 output tokens. |
| `total_tokens` | The source's reported total. The exporter preserves it rather than recomputing missing values. |

For this fixture, `100 + 20 = 120`; adding the cached and reasoning subsets again
would double-count them. A missing counter stays `null`. It never becomes zero.
A spec-v2 §10.5 LedgerRecord or §10.3 Outcome whose cash is unknown keeps it `null` the same way and
carries the marker `"cash-basis": "estimate-only"` in its `counters` (`"actual-spend-basis": "estimate-only"`
in its `evidence`); `tools/conform_spec.py` refuses an unmarked `null`.
If the latest token event has no cumulative usage, `cumulative_usage` is `null`
and `usage_status` is `"unknown"`, even if an earlier event had numbers. A partial
object can have `usage_status: "observed"` while individual fields remain `null`.

## Understand scope and provenance

| Export field | What it tells you |
| --- | --- |
| `cumulative_usage` | The latest observed session totals, not counters for one Holdshort task or model. Do not sum successive cumulative snapshots. |
| `last_observed_response_usage` | Usage supplied for the last observed response. It is not bound to a task ID or request ID by this exporter. |
| `latest_model`, `models_observed`, `reasoning_effort` | Labels read from session metadata. They do not independently verify a requested model, immutable revision or actual provider deployment. Multiple model labels do not divide the session totals between models. |
| `captured_at` | When the exporter ran. |
| `usage_observed_at` | The source timestamp of the latest token event, which can be absent. |
| `token_events_observed` | Number of token events read, not number of billable model calls. |
| `context_window_tokens` | A source-reported context-window value, if present. It is not consumed-token usage. |
| `source_id` | An opaque hash derived from the input filename. It is not a content digest or unique session identity; equal filenames produce equal IDs. |
| `provider_cost_usd`, `is_final_bill` | Cost remains `null` and final-bill status is `false`. Token counters alone do not establish charges. |

No session-wide number here proves a model's cost, a routing decision's savings,
or a per-task result. Those claims require separately bound requests, measured
usage, applicable prices and comparable trials. See the
[model policy pilot](MODEL_POLICY_PILOT_2026-10-14.md) for an example that explicitly
records unavailable per-model telemetry.

## What leaves the source file

The exporter selects usage counters, model/effort labels, timestamps and the
metadata fields listed above. It excludes prompts, conversation text, tool
arguments, credentials and account identifiers from other session fields. The
synthetic conversation marker in the fixture does not appear in the output.
Selected metadata is copied from the source and is not a general-purpose
redaction filter. Review an export before sharing it, especially if a source
puts private information in a model label or timestamp field.

Keep actual session files and private exports outside tracked evidence. Publish
only data you have checked and are authorized to share. The repository's
[engineering review](HOLDSHORT_USAGE_REVIEW_2026-10-13.md) explains the limits of
its historical usage snapshot.
