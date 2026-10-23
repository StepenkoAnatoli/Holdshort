# Cursor host adapter (template)

Skeleton for integrating Holdshort into Cursor. Cursor exposes model calls and
terminal commands through its agent; this adapter shows where to plug them.

## Responsibilities

1. Load `skills/holdshort/SKILL.md` and the host contract (`spec-v2.md`).
2. Provide authorized data/actions, model profiles, qualification evidence,
   acceptance checks, price bounds, and remaining allowances.
3. Supervise bounded commands via `tools/host_watchdog.py`.
4. Use `tools/dispatch_adapter.py` (or a config-driven adapter) for approved egress.
5. Record decisions/outcomes per `spec-v2.md`.

## Files

- `host-policy.json` — adapt from `hosts/claude-code/host-policy.json`.
- `route.py` — wiring skeleton; replace model calls with Cursor's agent API.
