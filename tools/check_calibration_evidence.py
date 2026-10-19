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
FORBIDDEN_NAMES = (re.compile(r".*\.prompt.*", re.I), re.compile(r"journal\.jsonl", re.I), re.compile(r"transcript.*", re.I))
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
        self.legacy_others: dict = {}  # legacy run: profile -> the review grade's other findings
        self.bootstrap_judge = False  # kit run judged under the bootstrap limitation (Item 3.3: a caveat in the table)

    def fail(self, rule: str, text: str) -> None:
        self.failures.append((rule, text))

    def limit(self, rule: str, text: str) -> None:
        self.limits.append((rule, text))

    @property
    def ok(self) -> bool:
        return not self.failures


class Malformed(Exception):
    """A value in a folder's JSON of the wrong shape: reported as a FAIL under the rule that reads it, never raised out."""


def is_id(v) -> bool:
    return isinstance(v, (str, int)) and not isinstance(v, bool)


def profiles_of(r: "Report") -> dict:
    """scores.json profiles, or {} when it is not an object (scores-derivable reports that once)."""
    v = r.scores.get("profiles")
    return v if isinstance(v, dict) else {}


def cases_of(r: "Report") -> list:
    """protocol.json cases, or [] when it is not a list (scores-derivable reports that once, for a legacy run)."""
    v = r.protocol.get("cases")
    return v if isinstance(v, list) else []


def others_of(rg: dict, where: str) -> list:
    """A review grade's other findings: a list of objects, each cluster an id or null."""
    others = rg.get("others")
    if others is None:
        return []
    if not isinstance(others, list):
        raise Malformed(f"{where}.others is not a list")
    for i, x in enumerate(others):
        if not isinstance(x, dict):
            raise Malformed(f"{where}.others[{i}] is not an object")
        if x.get("cluster") is not None and not is_id(x["cluster"]):
            raise Malformed(f"{where}.others[{i}].cluster is not a cluster id")
    return others


def guarded(r: "Report", rule: str, fn, *args, default=None):
    """Run one rule; a value of a shape no guard foresaw fails that rule instead of raising (C2: a FAIL line, never a
    traceback)."""
    try:
        return fn(*args)
    except Malformed as e:
        r.fail(rule, str(e))
    except (AttributeError, TypeError, KeyError, ValueError, IndexError) as e:
        r.fail(rule, f"a value has the wrong shape for this rule ({e.__class__.__name__}: {e})")
    return default


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


def template_statuses() -> tuple[str, ...]:
    """The template's two status values ("{{frozen | run complete; ...}}"): a kit run's status is one of them exactly."""
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8")).get("status") or ""
    return tuple(s.strip() for s in raw.strip().removeprefix("{{").removesuffix("}}").split(" | "))


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
    # a cluster with no id, or lenses that are not a list, holds nothing a finding can name: its findings then fail
    # scores-derivable as naming a cluster adjudication.json does not hold
    clusters, adjudications = adjudication.get("clusters"), adjudication.get("adjudications")
    for c in clusters if isinstance(clusters, list) else []:
        if isinstance(c, dict) and is_id(c.get("id")) and isinstance(c.get("lenses"), list) and c["lenses"]:
            out[c["id"]] = [x for x in c["lenses"] if isinstance(x, dict)]
    for a in adjudications if isinstance(adjudications, list) else []:
        cid = a.get("cluster").get("id") if isinstance(a, dict) and isinstance(a.get("cluster"), dict) else None
        if is_id(cid) and isinstance(a.get("lenses"), list) and a["lenses"]:
            out.setdefault(cid, [x for x in a["lenses"] if isinstance(x, dict)])
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
    for x in others_of(rg, "observations.json review-grade"):
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
    if not isinstance(truth, dict) or not all(v is None or isinstance(v, dict) for v in truth.values()):
        raise Malformed("observations.json review-grade.truth is not an object of findings")
    grade = {"truth": [{"id": k, **(v or {})} for k, v in truth.items()], "copiedFromHistory": rg.get("copiedFromHistory")}
    return OBS.review_result(grade, blocking, list(truth))


