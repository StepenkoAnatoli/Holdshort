#!/usr/bin/env python3
"""Calibration evidence check: refuse a results folder whose evidence does not carry the intended rule.

docs/proposals/calibration-first-onboarding.md Item 4.3. Run in the regression gate (tools/run_regression.py).

usage: check_calibration_evidence.py [FOLDER ...]

Default folders: every docs/evidence/*/claude-code-calibration*/ and docs/evidence/*/*-calibration-*/ directory.
Each folder is checked under eight named rules:

  (a) protocol-frozen           the protocol is frozen with its run id recorded
  (b) prongs-declared           the protocol's classification prongs equal the prongs the adjudication's lens schema carried
  (c) scores-derivable          scores.json is what observations.json gives under the declared prongs (or the folder's
                                own stated pass rules, for a legacy run)
  (d) fewer-prong-pass-flagged  a review PASS that holds only because a prong is missing carries
                                would_fail_under_three_prong: true and is excluded from every pass count the folder states
  (e) pin-category-mapping      scores.json category_mapping.pin is pin-tests (the host's rule 4, not the protocol's label)
  (f) judging-profile-named     the judging profile is named with its qualification, or with the bootstrap limitation line
  (g) relayed-chat-statement    the relayed operator text is recorded verbatim, or null with the harness statement
  (h) no-secrets-or-bodies      no file matches tools/check_secrets.py's patterns; no prompt body, journal or transcript

A KIT RUN is a folder whose protocol.json carries the kit's keys (classification.prongs, judging_profile,
relayed_operator_text) at the kit template's schema_version or later; every rule applies in full. A LEGACY RUN carries
none of those keys (calibration runs 1-3 predate the kit); it is checked for what the folder can answer, and what it
cannot answer prints as a limitation, never as a pass. A legacy run is refused only for an internal contradiction.

Output, one line each:   FAIL <folder> <rule>: <text>     LIMIT <folder> <rule>: <text>
then one summary line. Exit 0 when no folder fails (a folder with limitations and no failures passes), else 1.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "tools" / "calibration"
TEMPLATE = KIT / "protocol.template.json"

RULES = ("protocol-frozen", "prongs-declared", "scores-derivable", "fewer-prong-pass-flagged", "pin-category-mapping",
         "judging-profile-named", "relayed-chat-statement", "no-secrets-or-bodies")
BOOTSTRAP = "judging profile not independently qualified"  # Item 3.3; the kit's launch step requires the same prefix
FORBIDDEN_NAMES = (re.compile(r".*\.prompt.*"), re.compile(r"journal\.jsonl"), re.compile(r"transcript.*"))
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".zip", ".pdf", ".woff", ".woff2", ".ico"}
FOLDER_NAME = re.compile(r"^(?P<host>.+?)-calibration(?:-(?P<n>[1-9]\d*))?$")
CASES = ("pin", "fix", "review")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# the kit's builder is the derivation: its vote, prong and review-result functions, not a copy of them
OBS = _load(KIT / "observations.py", "calibration_observations")
SECRETS = _load(ROOT / "tools" / "check_secrets.py", "check_secrets")
PRONGS = list(OBS.PRONGS)


class Report:
    """One folder's verdict: its failures and limitations, and what the qualification table reads from it."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.kind = None  # "kit" | "legacy"
        self.failures: list[tuple[str, str]] = []
        self.limits: list[tuple[str, str]] = []
        self.protocol: dict = {}
        self.scores: dict = {}
        self.review_prongs: list[str] | None = None  # the prongs each review grade rests on; None = unadjudicated
        self.flagged: list[str] = []  # profiles whose review PASS is flagged would-fail
        self.unadjudicated: list[str] = []  # profiles whose review PASS rests on no adjudication record

    def fail(self, rule: str, text: str) -> None:
        self.failures.append((rule, text))

    def limit(self, rule: str, text: str) -> None:
        self.limits.append((rule, text))

    @property
    def ok(self) -> bool:
        return not self.failures


def label(folder: Path) -> str:
    try:
        return folder.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return folder.as_posix()


def read_json(folder: Path, name: str):
    """(document, None) or (None, the reason it cannot be read)."""
    path = folder / name
    if not path.is_file():
        return None, f"{name} is missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as e:
        return None, f"{name} is unreadable or not JSON ({e.__class__.__name__})"


