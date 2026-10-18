#!/usr/bin/env python3
"""tools/qualification_table.py: the generated qualification table (docs/proposals/calibration-first-onboarding.md, Item 4.4).

Hermetic: it reads the committed evidence folders and the synthetic fixtures under tests/fixtures/calibration-evidence/;
every write goes to a temporary directory. Nothing here calls a provider, reads a credential or needs the network.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "qualification_table.py"
TABLE = ROOT / "docs" / "evidence" / "qualification-table.md"
FIXTURES = ROOT / "tests" / "fixtures" / "calibration-evidence"
RUNS = ["docs/evidence/2026-10-17/claude-code-calibration", "docs/evidence/2026-10-17/claude-code-calibration-2",
        "docs/evidence/2026-10-18/claude-code-calibration-3"]
CATEGORY = {"pin": "pin-tests", "fix": "fix", "review": "review"}


def load_tool():
    spec = importlib.util.spec_from_file_location("qualification_table", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_tool(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, timeout=120, cwd=ROOT)


def rows(markdown: str) -> dict:
    """(host, profile, category) -> {column: cell}, from every host section's main table."""
    out, host, head = {}, None, None
    for line in markdown.splitlines():
        m = re.match(r"^## Host: (.+)$", line)
        if m:
            host, head = m.group(1), None
            continue
        if host is None or not line.startswith("| "):
            if not line.startswith("|"):
                head = None if not line.strip() else head
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if cells[0] == "profile":
            head = cells
            continue
        if head is None or set(line.replace("|", "").strip()) <= {"-", " "}:
            continue
        row = dict(zip(head, cells))
        out[(host, row["profile"], row["category"])] = row
    return out


def run_column(row: dict, n: int) -> str:
    return next(v for k, v in row.items() if k.startswith(f"run {n} "))