STATED = re.compile(r"^(\d+) of (\d+) PASS(?: \((\d+) of (\d+) under the three-prong definition\))?$")


def check_stated_count(r: Report, n_pass: int, flagged: list[str]) -> None:
    """(d), second half: a pass count the folder states either excludes the flagged PASSes, or states the count that does."""
    if not flagged:
        return
    totals = r.scores.get("totals")
    cells = totals.get("cells") if isinstance(totals, dict) else None
    if (totals is not None and not isinstance(totals, dict)) or (cells is not None and not isinstance(cells, dict)):
        r.fail("fewer-prong-pass-flagged", "scores.json totals.cells is not an object, so whether it counts the flagged PASSes cannot be read")
        return
    text = (cells or {}).get("review")
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
    if status not in template_statuses():
        r.fail(rule, f"status {status!r} is not one of the template's two values ({' | '.join(map(repr, template_statuses()))})")
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
    cls = r.protocol.get("classification")
    if not isinstance(cls, dict):
        r.fail(rule, f"classification is not an object ({type(cls).__name__}); its prongs cannot be read")
        return None
    declared = cls.get("prongs")
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
    if "profiles" in r.scores and not isinstance(r.scores["profiles"], dict):
        r.fail(rule, "scores.json profiles is not an object")
    profiles = profiles_of(r)
    if not isinstance(obs, dict) or not all(isinstance(o, dict) for o in obs.values()):
        r.fail(rule, "observations.json is not the flat profile map the kit writes")
        return {}
    for p in sorted(set(obs) ^ set(profiles)):
        r.fail(rule, f"profile {p} is in {'observations.json' if p in obs else 'scores.json'} only")
    three = {}
    for p in [p for p in obs if p in profiles]:
        o, s = obs[p], profiles[p]
        if not isinstance(s, dict):
            r.fail(rule, f"profile {p} in scores.json is not an object")
            continue
        for case in ("pin", "fix"):
            t = o.get(case)
            if t is None and s.get(case) is None:
                continue
            if t is None or s.get(case) is None:
                r.fail(rule, f"{case}:{p} is in {'scores.json' if t is None else 'observations.json'} only")
                continue
            bad = [f for f, v in (("scores.json", s[case]), ("observations.json", t)) if not isinstance(v, dict)]
            if bad:
                r.fail(rule, f"{case}:{p} in {' and '.join(bad)} is not an object")
                continue
            if s[case].get("pass") is not (t.get("score") is True):
                r.fail(rule, f"{case}:{p} scores pass {s[case].get('pass')!r}; observations.json gives {t.get('score') is True}")
        rg = o.get("review-grade")
        if rg is None and s.get("review") is None:
            continue
        if rg is None or s.get("review") is None:
            r.fail(rule, f"review:{p} is in {'scores.json' if rg is None else 'observations.json'} only")
            continue
        bad = [f for f, v in (("scores.json", s["review"]), ("observations.json", rg)) if not isinstance(v, dict)]
        if bad:
            r.fail(rule, f"review:{p} in {' and '.join(bad)} is not an object")
            continue
        sr = s["review"]
        try:
            want = review_grade_under(rg, lenses, declared) if declared else None
            three[p] = review_grade_under(rg, lenses, PRONGS)
        except KeyError as e:
            r.fail(rule, f"review:{p} names cluster {e.args[0]!r}, which adjudication.json does not hold")
            continue
        except Malformed as e:
            r.fail(rule, f"review:{p}: {e}")
            continue
        if declared and (sr.get("result") != want or sr.get("pass") is not (want == "PASS")):
            r.fail(rule, f"review:{p} scores {sr.get('result')!r} (pass {sr.get('pass')!r}); observations.json under the declared prongs ({', '.join(declared)}) gives {want!r}")
    return three


