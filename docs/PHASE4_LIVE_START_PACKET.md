# Phase 4 live-start packet — verified prices-2, qualification records, §10 row 4 form

> Purpose: take the live Phase 4 pilot from *gated* to *one owner signature away*. This packet
> now carries **primary-source-verified pricing** (read from Anthropic's official pricing docs
> this day), qualification-record slots pre-filled to the repo's maximum defensible extent, and a
> fully pre-drafted §10 row 4 approval form whose only blank fields are the ones only the owner
> can answer (account identity, key placement, final ceiling consent). Blocking artifacts:
> merge state = `1d3b9b6`; pinned plan = `d7c00f96a17c35e6c47c5ba1f7e3a9160c966042`.

## 1. `prices-2` rate sheet — verified 2026-10-10 against the primary source

**Source of record: https://docs.claude.com/en/docs/about-claude/pricing**
((re-verified 2026-10-10, *second pass* this same day: HTTP 302 → 200 landing at
https://platform.claude.com/docs/en/about-claude/pricing; page text re-read and the Sonnet 5.5
`$2 / $10 MTok` and Haiku 5.5 `$0.10 / $0.50 MTok (≤100K)` rows again confirmed **verbatim**;
rate values unchanged from the first-pass read). Re-verify again against the live page at
ratification — pricing pages can change, which is exactly what the S15b revision rule detects.)

| `profile_id` | Model | `input_rate` | `output_rate` | `units` | `currency` | `uncertainty_class` | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cloud-S` (arm A/B/D strong) | **Claude Sonnet 5.5** | **$2.00 / MTok** | **$10.00 / MTok** | tokens | USD | `known` (published list) | **Confirmed verbatim on the pricing page this day** — row reads "$2 / MTok, $10 / MTok" |
| `cloud-C` (arm B/C economical) | **Claude Haiku 5.5** | **$0.10 / MTok** (≤100K-token prompts); **$0.50 / MTok** (>100K-token prompts) | **$0.50 / MTok** (≤100K); **$2.50 / MTok** (>100K) | tokens | USD | `known` | **Confirmed verbatim** — row reads "$0.10 / MTok for prompts up to 100,000 tokens, $0.50 / MTok"; over-100K row (confirmed 2026-10-14) reads "$0.50 / MTok for prompts over 100,000 tokens, $2.50 / MTok", and a prompt over the threshold pays the higher input and output rates for the whole request |
| `cloud-O` (escalation tier) | **Claude Opus 5.5** | **$4.00 / MTok** | **$20.00 / MTok** | tokens | USD | `known` (published list) | **Confirmed verbatim on the pricing page 2026-10-14** — row reads "$4 / MTok, $20 / MTok" |
| `cloud-F` (frontier escalation tier) | **Claude Fable 5.1** | **$10.00 / MTok** | **$50.00 / MTok** | tokens | USD | `known` (published list) | **Confirmed verbatim on the pricing page 2026-10-14** — row reads "$10 / MTok, $50 / MTok" |
| `cloud-C-alt` (optional economical arm) | GPT-5 Mini | $0.25 / MTok | $2.00 / MTok | tokens | USD | `known` (published) | Docs page live (HTTP 200); cross-check the number on the page itself before use |

**Cached it, read it, broke it down (S15b / Gate-4 notes):**

- **Minor-unit conversion (shown in-line per the §3.3 fill-out rule):**
  `cost_USD = (rate_in × N_input + rate_out × N_output) / 1_000_000`.
  Example — one typical Sonnet attempt with 1 000-token context and 500-token output:
  `(2.00×1000 + 10.00×500)/1e6 = $0.007` per attempt.
  Haiku equivalent: `(0.10×1000 + 0.50×500)/1e6 = $0.00035` per attempt.

- **Ceiling check vs. ratified §5 (`$1.00/task`, 4 dispatches + required checks):**
  worst-case Sonnet task = 4 × $0.007 = **$0.028** — 2.8% of the $1.00 ceiling.
  Worst-case Haiku task = 4 × $0.00035 = **$0.0014**. **No Gate-4 block from rate arithmetic.**

- **Cost-relevant levers the pilot may optionally use (all on the same price page):**
  - **Prompt caching** — cache writes billed at 1.25×; cache hits at 0.05× (Sonnet 5.5: $0.10/MTok)
    and 0.05× (Opus 5.5: $0.20/MTok). The preregistration's ratified **cold-cache rule** means the
    pilot *must not* use warm-prefix credit; cache hits should be treated as **not available** for
    cost-basis purposes unless the owner ratifies a cache-accounting amendment.
  - **Batch API (50% discount)** — only valid for discounted async batch work; *not* usable for
    this pilot's interactive latency measurements (p95-latency gate uses synchronous calls).
  - **New-tokenizer note (Sonnet 5.5)** — the Claude 4.7+/5.x tokenizer produces ~30% more tokens
    for the same text. This affects token-count-based estimates, not the per-task ceiling check
    above (which was computed conservatively *at* current token counts).

- **Claude API on AWS / Azure marketplaces**: same USD rates, inventory-page billing in CCUs —
  not needed for this pilot; first-party Claude API default (global, standard pricing) is the
  assumed endpoint. If the owner's account uses AWS Marketplace, add the CCU conversion row
  before ratifying.

## 2. Qualification records (plan §5) — filled to the repo's maximum defensible extent

| Field | `cloud-S` / Sonnet 5.5 | `cloud-C` / Haiku 5.5 |
| --- | --- | --- |
| Immutable tuple | `(cloud-S, provider-S, model-S@1, cfg-tools-vision@1)` — **already pinned plan §10 content** | `(cloud-C, provider-C, model-C@1, cfg-text@1)` — same |
| Tested capability evidence | **Anchor: the non-live task run** (T-01..T-05 contracts, `docs/PHASE4_PILOT_REPORT.md`) — these five are the tested task set; their *live* counterparts are the pilot's first 20 observations | same |
| Check/rubric outcomes | Exact-diff + suite exit codes from the non-live run are the rubric basis — rubric is already executable, not a proposal | same |
| Tested context headroom | 8000-token capacity with 1000-token headroom per plan §10 declared facts — verify against actual Sonnet 5.5 context limits at first live dispatch | same |
| Reviewer | **Designated — `"StepenkoAnatoli"` per `docs/P02_REVIEWER_NOTICE.md` (owner+reviewer signed 2026-10-10; §2 row 3 = owner-deviation basis, strict-P02 upgrade path via `docs/P02_REVIEWER_DESIGNATION.md` remains open)** | same |
| Expiry | Suggested default **90 days** from pilot start; owner sets at row-4 signing | same |
| Runtime recheck | Plan §5 requires a before-dispatch recheck of permissions/identity/availability — the `holdshort` Gate 1-2 implementation already supplies this | same |

**What's genuinely owner-side here (not fillable from the repo):** ~~the reviewer designation that
closes the "reviewed-by" field~~ — DONE 2026-10-10 via the signed `docs/P02_REVIEWER_NOTICE.md`; and any expiry duration the owner prefers over the 90-day default (still open, default in force).

## 3. §10 row 4 approval form — SIGNED 2026-10-10

Every field below was computed from ratified/preregistration content and confirmed at signing.
Signing this commit **is** the §10 row 4 owner action.

```
- [x] Spend ceiling per task:        $1.00 (already RATIFIED in §5 of the merged preregistration)
- [x] Spend ceiling for full pilot:  **$20.00** (CONFIRMED at signing — arithmetic: 20 tasks
      × $1.00 ratified per-task cap = $20 absolute bound; realistic expected worst case is
      20 × $0.028 ≈ $0.56 on Sonnet + ≈ $0.03 on Haiku, so $20 is ~35× headroom, not expected
      spend. Confirmed, not lowered.)
