# Moonzila advisory UI design note — stored-preview vs generate-path

Status: **draft design note; not ratified, not written code, does not authorize any Phase 6 work**
(plan §13 boundary). Prepared on SmartRouter main `9b4bd687ac6bf24c1f437329b7dacfd60e18424b`;
pinned to [docs/DEVELOPMENT_PLAN.md §13](DEVELOPMENT_PLAN.md) and to the canonical routing skill
[skills/smart-router/SKILL.md](../skills/smart-router/SKILL.md). This note is design-specification
only; no code, no host changes, no consumer changes, no rate/cost claims.

## 1. Scope and non-scope

**What this note covers:** the Phase 6 "First advisory UI" surface — how Moonzila should display a
routing recommendation to its operator, and how *generating* a new recommendation differs from
*displaying a stored one*. It names the informational fields the UI needs, the permission boundary
between display and generate, the accounting separation, and the stale-authority invalidation rule.

**What it does not cover** (and does not implicitly authorize):
- Anything in plan §13's *next* stage: serial execution, privacy-before-prompt-bytes, reviewed
  edits/commands, local qualification/headroom work, manual overrides, Stop/recovery/reservation/
  settlement/recovery; shared reservations/bounded concurrency; engine hosting.
- Repository-internal implementation work; Research-Kit changes (§12); skill-packaging work (§14
  Phase 2 scope; already separately reviewed).
- Actual Moonzila-host roadmap/priority decisions (owner/its approved plan owns those).

## 2. Phase 13 boundary recap

Per plan §13, "First advisory UI" requires:

> requested profile, gate reasons, cost basis/unknowns, privacy destination, actual dispatch
> availability and pinned policy/workspace/conversation revisions. Display stored previews without
> inference; generate only with explicit permission/accounting; stale authority invalidates
> recommendations.

The plan's own separation stems from finding **F5** ("preview versus generation"): *displaying an
already-computed preview can be inference-free*; *generating or revalidating a recommendation may
infer/transmit/spend and must be separately authorized/accounted*. The operational fixtures that
make this concrete are **S13** (stored `route-C@policy-1` display authorized; Generate would
transmit S03's private bytes to a cloud profile without egress approval — display with zero new
calls must be permitted while Generate is blocked **before** egress) and **S24** (no
profile-selection tool, actual current identity unknown → advisory mode only; no claimed switch and
no claimed actual model), reinforced by **V05/V06** (advisory output correctness does not excuse an
unauthorized effect).

## 3. The two distinct paths

### 3.1 Path A — Display a stored preview (inference-free)

**When:** a stored recommendation exists (see 3.3) and authority/price/catalogue/verifier revisions
still match.

**Hardedges:**
- The UI performs **zero new model calls, zero embeddings, zero fetches, zero cache writes**. This
  is not a detail but the definition.
- Per **S13**: stored display with a distinct display/generate event trace.

**UI shape (notional):**

```
SmartRouter preview — stored
Profile:      (local-L, local, model-L@1, cfg-tools@1)          ← from stored record
Route:        direct
Difficulty:   trivial
Reason:       ordered gate-by-gate text from the stored record
Reservations: bound $0.02 (stored)
Calls:        2/6 used;  Deadline: within window  (stored observations)
Pinned revs:  policy=d7c00f9a… workspace/cnv=…
Fetched:      0 new calls, 0 egress   (display-generation event trace differs)
```

The `Fetched:` field is the operator-visible proof-of-no-inference — is a local UI counter, not a
host claim.

### 3.2 Path B — Generate a new recommendation (inference/spend path)

**When:** no stored preview exists, or a stored preview is invalidated by a revision change
(see 3.4), or the operator asks "give me a fresh recommendation".

**Hardedges:**
- Requires explicit user permission at call time (not assumed from prior consent), plus the
  host's own accounting path, before any model call, embedding, fetch, or cache write.
- Must use the canonical skill semantics ([smart-router SKILL.md](../skills/smart-router/SKILL.md))
  and its pinned references — Gate 1 (permissions/privacy/workflow) is checked **before** any
  transmission (S03/S17a/S17b); Gate 4 unknown/absent pricing/bounds account for **auxiliary**
  inference the generating call itself performs (per S06/S07).
- Must produce a *new* distinct UI event, not a recall of Path A's trace.

### 3.3 What a "stored preview" may carry (and what it may not)

A preview record may carry: route recommendation text, profile identity tuple as a read-only
display, difficulty label, gate-by-gate reason, conservative bound as stored ($ figure), used/
remaining call-slot observations, deadline / freshness limits recorded at the time of generation,
and pinned policy/workspace/conversation revision IDs.

