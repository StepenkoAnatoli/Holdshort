# Holdshort: agent rules

- **No prompt caching on Claude API calls.** The ratified cold-cache rule
  (`docs/PHASE3_PREREGISTRATION.md`, Cache conditions;
  `docs/PHASE4_LIVE_START_PACKET.md`, prompt-caching lever) forbids warm-prefix
  credit until the owner ratifies a cache-accounting amendment. Do not add
  `cache_control`, a `system` prompt or other request fields to
  `tools/dispatch_adapter.py` without that amendment. Enforced by the adapter's
  payload check and its refusal of nonzero cache usage. When the amendment
  exists, follow `docs/PROMPT_CACHING.md`.
