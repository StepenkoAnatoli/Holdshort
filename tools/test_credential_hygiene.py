#!/usr/bin/env python3
"""Tests for tools/check_credential_hygiene.py — the credential-store hygiene gate.

Invariants under test (each one is a real failure mode, observed or reasoned about):
  C1.  a non-Windows platform has no Windows Credential Manager: the surface is N/A and
       token-presence judgements are SKIPPED, never guessed (CI runners must stay green).
  C2.  a consistent machine (hosts.yml + matching keyring targets + intact GCM helper)
       is clean.
  C3.  keyring gh tokens with no hosts.yml are ORPHANED (exit 1) and the fix names each
       exact target — this was the live state of this machine at check introduction.
  C4.  a `git:` store entry the effective helper chain no longer reads is STALE (exit 1);
       the same entry with the generic `manager` helper intact is clean.
  C5.  a token for an account hosts.yml does not list is STALE; a hosts.yml entry with no
       recorded accounts does NOT produce a false positive for a named token.
  C6.  a hosts.yml host with no stored token and no inline token is STALE; an inline
       oauth_token is reported as information, never as a finding.
  C7.  .git-credentials entries whose host's chain lacks `store` are STALE (exit 1); when
       `store` IS the helper the file is informational only — and the credential value is
       never echoed into stdout/stderr.
  C8.  a malformed .git-credentials line is reported by line number, without echoing it.
  C9.  an unrecognized hosts.yml fails CLOSED (exit 2) — a misread hosts.yml must not
       hide an orphan.
  C10. a malformed baseline fails CLOSED (exit 2) instead of silently disabling triage.
  C11. --update-baseline records subjects (never values) and the next run is clean.
  C12. the hook's `export HOME=<repo root>` cannot hide the user's real credential
       config: USERPROFILE wins, so a decoy HOME config must not make a stale entry look
       reachable.
  C13. a UTF-16 store listing (what a redirected Windows console tool can emit) parses.
  C14. chain semantics match gitcredentials(7): an empty helper value resets the
       accumulated list, file order applies, and another URL's section does not leak in.
  C15. a file under ~/.secrets (e.g. research-kit) is flagged as
       plaintext-credential-file (exit 1) by NAME ONLY — fixture key material is
       piece-assembled and never echoed into stdout/stderr.
  C16. a missing ~/.secrets dir is clean (expected on CI runners and fresh machines).
  C17. a baselined plaintext-file entry is clean; --update-baseline records the
       subject (never any content).
  C18. a --secrets-dir override pointing at a non-directory fails CLOSED (exit 2).

Every fixture is a temp dir; the real credential store and the real hosts.yml are never
read (cmdkey is never executed, APPDATA/HOME/USERPROFILE all point into the fixture).
Fixture token values are piece-assembled so this tracked file never trips
tools/check_secrets.py itself, and no test ever prints a credential-shaped value.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "check_credential_hygiene.py"

# Registered in sys.modules: @dataclass resolves the defining module through it
# (exec_module without registration fails on Python 3.14+).
spec = importlib.util.spec_from_file_location("cch", TOOL)
cch = importlib.util.module_from_spec(spec)
sys.modules["cch"] = cch
spec.loader.exec_module(cch)

# Two pieces: the literal in this file is never a full token shape.
FAKE_PAT = "ghp_" + "A1b2C3d4E5" * 4


def listing(*entries: tuple[str, str]) -> str:
    """A cmdkey-style listing (target, user) with the real block structure."""
    blocks = []
    for target, user in entries:
        block = (f"    Target: LegacyGeneric:target={target}\n"
                 "    Type: Generic \n")
        if user:
            block += f"    User: {user}\n"
        block += "    Local machine persistence\n    \n"
        blocks.append(block)
    return "\n  Currently stored credentials:\n  \n" + "".join(blocks)


def gh_dir(tmp: Path, hosts_yml: str | None = None) -> Path:
    d = tmp / "ghcfg"
    d.mkdir(exist_ok=True)
    if hosts_yml is not None:
        (d / "hosts.yml").write_text(hosts_yml, encoding="utf-8")
    return d


def gitconfig(tmp: Path, content: str, name: str = "fixture-gitconfig") -> Path:
    p = tmp / name
    p.write_text(content, encoding="utf-8")
    return p


def env_for(tmp: Path, *, gitconfig_path: Path | None = None, home_dir: Path | None = None,
            home_config: str | None = None, extra: dict | None = None) -> dict:
    """Fixture env: git config scopes, user home, and APPDATA all inside the temp dir."""
    empty = tmp / "empty-gitconfig"
    if not empty.exists():
        empty.write_text("", encoding="utf-8")
    home = home_dir or (tmp / "userhome")
    home.mkdir(exist_ok=True)
    if home_config is not None:
        (home / ".gitconfig").write_text(home_config, encoding="utf-8")
    env = dict(os.environ)
    env["GIT_CONFIG_SYSTEM"] = str(empty)
    if gitconfig_path is not None:
        env["GIT_CONFIG_GLOBAL"] = str(gitconfig_path)
    else:
        env.pop("GIT_CONFIG_GLOBAL", None)
    env["USERPROFILE"] = str(home)
    env["HOME"] = str(home)
    env["APPDATA"] = str(tmp / "appdata-with-no-gh")
    env.pop("GH_CONFIG_DIR", None)
    env.update(extra or {})
    return env


def run_cli(tmp: Path, env: dict, *args: str):
    base = ["--baseline", str(tmp / "baseline.json")]
    return subprocess.run([sys.executable, str(TOOL), *base, *args],
                          capture_output=True, text=True, timeout=120, env=env)


class CredentialHygiene(unittest.TestCase):

    # C1 -------------------------------------------------------------------
    def test_c1_non_windows_surface_is_na_and_token_presence_not_guessed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            d = gh_dir(tmp, "github.com:\n    user: U\n    oauth_token: !!!\n")
            (entries, desc, available, hosts, _hdesc, creds, malformed, config,
             _secrets, _secrets_desc) = cch.inspect(
                store_path=None, gh_config_override=d, credentials_file=tmp / "none",
                platform="linux", config=[])
            self.assertFalse(available)
            self.assertEqual(entries, [])
            self.assertIn("N/A", desc)
            findings, _info, _other = cch.hygiene_findings(
                entries, available, hosts, creds, malformed, config)
        self.assertEqual(findings, [],
                         "a surface that does not exist must not be judged as 'no token'")

    # C2 -------------------------------------------------------------------
    def test_c2_consistent_machine_is_clean(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            d = gh_dir(tmp, "github.com:\n    user: U\n    oauth_token: !!!\n")
            lst = tmp / "listing.txt"
            lst.write_text(listing(("gh:github.com:U", "U"), ("gh:github.com:", ""),
                                   ("git:https://example.com", "U")), encoding="utf-8")
            cfg = gitconfig(tmp, "[credential]\n\thelper = manager\n")
            r = run_cli(tmp, env_for(tmp, gitconfig_path=cfg),
                        "--store-listing", str(lst), "--gh-config-dir", str(d))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("clean (0 new findings", r.stdout)

    # C3 -------------------------------------------------------------------
    def test_c3_orphaned_gh_keyring_tokens(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            d = gh_dir(tmp)          # exists, but no hosts.yml — the live state on 10-12
            lst = tmp / "listing.txt"
            lst.write_text(listing(("gh:github.com:U", "U"), ("gh:github.com:", "")),
                           encoding="utf-8")
            r = run_cli(tmp, env_for(tmp), "--store-listing", str(lst),
                        "--gh-config-dir", str(d), "--credentials-file", str(tmp / "none"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("orphaned-gh-keyring-token: gh:github.com:U", r.stdout)
        self.assertIn("orphaned-gh-keyring-token: gh:github.com:", r.stdout)
        self.assertIn("no hosts.yml", r.stdout)
        self.assertIn('cmdkey /delete:"gh:github.com:U"', r.stdout)

    # C4 -------------------------------------------------------------------
    def test_c4_stale_git_entry_vs_intact_manager_chain(self):
        reset = ("[credential]\n\thelper = manager\n"
                 '[credential "https://example.com"]\n\thelper =\n\thelper = other-helper\n')
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            d = gh_dir(tmp)
            lst = tmp / "listing.txt"
            lst.write_text(listing(("git:https://example.com", "U")), encoding="utf-8")
            stale = run_cli(tmp, env_for(tmp, gitconfig_path=gitconfig(tmp, reset)),
                            "--store-listing", str(lst), "--gh-config-dir", str(d))
            reachable = run_cli(
                tmp, env_for(tmp, gitconfig_path=gitconfig(
                    tmp, "[credential]\n\thelper = manager\n", name="keep.cfg")),
                "--store-listing", str(lst), "--gh-config-dir", str(d))
        self.assertEqual(stale.returncode, 1, stale.stdout + stale.stderr)
        self.assertIn("stale-git-credential: git:https://example.com", stale.stdout)
        self.assertIn("other-helper", stale.stdout)
        self.assertEqual(reachable.returncode, 0, reachable.stdout + reachable.stderr)
        self.assertIn("clean", reachable.stdout)

    # C5 -------------------------------------------------------------------
    def test_c5_account_not_listed_is_stale_but_empty_users_is_not_a_false_positive(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            lst = tmp / "listing.txt"
            lst.write_text(listing(("gh:github.com:Bob", "Bob")), encoding="utf-8")
            listed = gh_dir(tmp, "github.com:\n    user: Alice\n    oauth_token: !!!\n")
            r = run_cli(tmp, env_for(tmp), "--store-listing", str(lst),
                        "--gh-config-dir", str(listed))
            no_users = gh_dir(tmp, "github.com:\n    oauth_token: !!!\n")
            r2 = run_cli(tmp, env_for(tmp), "--store-listing", str(lst),
                         "--gh-config-dir", str(no_users))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("stale-gh-keyring-token: gh:github.com:Bob", r.stdout)
        self.assertEqual(r2.returncode, 0,
                         "a hosts.yml without recorded accounts must not condemn named tokens")
        self.assertIn("clean", r2.stdout)

    # C6 -------------------------------------------------------------------
    def test_c6_hosts_entry_without_token_is_stale_and_inline_token_is_info(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            lst = tmp / "listing.txt"
            lst.write_text(listing(("MicrosoftAccount:target=SSO_POP_User", "u")),
                           encoding="utf-8")
            no_token = gh_dir(tmp, "github.com:\n    user: U\n    oauth_token: !!!\n")
            r = run_cli(tmp, env_for(tmp), "--store-listing", str(lst),
                        "--gh-config-dir", str(no_token), "--credentials-file", str(tmp / "none"))
            inline = gh_dir(tmp, "github.com:\n    user: U\n    oauth_token: " + FAKE_PAT + "\n")
            r2 = run_cli(tmp, env_for(tmp), "--store-listing", str(lst),
                         "--gh-config-dir", str(inline), "--credentials-file", str(tmp / "none"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("stale-hosts-entry: hosts.yml:github.com", r.stdout)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertIn("inline oauth_token", r2.stdout)
        for out in (r2.stdout, r2.stderr):
            self.assertNotIn(FAKE_PAT, out, "hosts.yml token values must never be echoed")

    # C7 -------------------------------------------------------------------
    def test_c7_plaintext_store_entries_and_no_value_echo(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "userhome"
            home.mkdir()
            (home / ".git-credentials").write_text(
                f"https://user:{FAKE_PAT}@example.com\n", encoding="utf-8")
            d = gh_dir(tmp)
            lst = tmp / "listing.txt"
            lst.write_text(listing(), encoding="utf-8")
            no_store = run_cli(tmp, env_for(tmp, home_dir=home, gitconfig_path=gitconfig(
                tmp, "[credential]\n\thelper = manager\n")),
                "--store-listing", str(lst), "--gh-config-dir", str(d))
            with_store = run_cli(tmp, env_for(tmp, home_dir=home, gitconfig_path=gitconfig(
                tmp, "[credential]\n\thelper = store\n", name="store.cfg")),
                "--store-listing", str(lst), "--gh-config-dir", str(d))
        self.assertEqual(no_store.returncode, 1, no_store.stdout + no_store.stderr)
        self.assertIn("stale-plaintext-credential: store-file:example.com", no_store.stdout)
        self.assertEqual(with_store.returncode, 0, with_store.stdout + with_store.stderr)
        self.assertIn("in use for example.com", with_store.stdout)
        for r in (no_store, with_store):
            for out in (r.stdout, r.stderr):
                self.assertNotIn(FAKE_PAT, out, "the store file's value must never be echoed")

    # C8 -------------------------------------------------------------------
    def test_c8_malformed_store_line_reported_by_number_without_echo(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "userhome"
            home.mkdir()
            (home / ".git-credentials").write_text(f"example.com:{FAKE_PAT}\n", encoding="utf-8")
            d = gh_dir(tmp)
            lst = tmp / "listing.txt"
            lst.write_text(listing(), encoding="utf-8")
            r = run_cli(tmp, env_for(tmp, home_dir=home),
                        "--store-listing", str(lst), "--gh-config-dir", str(d))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("store-file:line-1", r.stdout)
        for out in (r.stdout, r.stderr):
            self.assertNotIn(FAKE_PAT, out)

    # C9 -------------------------------------------------------------------
    def test_c9_unrecognized_hosts_yml_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            d = gh_dir(tmp, "this line has no trailing colon and is not a host key\n")
            lst = tmp / "listing.txt"
            lst.write_text(listing(), encoding="utf-8")
            r = run_cli(tmp, env_for(tmp), "--store-listing", str(lst),
                        "--gh-config-dir", str(d))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("FAIL-CLOSED", r.stderr)

    # C10 ------------------------------------------------------------------
    def test_c10_malformed_baseline_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "baseline.json").write_text("{ this is not json", encoding="utf-8")
            d = gh_dir(tmp)
            lst = tmp / "listing.txt"
            lst.write_text(listing(), encoding="utf-8")
            r = run_cli(tmp, env_for(tmp), "--store-listing", str(lst),
                        "--gh-config-dir", str(d))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("FAIL-CLOSED", r.stderr)

    # C11 ------------------------------------------------------------------
    def test_c11_update_baseline_records_subjects_not_values(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            d = gh_dir(tmp)
            lst = tmp / "listing.txt"
            lst.write_text(listing(("gh:github.com:U", "U"),
                                   ("git:https://example.com", "U")), encoding="utf-8")
            env = env_for(tmp)
            args = ("--store-listing", str(lst), "--gh-config-dir", str(d))
            first = run_cli(tmp, env, *args)
            self.assertEqual(first.returncode, 1, first.stdout + first.stderr)
            upd = run_cli(tmp, env, *args, "--update-baseline", "--note", "unit-test triage")
            self.assertEqual(upd.returncode, 0, upd.stdout + upd.stderr)
            again = run_cli(tmp, env, *args)
            doc = json.loads((tmp / "baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("baselined", again.stdout)
        self.assertIn("gh:github.com:U", doc["entries"])
        self.assertIn("git:https://example.com", doc["entries"])
        self.assertEqual(doc["last_update_note"], "unit-test triage")
        self.assertNotIn(FAKE_PAT, json.dumps(doc))

    # C12 ------------------------------------------------------------------
    def test_c12_decoy_home_config_cannot_hide_a_stale_entry(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            real = tmp / "realhome"
            decoy = tmp / "hook-home"
            decoy.mkdir()
            # the decoy (a hook's HOME=<repo root>) would make the entry reachable
            (decoy / ".gitconfig").write_text("[credential]\n\thelper = manager\n",
                                              encoding="utf-8")
            d = gh_dir(tmp)
            lst = tmp / "listing.txt"
            lst.write_text(listing(("git:https://example.com", "U")), encoding="utf-8")
            # the real user config resets helpers for this URL: unreachable
            env = env_for(tmp, home_dir=real,
                          home_config='[credential "https://example.com"]\n\thelper =\n'
                                      "\thelper = other-helper\n",
                          extra={"HOME": str(decoy)})
            r = run_cli(tmp, env, "--store-listing", str(lst), "--gh-config-dir", str(d))
        self.assertEqual(r.returncode, 1,
                         "USERPROFILE's config must decide, not the hook-exported HOME")
        self.assertIn("stale-git-credential: git:https://example.com", r.stdout)

    # C13 ------------------------------------------------------------------
    def test_c13_utf16_store_listing_parses(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            d = gh_dir(tmp)
            lst = tmp / "listing.txt"
            lst.write_bytes(listing(("gh:github.com:U", "U")).encode("utf-16"))
            r = run_cli(tmp, env_for(tmp), "--store-listing", str(lst),
                        "--gh-config-dir", str(d))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("orphaned-gh-keyring-token: gh:github.com:U", r.stdout)

    # C14 ------------------------------------------------------------------
    def test_c14_chain_reset_semantics(self):
        E = cch.ConfigEntry
        reset = [E("file:sys", "credential.helper", "manager"),
                 E("file:user", "credential.https://github.com.helper", ""),
                 E("file:user", "credential.https://github.com.helper", "gh-helper")]
        self.assertEqual(cch.helper_chain("https://github.com", reset), ["gh-helper"])
        self.assertEqual(cch.helper_chain("https://example.com", reset), ["manager"])
        self.assertEqual(cch.helper_chain("http://github.com", reset), ["manager"])

        both = [E("f", "credential.helper", "manager"),
                E("f", "credential.https://github.com.helper", "extra")]
        self.assertEqual(cch.helper_chain("https://github.com", both), ["manager", "extra"])

        other_url = [E("f", "credential.https://gist.github.com.helper", "y")]
        self.assertEqual(cch.helper_chain("https://github.com", other_url), [],
                         "another URL's section must not leak into this chain")

        kinds = [cch.helper_kind(h) for h in
                 ["manager", "!/path/git-credential-manager", "store", "git-credential-store",
                  "!'C:\\Program Files\\GitHub CLI\\gh.exe' auth git-credential"]]
        self.assertEqual(kinds, ["manager", "manager", "store", "store", "gh"])


    # C15 ------------------------------------------------------------------
    def test_c15_secrets_dir_file_flagged_by_name_only(self):
        # Three pieces: no literal in this file is ever a full key shape.
        fake = "sk-ant-" + "fake0123456789" + "abcdef0123"
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "userhome"
            home.mkdir()
            secrets = home / ".secrets"
            secrets.mkdir()
            (secrets / "research-kit").write_text(f"RESEARCH_KIT_KEY={fake}\n",
                                                 encoding="utf-8")
            env = env_for(tmp, home_dir=home)
            r = run_cli(tmp, env)
            blob = r.stdout + r.stderr
        self.assertEqual(r.returncode, 1, blob)
        self.assertIn("plaintext-credential-file: plaintext-file:research-kit", r.stdout)
        self.assertNotIn(fake, blob,
                         "the gate must never echo file contents (names only)")

    # C16 ------------------------------------------------------------------
    def test_c16_missing_secrets_dir_is_clean(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            env = env_for(tmp)  # userhome has no .secrets dir
            r = run_cli(tmp, env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("clean (0 new findings", r.stdout)

    # C17 ------------------------------------------------------------------
    def test_c17_baselined_plaintext_entry_and_update_records_subject(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "userhome"
            (home / ".secrets").mkdir(parents=True)
            (home / ".secrets" / "research-kit").write_text("placeholder\n",
                                                           encoding="utf-8")
            env = env_for(tmp, home_dir=home)
            first = run_cli(tmp, env)
            self.assertEqual(first.returncode, 1, first.stdout + first.stderr)
            upd = run_cli(tmp, env, "--update-baseline", "--note", "unit-test triage")
            self.assertEqual(upd.returncode, 0, upd.stdout + upd.stderr)
            again = run_cli(tmp, env)
            self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
            doc = json.loads((tmp / "baseline.json").read_text(encoding="utf-8"))
        self.assertIn("plaintext-file:research-kit", doc["entries"])
        self.assertIn("plaintext-credential-file",
                      doc["entries"]["plaintext-file:research-kit"])

    # C18 ------------------------------------------------------------------
    def test_c18_secrets_override_not_a_directory_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            notdir = tmp / "not-a-dir"
            notdir.write_text("x", encoding="utf-8")
            r = run_cli(tmp, env_for(tmp), "--secrets-dir", str(notdir))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("FAIL-CLOSED", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