A preview record **must not** carry: authorization tokens, model-provider API keys, private
user bytes, per-record secret-bearing receipts, or any inline "can dispatch now" assertion that's
only evaluated fresh at dispatch time (plan §8 receipt rules: no raw prompts, no keys, no
authorization headers or credential URLs; keep opaque pinned references).

### 3.4 Stale-authority invalidation

A stored preview's validity must be tied to **revisions it was bound to** (plan §5/§7 binding):
authority/authorization + privacy, capability/catalogue, verifier contract, price list, and the
workspace/conversation content/policy revisions shown in the preview.

On any of these changing, the preview is **invalidated**: Path A shows it as stale/requires
regeneration, and Path B is required to continue. Revocation always wins (B02c). Fixtures that
drive this: S15a (auth revision flip), S15b (price revision flip), S15c (verifier revision flip)
— plus B02c's "revocation wins over stale cache".

## 4. UI permission & accounting separation (why this isn't just a UI wrinkle)

| Concern | Stored-preview display (Path A) | Generate-path (Path B) |
|---|---|---|
| New model calls / embeddings / fetches / cache writes | **None** (inference-free by definition) | All possible kinds; gated |
| Permission needed | None beyond read the stored record (no new egress) | Explicit user grant + host permission at call time |
| Host accounting | Zero new charge, **no accounting claim** | Full per-call accounting, host-obligated |
| Cache invalidation | Auto-invalidated by revision change (see 3.4) | Runs the skill's fresh-binding gate (S15/S16 fingerprints) |
| Terminal outcome | n/a (no attempt started) | Plan §7 classifier applies, incl. V05/V06 advisory semantics |
| Event trace | Distinct display-generation event | Distinct generation/publication event |

This separation is not only about cost. It preserves the plan's own **F5** premise (displaying a
preview must never substitute for a user-visible authorization) and enforces that a stored
recommendation cannot silently become a "free" dispatch pass (S13 — block Generate before egress
when the stored data is local-only).

## 5. Advisory boundary (plan §13 first stage + S24)

Plan §13's *first* advisory stage is recommendation display only. Moonzila in this stage **does
not** dispatch: no serial execution, no privacy-before-prompt-bytes work, no local
qualification/headroom run, no Stop/recovery/reservation work. Those are separately approved
(§13 stage 2) — not implied by adopting this note.

Where host support for identity/fresh evidence is missing, output is **advisory-only with an
explicit execution blocker** — never a silent downgrade (also per the canonical skill's own
frontmatter and "Boundaries with sibling skills" section; fixture S24).

## 6. Pinned revisions / receipts (what must be carried for audit)

Every stored preview (A) and every generated recommendation (B) should record, in its own
record:

- policy revision (the canonical skill's pinned spec revision and skill-repo commit).
- profile identity **tuple**, not just "the model name" (plan §5 qualification rule).
- task/input content fingerprint, and the fingerprint composition changes between the S15-family
  revisions and content (S16's whitespace-sensitivity).
- authority/privacy revision, capability/catalogue revision, verifier contract revision,
  price-list revision.
- timestamp and an explicit freshness/expiry rule.
- **No** raw prompts, no model-provider keys, no authorization headers, no credential URLs, no
  secret-bearing receipts (plan §8).

These are Moonzila-side metadata commitments; Moonzila's team owns whether they are persisted in
its own key-value store or re-derivable from its own revision ledger.

## 7. Acceptance gates Moonzila must satisfy late (Phase 6 runtime, not this note)

These are restated (plan §13): actual host **no-send** tests (assertively, not by description),
privacy/approval tests, serial cancellation/restart/replay/accounting tests, real client
environment, separately approved scope, and measured benefit. **Written design notes do not
satisfy these runtime gates.** Nothing in this note is a substitute for those tests or any
approved scope.

## 8. Status of this note

- **RATIFIED as structure**: the display-vs-generate separation, no-inference on stored display,
  stale-authority ordering, and prohibition on secret-bearing receipts (all directly the plan's
  own rules: F5/S13/V05-V06/S15a-c/B02c/§5/§8/§13).
- **PENDING**: all concrete Moonzila design choices (concrete field names, exact schema, storage
  backend, UI routing) plus any Phase 6 authorization.
- **BLOCKED**: any runtime host behavior claim until Phase 6 runtime gates run.

Nothing here changes the plan, the canonical skill, its review chain status, or Moonzila's roadmap.
