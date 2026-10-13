#!/usr/bin/env python3
"""Custody-directory ACL lockdown — the token tree must stay readable by the user alone.

The default custody tree is ~/.secrets/smart-router. Its intended policy is inheritance
broken on every object and full control granted to the user account alone, so SYSTEM
and Administrators hold no STANDING access to the files. ACL state regresses silently: an
installer, a profile tool, or one careless `icacls /reset` re-enables inheritance and the
credentials flow back to every administrator with no signal anywhere. This check rides the
pre-commit gate (tools/run_regression.py), so a commit cannot land while the tree sits
outside the lockdown.

Invariants (every object under the custody root):
  * exactly one ACE — an EMPTY DACL locks everyone out (a real bug this check's author
    hit: inherit-only (OI)(CI) flags on a FILE grant nothing), and every extra ACE is an
    extra principal;
  * that ACE is the current user, Allow, FullControl — anything else is standing access
    someone else holds, or access the user has lost;
  * no inherited ACE survives on ANY object (IsInherited=False) — the whole point of
    breaking inheritance; a credential file added to custody later arrives with an
    inherited user:(I)(F) ACE and must be converted to an explicit one (the per-file
    fix below does exactly that) before it passes here;
  * directories: the ACE propagates (ContainerInherit, ObjectInherit) so future children
    land as user:(I)(F) — checked from the flags on purpose — and inheritance is broken
    (AreAccessRulesProtected) so nothing from the profile can flow back in; the
    directory is the lockdown boundary;
  * files: the ACE carries no inherit/propagation flags (a (OI)(CI) or Inherit-only ACE
    on a file is exactly the shape of the empty-DACL bug);
  * the owner is the user — an object owned elsewhere can have its DACL rewritten
    without the user.

Surfaces and resolution (overridable for tests, matching the app_db / credential-hygiene
precedent):
  * custody root: --root, default <USERPROFILE>\\.secrets (USERPROFILE wins over HOME,
    because a hook can export HOME=<repo root> and hide the real profile);
  * ACL probe: one PowerShell Get-Acl pass emitting JSON metadata (path, owner,
    protection, per-ACE identity/rights/allow/inherited/flags). File CONTENTS are never
    read and never printed — output discipline: paths and ACL facts only, like
    check_credential_hygiene.py;
  * platform: the tree is a Windows-machine fact. Elsewhere — or when the root does not
    exist on this machine — the surface is N/A and the gate stays green (CI runners must
    not fail on that). An ACL that exists but cannot be read is never N/A: see the
    fail-closed exit below.

Exit codes — the count IS the interface, so CI or a human can branch on it:
  0    clean, or the surface does not exist on this machine (N/A)
  N    N object(s) outside the lockdown — refuse the commit; each is named above with
       its failing facts (0 is the only pass; N>1 is systemic drift, not a single miss)
  255  fail-closed — deliberately not a plausible object count: the ACL could not be
       read or parsed. An unreadable ACL could be hiding a foreign ACE, so it is never
       "clean"
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parent

FULL_CONTROL = "FullControl"
DIR_FLAGS = "ContainerInherit, ObjectInherit"
NO_FLAGS = "None"
FAIL_CLOSED = 255   # not a plausible object count — see the exit-code contract

# One PowerShell pass over the tree: ACL metadata only. Get-Acl reads the security
# descriptor, never file contents. __ROOT__ is replaced with the single-quote-escaped root.
PROBE = r"""
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$root = '__ROOT__'
$items = @(Get-Item -LiteralPath $root -Force) + @(Get-ChildItem -LiteralPath $root -Recurse -Force)
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$objs = foreach ($i in $items) {
  $acl = Get-Acl -LiteralPath $i.FullName
  [pscustomobject]@{
    path = $i.FullName
    is_dir = [bool]$i.PSIsContainer
    owner = $acl.Owner
    protected = [bool]$acl.AreAccessRulesProtected
    aces = @(@($acl.Access) | ForEach-Object {
      [pscustomobject]@{
        identity = $_.IdentityReference.Value
        rights = $_.FileSystemRights.ToString()
        allow = ($_.AccessControlType.ToString() -eq 'Allow')
        inherited = [bool]$_.IsInherited
        inh = $_.InheritanceFlags.ToString()
        prop = $_.PropagationFlags.ToString()
      }
    })
  }
}
@{ user = $user; objects = @($objs) } | ConvertTo-Json -Depth 6 -Compress
"""

ACE_FIELDS = ("identity", "rights", "allow", "inherited", "inh", "prop")
OBJ_FIELDS = ("path", "is_dir", "owner", "protected", "aces")

FIX_HINT = """\
  fix: re-lock the tree — for every directory:
         icacls "<dir>" /inheritance:r /grant:r "<user>:(OI)(CI)F" /C
       and for every file (never (OI)(CI) on a file: that is an inherit-only ACE and the
       file becomes unreadable; the same command also converts the inherited (I)(F) ACE
       a freshly added file arrives with into the explicit ACE this check wants):
         icacls "<file>" /inheritance:r /grant:r "<user>:F" /C
       then confirm with: python tools/check_custody_acl.py"""


class FailClosed(Exception):
    """A surface could not be read or parsed — never report this as clean."""


def _same(a: str, b: str) -> bool:
    return a.casefold() == b.casefold()


def default_root(env: dict | None = None) -> Path:
    """<USERPROFILE>\\.secrets — USERPROFILE wins over HOME (a hook can export HOME)."""
    env = env if env is not None else os.environ
    for var in ("USERPROFILE", "HOME"):
        if env.get(var):
            return Path(env[var]) / ".secrets" / "smart-router"
    return Path.home() / ".secrets" / "smart-router"


def na_reason(root: Path, platform: str | None = None) -> str | None:
    """None = verify now; otherwise the N/A reason. Surface absent is N/A, never a failure."""
    if (platform or os.name) != "nt":
        return "N/A on this platform (the custody tree is a Windows-machine fact)"
    if not root.is_dir():
        return f"N/A — no custody root at {root} (nothing to verify on this machine)"
    return None


# ---------------------------------------------------------------- probe

def probe_script(root: Path) -> str:
    return PROBE.replace("__ROOT__", str(root).replace("'", "''"))


def gather(root: Path) -> dict:
    """One PowerShell pass: ACL metadata only. Raises FailClosed on any doubt."""
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        raise FailClosed("no powershell/pwsh on PATH — the ACL cannot be read")
    b64 = base64.b64encode(probe_script(root).encode("utf-16-le")).decode("ascii")
    probe_env = dict(os.environ)
    probe_env["PSModulePath"] = str(Path(exe).parent / "Modules") + os.pathsep + probe_env.get("PSModulePath", "")
    try:
        proc = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-EncodedCommand", b64],
                              capture_output=True, timeout=60, env=probe_env)
    except subprocess.TimeoutExpired as e:
        raise FailClosed("the ACL probe timed out — the tree cannot be judged") from e
    except OSError as e:
        raise FailClosed(f"powershell could not run ({e})") from e
    if proc.returncode != 0:
        raise FailClosed(f"the ACL probe failed (exit {proc.returncode}): "
                         f"{proc.stderr.decode('utf-8', errors='replace')[:200]}")
    try:
        text = proc.stdout.decode("utf-8")
    except UnicodeDecodeError as e:
        raise FailClosed(f"the ACL probe output is not UTF-8 ({e})") from e
    return parse_facts(text)


def parse_facts(text: str) -> dict:
    """Probe JSON -> facts dict. Single-object/array shapes both normalize; any record
    missing an ACL field fails closed (a misread ACL could be hiding a foreign ACE)."""
    text = text.strip().lstrip("\ufeff")
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise FailClosed(f"the ACL probe output is not JSON ({e})") from e
    if not isinstance(doc, dict) or "user" not in doc or "objects" not in doc:
        raise FailClosed("the ACL probe output is missing user/objects — refusing to guess")
    objects = doc["objects"]
    if isinstance(objects, dict):
        objects = [objects]
    if objects is None:
        objects = []
    if not isinstance(objects, list):
        raise FailClosed("the ACL probe output: 'objects' is not a list")
    for obj in objects:
        missing = [f for f in OBJ_FIELDS if f not in obj]
        if missing:
            raise FailClosed(f"ACL record for {obj.get('path', '?')} is missing {missing}")
        aces = obj["aces"]
        if isinstance(aces, dict):
            aces = [aces]
        obj["aces"] = aces or []
        for ace in obj["aces"]:
            missing = [f for f in ACE_FIELDS if f not in ace]
            if missing:
                raise FailClosed(f"ACE record under {obj['path']} is missing {missing}")
    user = doc["user"]
    if not isinstance(user, str) or not user:
        raise FailClosed("the ACL probe output has no current user to compare against")
    return {"user": user, "objects": objects}


# ---------------------------------------------------------------- judgement

def evaluate(facts: dict) -> list[str]:
    """Pure lockdown judgement: one 'kind path: problem; ...' line per violating object."""
    user = facts.get("user", "")
    problems: list[str] = []
    for obj in facts.get("objects", []):
        path = str(obj.get("path", "?"))
        kind = "dir" if obj.get("is_dir") else "file"
        aces = obj.get("aces", [])
        issues: list[str] = []

        if not aces:
            issues.append("EMPTY DACL (nobody has access — the file is unreadable)")
        foreign = [str(a.get("identity", "")) for a in aces
                   if not _same(str(a.get("identity", "")), user)]
        if foreign:
            issues.append("foreign principal: " + ", ".join(foreign))
        if any(a.get("inherited") for a in aces):
            issues.append("inherited ACE present (every ACE on this tree must be explicit "
                          "— inheritance is broken here on purpose)")
        if kind == "dir" and not obj.get("protected"):
            issues.append("inheritance not broken (AreAccessRulesProtected=False)")
        if len(aces) == 1:
            a = aces[0]
            if not _same(str(a.get("identity", "")), user):
                issues.append("sole ACE is not the user")
            if not a.get("allow"):
                issues.append("sole ACE is not Allow")
            rights = str(a.get("rights", ""))
            if rights != FULL_CONTROL:
                issues.append(f"sole ACE rights are {rights!r}, not FullControl")
            if kind == "dir":
                if str(a.get("inh", "")) != DIR_FLAGS:
                    issues.append(f"dir ACE inheritance flags are {a.get('inh')!r}, want "
                                  f"{DIR_FLAGS!r} (future children must inherit access)")
                if str(a.get("prop", "")) != NO_FLAGS:
                    issues.append(f"dir ACE propagation flags are {a.get('prop')!r} "
                                  "(Inherit-only grants nothing)")
            else:
                if str(a.get("inh", "")) != NO_FLAGS or str(a.get("prop", "")) != NO_FLAGS:
                    issues.append(f"file ACE flags are inh={a.get('inh')!r} "
                                  f"prop={a.get('prop')!r} — (OI)(CI) on a file is an "
                                  "inherit-only ACE that grants nothing")
        if not _same(str(obj.get("owner", "")), user):
            issues.append(f"owner is {obj.get('owner')!r}, not the user")

        if issues:
            problems.append(f"{kind} {path}: " + "; ".join(issues))
    return problems


# ---------------------------------------------------------------- run

def fact_lines(facts: dict) -> list[str]:
    lines = []
    for obj in facts.get("objects", []):
        kind = "dir " if obj.get("is_dir") else "file"
        lines.append(f"  {kind} {obj.get('path')}")
        lines.append(f"        aces={len(obj.get('aces', []))} owner={obj.get('owner')} "
                     f"protected={obj.get('protected')}")
        for a in obj.get("aces", []):
            lines.append("        {identity} {rights} allow={allow} inherited={inherited} "
                         "inh={inh} prop={prop}".format(**a))
    return lines


def parse_args(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(
        description="Custody-directory ACL lockdown: the credential tree must stay "
                    "readable by the user alone. Read-only; no file content is ever "
                    "read or printed.")
    ap.add_argument("--root", type=Path, default=None,
                    help="custody root to audit (default: <USERPROFILE>\\.secrets)")
    ap.add_argument("--acl-json", type=Path, default=None,
                    help="file holding probe JSON (tests/other machines); default: probe "
                         "the live ACL")
    return ap.parse_args(argv)


def run(args) -> int:
    try:
        if args.acl_json is not None:
            if not args.acl_json.is_file():
                raise FailClosed(f"--acl-json {args.acl_json} is not a readable file")
            facts = parse_facts(args.acl_json.read_text(encoding="utf-8"))
        else:
            root = args.root if args.root is not None else default_root()
            reason = na_reason(root)
            if reason is not None:
                print(f"custody_acl: {reason}")
                return 0
            facts = gather(root)
        for line in fact_lines(facts):
            print(line)
        problems = evaluate(facts)
        if problems:
            print(f"custody_acl: {len(problems)} object(s) outside the lockdown — "
                  f"DO NOT COMMIT until fixed:")
            for p in problems:
                print(f"  - {p}")
            print(FIX_HINT)
            return len(problems)      # the count IS the exit code (see the contract)
        print(f"custody_acl: clean ({len(facts['objects'])} object(s): only {facts['user']}, "
              "inheritance broken on the tree, dirs keep inheritable FullControl)")
        return 0
    except (FailClosed, OSError) as e:
        print(f"custody_acl: FAIL-CLOSED — {e}", file=sys.stderr)
        return FAIL_CLOSED


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
