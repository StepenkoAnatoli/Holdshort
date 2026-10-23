# Generic host adapter (template)

This directory is a starting point for integrating Holdshort into a coding-agent
host that is not Claude Code. It is intentionally minimal: the policy and tools
live in `skills/` and `tools/`; this adapter only wires them to your host's
model calls, billing, and project state.

## Responsibilities

1. Read `skills/holdshort/SKILL.md` and the host contract (`skills/holdshort/references/spec-v2.md`).
2. Provide authorized data/actions, exact model profiles, fresh qualification evidence,
   acceptance checks, price bounds, and remaining allowances.
3. Call `tools/host_watchdog.py` (or its packaged entry point) to supervise bounded commands.
4. Use `tools/dispatch_adapter.py` (or a config-driven adapter) for approved egress, or
   implement your own adapter following the same fail-closed contract.
5. Record decisions/outcomes per `spec-v2.md` and run `tools/conform_spec.py` on Briefs.

## Files

- `host-policy.json` — your host's policy blocks (copy and adapt from
  `hosts/claude-code/host-policy.json`).
- `route.py` — a Python skeleton showing wiring. Replace model calls with your host's.

## Cross-platform notes

- On Windows, use Git Bash or call the Python entry points directly
  (`python -m tools.host_watchdog ...`). The `make` targets assume bash.
- All tools are stdlib-only; no third-party dependencies are required.
