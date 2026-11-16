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

- `route.py` — a Python skeleton showing wiring. Replace model calls with your host's.
- `full_loop.py` — policy validation, supervised command, dispatch dry-run and
  session-close accounting report, all using temporary demo data.
- `production_adapter.py` — a dry-run integration template despite its filename.
  Its dispatch helper requires the host's ledger path; reuse that ledger across
  every call and restart in a pilot. Authorized transport, qualification,
  acceptance checks and outcome recording still belong to the host.

## Cross-platform notes

- On Windows, use Git Bash or call the Python entry points directly
  (`python -m tools.host_watchdog ...`). The `make` targets assume bash.
- All tools are stdlib-only; no third-party dependencies are required.

## Installed tools and source checks

`python -m pip install .` installs the Python tools and their runtime data,
including adapter profiles. `holdshort-watchdog` works from the installation.
The host examples remain source-checkout templates.

The policy validator and regression gate need the checkout's skills, tests and
Git hooks. Run `holdshort-validate-skills --repo /path/to/Holdshort --strict` or
`holdshort-regression --repo /path/to/Holdshort`. Both refuse an incomplete
directory instead of claiming a pass with no files to check. The gate still
requires the checkout's hooks to be wired with `python tools/install_hooks.py`.

The package install test builds and installs a wheel in a temporary directory,
imports the provider adapters, and exercises all three installed commands:
`python tools/test_package_install.py` (requires pip, setuptools and wheel).
