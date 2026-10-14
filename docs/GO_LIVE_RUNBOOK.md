# Go-live runbook — first live dispatch session (post-row-4)

Owner authorization is in force: [PHASE4_LIVE_START_PACKET.md](PHASE4_LIVE_START_PACKET.md) §3
SIGNED 2026-10-10 — **$1.00/task, $20.00/pilot, 4 attempts + 1 same-profile repair,
api.anthropic.com ONLY, 90-day window**. The real Anthropic adapter is wired
(`tools/dispatch_adapter.py`, via `live_dispatcher.py --live`). This is the exact mechanical
sequence for the first live session. Every step is executable as written, except the two places
only the owner's hands can act (key pasting, the GO decision) — both marked **OWNER**.

---

## 0. Preconditions — verify before anything (≈1 min)

Run in order; each must satisfy before continuing:

```bash
python tools/check_clone_freshness.py                           # exit 0 = this clone IS origin/main
                                                                #  exactly: HEAD at the LIVE tip (never
                                                                #  the local tracking ref), no local-only
                                                                #  commits, clean worktree; exit 1 names
                                                                #  what is off, exit 2 = remote unreachable
python tools/run_regression.py                                  # full gate, exit 0
python tools/check_secrets.py                                   # clean, 0 hits
git config core.hooksPath                                       # prints .githooks (pre-commit
                                                                #  runs the same full gate on every
                                                                #  commit; a failing gate blocks the push)
mkdir -p tools/task_state                                        # per-task state dir (gitignored) for --task-store

python tools/live_dispatcher.py --live \                        # adapter present:
  --profile cloud-C --task-id preflight --request x \           # refusal expected WITHOUT .env
  --work-bound 0.01 --review-bound 0.01 --ledger /tmp/preflight.jsonl; echo "expect exit 2"
```

**Stop-condition**: any unexpected result blocks the session; fix and re-run before step 1.
The expected exit-2 above proves the fail-closed path: no key ⇒ no HTTP call.
Clone-freshness exit 1 (the tree under you is not the pushed tree) or exit 2 (remote
unreachable — provenance unverified) blocks the same way.

## 1. Key placement — `.env`, never committed *(OWNER: key pasting)*

1. `cp .env.example .env`
2. **OWNER**: paste the real Anthropic key into `.env` by hand
   (`ANTHROPIC_API_KEY=sk-ant-…`). The key must never appear in chat, terminals, logs, or any
   tracked file.
3. Verify placement ×3:

```bash
git check-ignore .env                                    # exit 0 = ignored ✓
git ls-files | grep -x '.env'                            # empty = never tracked ✓
python tools/check_secrets.py                            # still clean ✓
```

Replacing or removing a value — including the Windows credential-store cases, where a stored
credential outlives the session that created it — is
[CREDENTIAL_ROTATION_RUNBOOK.md](CREDENTIAL_ROTATION_RUNBOOK.md).

## 2. Dry-run warm-up — no network, proves the pipeline (no OWNER needed)

```bash
python tools/live_dispatcher.py \
  --profile cloud-C --task-id dryrun-1 --request "probe" \
  --work-bound 0.01 --review-bound 0.01 \
  --expected-in-tokens 10000 --expected-out-tokens 1000 \
  --ledger /tmp/dryrun_ledger.jsonl
# expect: {"decision": "dispatched", "cost_usd": 0.0015, ...}, exit 0

python tools/live_dispatcher.py --profile cloud-XYZ --task-id dryrun-2 \
  --request "x" --work-bound 0.01 --review-bound 0.01 --ledger /tmp/dryrun_ledger.jsonl
# expect: {"decision": "unknown-profile", ...} Gate-4 fail-closed, exit 1
```

## 3. Live dispatch — both flags required, one send *(OWNER: the GO decision)*

**OWNER checkpoint**: confirm `.env` holds a real key and you say GO. Nothing sends without
`--live` (wires the adapter) **and** `--confirm-egress` (explicit consent) together.

**Exact pilot-start invocation** (one live send, smallest profile scope, `cloud-C`):

```bash
python tools/live_dispatcher.py \
  --live --confirm-egress \
  --profile cloud-C \
  --task-id live-001 --request "<task prompt from the §3.1 contract>" \
  --work-bound 0.01 --review-bound 0.01 \
  --ledger tools/pilot_ledger.jsonl \
  --task-store tools/task_state
```

