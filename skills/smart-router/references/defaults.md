# Default Behavior in SmartRouter

**Status:** explanatory companion — non-normative. The normative contract is
[gates.md](gates.md) (fixture-pinned) and [spec-v2.md](spec-v2.md); where this narrative and
the normative files ever disagree, **the normative files win**. One ambiguity is noted
without resolution: this document lists `speculative` after `recommend-escalation` in the
preference order, while the conceptual ladder in
[gate5-economics.md](gate5-economics.md) places it before; the normative files do not fix
that precedence, and both documents agree `speculative` is an opt-in conditional mode, never
a ranked default.

By default, SmartRouter is conservative and prefers the simplest safe option.

## Default Decision Order

When multiple candidates pass Gates 1–4, SmartRouter applies this preference:

1. **`direct`** (highest preference)
   If the current or chosen profile is capable, verifiable, and affordable, SmartRouter will
   normally choose `direct`. This avoids the overhead of creating a new worker, writing a
   brief, and managing isolation.

2. **`delegate`**
   Only chosen when doing the work directly is unsuitable *and* an isolated worker shows a
   clear all-overhead benefit.

3. **`recommend-escalation`**
   Used when none of the currently available profiles is a good fit, but a stronger eligible
   profile exists.

4. **`blocked`**
   Used when no candidate survives all five gates.

5. **`speculative`**
   **Not** a default. It is only used when uncertainty is high **and** the Host has
   explicitly opted in.

## Other Default Settings

| Feature              | Default Value              | Notes |
|----------------------|----------------------------|-------|
| Isolation            | `worktree+branch` for most non-trivial work | Can be lower only for truly trivial tasks |
| HumanGate            | `none`                     | Raised automatically when risk or uncertainty is high |
| NestedAllowed        | `no`                       | Must be explicitly enabled |
| MaxNestingDepth      | `0` or `1`                 | 2 only if Host policy allows |
| Speculative mode     | Off                        | Requires explicit Host opt-in |
| Ownership            | `worker` on any `delegate` | Sticky — feedback returns to the same owner |

## Summary

**Default behavior = prefer `direct`, stay simple, stay safe.**

SmartRouter only moves to more complex options (`delegate`, nested workers, speculative
parallel, higher HumanGate, stronger isolation) when the simpler path is clearly insufficient
or too risky.
