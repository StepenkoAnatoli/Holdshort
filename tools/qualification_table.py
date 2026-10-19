#!/usr/bin/env python3
"""Generate docs/evidence/qualification-table.md from every calibration evidence folder the evidence check accepts.

docs/proposals/calibration-first-onboarding.md Item 4.4. The table is generated, never edited by hand: the regression
gate runs `--check`, which exits 1 when the committed table differs from the generated one.

usage: qualification_table.py [--check] [--table PATH] [FOLDER ...]

FOLDER defaults to the evidence check's own discovery (tools/check_calibration_evidence.py). The check runs first; on any
failure its lines are printed and nothing is written (exit 1). Without --check the table is written to PATH (default
docs/evidence/qualification-table.md), exit 0. With --check nothing is written; exit 0 when PATH holds exactly the
generated table, else 1.

One row per (host, profile, category): the profile's model, effort and config as the folder's protocol names them,
the grade per run in run order, the adjudication schema and prongs each run's review grade rests on, the caveats, and
a pass count that excludes every caveated PASS. Profiles are labelled as the folders label them; a host adapter's
profile ids are not assumed.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "docs" / "evidence" / "qualification-table.md"


def _load_check():
    spec = importlib.util.spec_from_file_location("check_calibration_evidence", ROOT / "tools" / "check_calibration_evidence.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CHECK = _load_check()
CASES = ("pin", "fix", "review")
LEGACY_CATEGORY = {"pin": "pin-tests", "fix": "fix", "review": "review"}  # the host's rule 4 for the pin case

DOES_NOT_SUPPORT = (
    "No ordering between models: each cell is one observation under one run's protocol; no row ranks a model, an effort "
    "or a profile above another, however the counts compare.",
    "No cross-host comparison outside the shared pack's cells: a host pack is graded on that host's own code, so only "
    "cells graded on the shared subject pack compare across hosts.",
    "No claim about tiers it did not run: a cell speaks for the tier its run graded (runs 1-3 record no tier), and nothing "
    "here extends to a tier no run graded.",
    "No qualification: the host's rules qualify a profile for a category, from the runs this table lists; the table counts "
    "passes and names caveats, and grants nothing.",
)


def esc(v) -> str:
    return str(v).replace("|", "\\|").replace("\n", " ")


def host_of(folder: Path, protocol: dict) -> str:
    m = CHECK.FOLDER_NAME.match(folder.name)
    return m.group("host") if m else str(protocol.get("host") or folder.name)


def run_number(folder: Path, position: int) -> int:
    """The run's number from its folder name (<host>-calibration-<n>; no suffix is run 1), as the folders number their
    runs; a folder named otherwise keeps its position among the host's runs."""
    m = CHECK.FOLDER_NAME.match(folder.name)
    return int(m.group("n") or 1) if m else position


def profile_entries(protocol: dict) -> list[dict]:
    """The protocol's profile entries that name a key; the check does not read them, so a malformed one is left out."""
    lists = [protocol.get(k) for k in ("profiles", "review_only_profiles")]
    return [p for v in lists if isinstance(v, list) for p in v if isinstance(p, dict) and isinstance(p.get("key"), str)]


def grade_of(case: str, sc: dict) -> str:
    if "ungraded" in sc:
        return "UNGRADED"
    if case == "review" and sc.get("result") in ("PASS", "PARTIAL", "FAIL"):
        return sc["result"]
    return "PASS" if sc.get("pass") is True else "FAIL"


class Run:
    def __init__(self, n: int, report):
        self.n, self.r = n, report
        self.folder, self.protocol, self.scores = report.folder, report.protocol, report.scores
        self.category = dict(LEGACY_CATEGORY)
        mapping = self.scores.get("category_mapping")
        if isinstance(mapping, dict):  # the check accepted it: pin is pin-tests
            self.category.update({c: mapping[c] for c in CASES if isinstance(mapping.get(c), str)})

    def label(self) -> str:
        return f"run {self.n} ({self.scores.get('run_id') or self.protocol.get('run_id')})"

    def adjudication(self) -> str:
        prongs = self.r.review_prongs
        if prongs is None:
            return f"run {self.n}: none"
        missing = [p for p in CHECK.PRONGS if p not in prongs]
        return (f"run {self.n}: schema {self.scores.get('schema_version')}, {'+'.join(prongs)}"
                + (f" (missing {', '.join(missing)})" if missing else ""))

    def cell(self, profile: str, case: str):
        """(text, grade, caveats) or None when the run holds no cell for the profile and case."""
        sc = (self.scores.get("profiles") or {}).get(profile, {})
        sc = sc.get(case) if isinstance(sc, dict) else None
        if not isinstance(sc, dict):
            if f"{case}:{profile}" in (self.scores.get("void_cells") or {}):
                return "void", "void", ["void"]
            return None
        grade, caveats = grade_of(case, sc), []
        if case == "review" and grade == "PASS":
            if profile in self.r.flagged:
                caveats.append(f"{len(self.r.review_prongs or [])}-prong, would fail")
            if profile in self.r.unadjudicated:
                caveats.append("unadjudicated")
            if self.r.bootstrap_judge:
                caveats.append("judge not qualified")
        if sc.get("supplementary_run"):
            caveats.append("supplementary")
        return (grade + (f" ({', '.join(caveats)})" if caveats else "")), grade, caveats