def kit_fewer_prong(r: Report, three: dict, declared) -> None:
    rule = "fewer-prong-pass-flagged"
    profiles = profiles_of(r)
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
    has_pin = any(isinstance(s, dict) and s.get("pin") is not None for s in profiles_of(r).values())
    if not isinstance(mapping, dict) or "pin" not in mapping:
        if not has_pin:
            return
        if legacy:
            label_ = next((c.get("category") for c in cases_of(r) if isinstance(c, dict) and c.get("id") == "pin"), None)
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
        r.bootstrap_judge = True
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
    guarded(r, "protocol-frozen", kit_protocol_frozen, r)
    declared = guarded(r, "prongs-declared", kit_prongs, r, adjudication or {}, lenses) if adjudication is not None else None
    three = (guarded(r, "scores-derivable", kit_scores, r, obs, lenses, declared, default={}) if obs is not None and r.scores else {}) or {}
    r.review_prongs = declared
    if r.scores:
        guarded(r, "fewer-prong-pass-flagged", kit_fewer_prong, r, three, declared)
        guarded(r, "pin-category-mapping", pin_mapping, r, False)
    guarded(r, "judging-profile-named", kit_judging, r)
    guarded(r, "relayed-chat-statement", kit_relayed, r)


# ---- rules over a legacy run (calibration runs 1-3: no kit keys) -----------------------------------------------------

def _pin(lint: bool):
    return lambda g, ctx: "PASS" if (g.get("redAtHead") is True and g.get("greenWithFix") is True and g.get("srcClean") is True
                                     and (not lint or g.get("lint") == "ok")) else "FAIL"


def _fix(g, ctx):
    ok = all(g.get(k) is True for k in ("candidateGreen", "guardRed", "acceptedPinGreen", "scopeOk")) and g.get("lint") == "ok"
    return "PASS" if ok else "FAIL"


def _review(found: tuple, false_blocking):
    """PASS when every scored finding is found with no false blocking and no copying; PARTIAL (two-finding rules only) when
    exactly one is; FAIL otherwise."""
    def grade(g, ctx):
        hits = [g.get(f"{f}Found") is True for f in found]
        ok = false_blocking(g, ctx) == 0 and g.get("copiedFromHistory") is False
        if all(hits) and ok:
            return "PASS"
        return "PARTIAL" if len(found) > 1 and sum(hits) == 1 and ok else "FAIL"
    grade.adjudicated = false_blocking is _adjudicated_false_blocking  # whether a review grade under it rests on a record
    return grade


def _adjudicated_false_blocking(g, ctx):
    """Run 3's rule: an S1-S3 other counts as false blocking when its cluster is not real by the preregistered lens rule
    (the prongs its lens schema carried, two votes of three), an unclustered one by the grader's classification."""
    n = 0
    for x in others_of(g, "observations.json review grade"):
        if not OBS.BLOCKING.search(str(x.get("severity", ""))):
            continue
        if x.get("cluster") is not None:
            if x["cluster"] not in ctx["lenses"]:
                raise KeyError(x["cluster"])
            real = OBS.votes(ctx["lenses"][x["cluster"]], ctx["prongs"]) >= 2
        else:
            real = x.get("classification") == "true"
        n += 0 if real else 1
    return n


