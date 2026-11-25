"""Keep the developer's own git config out of the gate and its tests.

Two kinds of config would otherwise reach a test's git processes:

* Config given on a git command line. `git -c name=value <command>` puts the setting in
  GIT_CONFIG_PARAMETERS (newer Git can also use GIT_CONFIG_COUNT with GIT_CONFIG_KEY_<n>
  and GIT_CONFIG_VALUE_<n>). Every process that command starts inherits it, a pre-commit
  hook included, and it overrides even the config files a test points git at. `-c
  user.name=...` replaced the name tools/test_install_hooks.py checks, and `-c
  commit.gpgsign=true` made the test repositories' commits ask for a signing key.
* Personal config: ~/.gitconfig and $XDG_CONFIG_HOME/git/config. The pre-commit hook
  sets HOME to the repository, so the gate never reads it there; a test run on its own
  would. System config (/etc/gitconfig, or Git for Windows' own) is read under the hook
  too, so it is kept.

tools/run_regression.py runs each check with without_command_line_config(). Each test
that starts git calls isolate_git_config() when it loads, so it sees the config it would
see under the hook when run on its own too. tools/test_run_regression.py checks that every
such test does. A test that sets GIT_CONFIG_GLOBAL in a child's environment still gets the
file it names.
"""
from __future__ import annotations

import os
import re

COMMAND_LINE_CONFIG = re.compile(r"GIT_CONFIG_(PARAMETERS|COUNT|KEY_\d+|VALUE_\d+)")

# Git's documented value for "read no global config file"; Git for Windows maps it to NUL.
NO_PERSONAL_CONFIG = "/dev/null"


def without_command_line_config(environ=None) -> dict:
    """A copy of `environ` (default os.environ) without command-line git config."""
    environ = os.environ if environ is None else environ
    return {k: v for k, v in environ.items() if not COMMAND_LINE_CONFIG.fullmatch(k)}


def isolate_git_config() -> None:
    """Make this process's git children read neither command-line nor personal config."""
    for name in [k for k in os.environ if COMMAND_LINE_CONFIG.fullmatch(k)]:
        del os.environ[name]
    os.environ["GIT_CONFIG_GLOBAL"] = NO_PERSONAL_CONFIG