Before the send, the dispatcher posts the prompt to api.anthropic.com's free
`/v1/messages/count_tokens` endpoint, adds 5% to the count, and reserves that many input
tokens (or `--expected-in-tokens`, if larger) plus the adapter's `max_tokens` (4096) of output
at the profile's rates. It refuses with `blocked-cost-cap` if the reservation does not fit
what is left of the task's $1.00 (with `--task-store`, earlier sends of the same task count).
If the count request itself fails (rate limit, network, key), the run stops with an error
before anything is sent and writes no ledger line; re-run it. The pilot cap only
sees sends made by the same process, and each CLI run is a new process, so pilot totals come
from `pilot_report` after each send (§4). The count is the API's own estimate, so a send can
still slightly exceed its reservation; it is recorded at actual cost, and the ledger reason
says so.

`--task-store tools/task_state` is REQUIRED in the pilot invocation: it persists the 300 s
whole-task deadline and the attempt/repair counters across restarts (§6 limitation closed
by this flag; `tools/test_task_persistence.py` pins the behavior).

Expected: **exit 0**, ledger line `"decision": "dispatched"` with a **nonzero `cost_usd`**
computed from the adapter's actual usage tokens against the prices-2 rates. Refusal cases
(exit 2, `dispatch-refused`, no HTTP, no ledger line): missing `.env` key; profile with no
approved Anthropic mapping (`cloud-C-alt` is refused — its provider is NOT approved).

The ledger lands at `tools/pilot_ledger.jsonl` (gitignored by design; committed only if the
pilot-close report asks). Keep the output JSON of each send in your session log.

## 4. Ledger verification — after EACH live dispatch

```bash
python tools/pilot_close.py --ledger tools/pilot_ledger.jsonl           # per-task closures
python tools/pilot_close.py --ledger tools/pilot_ledger.jsonl --markdown  # report-ready block
python tools/pilot_report.py --ledger tools/pilot_ledger.jsonl           # accounting status
```

Pass criteria, in order:
- `pilot_close` exit 0, `accounting_status: "intact"`, per-task `Caps OK` column OK;
- `pilot_report` exit 0, spend ≤ **$1.00** per task and ≤ **$20.00** pilot;
- dispatch count ≤ 4 per task, ≤ 1 same-profile repair, 300 s per task.

Fail actions:
- exit 1 (`GAPS_FOUND`) → **stop**; per preregistration §6 drift rule, affected observations are
  excluded and the cause must be understood before restart. Do not edit any ledger line.
- any observed unauthorized effect (egress to a non-approved host, credential exposure,
  privilege escalation) ⇒ **zero-tolerance**: copy the ledger aside unchanged, decision is
  `reject (stop)`, session over.

## 5. Session close — ONE command does it all

- [ ] `python tools/pilot_close.py --ledger tools/pilot_ledger.jsonl --with-sheet \
      --assignments tools/live_fill_assignments.json` — THE single close
      command: per-task closures + pilot totals AND the mechanically-filled live-fill
      sheet in one artifact. **Replaces the separate `live_fill_tally.py --import`
      invocation.** Verified in one run:
      accounting intact, all tasks closed, sheet tally clean (dispatch-refused
      blocks disclosed inline, never silently skipped). Violations exit 1 →
      stop + disclose, never edit ledger lines.
- [ ] `python tools/run_regression.py` — all checks PASS after close
      (incl. `live_fill_sheet_integrity`; generated-skeleton sheets are disclosed,
      emitted by the same close run, and only pass tally when placed).
- [ ] `git status --porcelain` empty (`.env` ignored, ledger ignored).
- [ ] Spend from the embedded `pilot_totals` ≤ $20.00 pilot / ≤ $1.00 task.
      If you decide to commit the ledger as pilot-close evidence for the report, review
      it first — it is gitignored by default and stays that way unless explicitly
      `git add -f`ed by you.

## 6. Known boundaries (honest limitations)

- The adapter's HTTP paths (`_http_count_transport`, then `_http_transport`) are stdlib
  `urllib` and were exercised only via mocked-transport tests — the first real calls ARE the
  moment this runbook reaches step 3. Their correctness is verified by the dispatch's own usage
  figures matching what `pilot_report` recomputes (step 4's intact check).
- Wall-clock + counters across restarts: pass `--task-store tools/task_state` to persist
  per-task attempts/spent/repairs and the task's `started` anchor to JSON (atomic writes), so
  the 300 s deadline applies to the task's WHOLE lifetime, not per dispatcher process.
  Without the flag, behavior is per-process counters as before.
- Clone freshness (`tools/check_clone_freshness.py`) is read-only: it never fetches, so a stale
  local `origin/main` stays stale — the report names it rather than fixing it. Exit 2
  (FAIL-CLOSED) is not a pass: with no reachable remote the pushed-tree question is
  unanswered; `--offline` compares against the last fetch only and says so in its output.
- Cache-credit accounting, `--strict`-non-empty promotion, and consumer-owned phases (5–7) are
  out of scope, unchanged from the live-start packet.