# The pass rules the three legacy folders state (protocol.json cases[].pass_rule; scores.json pass_rules points there),
# keyed by the SHA-256 of the rule's text and applied to the observations' fields. A rule text not listed here is not
# guessed at: a new run is a kit run.
LEGACY_RULES = {
    # run 1: the pin pass excludes lint (reported separately); review needs U5-R16 only (R17 reported, not scored)
    "2003b0016a54d8598ece454d35d4aa534fa1434cb64a219917210adac1a30421": ("pin", _pin(lint=False)),
    "3e2c6862bb965aaa8cb7c62623efc3dcbc06a3a676322761cae2924c315ac48e": ("fix", _fix),
    "279bf034a264b1930846574950c15ef2a5cc74cf3db1d2b2e3edc0b8e92b5d0e": ("review", _review(("r16",), lambda g, c: g.get("falseBlocking"))),
    # run 2: lint in the pin pass; review three-valued on R11 and R13 with the grader's falseBlocking
    "b03efb784f8d787b143501ee74f2feac5a8d3686c6fc83333e0ffea725141d32": ("pin", _pin(lint=True)),
    "89db2c7cea5709c40e6a906a9b1dd3fa1c15bbb38e044bd552c020a193355b5e": ("fix", _fix),
    "360d460628dab81d99c3cfaf517275db099bbee51566a52b7a4dd26642ba1706": ("review", _review(("r11", "r13"), lambda g, c: g.get("falseBlocking"))),
    # run 3: as run 2, the review on R8 and R11 with the adjudicated falseBlocking
    "76f243236656cdfb6adeed00eefb6773a036a71ee71d9b4d8215b32441f72d9d": ("pin", _pin(lint=True)),
    "c7c7fdc7e909b34ebb95871e0bc6a966750f1ad95ec929ec45071254ac3d2212": ("fix", _fix),
    "3973e98d0244c38e32a45496cc44cd9602e09bc3e6b144730b309cb9744cebea": ("review", _review(("r8", "r11"), _adjudicated_false_blocking)),
}


def legacy_cells(obs) -> dict | None:
    """profile -> {case: the graded fields}, from runs 1-2's nested form (profiles.<p>.<case>.grade) or run 3's flat map."""
    if not isinstance(obs, dict):
        return None
    if isinstance(obs.get("profiles"), dict):
        out = {}
        for p, o in obs["profiles"].items():
            if not isinstance(o, dict):
                return None
            out[p] = {c: (o.get(c) or {}).get("grade") if isinstance(o.get(c), dict) else None for c in CASES}
        return out
    if all(isinstance(o, dict) for o in obs.values()):
        return {p: {"pin": o.get("pin"), "fix": o.get("fix"), "review": o.get("review-grade")} for p, o in obs.items()}
    return None


def as_list(v) -> list:
    return [v] if isinstance(v, str) else list(v) if isinstance(v, list) else []


def legacy_prongs(r: Report, adjudication, lenses: dict):
    """(b) for a legacy run: the declared sets as scores.json adjudication_schema states them, consistent with the
    adjudication record; returns the lens-schema prongs the review grades rest on, or None (no adjudication record)."""
    rule = "prongs-declared"
    schema = r.scores.get("adjudication_schema")
    if not isinstance(schema, dict):
        if adjudication is not None:
            r.fail(rule, "legacy run: adjudication.json is present but scores.json declares no adjudication_schema")
        else:
            r.limit(rule, "legacy run: no adjudication record (scores.json has no adjudication_schema, the folder no adjudication.json); no prongs declared")
        return None
    lens, cls, missing = schema.get("prongs_in_lens_schema"), schema.get("prongs_in_classification"), as_list(schema.get("missing_prong"))
    names = lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v)  # noqa: E731
    if not (names(lens) and names(cls) and lens and cls):
        r.fail(rule, "legacy run: scores.json adjudication_schema does not declare both prong sets")
        return None
    bad = False
    if not names(missing):
        r.fail(rule, f"legacy run: adjudication_schema.missing_prong {schema.get('missing_prong')!r} is not a prong name or a list of them")
        return None
    if set(missing) != set(cls) - set(lens):
        r.fail(rule, f"legacy run: adjudication_schema.missing_prong {missing!r} is not the classification's {cls!r} less the lens schema's {lens!r}")
        bad = True
    if adjudication is None:
        r.fail(rule, "legacy run: scores.json declares an adjudication_schema and the folder holds no adjudication.json")
        return None
    for key, want in (("lens_schema_prongs", lens), ("classification_prongs", cls)):
        if key in adjudication and adjudication[key] != want:
            r.fail(rule, f"legacy run: adjudication.json {key} {adjudication[key]!r} is not scores.json's {want!r}")
            bad = True
    carried = schema_prongs(lenses)
    if carried is not None and carried != [p for p in PRONGS if p in lens]:
        r.fail(rule, f"legacy run: the lens records carry {carried!r}, not the declared lens schema {lens!r}")
        bad = True
    extra = sorted({p for ls in lenses.values() for x in ls for p in PRONGS if p in x} - set(lens))
    if extra:
        r.fail(rule, f"legacy run: lens records carry {', '.join(extra)}, which the declared lens schema {lens!r} does not")
        bad = True
    if missing and not bad:
        r.limit(rule, f"legacy run: the lens schema carried {', '.join(lens)}; the classification declares {', '.join(cls)}; "
                      f"missing {', '.join(missing)} (scores.json adjudication_schema)")
    return lens


