# Convenience targets. `make setup` is the one-command onboarding.

SHELL := /bin/bash
# Prefer python3: many distributions ship no bare `python`. Fall back to `python`
# because a Windows Python install often provides only that name.
PY ?= $(shell command -v python3 >/dev/null 2>&1 && echo python3 || echo python)

.PHONY: setup gate hooks check clean-proof

## setup: clone (optional URL arg), wire the pre-commit gate, PROVE it fires
##   make setup                       # current checkout
##   make setup REPO=<clone-url> DEST=<dir>
REPO ?=
DEST ?=
setup:
	bash tools/setup_machine.sh $(if $(REPO),$(REPO) $(DEST),)

## gate: run the full regression gate (same thing the hook and CI run)
gate:
	$(PY) tools/run_regression.py

## hooks: wire the pre-commit gate only (no proof run)
hooks:
	$(PY) tools/install_hooks.py

## check: secrets scan only
check:
	$(PY) tools/check_secrets.py