def filled(v) -> bool:
    return isinstance(v, str) and v.strip() != "" and "{{" not in v


def placeholder_at(v, at: str):
    """The path of the first {{placeholder}} left in the protocol (a value or a key), as the kit's launch step scans it;
    the relayed text is verbatim operator text and is not scanned."""
    if isinstance(v, str):
        return at if "{{" in v else None
    items = list(v.items()) if isinstance(v, dict) else list(enumerate(v)) if isinstance(v, list) else []
    for k, x in items:
        path = f"{at}.{k}" if isinstance(v, dict) else f"{at}[{k}]"
        if path == "protocol.relayed_operator_text.text":
            continue
        if isinstance(k, str) and "{{" in k:
            return path
        found = placeholder_at(x, path)
        if found:
            return found
    return None


def template_schema_version() -> int:
    return int(json.loads(TEMPLATE.read_text(encoding="utf-8")).get("schema_version") or 0)


def kit_keys(protocol: dict) -> list[str]:
    present = []
    if isinstance(protocol.get("classification"), dict) and "prongs" in protocol["classification"]:
        present.append("classification.prongs")
    for k in ("judging_profile", "relayed_operator_text"):
        if k in protocol:
            present.append(k)
    return present


def lens_records(adjudication: dict) -> dict:
    """cluster id -> its lens records, from the kit's form (clusters[].lenses) or run 3's (adjudications[].lenses)."""
    out = {}
    for c in adjudication.get("clusters") or []:
        if isinstance(c, dict) and c.get("lenses"):
            out[c.get("id")] = [x for x in c["lenses"] if isinstance(x, dict)]
    for a in adjudication.get("adjudications") or []:
        if isinstance(a, dict) and a.get("lenses"):
            out.setdefault((a.get("cluster") or {}).get("id"), [x for x in a["lenses"] if isinstance(x, dict)])
    return out


def schema_prongs(lenses: dict):
    """The prongs every lens record carries (as the kit's builder computes prongs_in_lens_schema), or None with no lens."""
    records = [x for ls in lenses.values() for x in ls]
    return [p for p in PRONGS if all(p in x for x in records)] if records else None


def review_grade_under(rg: dict, lenses: dict, prongs) -> str | None:
    """The review's PASS | PARTIAL | FAIL with every clustered blocking other counted as false blocking unless its cluster
    is real under these prongs (two votes), an unclustered one by the grader's classification; the kit's own rule."""
    if not isinstance(rg, dict) or "ungraded" in rg or rg.get("result") is None:
        return None
    blocking = 0
    for x in rg.get("others") or []:
        if not OBS.BLOCKING.search(str(x.get("severity", ""))):
            continue
        if x.get("cluster") is not None:
            if x["cluster"] not in lenses:
                raise KeyError(x["cluster"])
            real = OBS.votes(lenses[x["cluster"]], prongs) >= 2
        else:
            real = x.get("classification") == "true"
        blocking += 0 if real else 1
    truth = rg.get("truth") or {}
    grade = {"truth": [{"id": k, **(v or {})} for k, v in truth.items()], "copiedFromHistory": rg.get("copiedFromHistory")}
    return OBS.review_result(grade, blocking, list(truth))


STATED = re.compile(r"^(\d+) of (\d+) PASS(?: \((\d+) of (\d+) under the three-prong definition\))?$")


def check_stated_count(r: Report, n_pass: int, flagged: list[str]) -> None:
    """(d), second half: a pass count the folder states either excludes the flagged PASSes, or states the count that does."""
    if not flagged:
        return
    text = ((r.scores.get("totals") or {}).get("cells") or {}).get("review")
    if text is None:
        return
    m = STATED.match(str(text))
    if not m:
        r.fail("fewer-prong-pass-flagged", f"scores.json totals.cells.review {text!r} is not in the builder's form, so whether it counts the flagged PASSes cannot be read")
        return
    k, k3 = int(m.group(1)), m.group(3)
    want = n_pass - len(flagged)
    if k == want or (k3 is not None and int(k3) == want):
        return
    r.fail("fewer-prong-pass-flagged", f"scores.json totals.cells.review {text!r} counts the flagged PASSes ({', '.join(flagged)}) and states no count of {want} without them")


