# Go-live quick reference sheet

One-page card for driving the session, condensed from the full
[GO_LIVE_RUNBOOK.md](GO_LIVE_RUNBOOK.md). **OWNER** marks the two steps only you can do.
If any box fails: **stop, fix, re-run that box** — details and rationale live in the runbook.

Authorization (row-4, SIGNED 2026-10-10): $1.00/task · $20.00/pilot · 4 attempts + 1
same-profile repair · 300 s/task wall-clock (task-store enforced) · api.anthropic.com ONLY.

# To onboard a new machine (one command): bash tools/setup_machine.sh <repo-url>
# — wires the hook, proves enforcement, and ends with the §0–§2 preflight automated.

## 0 · PREFLIGHT (≈1 min, no key needed)

```
□ git rev-parse HEAD == ls-remote origin main        → parity-OK
□ python tools/run_regression.py                     → all checks PASS, exit 0 (11 checks)
□ git config core.hooksPath                          → .githooks
□ python tools/check_secrets.py                      → clean, 0 hits
□ mkdir -p tools/task_state                          → state dir exists
□ python tools/live_dispatcher.py --live … (no .env) → exit 2, "dispatch-refused", no HTTP
```

## 1 · KEY PLACEMENT (OWNER hands)

```
□ cp .env.example .env
□ paste real ANTHROPIC_API_KEY=sk-ant-… into .env BY HAND (never in chat/terminal/log/repo)
□ git check-ignore .env         → ignored (exit 0)
□ git ls-files | grep -x .env   → empty (never tracked)
□ python tools/check_secrets.py → still clean
```

## 2 · DRY-RUN (no network)

```
□ cloud-C dryrun-1   → {"decision":"dispatched","cost_usd":0.0015}, exit 0
□ cloud-XYZ dryrun-2 → {"decision":"unknown-profile"} (Gate-4 fail-closed), exit 1
```

## 3 · LIVE SEND (OWNER: say GO) — one task, cloud-C, one send

```bash
python tools/live_dispatcher.py \
  --live --confirm-egress \
  --profile cloud-C \
  --task-id live-001 --request "<task prompt from the runbook §3.1 contract>" \
  --work-bound 0.01 --review-bound 0.01 \
  --expected-in-tokens <upper bound on the prompt's input tokens> \
  --ledger tools/pilot_ledger.jsonl \
  --task-store tools/task_state
```

```
□ BOTH flags present: --live AND --confirm-egress (separately nothing sends)
□ --expected-in-tokens set: worst-case cost is reserved before the send (blocked-gate4 without it)
□ --task-store always on (deadline/counters survive restarts)
□ exit 0, ledger "dispatched", nonzero cost_usd
```

Refusals (exit 2, no HTTP) are SUCCESS of the guard: missing key, unapproved endpoint,
`cloud-C-alt` (different provider) — all correctly blocked before any call.

## 4 · AFTER EACH DISPATCH

```
□ python tools/pilot_close.py  --ledger tools/pilot_ledger.jsonl → exit 0, "intact", Caps OK
□ python tools/pilot_report.py --ledger tools/pilot_ledger.jsonl → exit 0, spend within caps
□ (periodic) python tools/task_crosscheck.py — state vs ledger, exit 0
□ limits: ≤ 4 attempts/task · ≤ 1 same-profile repair · 300 s/task
```

`GAPS_FOUND` (exit 1) → **STOP**; excluded observations per preregistration §6; never edit a
ledger line. Zero-tolerance: unauthorized egress / credential exposure / privilege escalation ⇒
freeze the ledger (copy, never edit), reject (stop) — spend and quality are irrelevant.

## 5 · SESSION CLOSE — one command

```
□ ledger honest: blocks + dispatches both recorded, zero manual edits
□ python tools/pilot_close.py --ledger tools/pilot_ledger.jsonl --with-sheet \
      --assignments tools/live_fill_assignments.json      → THE single close command:
      closures + totals + mechanically-filled live-fill sheet in one artifact
□ its exit 0: accounting intact, all tasks closed, sheet tally clean
      (violations exit 1 → §8/§6 drift rule: stop, disclose, never edit lines)
      note: a skeleton sheet is generated + filled in the same run if absent;
      inspect the `live_fill_sheet` block for per-cell coverage and any
      `ledger_lines_unplaced` findings
□ run_regression.py all PASS post-close (incl. live_fill_sheet_integrity)
□ git status --porcelain       → empty (.env + ledger gitignored)
□ spend ≤ $1.00/task, ≤ $20.00/pilot   (confirm from the embedded pilot_totals)
```
Ledger commit is owner-only, via explicit `git add -f` after review (it stays gitignored
otherwise).