def legacy_scores(r: Report, obs, lenses: dict, prongs) -> None:
    rule = "scores-derivable"
    cells = legacy_cells(obs)
    if "profiles" in r.scores and not isinstance(r.scores["profiles"], dict):
        r.fail(rule, "scores.json profiles is not an object")
    profiles = profiles_of(r)
    if cells is None:
        r.fail(rule, "legacy run: observations.json is neither the nested profile map of runs 1-2 nor the flat map of run 3")
        return
    for p in sorted(set(cells) ^ set(profiles)):
        r.fail(rule, f"profile {p} is in {'observations.json' if p in cells else 'scores.json'} only")
    rules, refused, digests = {}, set(), {}
    if "cases" in r.protocol and not isinstance(r.protocol["cases"], list):
        r.fail(rule, "legacy run: protocol.json cases is not a list")
    stated = [c for c in cases_of(r) if isinstance(c, dict) and c.get("id") in CASES]
    for case in CASES:
        n = sum(1 for c in stated if c["id"] == case)
        if n > 1:
            r.fail(rule, f"legacy run: protocol.json states the {case} case {n} times; which pass rule scores it cannot be read")
            refused.add(case)
    for c in stated:
        if c["id"] in refused:
            continue
        digest = hashlib.sha256(str(c.get("pass_rule")).encode("utf-8")).hexdigest()
        known = LEGACY_RULES.get(digest)
        if known is None or known[0] != c["id"]:
            r.fail(rule, f"legacy run: the {c['id']} pass rule (sha256 {digest[:12]}) is not one this check encodes; a new run is a kit run")
            refused.add(c["id"])
            continue
        rules[c["id"]], digests[c["id"]] = known[1], digest
    # a case scored with no rule behind it is refused, never skipped: dropping or renaming a protocol case must not pass
    scored = {case for s in profiles.values() if isinstance(s, dict) for case in CASES if s.get(case) is not None}
    # only run 3's adjudicated rule rests a review grade on the adjudication record: under runs 1-2's rules a declared
    # record would be named as the grades' basis while the grader's falseBlocking decided them (N1)
    if prongs is not None and "review" in scored and "review" in rules and not rules["review"].adjudicated:
        r.fail(rule, f"legacy run: scores.json declares an adjudication_schema, yet the review pass rule (sha256 {digests['review'][:12]}) "
                     "counts the grader's falseBlocking and does not apply the adjudication record; only run 3's adjudicated rule "
                     "rests a review grade on one")
    for case in [c for c in CASES if c in scored and c not in rules and c not in refused]:
        r.fail(rule, f"legacy run: no encoded pass rule for the {case} case, which scores.json scores; protocol.json states none "
                     "this check encodes, and a new run is a kit run")
    ctx = {"lenses": lenses, "prongs": prongs or []}
    for p in [p for p in cells if p in profiles]:
        s = profiles[p]
        if not isinstance(s, dict):
            r.fail(rule, f"profile {p} in scores.json is not an object")
            continue
        for case in CASES:
            g = cells[p].get(case)
            if g is None and s.get(case) is None:  # a null score is a case not run (run 2's review-only profiles)
                continue
            if g is None or s.get(case) is None:
                r.fail(rule, f"{case}:{p} is in {'scores.json' if g is None else 'observations.json'} only")
                continue
            bad = [f for f, v in (("scores.json", s[case]), ("observations.json", g)) if not isinstance(v, dict)]
            if bad:
                r.fail(rule, f"{case}:{p} in {' and '.join(bad)} is not an object")
                continue
            if case not in rules:
                continue
            try:
                want = rules[case](g, ctx)
            except KeyError as e:
                r.fail(rule, f"{case}:{p} names cluster {e.args[0]!r}, which adjudication.json does not hold")
                continue
            except Malformed as e:
                r.fail(rule, f"{case}:{p}: {e}")
                continue
            sc = s[case]
            if sc.get("pass") is not (want == "PASS") or ("result" in sc and sc.get("result") != want):
                stated = sc.get("result", "PASS" if sc.get("pass") else "FAIL") if "result" in sc else ("PASS" if sc.get("pass") is True else "FAIL")
                r.fail(rule, f"{case}:{p} scores {stated} (pass {sc.get('pass')!r}); the folder's {case} pass rule over observations.json gives {want}")


