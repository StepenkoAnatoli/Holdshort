---
authority: decision
status: live
---

# Prompt caching: status and owner checklist

Recorded 2026-11-15.

## Status: blocked by the cold-cache rule

The repo's only Messages API call is `_http_transport` in
`tools/dispatch_adapter.py`. It sends one plain user string with no system
prompt, no tools, no history and `stream: false`.

Caching is not allowed there:

- `docs/PHASE3_PREREGISTRATION.md` (Repetitions, Cache conditions; RATIFIED)
  requires a cold cache on every trial, with no warm-prefix credit.
- `docs/PHASE4_LIVE_START_PACKET.md` treats cache hits as not available
  "unless the owner ratifies a cache-accounting amendment".
- The adapter enforces this. `_BillingContext.payload` rejects any extra request
  field, and `_http_transport` refuses nonzero `cache_creation_input_tokens`,
  `cache_read_input_tokens` or `cache_creation` usage.
- `tools/prices-2.json` has no cache rates, and the billing qualification is
  bound to that file's hash.
- Each task runs twice. With caching on, the second run would read the first
  run's cache and break the cold-cache condition.

Re-check: `grep -n "cached-token" tools/dispatch_adapter.py`

## Owner checklist (apply only after the amendment is ratified)

The owner asked on 2026-11-15 that caching work follow these steps:

1. Read the current docs first, not memory:
   `https://platform.claude.com/docs/en/build-with-claude/prompt-caching`.
2. Show the current prompt structure before changing anything.
3. Put static content first and dynamic content last: tools, then system prompt
   and reference documents, then history, then the newest user message. Nothing
   dynamic (timestamps, IDs, user values) goes before a breakpoint.
4. Put breakpoints at the end of the static block and on the last history
   message, within the maximum the docs allow.
5. Keep the cached prefix byte-identical: same ordering, whitespace and JSON
   key order.
6. Make it work with streaming if the call streams.
7. Log `cache_creation_input_tokens`, `cache_read_input_tokens`, `input_tokens`
   and a computed hit rate for each request.
8. Handle prompts below the minimum length, expiry after the TTL, and history
   trimming. Pick a trimming strategy that does not invalidate the cache every
   turn.
9. Add a test that sends the same prefix twice and checks that the second call
   reads from the cache.
10. Keep changes minimal and in the existing style. End with a short summary.

For Holdshort, also: add cache write and read rates to `tools/prices-2.json`,
re-qualify billing (the price hash changes), and allow cache usage fields in
`_http_transport`.

## Doc facts read 2026-11-15 (re-check before relying on them)

- Syntax: `cache_control: {"type": "ephemeral"}`, optional `"ttl": "1h"`. The
  default lifetime is 5 minutes. A top-level `cache_control` gives automatic
  caching (not on Bedrock `bedrock-runtime`).
- At most 4 breakpoints. The automatic breakpoint uses one. The lookback window
  is 20 blocks.
- Minimum cacheable prefix: 512 tokens for Opus 5.5, Sonnet 5.5, Haiku 5.5 and
  Fable 5.1 (every model this repo maps). Shorter prompts are silently not
  cached.
- Prices: 5-minute writes cost 1.25× the input rate, 1-hour writes 2×. Reads
  cost 0.05× on Opus 5.5 and Sonnet 5.5, 0.025× on Fable 5.1 and 0.1× on other
  models.
- Usage: total input = `cache_read_input_tokens` +
  `cache_creation_input_tokens` + `input_tokens`. `cache_creation` splits writes
  into `ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`.
