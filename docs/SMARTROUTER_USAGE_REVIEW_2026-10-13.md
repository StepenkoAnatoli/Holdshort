# SmartRouter use, review and autonomy record — 2026-10-13

This is an observed engineering record, not an economic promotion or a live-provider
qualification. The user requested: push the local work; review gaps; use SmartRouter
while working and record findings, GPT usage, bugs and future risks; run without HITL
unless explicitly requested. No separately billed provider pilot was dispatched.

## Revisions and scope

- Original local work was committed and pushed as `d9645140767684f6db629c953b8937fb656f086b`
  on `codex/local-redaction-watchdog`. All 25 steps of its commit gate passed.
- The autonomy implementation starts from GitHub main
  `2e58899d83b59bf14300a91e773405b70459b011`, in a separate worktree and branch.
- The original snapshot and current main have different watchdog APIs: a structured
  state evaluator versus an executable command supervisor. Findings below identify
  their scope rather than assuming the snapshots are interchangeable.
- The v3.0 user-directed policy supersedes risk-inferred HITL defaults. It changes
  behavior intentionally; the five eligibility gates and object enums remain intact.

## SmartRouter applied to the current host

The canonical skill was read and applied to automatic selection/dispatch of an
additional GPT profile. The existing user-directed Codex session remains the host
of this engineering work; SmartRouter did not switch its model or dispatch a new
provider call. Local commands and read-only tools are observed host actions, not
evidence that an unregistered model profile passed the routing gates.

```
Difficulty:        high-or-ambiguous
Route:             blocked
Profile:           none — blocked
Isolation:         worktree+branch
IsolationReason:   policy/tool changes require a separate checkout and verification
Owner:             none
HumanGate:         none
NestedAllowed:     no
MaxNestingDepth:   0
Reservations:      unknown/blocked for additional automatic model dispatch
Calls:             additional router-dispatched provider calls 0 / approved limit unknown
Deadline:          no additional-dispatch deadline supplied
Uncertainty:       immutable model revision, qualified host-profile fingerprint, tool-config revision, conservative allowance mapping, final provider billing
Advisory: recommendation only — no dispatch performed or claimed
```

| Ordered gate | Observed result for additional automatic GPT dispatch |
| --- | --- |
| 1 identity/permissions | First blocker: the runtime label is visible, but a complete immutable dispatch identity and binding are not supplied by this host integration. User authorization covers this engineering task, not an arbitrary new paid-provider trial. |
| 2 capability | Not used to resurrect the rejection. Fresh profile qualification/fingerprint and tested context headroom are missing. Available tools and successful commands establish only the specific checks observed. |
| 3 verification | Readiness evidence: existing regression gate and targeted synthetic reproducers are available. Acceptance for autonomy includes no inferred human menu, explicit opt-in retained, no command after terminal repair exhaustion, and redaction before writes. |
| 4 affordability | No automatic reservation claimed. Subscription usage percentages and best-effort tokens do not provide a conservative per-dispatch cash/call reservation contract. |
| 5 economics | No ranking or savings claim: the eligible set for this automatic-dispatch audit is empty. |

This result is itself a product gap: a compliant host needs identity/catalog,
qualification, accounting and reservation adapters. Changing the running chat's
model label alone would not supply them. Manual continuation of this already
authorized session is not presented as router-qualified automatic dispatch.

## Observed GPT usage

[Usage snapshot](evidence/2026-10-13/usage-snapshot.json) records the exact chat's
local token-count metadata. `tools/usage_snapshot.py` takes one explicitly supplied
rollout and exports only selected metadata; it does not copy prompts, tool arguments,
credentials, account IDs or conversation text. Its source identifier is hashed.

- Observed runtime model label: `gpt-6.1-sol`; reasoning effort: `high`.
- Model label is observed metadata, not a qualification or immutable provider snapshot.
- Token counts are cumulative session observations. Cached input overlaps input;
  reasoning output overlaps output. Do not add either subset twice.
- Dollar cost remains `null`. Missing usage remains `null`, never zero. The snapshot
  is explicitly timestamped and is not a final bill or a per-task model comparison.
- The Codex account-limit read during this work showed 13% consumed in the 300-minute
  window and 22% in the 10,080-minute window. These are account-wide capacity signals,
  not this task's spend; window resets make naive before/after subtraction invalid.
- Large repeated histories make cumulative input much larger than unique source text.
  The initial broad workspace file search and verbose source dumps added avoidable
  context. Future runs should scope searches to the intended repo and emit selected
  findings rather than complete files repeatedly.

