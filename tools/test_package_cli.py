"""Source-only checks must never pass against the installed wheel's missing files."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import package_cli

ROOT = Path(__file__).resolve().parents[1]


class CheckoutCommands(unittest.TestCase):
    def test_empty_directory_is_refused_without_running_a_check(self):
        with tempfile.TemporaryDirectory() as td, patch.object(package_cli.subprocess, "call") as call:
            for command in (package_cli.validate_skills, package_cli.regression):
                with self.subTest(command=command.__name__), contextlib.redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(command(["--repo", td]), 2)
                    self.assertIn("source checkout", err.getvalue())
            call.assert_not_called()

    def test_checkout_and_flags_are_passed_as_arguments(self):
        with patch.object(package_cli.subprocess, "call", return_value=7) as call:
            self.assertEqual(package_cli.validate_skills(["--repo", str(ROOT), "--strict"]), 7)
            args, kwargs = call.call_args
            self.assertEqual(args[0][-1], "--strict")
            self.assertEqual(Path(args[0][1]), ROOT / "tools" / "validate_skills.py")
            self.assertEqual(kwargs["cwd"], ROOT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
