#!/usr/bin/env python3
# Lineage: generalises the results pull request of calibration run 3 (#101: its branch, its file list, its body in this
# repository's template), printed instead of opened, as proposal Item 4.2 asks.
"""Print the results pull request for one calibration evidence folder, and ask the operator to open it.

usage: request.py RESULTS_DIR [--repo-root ROOT] [--branch NAME] [--issue N]

RESULTS_DIR is the run's evidence folder (docs/evidence/<date>/<host>-calibration-<n>/) holding at least protocol.json
and scores.json (observations.py writes the rest). It prints the branch name, the files, a title and a pull-request
body in this repository's template (Problem and resulting behavior; Related issue; Validation; Remaining limits or
risks) filled from the protocol and the scores, and ends with the sentence that asks the operator to open the pull
request. It runs no command: no git, no push, no pull request. The operator's push is the operator's consent that the
evidence may be shared, which no agent gives for them. Exit 0 when printed, 2 when an input is missing or unreadable.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SECTIONS = ("## Problem and resulting behavior", "## Related issue", "## Validation", "## Remaining limits or risks")
OPERATOR = ("Operator: please open the pull request yourself - push the branch {branch} and open it with the title and body above. "
            "This kit never pushes and never opens a pull request: your push is your consent that this evidence may be shared, "
            "and the pull request is then reviewed like any other, by a reviewer who did not run it.")


def load(path: Path, what: str) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"request.py: refused: {what} not found: {path}")
    except (OSError, ValueError) as e:
        raise SystemExit(f"request.py: refused: {what} unreadable: {path} ({e})")
    if not isinstance(doc, dict):
        raise SystemExit(f"request.py: refused: {what} is not an object: {path}")
    return doc


def body(protocol: dict, scores: dict, issue: str | None) -> list[str]:
    pack = protocol.get("subject_pack") or scores.get("pack") or {}
    profiles = [p.get("key") for p in protocol.get("profiles") or []]
    review_only = [p.get("key") for p in protocol.get("review_only_profiles") or []]
    cases = protocol.get("cases") or []
    cells = (scores.get("totals") or {}).get("cells") or {}
    non_pass = (scores.get("totals") or {}).get("non_pass") or []
    schema = scores.get("adjudication_schema") or {}
    judge = protocol.get("judging_profile") or {}
    relayed = protocol.get("relayed_operator_text") or {}
    would_fail = [f"review:{p} PASS (2-prong, would fail)" for p, s in sorted((scores.get("profiles") or {}).items())
                  if (s.get("review") or {}).get("would_fail_under_three_prong")]
    out = [SECTIONS[0], ""]
    out.append(f"Calibration results for the host {protocol.get('host')}: {len(profiles)} profiles ({', '.join(profiles)})"
               + (f" plus {len(review_only)} review-only ({', '.join(review_only)})" if review_only else "")
               + f" on the subject pack {pack.get('pack')} version {pack.get('pack_version')} ({pack.get('kind')} pack), cases "
               + ", ".join(f"{c.get('id')} ({c.get('category')}, {c.get('tier')})" for c in cases)
               + f". Run {scores.get('run_id') or protocol.get('run_id')}"
               + (f" with the supplementary run {scores.get('supplementary_run_id')}" if scores.get("supplementary_run_id") else "")
               + f"; the protocol was frozen at {protocol.get('frozen_at')} on revision {protocol.get('revision')}, before the launch.")
    out.append("")
    for case, text in cells.items():
        out.append(f"- {case}: {text}")
    if non_pass:
        out.append(f"- not PASS: {', '.join(non_pass)}")
    out.append("")
    out.append("The results support qualification decisions under the host's own rules; nothing in this folder changes a host policy.")
    out += ["", SECTIONS[1], ""]
    out.append(f"Related to #{issue}" if issue else
               "Related to the calibration-first onboarding proposal (docs/proposals/calibration-first-onboarding.md); no issue number was given (--issue).")
    out += ["", SECTIONS[2], ""]
    out.append(f"- The frozen protocol: protocol.json, run id {protocol.get('run_id')}, frozen at {protocol.get('frozen_at')}, amendments "
               + (", ".join(a.get("id", "?") for a in protocol.get("amendments") or []) or "none") + ".")
    out.append("- scores.json and observations.json built by tools/calibration/observations.py from the harness journal, the run file, "
               "the pack manifest and grade.sh's grades; every review grade under the classification's prongs.")
    missing = schema.get("missing_prong") or []
    out.append(f"- Prongs: the classification declares {', '.join(schema.get('prongs_in_classification') or [])}; the lens schema carried "
               f"{', '.join(schema.get('prongs_in_lens_schema') or []) or 'no lens records'}"
               + (f"; missing from the lens schema: {', '.join(missing)}" if missing else "") + ".")
    q = judge.get("qualification")
    out.append(f"- Judging: judging profile {judge.get('key')} ({judge.get('model')}, {judge.get('effort')}); "
               + (f"qualification: {q}." if q else f"{judge.get('limitation')}."))
    out.append(f"- Relayed operator text: {relayed.get('statement')}"
               + (f' (recorded before the launch: "{relayed.get("text")}")' if relayed.get("text") else "") + ".")
    out.append("- Not run by this printer: `python3 tools/run_regression.py` (check_secrets included) on the commit that adds this "
               "folder; run it and replace this line with its result.")
    out += ["", SECTIONS[3], ""]
    for limit in protocol.get("limits") or []:
        out.append(f"- {limit}")
    for row in would_fail:
        out.append(f"- {row}: a PASS under the run's rule that fails under the full three-prong definition; it is not an ordinary PASS.")
    if judge.get("limitation") and not q:
        out.append(f"- {judge.get('limitation')}")
    for a in protocol.get("amendments") or []:
        out.append(f"- amendment {a.get('id')}: {a.get('change')}")
    out.append("- No model ranking, no cross-host comparison outside a shared pack's cells, and no claim about tiers the run did not run.")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="print the results pull request for a calibration evidence folder")
    ap.add_argument("results", type=Path)
    ap.add_argument("--repo-root", type=Path, default=Path("."))
    ap.add_argument("--branch")
    ap.add_argument("--issue")
    a = ap.parse_args(argv)
    try:
        if not a.results.is_dir():
            raise SystemExit(f"request.py: refused: not a directory: {a.results}")
        missing = [n for n in ("protocol.json", "scores.json") if not (a.results / n).is_file()]
        if missing:
            raise SystemExit(f"request.py: refused: {a.results} has no {' and no '.join(missing)} (observations.py writes scores.json; the frozen protocol.json is copied in)")
        protocol = load(a.results / "protocol.json", "protocol.json")
        scores = load(a.results / "scores.json", "scores.json")
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 2
    folder = a.results.resolve()
    try:
        rel = folder.relative_to(a.repo_root.resolve())
    except ValueError:
        rel = a.results
    branch = a.branch or f"evidence/{folder.name}"
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    pack = protocol.get("subject_pack") or {}
    lines = [f"Branch: {branch}", "", "Files:"]
    lines += [f"  {rel.as_posix()}/{p.relative_to(folder).as_posix()}" for p in files]
    lines += ["", f"Title: evidence: {folder.name} ({pack.get('pack')} version {pack.get('pack_version')})", "", "Body:", ""]
    lines += body(protocol, scores, a.issue)
    lines += ["", OPERATOR.format(branch=branch)]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
