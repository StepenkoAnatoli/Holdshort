# Review brief — blocker checklist (canonical-referring, never selecting)

Supplies the review evidence-record structure for `holdshort-review`. Pinned specification source:
plan sections 3, 5-8 at merge `d7c00f96a17c35e6c47c5ba1f7e3a9160c966042`.

A blocker is any of:

| Category | Question the reviewer must answer with evidence |
| --- | --- |
| Safety / privacy / permission | Is there any observed or plausible unauthorized effect, data destination or identity gap? What fact makes it blocking rather than advisory? |
| Authority conflict | Is there any competing active selection authority (tiers/headers/score approvals) alongside the canonical skill? Where is its deactivation documented? |
| Required check | Which required check failed, was skipped, or cannot run (missing runner)? What exact evidence was expected vs observed? |
| Release gate | Which mandatory gate (packaging, validation, review record, privacy, cap, accounting) is unsatisfied? |
| Redistribution / license | Is any copied upstream material present without documented grant? Which source, which license, which permission evidence? |
| Accounting | Are all dispatches/charges accounted once, with units and uncertainty stated? Any release of an uncertain reservation? |

Each record needs:

- ID and short name
- Category (from table above)
- Severity: blocking / nonblocking
- Exact revision reviewed (full commit hash)
- Evidence (file:line, command, or fixture reference)
- Required correction, with a concrete acceptance case
- Disposition: `unresolved` / `corrected and rechecked` / `nonblocking`

## Hard rules for the reviewer

- A disclosure that a defect exists **is not** a waiver: blockers remain blockers until corrected and
  rechecked.
- Numeric scores or averages cannot substitute for a missing blocker record.
- Non-author review status must be verifiable from the record alone; author self-review cannot close
  a blocking gate that requires independence (plan P01/P02).
- Evidence covers what was actually checked. Untested runtime behavior stays untested in the record
  — never claimed as verified.