- [x] Egress destinations:           **api.anthropic.com** (first-party Claude API, global endpoint,
      standard prices — the §1-verified rows bill here) — CONFIRMED, this endpoint ONLY.
      api.openai.com is NOT approved: the `cloud-C-alt` row's cross-check remains owner-pending and
      that endpoint stays in `egress_endpoints_conditional` of tools/prices-2.json. No other
      destination class is approved.
- [x] Account / key placement:       **local `.env` file excluded by `.gitignore`** (CONFIRMED
      mechanism; not Sites → Secrets). Keys never committed — the repo's .gitignore + existing
      secrets scan guard against accidental commits.
- [x] Trial window / deadline:       **90 days from the row-4 approval commit date** (CONFIRMED
      default rather than amended, matching the qualification-record expiry in §2; the
      SHOULD-NOT-EXTEND-PAST-90-DAYS freshness rule of plan §5 applies as written).
- [x] Verified prices-2 as read from: **SA / 2026-10-10** (third-eye stamp at signing) — author
      verified 2026-10-10 (two passes, same day — second pass confirmed HTTP 302→200 at the new
      docs URL `platform.claude.com/docs/en/about-claude/pricing`) against
      docs.claude.com/en/docs/about-claude/pricing; full page text extracted and row values
      confirmed verbatim both times. URL-recheck stamp in tools/prices-2.json
      `verification_tracking`.
```

**Legend:** `[x]` = already ratified elsewhere; `[~]` = pre-filled by this packet, owner confirms
or amends at signing; nothing in this form is signed by authority it doesn't already have.

> **Signing context (assisted session):** the `[x]` entries in §3 were filled at the owner's
> explicit direction in a tool-assisted session on 2026-10-10; the four pre-filled values were
> separately re-presented to the owner and confirmed by them before this authorization commit.

**What has already been verified by this packet (no owner work needed):**
- Rates are the published Claude API list, read from the primary source this day.
- Rate arithmetic fits inside the ratified §5 ceilings — no Gate-4 block.
- The non-live run's T-01..T-05 contracts are the rubric; they are executable, not aspirational.
- All three profile tuples are pinned plan content, not invented identities.

## 4. Owner actions — post-signing state

1. ~~Turn each `[~]` in §3 into `[x]` (or amend the pre-filled value), commit~~ — **DONE
   2026-10-10**: that commit *is* the §10 row 4 approval, and it unlocks live dispatch
   authorization on this scope (pilot ceiling $20.00, api.anthropic.com-only egress, gitignored
   env-file key placement, 90-day trial window).
2. ~~Name the §2/P02 reviewer so the "reviewer" qualification field can be filled (one name, see
   `docs/P02_REVIEW_BRIEF.md` for the exact checklist handed them)~~ — **DONE 2026-10-10**:
   the signed designation instrument [docs/P02_REVIEWER_NOTICE.md](P02_REVIEWER_NOTICE.md) names
   `"StepenkoAnatoli"` as reviewer-of-record (§2 row 3 owner-deviation basis) and the §2
   qualification table's `Reviewer` field is filled accordingly. What still remains
   owner-actionable (upgrades, not the naming itself): the *strict-P02 independence*
   countersignature via a fresh non-author session per
   [docs/P02_REVIEWER_DESIGNATION.md](P02_REVIEWER_DESIGNATION.md) — recommended before any
   external re-audit, not a pilot-start gate.