class Table(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = load_tool().generate()
        cls.rows = rows(cls.text)

    def test_one_row_per_profile_and_category_the_folders_hold(self):
        want = set()
        for rel in RUNS:
            scores = json.loads((ROOT / rel / "scores.json").read_text())
            for p, s in scores["profiles"].items():
                want |= {("claude-code", p, CATEGORY[c]) for c, e in s.items() if c in CATEGORY and e is not None}
        self.assertEqual(set(self.rows), want)
        self.assertEqual(len(self.rows), 39)  # 12 profiles x 3 categories, plus 3 review-only profiles

    def test_model_effort_and_config_as_the_protocols_name_them(self):
        row = self.rows[("claude-code", "opus-max", "review")]
        self.assertEqual((row["model"], row["effort"], row["config"]), ("opus", "max", "not named"))
        row = self.rows[("claude-code", "haiku-low", "pin-tests")]
        self.assertEqual((row["model"], row["effort"]), ("haiku", "low"))

    def test_run3_flagged_cells_read_two_prong_would_fail_and_do_not_count(self):
        for p in ("haiku-medium", "haiku-high"):
            row = self.rows[("claude-code", p, "review")]
            self.assertEqual(run_column(row, 3), "PASS (2-prong, would fail)")
            self.assertEqual((run_column(row, 1), run_column(row, 2)), ("FAIL", "FAIL"))
            self.assertEqual(row["passes"], "0 of 3")
            self.assertIn("run 3: 2-prong, would fail", row["caveats"])

    def test_runs_1_2_review_passes_read_unadjudicated_and_do_not_count(self):
        row = self.rows[("claude-code", "opus-high", "review")]
        self.assertEqual([run_column(row, n) for n in (1, 2, 3)], ["PASS (unadjudicated)", "PASS (unadjudicated)", "PASS"])
        self.assertEqual(row["passes"], "1 of 3")
        row = self.rows[("claude-code", "opus-max", "review")]
        self.assertEqual([run_column(row, n) for n in (1, 2, 3)], ["-", "PASS (unadjudicated)", "PASS"])
        self.assertEqual(row["passes"], "1 of 2")
        row = self.rows[("claude-code", "sonnet-low", "review")]
        self.assertEqual([run_column(row, n) for n in (1, 2, 3)], ["PASS (unadjudicated)", "PARTIAL", "PASS"])

    def test_supplementary_cells_are_caveated_and_do_not_count(self):
        row = self.rows[("claude-code", "haiku-high", "fix")]
        self.assertEqual(run_column(row, 3), "PASS (supplementary)")
        self.assertEqual(row["passes"], "2 of 3")
        row = self.rows[("claude-code", "haiku-low", "review")]
        self.assertEqual(run_column(row, 3), "PASS (supplementary)")
        self.assertEqual(row["passes"], "0 of 3")

    def test_pin_and_fix_cells_count_and_rest_on_no_adjudication(self):
        row = self.rows[("claude-code", "fable-medium", "pin-tests")]
        self.assertEqual([run_column(row, n) for n in (1, 2, 3)], ["PASS", "PASS", "FAIL"])
        self.assertEqual(row["passes"], "2 of 3")
        self.assertEqual(row["adjudication"], "mechanical")

    def test_review_rows_name_the_schema_and_prongs_each_run_rests_on(self):
        row = self.rows[("claude-code", "fable-high", "review")]
        self.assertEqual(row["adjudication"], "run 1: none; run 2: none; run 3: schema 1, holds+reachable (missing forbidden)")

    def test_the_header_states_what_the_table_does_not_support(self):
        tool = load_tool()
        self.assertEqual(len(tool.DOES_NOT_SUPPORT), 4)
        for s in tool.DOES_NOT_SUPPORT:
            self.assertIn(f"- {s}", self.text)
        for words in ("No ordering between models", "No cross-host comparison outside the shared pack's cells",
                      "No claim about tiers it did not run", "No qualification: the host's rules qualify"):
            self.assertIn(words, self.text)
        head = self.text.split("## Host:", 1)[0]
        self.assertIn("## What this table does not support", head)

    def test_the_run_legend_names_each_run_id_and_the_limitations(self):
        for rid in ("wf_052c5f34-973", "wf_fe91e1d6-d78", "wf_4e9ef48d-066", "wf_dbe29a64-3b2"):
            self.assertIn(rid, self.text)
        self.assertIn("LIMIT docs/evidence/2026-10-18/claude-code-calibration-3 fewer-prong-pass-flagged", self.text)

    def test_generation_is_deterministic(self):
        self.assertEqual(load_tool().generate(), self.text)


class Docs(unittest.TestCase):
    def test_the_evidence_readme_says_what_the_table_supports_and_does_not(self):
        text = (ROOT / "docs" / "evidence" / "README.md").read_text(encoding="utf-8")
        section = text.split("## Qualification table", 1)[1].split("\n## ", 1)[0]
        for s in load_tool().DOES_NOT_SUPPORT:
            self.assertIn(s.split(":", 1)[0], section)
        for words in ("qualification_table.py --check", "PASS (2-prong, would fail)", "PASS (unadjudicated)", "supplementary", "not counted"):
            self.assertIn(words, section, words)


class Gate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_check_passes_on_the_committed_table(self):
        p = run_tool("--check")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(TABLE.read_text(encoding="utf-8"), load_tool().generate())

    def test_check_fails_on_an_edited_copy(self):
        copy = self.root / "table.md"
        text = TABLE.read_text(encoding="utf-8")
        for edited in (text.replace("PASS (2-prong, would fail)", "PASS", 1), text + "\n", text.replace("0 of 3", "1 of 3", 1)):
            copy.write_text(edited, encoding="utf-8")
            p = run_tool("--check", "--table", str(copy))
            self.assertEqual(p.returncode, 1, p.stdout)
            self.assertIn("differs from the generated table", p.stdout)
        (self.root / "missing.md").unlink(missing_ok=True)
        p = run_tool("--check", "--table", str(self.root / "missing.md"))
        self.assertEqual(p.returncode, 1, p.stdout)

    def test_write_produces_the_committed_bytes(self):
        out = self.root / "out.md"
        p = run_tool("--table", str(out))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(out.read_bytes(), TABLE.read_bytes())

    def test_it_refuses_to_write_when_the_check_fails(self):
        out = self.root / "out.md"
        p = run_tool("--table", str(out), *RUNS, str(FIXTURES / "a-protocol-frozen" / "fixture-host-calibration-1"))
        self.assertEqual(p.returncode, 1)
        self.assertIn("FAIL tests/fixtures/calibration-evidence/a-protocol-frozen/fixture-host-calibration-1 protocol-frozen", p.stdout)
        self.assertIn("refused", p.stdout)
        self.assertFalse(out.exists())

    def test_a_kit_run_gets_its_own_host_section_and_counts_its_passes(self):
        out = self.root / "out.md"
        p = run_tool("--table", str(out), str(FIXTURES / "pass" / "fixture-host-calibration-1"))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        r = rows(out.read_text(encoding="utf-8"))
        self.assertEqual(set(r), {("fixture-host", "alpha-low", "pin-tests"), ("fixture-host", "alpha-low", "fix"), ("fixture-host", "beta-max", "review")})
        review = r[("fixture-host", "beta-max", "review")]
        self.assertEqual((run_column(review, 1), review["passes"], review["tier"]), ("PASS", "1 of 1", "T1"))
        self.assertEqual(review["adjudication"], "run 1: schema 1, holds+reachable+forbidden")

    def test_each_run_is_labelled_by_its_folders_run_number_not_its_position(self):
        # F6: runs 1 and 3 alone are runs 1 and 3, not runs 1 and 2; a kit run in a -calibration-4 folder is run 4
        run3_id = json.loads((ROOT / RUNS[2] / "scores.json").read_text())["run_id"]
        text = load_tool().generate([ROOT / RUNS[0], ROOT / RUNS[2]])
        row = rows(text)[("claude-code", "haiku-medium", "review")]
        self.assertEqual([k for k in row if k.startswith("run ")], [f"run 1 ({json.loads((ROOT / RUNS[0] / 'scores.json').read_text())['run_id']})", f"run 3 ({run3_id})"])
        self.assertEqual(run_column(row, 3), "PASS (2-prong, would fail)")
        self.assertTrue(row["adjudication"].startswith("run 1: none; run 3: schema"), row["adjudication"])
        self.assertIn("run 3: 2-prong, would fail", row["caveats"])
        self.assertIn(f"| 3 | `{RUNS[2]}` | {run3_id} |", text)
        self.assertNotIn("run 2", text.split("## Host: claude-code", 1)[1])
        folder = self.root / "k" / "fixture-host-calibration-4"
        shutil.copytree(FIXTURES / "pass" / "fixture-host-calibration-1", folder)
        review = rows(load_tool().generate([folder]))[("fixture-host", "beta-max", "review")]
        self.assertEqual(run_column(review, 4), "PASS")
        self.assertEqual(review["adjudication"], "run 4: schema 1, holds+reachable+forbidden")
        tool = load_tool()  # a folder with no -<n> suffix is run 1 wherever it sorts; a name of another form keeps its position
        self.assertEqual([tool.run_number(Path(n), 5) for n in ("claude-code-calibration", "claude-code-calibration-7", "results")], [1, 7, 5])

    def test_a_bootstrap_judge_caveats_the_kit_runs_review_cells(self):
        folder = self.root / "b" / "fixture-host-calibration-1"
        shutil.copytree(FIXTURES / "pass" / "fixture-host-calibration-1", folder)
        proto = json.loads((folder / "protocol.json").read_text())
        proto["judging_profile"].update(qualification=None, limitation="judging profile not independently qualified, host-declared by the lead")
        (folder / "protocol.json").write_text(json.dumps(proto, indent=1) + "\n")
        out = self.root / "out.md"
        self.assertEqual(run_tool("--table", str(out), str(folder)).returncode, 0)
        review = rows(out.read_text(encoding="utf-8"))[("fixture-host", "beta-max", "review")]
        self.assertEqual((run_column(review, 1), review["passes"]), ("PASS (judge not qualified)", "0 of 1"))


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2, exit=False).result.wasSuccessful() else 1)