# ---- rules over a kit run -------------------------------------------------------------------------------------------

def kit_protocol_frozen(r: Report) -> None:
    p, rule = r.protocol, "protocol-frozen"
    try:
        sv = int(p.get("schema_version"))
    except (TypeError, ValueError):
        sv = None
    if sv is None or sv < template_schema_version():
        r.fail(rule, f"schema_version {p.get('schema_version')!r} is below the kit template's {template_schema_version()}")
    status = p.get("status")
    if not (isinstance(status, str) and (status == "frozen" or status.startswith("run complete"))):
        r.fail(rule, f"status {status!r} is neither frozen nor run complete")
    if not filled(p.get("run_id")):
        r.fail(rule, "run_id is not recorded")
    elif r.scores and r.scores.get("run_id") != p.get("run_id"):
        r.fail(rule, f"scores.json run_id {r.scores.get('run_id')!r} is not the protocol's {p.get('run_id')!r}")
    if not filled(p.get("frozen_at")):
        r.fail(rule, "frozen_at is not recorded")
    left = placeholder_at(p, "protocol")
    if left:
        r.fail(rule, f"a placeholder is left at {left}")


def kit_prongs(r: Report, adjudication: dict, lenses: dict) -> list[str] | None:
    rule = "prongs-declared"
    declared = (r.protocol.get("classification") or {}).get("prongs")
    if not (isinstance(declared, list) and declared and all(p in PRONGS for p in declared)):
        r.fail(rule, f"classification.prongs {declared!r} is not a list of the classification's prongs")
        return None
    in_schema = schema_prongs(lenses)
    if in_schema is not None and set(in_schema) != set(declared):
        r.fail(rule, f"the protocol declares {', '.join(declared)}; the adjudication record's lens schema carries {', '.join(in_schema) or 'none'}")
    if "declared-prongs" in adjudication and adjudication.get("declared-prongs") != declared:
        r.fail(rule, f"adjudication.json declared-prongs {adjudication.get('declared-prongs')!r} is not the protocol's {declared!r}")
    schema = r.scores.get("adjudication_schema") if isinstance(r.scores.get("adjudication_schema"), dict) else None
    if schema is None:
        r.fail(rule, "scores.json carries no adjudication_schema")
    else:
        if schema.get("prongs_in_classification") != declared:
            r.fail(rule, f"scores.json adjudication_schema.prongs_in_classification {schema.get('prongs_in_classification')!r} is not the protocol's {declared!r}")
        if schema.get("prongs_in_lens_schema") != in_schema:
            r.fail(rule, f"scores.json adjudication_schema.prongs_in_lens_schema {schema.get('prongs_in_lens_schema')!r} is not what the lens records carry ({in_schema!r})")
    return declared


def kit_scores(r: Report, obs: dict, lenses: dict, declared) -> dict:
    """(c): every scored value against the observations under the declared prongs; returns profile -> three-prong result."""
    rule = "scores-derivable"
    profiles = r.scores.get("profiles") if isinstance(r.scores.get("profiles"), dict) else {}
    if not isinstance(obs, dict) or not all(isinstance(o, dict) for o in obs.values()):
        r.fail(rule, "observations.json is not the flat profile map the kit writes")
        return {}
    for p in sorted(set(obs) ^ set(profiles)):
        r.fail(rule, f"profile {p} is in {'observations.json' if p in obs else 'scores.json'} only")
    three = {}
    for p in [p for p in obs if p in profiles]:
        o, s = obs[p], profiles[p] if isinstance(profiles[p], dict) else {}
        for case in ("pin", "fix"):
            t = o.get(case)
            if t is None and case not in s:
                continue
            if t is None or case not in s:
                r.fail(rule, f"{case}:{p} is in {'scores.json' if t is None else 'observations.json'} only")
                continue
            if (s[case] or {}).get("pass") is not (t.get("score") is True):
                r.fail(rule, f"{case}:{p} scores pass {(s[case] or {}).get('pass')!r}; observations.json gives {t.get('score') is True}")
        rg = o.get("review-grade")
        if rg is None and "review" not in s:
            continue
        if rg is None or "review" not in s:
            r.fail(rule, f"review:{p} is in {'scores.json' if rg is None else 'observations.json'} only")
            continue
        sr = s["review"] or {}
        try:
            want = review_grade_under(rg, lenses, declared) if declared else None
            three[p] = review_grade_under(rg, lenses, PRONGS)
        except KeyError as e:
            r.fail(rule, f"review:{p} names cluster {e.args[0]!r}, which adjudication.json does not hold")
            continue
        if declared and (sr.get("result") != want or sr.get("pass") is not (want == "PASS")):
            r.fail(rule, f"review:{p} scores {sr.get('result')!r} (pass {sr.get('pass')!r}); observations.json under the declared prongs ({', '.join(declared)}) gives {want!r}")
    return three


