# Gate 4 — Affordability (with focus on Verification Costs)

**Status:** explanatory companion to Gate 4 in [gates.md](gates.md) — non-normative. The
normative contract is [gates.md](gates.md) (fixture-pinned) and [spec-v2.md](spec-v2.md);
where this narrative and the normative files ever disagree, **the normative files win**.

Gate 4 is the budget gate. Its central rule is:

> The system must be able to afford **both** the work **and** the verification required to
> prove that work is correct.

## Why Verification Costs Belong in Gate 4

Gate 3 only asks:
"Does a valid acceptance contract exist and can the checks be run?"

Gate 4 asks the harder economic question:
"Do we still have enough money and call budget left to pay for the work **plus** those checks?"

This prevents a common failure mode where a system approves work because it looks cheap, only
to discover later that running the necessary tests or reviews pushes it over budget.

## What Gate 4 Calculates

Gate 4 builds a **conservative all-in bound** that includes:

1. **Direct work cost**
   Tokens / API calls needed to produce the artifact.

2. **Required verification cost**
   - Running the acceptance checks defined in Gate 3
   - Any mandatory review or secondary model call
   - Re-runs that are reasonably expected

3. **Overhead**
   Brief construction, context priming, possible one corrective attempt, etc.

Only after this full bound is calculated does Gate 4 compare it against the remaining
allowance.

## Key Rules for Verification Costs

| Rule | Meaning |
|------|---------|
| Verification is mandatory | You cannot ignore the cost of checks just because they are "only tests". |
| Conservative estimate | Use upper-bound pricing, not optimistic averages. |
| Equality is allowed | If the bound exactly equals the remaining budget, it still passes. |
| Unknown cost = block | If the price of verification is unknown or unbounded, Gate 4 fails under any strict cap. |
| Deadline is strict | Current time must be **before** the deadline (equality expires). |

## Practical Example

**Situation:**
- Remaining budget: $0.40
- Estimated cost of implementation: $0.22
- Cost of required test suite + review: $0.25

**Gate 4 calculation:**
$0.22 + $0.25 = $0.47 → exceeds $0.40 → **candidate rejected**

Even though the model is capable (Gate 2) and an acceptance contract exists (Gate 3), the
candidate is still blocked because the full cost (work + proof) does not fit.

## Relationship to Other Gates

- **Gate 3** ensures verification is *possible*.
- **Gate 4** ensures verification is *affordable*.
- Only candidates that survive both gates reach the final economic comparison in Gate 5.

This separation is deliberate: correctness requirements are established first, then the system
checks whether it can actually pay for them.

**Summary**
Gate 4 treats verification as a first-class cost, not an optional extra. A route is only
considered affordable when the system can pay for producing the work **and** proving that the
work is correct.
