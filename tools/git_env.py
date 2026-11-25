"""Keep config given on a git command line out of the gate and its tests.

`git -c name=value <command>` puts the setting in GIT_CONFIG_PARAMETERS (newer Git can
also use GIT_CONFIG_COUNT with GIT_CONFIG_KEY_<n> and GIT_CONFIG_VALUE_<n>). Every process
that command starts inherits it, a pre-commit hook included, and every git process those
start reads it as config. That overrides what a test set up in its own repository:
`-c user.name=...` replaced the name tools/test_install_hooks.py checks, and
`-c commit.gpgsign=true` made the test repositories' commits ask for a signing key.

tools/run_regression.py runs each check with without_command_line_config(). Each test
that starts git calls drop_command_line_config() when it loads, so it is isolated when
run on its own too. tools/test_run_regression.py checks that every such test does.
"""
from __future__ import annotations

import os
import re

COMMAND_LINE_CONFIG = re.compile(r"GIT_CONFIG_(PARAMETERS|COUNT|KEY_\d+|VALUE_\d+)")


def without_command_line_config(environ=None) -> dict:
    """A copy of `environ` (default os.environ) without command-line git config."""
    environ = os.environ if environ is None else environ
    return {k: v for k, v in environ.items() if not COMMAND_LINE_CONFIG.fullmatch(k)}


def drop_command_line_config() -> None:
    """Remove command-line git config from this process's own environment."""
    for name in [k for k in os.environ if COMMAND_LINE_CONFIG.fullmatch(k)]:
        del os.environ[name]