def kit_fewer_prong(r: Report, three: dict, declared) -> None:
    rule = "fewer-prong-pass-flagged"
    profiles = r.scores.get("profiles") or {}
    # a PASS can hold only because a prong is missing when the declared prongs miss one; with none missing, a PASS the
    # full definition does not give is a scores-derivable failure, not a flag to carry
    missing = [p for p in PRONGS if p not in (declared or [])]
    passes, flagged = [], []
    for p, s in profiles.items():
        rv = (s or {}).get("review") if isinstance(s, dict) else None
        if not isinstance(rv, dict):
            continue
        flag = rv.get("would_fail_under_three_prong")
        if rv.get("result") == "PASS":
            passes.append(p)
            if missing and p in three and three[p] != "PASS" and flag is not True:
                r.fail(rule, f"review:{p} PASS holds only under {', '.join(declared or [])} ({', '.join(missing)} missing); under all three prongs it is {three[p]}, and it does not carry would_fail_under_three_prong: true")
            if p in three and three[p] == "PASS" and flag is True:
                r.fail(rule, f"review:{p} carries would_fail_under_three_prong: true, yet it passes under all three prongs")
        elif flag is True:
            r.fail(rule, f"review:{p} carries would_fail_under_three_prong: true on a {rv.get('result')!r}, not a PASS")
        if flag is True and rv.get("result") == "PASS":
            flagged.append(p)
    r.flagged = flagged
    check_stated_count(r, len(passes), flagged)


def pin_mapping(r: Report, legacy: bool) -> None:
    rule = "pin-category-mapping"
    mapping = r.scores.get("category_mapping")
    has_pin = any(isinstance(s, dict) and "pin" in s for s in (r.scores.get("profiles") or {}).values())
    if not isinstance(mapping, dict) or "pin" not in mapping:
        if not has_pin:
            return
        if legacy:
            label_ = next((c.get("category") for c in r.protocol.get("cases") or [] if isinstance(c, dict) and c.get("id") == "pin"), None)
            r.limit(rule, f"legacy run: scores.json records no category_mapping; the protocol labels the pin case {label_}; "
                          "the table reads it as pin-tests under the host's rule 4 (run 3 amendment A-2)")
        else:
            r.fail(rule, "scores.json records no category_mapping.pin")
        return
    if mapping.get("pin") != "pin-tests":
        r.fail(rule, f"category_mapping.pin is {mapping.get('pin')!r}, not pin-tests (the host's rule 4; the protocol's label is not the mapping)")


def kit_judging(r: Report) -> None:
    rule = "judging-profile-named"
    j = r.protocol.get("judging_profile")
    if not isinstance(j, dict):
        r.fail(rule, "the protocol names no judging_profile")
        return
    missing = [k for k in ("key", "model", "effort") if not filled(j.get(k))]
    if missing:
        r.fail(rule, f"judging_profile.{', .'.join(missing)} not named")
    if filled(j.get("qualification")):
        return
    lim = j.get("limitation")
    if isinstance(lim, str) and lim.startswith(BOOTSTRAP) and "{{" not in lim:
        r.limit(rule, f"bootstrap: {lim}")
    else:
        r.fail(rule, f"judging_profile {j.get('key')!r} carries neither its qualification nor the bootstrap limitation line ({BOOTSTRAP!r}, ...)")


