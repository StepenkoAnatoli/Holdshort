"""Regression coverage for project-owned credential inventory boundaries."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_credential_hygiene as hygiene
import check_custody_acl as acl


class ProjectScope(unittest.TestCase):
    def test_default_inventory_excludes_sibling_projects(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            sibling = home / ".secrets" / "unrelated-project"
            sibling.mkdir(parents=True)
            (sibling / "key.txt").write_text("unrelated fixture", encoding="utf-8")
            with patch.object(hygiene, "user_home", return_value=home):
                selected = hygiene.resolve_secrets_dir(None)
                self.assertEqual(selected, home / ".secrets" / "smart-router")
                names, _ = hygiene.plaintext_names(selected)
                self.assertEqual(names, [])

    def test_acl_default_is_scoped_and_explicit_override_remains_available(self):
        home = Path("C:/fixture-user")
        self.assertEqual(acl.default_root({"USERPROFILE": str(home), "HOME": "C:/decoy"}),
                         home / ".secrets" / "smart-router")
        self.assertEqual(hygiene.resolve_secrets_dir(Path("explicit-project")),
                         Path("explicit-project"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