def host_section(host: str, runs: list[Run]) -> list[str]:
    out = [f"## Host: {host}", "", "| run | folder | run id | supplementary run | kind | review grades rest on |", "|---|---|---|---|---|---|"]
    for run in runs:
        out.append(f"| {run.n} | `{CHECK.label(run.folder)}` | {esc(run.scores.get('run_id'))} | {esc(run.scores.get('supplementary_run_id') or '-')} | "
                   f"{run.r.kind} | {esc(run.adjudication().split(': ', 1)[1])} |")
    order, seen = [], {}
    for run in runs:
        for e in profile_entries(run.protocol):
            key = e.get("key")
            if key not in seen:
                order.append(key)
                seen[key] = []
            seen[key].append(e)
        for p in run.scores.get("profiles") or {}:
            if p not in seen:
                order.append(p)
                seen[p] = []
    head = ["profile", "model", "effort", "config", "category", "tier"] + [r.label() for r in runs] + ["passes", "adjudication", "caveats"]
    out += ["", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for p in order:
        names = lambda k: " / ".join(dict.fromkeys(str(e.get(k)) for e in seen[p] if e.get(k) is not None)) or "not named"  # noqa: E731
        for case in CASES:
            cells = [(run, run.cell(p, case)) for run in runs]
            if not any(c for _, c in cells):
                continue
            categories = sorted({run.category[case] for run, c in cells if c})
            tiers = sorted({str(((run.scores.get("profiles") or {}).get(p) or {}).get(case, {}).get("tier")) for run, c in cells
                            if c and isinstance(((run.scores.get("profiles") or {}).get(p) or {}).get(case), dict)
                            and ((run.scores.get("profiles") or {}).get(p) or {}).get(case, {}).get("tier")})
            graded = [(run, c) for run, c in cells if c and c[1] != "void"]
            counted = sum(1 for _, c in graded if c[1] == "PASS" and not c[2])
            caveats = "; ".join(f"run {run.n}: {', '.join(c[2])}" for run, c in cells if c and c[2]) or "-"
            adjudication = "mechanical" if case != "review" else "; ".join(run.adjudication() for run, c in cells if c)
            row = [p, names("model"), names("effort"), names("config"), " / ".join(categories), ", ".join(tiers) or "not recorded"]
            row += [c[0] if c else "-" for _, c in cells]
            row += [f"{counted} of {len(graded)}", adjudication, caveats]
            out.append("| " + " | ".join(esc(v) for v in row) + " |")
    return out


def generate(folders: list[Path] | None = None, reports=None) -> str:
    reports = reports if reports is not None else [CHECK.check_folder(f) for f in (folders if folders is not None else CHECK.discover())]
    hosts: dict[str, list] = {}
    for r in sorted(reports, key=lambda r: CHECK.run_key(r.folder)):
        hosts.setdefault(host_of(r.folder, r.protocol), []).append(r)
    out = [
        "# Qualification table",
        "",
        "Generated by `tools/qualification_table.py` from every calibration evidence folder `tools/check_calibration_evidence.py` "
        "accepts; do not edit it by hand. The regression gate runs `python3 tools/qualification_table.py --check`, which fails "
        "when this file differs from the generated table.",
        "",
        "## What this table does not support",
        "",
        *[f"- {s}" for s in DOES_NOT_SUPPORT],
        "",
        "## How to read it",
        "",
        "- One row per host, profile and category. Model, effort and config are as the run's protocol names them (`not named` "
        "when it names none); profiles carry the folders' labels, not a host adapter's profile ids. The pin case is the host "
        "category `pin-tests` (the host's rule 4) whatever a protocol labels it.",
        "- A run column holds that run's grade for the cell: `PASS`, `PARTIAL`, `FAIL`, `UNGRADED`, `void`, or `-` when the "
        "run did not grade the profile on the category. A caveat is written after the grade in parentheses.",
        "- Caveats: `2-prong, would fail` - a review PASS that holds only because the lens schema lacked a prong of the "
        "classification (it fails under the full definition); `unadjudicated` - a review PASS from a run with no adjudication "
        "record; `supplementary` - a cell graded in a supplementary run that replaced a void main-run cell; `void` - a void cell "
        "with no replacement; `judge not qualified` - a review PASS judged under the bootstrap limitation.",
        "- `passes` counts the uncaveated PASSes of the row's graded cells: a PASS with any caveat is shown and not counted.",
        "- `adjudication` names, per run, the schema version (`scores.json` `schema_version`) and the prongs the review grade "
        "rests on; `none` means no adjudication record; pin and fix are graded mechanically.",
        "",
        "## Limitations the evidence check recorded",
        "",
    ]
    limits = [f"- `LIMIT {CHECK.label(r.folder)} {rule}: {text}`" for r in sorted(reports, key=lambda r: CHECK.run_key(r.folder)) for rule, text in r.limits]
    out += limits or ["- none"]
    for host, rs in hosts.items():
        out += [""] + host_section(host, [Run(run_number(r.folder, i), r) for i, r in enumerate(rs, 1)])
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when the table at --table differs from the generated one")
    ap.add_argument("--table", type=Path, default=TABLE)
    ap.add_argument("folders", nargs="*", type=Path)
    a = ap.parse_args(argv)
    reports = CHECK.check_folders(a.folders or CHECK.discover())
    failed = [(r, rule, text) for r in reports for rule, text in r.failures]
    if failed:
        for r, rule, text in failed:
            print(f"FAIL {CHECK.label(r.folder)} {rule}: {text}")
        print("qualification_table: refused: the evidence check fails; nothing written")
        return 1
    text = generate(reports=reports)
    shown = CHECK.label(a.table)
    if a.check:
        try:
            current = a.table.read_text(encoding="utf-8")
        except OSError:
            current = None
        if current != text:
            print(f"qualification_table: {shown} differs from the generated table; run python3 tools/qualification_table.py and commit the result")
            return 1
        print(f"qualification_table: {shown} is the generated table")
        return 0
    a.table.parent.mkdir(parents=True, exist_ok=True)
    a.table.write_text(text, encoding="utf-8")
    print(f"qualification_table: written {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