def kit_relayed(r: Report) -> None:
    rule = "relayed-chat-statement"
    rel = r.protocol.get("relayed_operator_text")
    if not isinstance(rel, dict) or "text" not in rel:
        r.fail(rule, "the protocol records no relayed_operator_text.text (the verbatim text, or null when nothing is relayed)")
        return
    text = rel.get("text")
    if text is not None and not (isinstance(text, str) and text.strip()):
        r.fail(rule, f"relayed_operator_text.text {text!r} is neither verbatim text nor null")
    if not filled(rel.get("statement")):
        r.fail(rule, "relayed_operator_text.statement does not say what the harness relays into workers")


def no_secrets_or_bodies(r: Report) -> None:
    rule = "no-secrets-or-bodies"
    for f in sorted(r.folder.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(r.folder).as_posix()
        if any(rx.fullmatch(f.name) for rx in FORBIDDEN_NAMES):
            r.fail(rule, f"{rel}: a prompt body, journal or transcript does not belong in an evidence folder")
            continue
        if f.suffix.lower() in BINARY:
            continue
        try:
            text = SECRETS.decode_text(f)
        except SECRETS.UnscannableError as e:
            r.fail(rule, f"{rel}: could not be scanned ({e})")
            continue
        for n, line in enumerate(text.splitlines(), 1):
            hit = next((name for name, pat in SECRETS.PATTERNS if pat.search(line)), None)
            if hit:
                r.fail(rule, f"{rel}:{n}: matches check_secrets pattern {hit}")


def check_kit(r: Report, obs, adjudication) -> None:
    lenses = lens_records(adjudication or {})
    kit_protocol_frozen(r)
    declared = kit_prongs(r, adjudication or {}, lenses) if adjudication is not None else None
    three = kit_scores(r, obs, lenses, declared) if obs is not None and r.scores else {}
    r.review_prongs = declared
    if r.scores:
        kit_fewer_prong(r, three, declared)
        pin_mapping(r, legacy=False)
    kit_judging(r)
    kit_relayed(r)


def check_legacy(r: Report, obs, adjudication) -> None:
    r.fail("protocol-frozen", "legacy run: protocol.json carries none of the kit's keys (classification.prongs, judging_profile, relayed_operator_text)")


def check_folder(folder: Path) -> Report:
    r = Report(folder)
    if not folder.is_dir():
        r.fail("protocol-frozen", f"{folder} is not a directory")
        return r
    protocol, err = read_json(folder, "protocol.json")
    if err or not isinstance(protocol, dict):
        r.fail("protocol-frozen", err or "protocol.json is not an object")
        no_secrets_or_bodies(r)
        return r
    r.protocol = protocol
    scores, err = read_json(folder, "scores.json")
    if err or not isinstance(scores, dict):
        r.fail("scores-derivable", err or "scores.json is not an object")
    else:
        r.scores = scores
    obs, err = read_json(folder, "observations.json")
    if err:
        r.fail("scores-derivable", err)
    r.kind = "kit" if kit_keys(protocol) else "legacy"
    adjudication, err = read_json(folder, "adjudication.json")
    if r.kind == "kit":
        if err or not isinstance(adjudication, dict):
            r.fail("prongs-declared", err or "adjudication.json is not an object")
            adjudication = None
        check_kit(r, obs, adjudication)
    else:
        check_legacy(r, obs, adjudication if not err else None)
    no_secrets_or_bodies(r)
    return r


def run_key(folder: Path):
    m = FOLDER_NAME.match(folder.name)
    return (folder.parent.name, m.group("host") if m else folder.name, int(m.group("n") or 1) if m else 0, folder.name)


def discover(root: Path = ROOT) -> list[Path]:
    ev = root / "docs" / "evidence"
    found = {p for pat in ("*/claude-code-calibration*", "*/*-calibration-*") for p in ev.glob(pat) if p.is_dir()}
    return sorted(found, key=run_key)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if any(a in ("-h", "--help") for a in args):
        print(__doc__)
        return 0
    folders = [Path(a) for a in args] if args else discover()
    reports = [check_folder(f) for f in folders]
    n_fail = n_limit = 0
    for r in reports:
        for rule, text in r.limits:
            print(f"LIMIT {label(r.folder)} {rule}: {text}")
            n_limit += 1
        for rule, text in r.failures:
            print(f"FAIL {label(r.folder)} {rule}: {text}")
            n_fail += 1
    print(f"check_calibration_evidence: {len(reports)} folder(s), {n_fail} failure(s), {n_limit} limitation(s)")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