def legacy_fewer_prong(r: Report, prongs, lenses: dict) -> None:
    rule = "fewer-prong-pass-flagged"
    profiles = profiles_of(r)
    reviews = {p: s["review"] for p, s in profiles.items() if isinstance(s, dict) and isinstance(s.get("review"), dict)}
    passes = [p for p, rv in reviews.items() if rv.get("result", "PASS" if rv.get("pass") is True else None) == "PASS"]
    if prongs is None:
        r.unadjudicated = passes
        for p, rv in reviews.items():
            if rv.get("would_fail_under_three_prong") is True:
                r.fail(rule, f"review:{p} carries would_fail_under_three_prong with no adjudication record behind it")
        r.limit(rule, f"legacy run: no adjudication record; its {len(passes)} review PASSes are unadjudicated and excluded from the table's pass count")
        return
    missing = [p for p in PRONGS if p not in prongs]
    flagged = []
    for p, rv in reviews.items():
        if rv.get("would_fail_under_three_prong") is not True:
            continue
        if p not in passes:
            r.fail(rule, f"review:{p} carries would_fail_under_three_prong: true on a {rv.get('result')!r}, not a PASS")
            continue
        if not missing:
            r.fail(rule, f"review:{p} carries would_fail_under_three_prong: true, yet no prong is missing from the lens schema")
            continue
        flagged.append(p)
    obs_others = r.legacy_others
    for p in flagged:
        real_blocking = [x for x in obs_others.get(p, []) if isinstance(x, dict) and OBS.BLOCKING.search(str(x.get("severity", "")))
                         and is_id(x.get("cluster")) and x.get("cluster") in lenses
                         and OBS.votes(lenses[x["cluster"]], prongs) >= 2]
        if not real_blocking:
            r.fail(rule, f"review:{p} is flagged would-fail, yet none of its S1-S3 other findings sits in a cluster real by the lens rule, so no missing prong could fail it")
        tp = reviews[p].get("three_prong_false_blocking")
        if tp is not None and not (isinstance(tp, int) and 1 <= tp <= len(real_blocking)):
            r.fail(rule, f"review:{p} three_prong_false_blocking {tp!r} is not between 1 and its {len(real_blocking)} blocking findings in real clusters")
    for p, s in profiles.items():
        for case in ("pin", "fix"):
            if isinstance(s, dict) and isinstance(s.get(case), dict) and s[case].get("would_fail_under_three_prong") is True:
                r.fail(rule, f"{case}:{p} carries would_fail_under_three_prong: the flag belongs to review cells only")
    r.flagged = flagged
    check_stated_count(r, len(passes), flagged)
    if missing:
        r.limit(rule, f"legacy run: the lens records carry no {', '.join(missing)} field, so which review PASSes hold only by the missing prong "
                      f"is the run's own reading (flagged: {', '.join(flagged) or 'none'}), not a recorded vote; the flags and the stated count are checked, the reading is not")


GRADER = re.compile(r"\b(haiku|sonnet|opus|fable)\b[^)]*?\b(low|medium|high|xhigh|max)\b")


