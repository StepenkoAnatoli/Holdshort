# Billing qualification capture runbook

G2 (strict live billable-cost upper bound) stays open until a host captures and
reviews real provider evidence. This runbook describes the minimum process.

## Steps

1. Capture provider artifacts (local files only, never commit secrets):
   - Provider limit evidence (rate limits / token ceilings) -> `provider-limit.txt`
   - Rate evidence (pricing) -> `rate.txt`
   - Request-scope evidence (exact request shape) -> `request-scope.txt`
2. Compute sha256 for each artifact: `sha256sum <file>`.
3. Assemble a qualification record matching `tools/live_billing_qualification.json`
   schema (schema_version 1, qualified true, matching price_revision/price_sha256,
   verified_at < now < expires_at, profiles with input_token_ceiling and
   max_output_tokens, bound_kind "provider-enforced-token-ceiling", evidence_refs
   for each profile).
4. Host review: a human must set `qualified: true` only after reviewing the
   captured evidence. Artifact hashes prove integrity, not truth.
5. Validate: `python tools/qualify_billing.py validate <record> --prices <prices>`.
6. Keep `final_bill_guaranteed: false` always. Scope is modeled request tokens
   only; cached tokens must be zero.

## Synthetic records

For CI/tests only: `python tools/qualify_billing.py synthetic <outdir>`.
Synthetic records are never provider evidence.
