#!/usr/bin/env python3
"""Tests for tools/check_custody_acl.py — the custody-directory ACL lockdown gate.

Invariants under test (each one is a real failure mode, observed or reasoned about):
  L1.  a surface that does not exist is N/A and never a failure: non-Windows has no
       Windows ACLs to judge (CI runners must stay green), and a machine without the
       custody root has nothing to verify.
  L2.  the locked-down tree (directories explicit + inheritable + protected, files
       explicit) is clean — the exact state this machine was brought to on 2026-10-12.
  L3.  a foreign principal (SYSTEM, Administrators) is a lockdown violation (exit 1)
       and is named in the output.
  L4.  an EMPTY DACL is a violation (exit 1) — it locks everyone out; this is the real
       bug an inherit-only (OI)(CI) grant on a file produced during the 10-12 lockdown.
  L5.  an inherited ACE on ANY object is a violation — "no inherited ACE left" is the
       whole point of breaking inheritance — and so is a directory with unbroken
       inheritance: the directory is the boundary and must carry its own explicit ACE.
  L6.  a directory ACE that does not propagate (flags other than
       ContainerInherit, ObjectInherit) is a violation: future children would land with
       an empty DACL.
  L7.  a file ACE carrying (OI)(CI)/Inherit-only flags is a violation (exit 1) — the
       exact shape of the empty-DACL bug, even when its rights read FullControl.
  L8.  an owner other than the user is a violation: a foreign owner can rewrite the DACL.
  L9.  a sole ACE that is not Allow / not FullControl is a violation (access someone
       lost, or not actually granted).
  L10. a file freshly added to custody — the inherited user:(I)(F) state it arrives in
       — is REFUSED (exit 1) until its ACE is converted to explicit: parity with the
       original audit's "no inherited ACE left", so drift cannot hide behind "but it is
       only the user's own inherited ACE".
  L11. unreadable or malformed probe output fails CLOSED (exit 255 — deliberately not a
       plausible object count) — a misread ACL could be hiding a foreign ACE and is
       never "clean".
  L12. single-object probe JSON (what ConvertTo-Json emits for a one-item tree)
       normalizes to the same facts shape the judgement expects.
  L13. the real probe runs on Windows, resolves the identity the safe way (a
       domain-qualified [WindowsIdentity] name, never a bare whoami-style name), and
       emits ACL METADATA ONLY (paths, owner, protection, ACE facts — never file
       contents).
  L14. the exit code equals the number of violating objects (0 clean, N for N bad
       objects) — the interface CI and humans branch on.

Every fixture is a temp dir or a fixture JSON file; the real custody tree is never read
(the one live probe, L13, inspects a temp dir it creates). No test prints or writes a
credential-shaped value, so this tracked file cannot trip tools/check_secrets.py.
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
TOOL = REPO / "tools" / "check_custody_acl.py"

# Registered in sys.modules so the module behaves like a normal import for introspection.
spec = importlib.util.spec_from_file_location("cca", TOOL)
cca = importlib.util.module_from_spec(spec)
sys.modules["cca"] = cca
spec.loader.exec_module(cca)

USER = "DESKTOP-B6JNGAJ\\PC"
ROOT = "C:\\Users\\PC\\.secrets"


def ace(identity=USER, rights="FullControl", allow=True, inherited=False,
        inh="None", prop="None") -> dict:
    return {"identity": identity, "rights": rights, "allow": allow,
            "inherited": inherited, "inh": inh, "prop": prop}


def dir_obj(path=ROOT, aces=None, owner=USER, protected=True) -> dict:
    return {"path": path, "is_dir": True, "owner": owner, "protected": protected,
            "aces": aces if aces is not None else [ace(inh=cca.DIR_FLAGS)]}


def file_obj(path, aces=None, owner=USER, protected=True) -> dict:
    return {"path": path, "is_dir": False, "owner": owner, "protected": protected,
            "aces": aces if aces is not None else [ace()]}


def locked_objects() -> list[dict]:
    """The 2026-10-12 state: 2 locked directories, 6 explicit non-inheritable files."""
    objs = [dir_obj(ROOT), dir_obj(ROOT + "\\router-key-file")]
    for i in range(6):
        objs.append(file_obj(f"{ROOT}\\router-key-file\\f{i}.dat"))
    return objs


def write_fixture(tmp: Path, objects: list[dict], user: str = USER) -> Path:
    p = tmp / "facts.json"
    p.write_text(json.dumps({"user": user, "objects": objects}), encoding="utf-8")
    return p


def run_cli(*args: str):
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, timeout=120)


class CustodyAcl(unittest.TestCase):

    # L1 -------------------------------------------------------------------
    def test_l1_absent_surface_is_na_never_a_failure(self):
        self.assertIn("N/A", cca.na_reason(Path("no-such-root"), platform="linux"))
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self.assertIsNone(cca.na_reason(tmp, platform="nt"),
                              "an existing root on Windows must be verified, not skipped")
            self.assertIn("N/A", cca.na_reason(tmp / "absent", platform="nt"))
        # the CLI agrees, whichever platform it runs on: no root -> N/A -> exit 0
        r = run_cli("--root", "no-such-root")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("N/A", r.stdout)

    # L2 -------------------------------------------------------------------
    def test_l2_locked_tree_is_clean(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = write_fixture(Path(td), locked_objects())
            r = run_cli("--acl-json", str(fixture))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("clean", r.stdout)
        self.assertIn(USER, r.stdout)

    # L3 -------------------------------------------------------------------
    def test_l3_foreign_principal_is_a_violation_and_is_named(self):
        objs = locked_objects()
        objs[0]["aces"] = [ace(inh=cca.DIR_FLAGS),
                           ace(identity="NT AUTHORITY\\SYSTEM", inh=cca.DIR_FLAGS),
                           ace(identity="BUILTIN\\Administrators", inh=cca.DIR_FLAGS)]
        with tempfile.TemporaryDirectory() as td:
            fixture = write_fixture(Path(td), objs)
            r = run_cli("--acl-json", str(fixture))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("foreign principal", r.stdout)
        self.assertIn("NT AUTHORITY\\SYSTEM", r.stdout)
        self.assertIn("BUILTIN\\Administrators", r.stdout)
        self.assertIn("DO NOT COMMIT", r.stdout)

    # L4 -------------------------------------------------------------------
    def test_l4_empty_dacl_is_a_violation(self):
        objs = locked_objects()
        objs[2] = file_obj(objs[2]["path"], aces=[])
        with tempfile.TemporaryDirectory() as td:
            fixture = write_fixture(Path(td), objs)
            r = run_cli("--acl-json", str(fixture))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("EMPTY DACL", r.stdout)

    # L5 -------------------------------------------------------------------
    def test_l5_directory_boundary_must_be_explicit_and_protected(self):
        objs = locked_objects()
        objs[1] = dir_obj(objs[1]["path"], aces=[ace(inherited=True, inh=cca.DIR_FLAGS)],
                          protected=False)
        with tempfile.TemporaryDirectory() as td:
            fixture = write_fixture(Path(td), objs)
            r = run_cli("--acl-json", str(fixture))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("inherited ACE present", r.stdout)
        self.assertIn("inheritance not broken", r.stdout)

    # L6 -------------------------------------------------------------------
    def test_l6_directory_ace_must_propagate(self):
        objs = locked_objects()
        objs[0] = dir_obj(objs[0]["path"], aces=[ace()])  # explicit but flags None
        with tempfile.TemporaryDirectory() as td:
            fixture = write_fixture(Path(td), objs)
            r = run_cli("--acl-json", str(fixture))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("dir ACE inheritance flags", r.stdout)

    # L7 -------------------------------------------------------------------
    def test_l7_inherit_only_file_ace_is_a_violation(self):
        # the real 2026-10-12 bug shape: /grant:r "user:(OI)(CI)F" applied to a FILE
        objs = locked_objects()
        objs[2] = file_obj(objs[2]["path"],
                           aces=[ace(inh=cca.DIR_FLAGS, prop="InheritOnly")])
        with tempfile.TemporaryDirectory() as td:
            fixture = write_fixture(Path(td), objs)
            r = run_cli("--acl-json", str(fixture))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("file ACE flags", r.stdout)
        self.assertIn("InheritOnly", r.stdout)

    # L8 -------------------------------------------------------------------
    def test_l8_foreign_owner_is_a_violation(self):
        objs = locked_objects()
        objs[3] = file_obj(objs[3]["path"], owner="NT AUTHORITY\\SYSTEM")
        with tempfile.TemporaryDirectory() as td:
            fixture = write_fixture(Path(td), objs)
            r = run_cli("--acl-json", str(fixture))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("owner is", r.stdout)

    # L9 -------------------------------------------------------------------
    def test_l9_sole_ace_must_be_allow_and_full_control(self):
        objs = locked_objects()
        objs[2] = file_obj(objs[2]["path"], aces=[ace(allow=False, rights="Modify")])
        with tempfile.TemporaryDirectory() as td:
            fixture = write_fixture(Path(td), objs)
            r = run_cli("--acl-json", str(fixture))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("sole ACE is not Allow", r.stdout)
        self.assertIn("sole ACE rights are 'Modify'", r.stdout)

    # L10 ------------------------------------------------------------------
    def test_l10_inherited_file_ace_is_refused_until_explicit(self):
        objs = locked_objects()
        objs.append(file_obj(f"{ROOT}\\router-key-file\\new.dat",
                             aces=[ace(inherited=True)]))
        with tempfile.TemporaryDirectory() as td:
            fixture = write_fixture(Path(td), objs)
            r = run_cli("--acl-json", str(fixture))
        self.assertEqual(r.returncode, 1,
                         "the state a freshly added file arrives in must fail until its "
                         "ACE is converted to explicit: " + r.stdout + r.stderr)
        self.assertIn("inherited ACE present", r.stdout)

    # L11 ------------------------------------------------------------------
    def test_l11_unreadable_or_malformed_probe_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bad_json = tmp / "bad.json"
            bad_json.write_text("{ this is not json", encoding="utf-8")
            r1 = run_cli("--acl-json", str(bad_json))
            missing_field = tmp / "missing.json"
            missing_field.write_text(json.dumps(
                {"user": USER, "objects": [{"path": "x", "aces": [{"identity": USER}]}]}),
                encoding="utf-8")
            r2 = run_cli("--acl-json", str(missing_field))
            r3 = run_cli("--acl-json", str(tmp / "absent.json"))
        for r in (r1, r2, r3):
            self.assertEqual(r.returncode, 255, r.stdout + r.stderr)
            self.assertIn("FAIL-CLOSED", r.stderr)

    # L12 ------------------------------------------------------------------
    def test_l12_single_object_json_normalizes(self):
        single = json.dumps({"user": USER,
                             "objects": {"path": ROOT, "is_dir": True, "owner": USER,
                                         "protected": True, "aces": ace(inh=cca.DIR_FLAGS)}})
        facts = cca.parse_facts(single)
        self.assertEqual(len(facts["objects"]), 1)
        self.assertIsInstance(facts["objects"][0]["aces"], list)
        self.assertEqual(cca.evaluate(facts), [])

    # L13 ------------------------------------------------------------------
    @unittest.skipUnless(os.name == "nt", "the ACL probe is Windows-only")
    def test_l13_probe_emits_metadata_only(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "any-file.dat").write_bytes(b"contents must never be read or emitted")
            facts = cca.gather(tmp)
            paths = [o["path"] for o in facts["objects"]]
        self.assertTrue(facts["user"], "the probe must report the identity to compare with")
        self.assertIn("\\", facts["user"],
                      "identity must be domain-qualified ([WindowsIdentity] style); a "
                      "bare whoami-style name broke every comparison once")
        self.assertTrue(any(p.casefold() == str(tmp).casefold() for p in paths), paths)
        for o in facts["objects"]:
            self.assertEqual(sorted(o), sorted(cca.OBJ_FIELDS),
                             "probe records must carry ACL facts only, never contents")
            self.assertIsInstance(o["aces"], list)

    # L14 ------------------------------------------------------------------
    def test_l14_exit_code_is_the_bad_object_count(self):
        objs = locked_objects()
        objs[2] = file_obj(objs[2]["path"], aces=[])                    # bad object 1
        objs[3] = file_obj(objs[3]["path"], owner="NT AUTHORITY\\SYSTEM")  # bad object 2
        with tempfile.TemporaryDirectory() as td:
            fixture = write_fixture(Path(td), objs)
            two = run_cli("--acl-json", str(fixture))
        self.assertEqual(two.returncode, 2,
                         "exit code = number of bad objects: " + two.stdout + two.stderr)
        objs[4] = file_obj(objs[4]["path"], aces=[ace(rights="Modify")])  # bad object 3
        with tempfile.TemporaryDirectory() as td:
            fixture = write_fixture(Path(td), objs)
            three = run_cli("--acl-json", str(fixture))
        self.assertEqual(three.returncode, 3, three.stdout + three.stderr)

    # L15 ------------------------------------------------------------------
    def test_l15_legacy_custody_folder_fails_closed_not_na(self):
        # ADR-0003: a machine that still has .secrets/smart-router has not migrated
        with tempfile.TemporaryDirectory() as td:
            secrets = Path(td) / ".secrets"
            (secrets / "smart-router").mkdir(parents=True)
            root = secrets / "holdshort"
            with self.assertRaises(cca.FailClosed):
                cca.na_reason(root, platform="nt")            # new root absent: not N/A
            root.mkdir()
            with self.assertRaises(cca.FailClosed):
                cca.na_reason(root, platform="nt")            # both present: still refused
            self.assertIn("N/A", cca.na_reason(root, platform="linux"))
            r = run_cli("--root", str(root))
            if os.name == "nt":
                self.assertEqual(r.returncode, cca.FAIL_CLOSED, r.stdout + r.stderr)
                self.assertIn("legacy custody folder", r.stderr)
            (secrets / "smart-router").rmdir()
            self.assertIsNone(cca.na_reason(root, platform="nt"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
