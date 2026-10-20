# Prompt cards for the owner — paste into a fresh agent session

Two cards, two distinct jobs. Each is self-contained: paste the whole block into a *fresh*
agent instance (new session, scratch clone of this repo, read-only unless the card says
otherwise). Neither card can be executed meaningfully by a session that authored the reviewed
content — that is the independence requirement each card exists to satisfy.

---

## Card 1 — P02 §2 nine-item walkthrough (designated fresh-session)

> Source procedure: [P02_REVIEWER_DESIGNATION.md](P02_REVIEWER_DESIGNATION.md) §2; the record to
> countersign is [P02_REVIEW_RECORD.md](P02_REVIEW_RECORD.md). Paste Card 1 verbatim:

```
You are the designated fresh-session reviewer for a plan-P02 delta review. Work read-only in a
scratch clone of https://github.com/StepenkoAnatoli/Holdshort.git (branch main). BASE=6d20b04,
HEAD_DELTA=2f4b141. Do NOT trust any recorded output; re-derive all nine items below yourself and
write down what you actually observe:

  1. git log --oneline 6d20b04..2f4b141 | wc -l   AND   git diff --name-only 6d20b04..2f4b141 | wc -l
     (record expects 5 commits, 9 files)
  2. git diff --name-only 6d20b04..2f4b141 -- skills/ | wc -l     (record expects 0)
  3. git diff --numstat 6d20b04..2f4b141 -- docs/DEVELOPMENT_PLAN.md
     (record expects a 2/2 typo-only delta: 'recieve' -> 'receive')
  4. Run the decision suite: python tests/holdshort_decisions.py
     (record expects 79/79 assertions + 52/52 fixture IDs, exit 0)
  5. Run the skills validator both ways: python tools/validate_skills.py  AND
     python tools/validate_skills.py --strict        (both exit 0 expected)
  6. Phase-1 smoke: python fixture_checks.py         (exit 0 expected)
  7. Seeds: the preregistration's seed table must match what
     docs/PHASE3_PREREGISTRATION.md actually declares (6/6 rows)
  8. Thresholds §4/§5: confirm the merged thresholds are byte-identical to the record's table
     (no silent amendments; every item still carries its RATIFIED/PENDING label)
  9. Secrets: python tools/check_secrets.py          (expected: clean, 0 hits)

When all nine observations are in hand, countersign docs/P02_REVIEW_RECORD.md §5 by APPENDING a
new signature row (do not modify the existing rows):
  | Independent countersignature (fresh session) | <your session id> | <date> |
  | Attest: nine §2 items re-derived fresh on this clone with observed outputs per the table above. |

Exit rule: if ANY observed value disagrees with the recorded expectation, do NOT countersign —
write a findings block instead (item, observed, expected, your assessment) and stop. A
countersignature under disagreement is worthless; findings close nothing.
```

---

## Card 2 — Strict-P02 countersignature (the independence upgrade)

> Source: [P02_REVIEWER_DESIGNATION.md](P02_REVIEWER_DESIGNATION.md) §1. Paste Card 2 verbatim
> *after* (or combined with) Card 1's walkthrough — this signature upgrades the §5 record's
> R-D1 status from *owner-deviation closure* to a *strictly valid* P02 closure:

```
You are the strictly-independent P02 countersigner for the Holdshort Phase-3 release gate.
Requirements before you sign:
  * You must be a fresh agent session with no authorship history of this repo's plan artefacts.
  * Work read-only in a scratch clone; you need no merge/push authority.
  * First execute the nine-item walkthrough (Card 1 above); every item must match the
    docs/P02_REVIEW_RECORD.md §2 expectations with exit codes captured, not filtered.
  * Read skills/holdshort-review/references/blocked-review.md L32-33 and confirm you
    understand why author self-review could not previously close this gate.
Then:
  * Append your row to docs/P02_REVIEW_RECORD.md §5 BEFORE the owner-deviation row, marked
    'Independent countersignature (strict P02)', naming your session/instance and date, with a
    one-line attestation covering: delta scope verified, skills tree untouched by the delta,
    plan delta typo-only, suites/validator/smoke exits 0 re-observed, thresholds unchanged,
    secrets scan clean — all observed by you, not cited.
  * Your row converts R-D1 to closed-by-independence. State that transition explicitly in the
    attestation. Do NOT claim any additional authority (no spend, no egress, no merge).
If any item mismatches: produce findings, do not sign, stop.
```

---

**Which card when:** Card 1 alone yields a non-author observed walkthrough (useful, keeps the
deviation closure honest). Card 2 *presupposes* Card 1's walkthrough and is the instrument that
upgrades the record. If the reviewer will be an agent you cannot retain afterwards, run Card 2
with Card 1 embedded — it is written to stand alone.
