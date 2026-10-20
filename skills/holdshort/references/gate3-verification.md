# Gate 3 — Verification (Detailed Explanation)

**Status:** explanatory companion to Gate 3 in [gates.md](gates.md) — non-normative. The
normative contract is [gates.md](gates.md) (fixture-pinned) and [spec-v2.md](spec-v2.md);
where this narrative and the normative files ever disagree, **the normative files win**.

Gate 3 is the correctness gate. Its job is to ensure that **any work we decide to run can
actually be proven right or wrong** using objective evidence.

## Core Rule

> The acceptance contract must be defined **before** work starts, and the required checks must
> be available and affordable.

If this condition is not met, the candidate is rejected at Gate 3.

## What Gate 3 Checks

1. **Acceptance Contract Exists**
   - There must be a clear, predefined definition of success.
   - This usually consists of concrete commands or checks (e.g. `pytest`, `npm test`, specific
     assertions, linting, type checking, etc.).
   - Vague goals such as "make it better" or "it should work" are not acceptable.

2. **Checks Are Available**
   - The tools or runners needed to execute those checks must actually exist and be reachable
     in the environment.
   - If a required test runner, browser, or verification service is missing → the candidate
     fails Gate 3.

3. **Checks Are Affordable**
   - Running the verification must fit inside the remaining budget (this is later confirmed
     more strictly in Gate 4, but Gate 3 already rejects obviously impossible verification).

4. **Timing Matters**
   - The contract must be set **before** any implementation begins.
   - Defining success criteria after the model has already produced output is not allowed (it
     invites post-hoc rationalization).

## Possible Outcomes at Gate 3

| Situation | Result | Meaning |
|---------|--------|---------|
| Acceptance contract missing or vague | **Blocked** | Cannot start work |
| Required verification tool/runner is unavailable | **Blocked** | Cannot start work |
| Work starts, but later evidence is missing or ambiguous | **Unverified** | Result cannot be trusted |
| Checks run and fail | **Failed** | Work is incorrect |
| Checks run and pass with observed evidence | **Accepted** (later) | Work meets the contract |

## Why This Gate Exists

Many systems let models claim "tests passed" without any real evidence. Gate 3 prevents that
class of failure.

It forces the system to answer three questions **before** spending tokens or creating side
effects:

1. How will we know this is correct?
2. Can we actually run those checks?
3. Are we willing to pay for those checks?

If any answer is "no" or "unknown", the candidate is rejected.

## Relationship to Other Gates

- **Gate 1 & 2** ask: "Are we allowed to do this?" and "Can the model do this?"
- **Gate 3** asks: "Can we *prove* it was done correctly?"
- **Gate 4** then asks: "Can we afford both the work *and* the proof?"

Gate 3 sits in the middle because correctness is more important than cost, but it only becomes
relevant after permission and capability have been established.

## Practical Example

**Task:** "Fix the failing authentication tests."

- Good acceptance contract:
  `pytest tests/auth/ -q` must exit with code 0 and produce no failures.

- Gate 3 passes only if:
  - The test command is clearly defined, **and**
  - `pytest` (or the required runner) is available in the environment.

- If the environment has no test runner → Gate 3 fails → candidate is blocked, even if the
  model is otherwise perfect and cheap.

**In short:**
Gate 3 guarantees that every piece of work Holdshort approves has a predefined, executable,
and observable definition of success. Without that, the system refuses to proceed.