Official interpretation: [OpenAI observability and usage](https://developers.openai.com/api/docs/guides/agents-api/observability)
describes usage as best effort and potentially incomplete, with missing values distinct
from zero and recorded counts distinct from a final bill. This record makes no
subscription-token-to-dollar conversion and no router savings claim.

## Reproduced findings

| ID | Priority/scope | Evidence and implication | Disposition |
| --- | --- | --- | --- |
| F01 | P1, existing dispatcher on both bases | Mock transport with an honest $1 bound: first call reaches the $1 task cap; a second call is still sent, then returns `blocked-cost-cap` with cost $0. Two physical sends and modeled $2 charges become one recorded attempt and $1. Caps must reserve remaining all-in allowance before send, and every physical dispatch must be accounted even on overrun/error. | Fixed in the October 14 follow-up: durable work/review reservations and protected verification call slots precede transport. Failed sends retain attempts and known or uncertain usage; overruns are recorded and stop the pilot. See [dispatch accounting](DISPATCH_ACCOUNTING.md) and `tools/test_dispatch_budget.py`. Input-count estimates and final billing remain limitations. No live calls made. |
| F02 | P1, existing pilot accounting | Two dispatcher instances sharing the same task store and ledger each accept a distinct $1 task under a $1 pilot cap. Each instance begins with `pilot_spent = 0`. | Fixed in the October 14 follow-up: a shared SQLite authority coordinates local instances, persists reservations across restarts, and retains uncertainty after crashes. A two-process send-boundary test admits only one $0.75 send under a $1 pilot cap. Older ledgers without an authority require reconciliation. |
| F03 | P1, existing task persistence | Save attempts=4/spend=1/repairs=1, corrupt that task file, then resume. Counters become 0/0/0. The comment claims ledger re-derivation, but this load path does not perform it. | Fixed during remaining-branch integration: corrupt/unreadable/invalid state blocks before dispatch, preserves the file and reports the unknown attempt counter as null. Authoritative recovery remains future work. |
| F04 | P1, original snapshot byte redactor | UTF-16 LE and BE synthetic credentials produce zero redaction findings and survive decoded output. The repo scanner already understands those encodings. | Open in original snapshot; autonomy code uses the current text redactor for decoded supervisor output. |
| F05 | P1, original snapshot watchdog | Set `repair_allowance=2` after one distinct failed repair: evaluator authorizes another repair, overriding R01/R02/R03. Current main's CLI also permitted arbitrary allowances. | Fixed in autonomy supervisor: allowance is 0 or 1, pure policy clamps at one, and terminal failure blocks later launches. |
| F06 | P1, original structured-state watchdog | Missing budget returns `repair`; NaN clock returns `repair`; attempt `[{}]` returns `continue`. Incomplete state is interpreted as permission to proceed. | Open for the original API; current command supervisor rejects nonfinite timeout. Full host counter/identity validation still needs work. |
| F07 | P1, current main HITL behavior | A decision with HumanGate none could still emit needs-human and Approve/Guide/Take over/Abort on routine failures. Class lookup defaulted to review-before-merge even for unknown classes. | Fixed: blocked with no menu by default; HITL and published human tables require explicit request. |
| F08 | P1, current main supervisor writers | Agent output was persisted raw in state/history and escalation packages even though a pre-write text redactor existed. | Fixed: redact decoded output before truncation, redact state/package objects, and sanitize emitted messages. Synthetic writer test passes. |
| F09 | P2, existing Windows test harness | The full gate's message-schema test opened a SQLite reader without closing it. Temporary-directory cleanup then raised WinError 32 on the still-open database. | Fixed with explicit reader closure; all original redaction and raw-file assertions retained. |
| F10 | P2, existing credential test harness | New plaintext-directory tests invoked the CLI with synthetic HOME/APPDATA but no store-listing fixture. On Windows they read the real OS store and judged those entries against the deliberately empty fixture config; the missing-directory test failed with unrelated orphan/stale findings. | Fixed: the test helper supplies an explicit empty listing unless the test supplies its own. Production checks still read the real store. |
| F11 | P2, existing host dry-run and provenance | Git porcelain reports Windows paths using forward slashes; raw backslash comparisons reported existing worktrees absent and the cleanup proof could miss survivors. The provenance check had the same false rejection. | Fixed: parse records and normalize paths for presence/cleanup. Provenance also binds the claimed path to its exact branch in NUL-delimited porcelain; a wrong-branch test preserves refusal. Existing lifecycle tests retain all five proofs. |

## Errors encountered and resolved

- Windows ACL probe failed because inherited PSModulePath resolved a security module
  from another PowerShell runtime. Setting the module path for the checking process
  to Windows PowerShell's own modules made the unchanged ACL test pass. No ACLs or
  system-wide settings were changed.
- The app-store scanner found 38 copies of five untriaged synthetic fixture values.
  Each digest was matched against an independently reconstructed fixture or exact
  prefix, with redacted historical context confirming smoke-test origin. Only those
  five exact hashes were added to the baseline; stores and credential values were
  not changed or emitted. Other unknown hashes still refuse commits.
- Initial Git push of the old-base snapshot was refused by OAuth workflow-scope
  restrictions. Creating the remote branch at its existing base commit through the
  connected GitHub API, then pushing only the local non-workflow delta, succeeded.
  No token scopes, workflow contents, or main protection were weakened.
- An intermediate safe-print refactor produced a NameError. The targeted supervisor
  suite caught it; the call sites were corrected and the suite passed before commit.
- The full autonomy gate exposed an unclosed SQLite reader in the existing message
  schema test. Explicit connection closure fixes Windows cleanup without bypassing
  the gate or weakening its secret-redaction assertions.
- The credential test harness accidentally read the real OS store while using fake
  host configuration. An explicit fixture listing restores the test's stated
  isolation; it does not suppress findings in the production hygiene check.
- Under slow Windows startup, two supervisor tests exceeded the harness's outer
  30-second process wait. That outer wait is now 60 seconds; supervised command
  deadlines and policy assertions are unchanged. The watcher change test also
  planted its fixture before startup completed. It now waits for an observed clean
  startup scan and still requires a change-triggered alert, never a startup alert.

## Future risks and missing evidence

1. No live GPT A/B/C/D economic comparison or qualification was run. Model rankings,
   latency/cost-per-verified-success, cache benefits and cross-provider fallback must
   be measured under a frozen protocol rather than inferred from this session.
2. A process timeout does not prove descendant process-tree cleanup. A killed child
   may leave grandchildren running; worker environment ports, databases and ignored
   dependencies also remain outside worktree checkout isolation.
3. Shared reservations and append-only ledgers need cross-process coordination.
   Atomic file replacement alone does not prevent two writers spending the same
   allowance or losing registry/state updates.
4. The old structured watchdog trusts a supplied `now`; repeated stale snapshots can
   keep the same result. A host must supply current time and consume repair grants
   atomically. The newer command supervisor also has per-command timing rather than
   a fully persisted original-task wall-clock reservation.
5. Higher human gates in examples and published eval tables are historical or opt-in
   behavior. Hosts must adopt v3.0 defaults explicitly; a policy document cannot
   enforce an external launcher's behavior or override server-required CI.
6. The README completion language and signed live-start packet disagree about what
   is pending. Release snapshots, current skill version and actual consumer adoption
   require separate evidence; report completion is not runtime promotion.
7. A non-mutating merge-tree check found three conflicts between the preserved
   original snapshot and current main: host-hil-policy.md (content), host_watchdog.py
   and test_host_watchdog.py (add/add). Do not merge that old snapshot blindly.
   The autonomy implementation starts from current main and carries the verified
   fixture triage forward separately.
8. Class-breaker evaluation still counts historical `needs-human` outcomes as its
   escalation metric. Default `blocked` outcomes need a separately frozen metric
   definition before comparisons with that historical rate; do not silently change
   the preregistered statistic when switching to autonomous operation.
9. Explicit HITL requests belong to the Host's persistent task/project policy. The
   supervisor flag is per invocation; a Host must keep supplying the requested
   mode after restarts and record its provenance. The flag alone is not an
   authenticated user-request store.
10. Supervisor redaction operates on decoded text. A child that emits UTF-16 or
    another undeclared stream encoding needs an explicit decoding contract; text
    redaction alone is not proof of byte-stream coverage. Validate that before
    handling arbitrary provider logs or files.

## Validation record

Original snapshot: full 25-step commit gate passed, including 17 redaction and 25
structured-watchdog tests. Autonomy targeted tests: 18 command-supervisor tests,
9 class-breaker tests, 4 metadata-export tests, strict skill validation and docs-drift
check passed. Full autonomy commit-gate result is recorded in the commit/push handoff.
The synthetic probes above are review evidence, not a newly authorized model trial.
The final supervisor review also found that a terminal timeout or caller-supplied
gate could be forgotten by the next invocation. Terminal reasons are now persisted;
restart tests prove neither case launches another command after the flags disappear.

## Project boundary correction

SmartRouter recheck after the scope change: the additional automatic-dispatch
candidate remains blocked on its immutable identity/qualification/accounting inputs;
no rejected candidate was resurrected. HumanGate remains none under v3.0. The
existing worktree continues to isolate the user-directed local edits. Added acceptance
evidence: zero withdrawn-project references in current text, no legacy binary bundles
in the current tree, scoped custody tests, and 94/94 routing-fixture assertions.

The user clarified that a separate data-collection project had been recorded here
by mistake. Removed its handoff document, adoption/governance references, personal
inventory entry and named fixture coupling. Credential scanners now default to the
SmartRouter-owned `~/.secrets/smart-router` subtree; explicit overrides remain
available for real project custody and isolated tests. No other checkout, credential
file or ACL was changed. Historical binary bundles containing the withdrawn material
were removed from the current source tree; tagged releases remain historical snapshots.

The default ACL probe now prepends the selected PowerShell executable's own module
folder to its child environment. This fixes the mixed-version module-import failure
without changing machine-wide module paths. Scope tests keep sibling project
inventories out of the router's default scan.

## Remaining branch integration — 14 October 2026

The [integration record](REMAINING_BRANCH_INTEGRATION.md) records the reviewed
gap-closure merge and the useful changes ported from the original snapshot.
F03 now blocks invalid state without replacing counters. The original redaction
layer is wired into both ledger and state writes, with UTF-16 coverage added;
this addresses the tested F04 encoding reproductions and extends the writer
coverage discussed in F08. Shared-plan checks now refuse before spawning and
bind launch evidence to the task, branch and worktree. The later
[dispatch accounting follow-up](DISPATCH_ACCOUNTING.md) addresses F01/F02 with
synthetic process and crash tests. No live-model qualification or bill was
inferred from these tests.