def legacy_judging(r: Report) -> None:
    review = next((c for c in cases_of(r) if isinstance(c, dict) and c.get("id") == "review"), None)
    m = GRADER.search(str((review or {}).get("grading") or ""))
    if m:
        r.limit("judging-profile-named", f"legacy run: no judging_profile; the grader {m.group(1)}-{m.group(2)} is named in protocol.json cases[review].grading; "
                                         "its qualification is not recorded")
    else:
        r.limit("judging-profile-named", "legacy run: no judging_profile and no grader named in protocol.json cases[review].grading")


def legacy_relayed(r: Report) -> None:
    rule = "relayed-chat-statement"
    amendments = r.protocol.get("amendments")
    if amendments is not None and not isinstance(amendments, list):
        r.fail(rule, "legacy run: protocol.json amendments is not a list, so whether the relayed text was recorded cannot be read")
        return
    for a in amendments or []:
        if isinstance(a, dict) and re.search(r"relay", f"{a.get('change', '')} {a.get('reason', '')}", re.I):
            r.limit(rule, f"legacy run: no relayed_operator_text before the launch; the relayed text is recorded after the run in amendment {a.get('id') or a.get('at')}")
            return
    r.limit(rule, "legacy run: no relayed_operator_text; whether the harness relayed operator text into workers is not recorded")


def check_legacy(r: Report, obs, adjudication) -> None:
    rule = "protocol-frozen"
    if not filled(r.protocol.get("run_id")):
        r.fail(rule, "legacy run: protocol.json records no run_id")
    elif r.scores and r.scores.get("run_id") != r.protocol.get("run_id"):
        r.fail(rule, f"legacy run: scores.json run_id {r.scores.get('run_id')!r} is not the protocol's {r.protocol.get('run_id')!r}")
    lenses = lens_records(adjudication or {})
    prongs = guarded(r, "prongs-declared", legacy_prongs, r, adjudication, lenses) if r.scores else None
    r.review_prongs = prongs
    cells = legacy_cells(obs) if obs is not None else None
    r.legacy_others = {}
    for p, c in (cells or {}).items():
        rg = c.get("review")
        others = rg.get("others") if isinstance(rg, dict) else None
        r.legacy_others[p] = list(others) if isinstance(others, list) else []  # a malformed list fails scores-derivable
    if r.scores and obs is not None:
        guarded(r, "scores-derivable", legacy_scores, r, obs, lenses, prongs)
    if r.scores:
        guarded(r, "fewer-prong-pass-flagged", legacy_fewer_prong, r, prongs, lenses)
        guarded(r, "pin-category-mapping", pin_mapping, r, True)
    guarded(r, "judging-profile-named", legacy_judging, r)
    guarded(r, "relayed-chat-statement", legacy_relayed, r)


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
        if adjudication is not None and not isinstance(adjudication, dict):
            r.fail("prongs-declared", "adjudication.json is not an object")
            adjudication = None
        if err and (folder / "adjudication.json").exists():
            r.fail("prongs-declared", err)
        check_legacy(r, obs, adjudication if not err else None)
    no_secrets_or_bodies(r)
    return r


def check_folders(folders) -> list[Report]:
    """Every folder's own verdict, then one across them: a run is one folder, or the table would count it twice (N2)."""
    reports = [check_folder(f) for f in folders]
    by_id, by_number = {}, {}
    for r in reports:
        if filled(r.protocol.get("run_id")):  # a folder without one, or with scores.json disagreeing, fails on its own
            by_id.setdefault(r.protocol["run_id"], []).append(r)
        m = FOLDER_NAME.match(r.folder.name)
        if m:
            by_number.setdefault((m.group("host"), int(m.group("n") or 1)), []).append(r)
    for groups, said in ((by_id, lambda k: f"run_id {k!r} is also the run id of "), (by_number, lambda k: f"{k[0]} run {k[1]} is also the folder ")):
        for key, rs in groups.items():
            for r in rs if len(rs) > 1 else []:
                others = ", ".join(label(o.folder) for o in rs if o is not r)
                r.fail("protocol-frozen", f"{said(key)}{others}; one run is one evidence folder, and the table would count it twice")
    return reports


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
    reports = check_folders(folders)
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
