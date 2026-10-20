# Host integrations

Reference integrations of the Holdshort policy into a concrete host. A host is the application that
runs the agent and connects routing decisions to model calls, permissions, billing and project state
(README, "Use Holdshort in a coding-agent host"). Each integration here is offered as a worked
example and a source of friction reports, not as a gate component of this repository.

| Directory | Host | Language | Status |
| --- | --- | --- | --- |
| `claude-code/` | a Claude Code session that plans and delegates coding units to workflow sub-agents (the MoonAliza build, 2026-10) | Node (no dependencies) | reference; its tests run with `node --test hosts/claude-code/route.test.mjs` (69 cases), its JSON artifacts are checked by `tools/test_claude_code_host_artifacts.py` in the regression gate |

`hosts/claude-code/` was copied from the host's own `docs/orchestration/smartrouter/` at the revision
named in its README, and differs from it since the ADR-0003 rename (the policy's upstream block, the
decision field and the Brief text say `holdshort`); paths inside the README are the host's. Its `trace/` is the host's real ledger
(§10.5 records, usage readings, outcomes) with every cash field `null` — see
`docs/proposals/usage-windows-gate4.md`, Item 4, for why `tools/conform_spec.py` refuses those
records today. The friction log at the end of its README cites `fbe7bca`.
