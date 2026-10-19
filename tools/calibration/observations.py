#!/usr/bin/env python3
# Lineage: generalises calibration run 3's observation builder (journal + run file + mechanical grades + grader fields +
# preregistered three-lens adjudication -> observations.json, scores.json and the tables); every run-3 constant is now
# read from the subject-pack manifest, the frozen protocol or the harness files.
"""Build a calibration run's results from the harness journal, the run file, the pack manifest and the grades.

usage: observations.py JOURNAL RUN_FILE MANIFEST GRADES_DIR OUT_DIR [--protocol PROTOCOL]
                       [--void CASE:PROFILE ...] [--supplementary JOURNAL RUN_FILE]

Writes into OUT_DIR: observations.json (the flat profile map hosts/claude-code/route.mjs `rate` reads), scores.json,
results-table.md, clusters.md, tokens-and-estimates.md, adjudication.json and void-cells.json. Exit 0 when written,
2 when an input is missing, unparseable or inconsistent (the reason is on stderr). It never calls a provider and
never reads a credential.

THE HARNESS JOURNAL FORMAT (as the Claude Code workflow harness writes it; another host writes the same two files
from its own records, and the builder needs nothing else from the harness):

  JOURNAL - JSON lines, one event per line; a line that does not parse is skipped.
    {"type": "started", "agentId": ID, "label": LABEL, ...}  an agent began
    {"type": "result",  "agentId": ID, "result": OBJECT}     its structured output (the schema the script gave it)
    {"type": "error",   "agentId": ID, "error" | "message": TEXT}  it ended without a structured output
    {"type": "retry" | "schema_retry", "agentId": ID}       a harness retry: counted as such, never as a model retry
    Any other type ("launched", ...) is ignored.
  RUN_FILE - one JSON object the harness writes when the run ends.
    "runId": the run id.
    "workflowProgress": a list; each {"type": "workflow_agent", "label": LABEL, "model": the resolved model id,
        "state": "done" | "error" | ..., "tokens": N, "durationMs": N, "attempt": 1 + harness retries} is one agent;
        entries of any other type are ignored, and an agent counts only in state done or error.
    "result": the workflow script's return value, {"results": [...], "clusters": {"clusters": [...]},
        "adjudications": [{"cluster": {...}, "lenses": [...], "real": BOOL, "realVotes": "k/n"}]}.
  LABEL (run.template.js names its agents so): "<case>:<profile>" for a cell (case pin | fix | review),
    "grade:<profile>" for a review's grader, "cluster:<name>" for the clustering agent, "lens:<cluster>:<lens>"
    (or run 3's "<cluster>:<lens>") for a lens (reproduce | reachability | refute). Any other label is counted
    under "other", so the token totals always sum to the run's agents.
  GRADES_DIR - grade.sh's outputs, one file per pin or fix cell, named <case>-<profile>.json.

A void cell (protocol Item 3.2: it halted on relayed operator text) is named with --void and must be re-run once in a
supplementary run given with --supplementary; its main-run usage and output go to void-cells.json, the
supplementary cell replaces it, and the supplementary run's cells must all be declared void.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

CASES = ("pin", "fix", "review")
LENSES = ("reproduce", "reachability", "refute")
PRONGS = ("holds", "reachable", "forbidden")
BLOCKING = re.compile(r"S[123]")


class Refused(Exception):
    """An input the builder cannot honestly build from; the message names it."""


def read_json(path: Path, what: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refused(f"{what} not found: {path}")
    except (OSError, ValueError) as e:
        raise Refused(f"{what} unreadable or not JSON: {path} ({e})")


def load_journal(path: Path):
    if not path.is_file():
        raise Refused(f"journal not found: {path}")
    started, results, errors, retries = {}, {}, {}, collections.Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        t, aid = e.get("type"), e.get("agentId")
        if t == "started":
            started[aid] = e.get("label")
        elif t == "result":
            results[started.get(aid, "?")] = e.get("result")
        elif t == "error":
            errors[started.get(aid, "?")] = e.get("error") or e.get("message")
        elif t in ("retry", "schema_retry"):
            retries[started.get(aid, "?")] += 1
    return results, errors, retries


def load_run(path: Path):
    d = read_json(path, "run file")
    if not isinstance(d, dict):
        raise Refused(f"run file is not an object: {path}")
    run_id = d.get("runId")
    usage, attempts = {}, collections.Counter()
    for ev in d.get("workflowProgress") or []:
        if not isinstance(ev, dict) or ev.get("type") != "workflow_agent" or ev.get("state") not in ("done", "error"):
            continue
        label = ev.get("label")
        prev = usage.get(label)
        tokens = (ev.get("tokens") or 0) + ((prev or {}).get("tokens") or 0)
        usage[label] = {"label": label, "model": ev.get("model"), "effort": ev.get("effort"), "state": ev.get("state"),
                        "tokens": tokens, "ms": ev.get("durationMs"), "run": run_id}
        attempts[label] = max(attempts[label], int(ev.get("attempt") or 1) - 1)
    final = d.get("result") or {}
    clusters = ((final.get("clusters") or {}).get("clusters")) or []
    adjs = [a for a in (final.get("adjudications") or []) if a]
    return run_id, usage, attempts, clusters, adjs


def label_kind(label: str) -> str:
    parts = (label or "").split(":")
    if parts[0] in CASES and len(parts) == 2:
        return "items"
    if parts[0] == "grade":
        return "graders"
    if parts[0] == "cluster":
        return "clustering"
    if parts[0] == "lens" or (len(parts) == 2 and parts[1] in LENSES):
        return "lenses"
    return "other"


def lens_ok(lens: dict, prong: str) -> bool:
    if prong == "holds":
        return lens.get("holds") is True
    if prong == "reachable":
        return "reachable" in lens and lens.get("reachable") != "no"
    if prong == "forbidden":
        return lens.get("forbidden") is True
    return False


def votes(lenses: list, prongs) -> int:
    return sum(1 for lens in lenses if all(lens_ok(lens, p) for p in prongs))


def review_result(grade: dict, false_blocking: int, truth_ids) -> str:
    """Protocol rule: PASS when every ground-truth finding is found AND false blocking is 0 AND nothing was copied;
    PARTIAL when some but not all are found under the same two conditions; FAIL otherwise."""
    by_id = {t.get("id"): t for t in (grade.get("truth") or []) if isinstance(t, dict)}
    found = [bool((by_id.get(i) or {}).get("found")) for i in truth_ids]
    ok = false_blocking == 0 and grade.get("copiedFromHistory") is False
    if found and all(found) and ok:
        return "PASS"
    if any(found) and ok:
        return "PARTIAL"
    return "FAIL"


def merge_adjudications(adj_lists, declared):
    """cluster id -> merged record; a supplementary record that reuses a main cluster adds members only."""
    merged = {}
    for adjs in adj_lists:
        for a in adjs:
            c = a.get("cluster") or {}
            cid = c.get("id")
            m = merged.get(cid)
            if m is None:
                m = merged[cid] = {"id": cid, "title": c.get("title"), "claim": c.get("claim"), "members": [], "graderClassifications": [],
                                   "lenses": [], "real": a.get("real"), "realVotes": a.get("realVotes")}
            for mem, gc in zip(c.get("members") or [], (c.get("graderClassifications") or []) + [None] * len(c.get("members") or [])):
                if mem not in m["members"]:
                    m["members"].append(mem)
                    m["graderClassifications"].append(gc)
            if not m["lenses"] and not a.get("fromMainRun"):
                m["lenses"] = [x for x in (a.get("lenses") or []) if x]
            if m["real"] is None:
                m["real"] = a.get("real")
    for m in merged.values():
        n3, nd = votes(m["lenses"], PRONGS), votes(m["lenses"], declared)
        m["threeProngVotes"] = f"{n3}/{len(m['lenses'])}"
        m["threeProngReal"] = n3 >= 2
        m["declaredRuleReal"] = nd >= 2
        if m["real"] is None:
            m["real"] = m["declaredRuleReal"]
        m["real"] = bool(m["real"])
        m["declaredRuleDisagrees"] = m["real"] != m["declaredRuleReal"]
    return merged


def member_map(merged):
    out = {}
    for m in merged.values():
        for mem in m["members"]:
            parts = str(mem).strip().rsplit(" ", 1)
            if len(parts) == 2:
                out[(parts[0], parts[1])] = m
    return out


def money(tokens, rate):
    return None if rate is None or tokens is None else round(tokens * rate / 1e6, 4)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("journal", type=Path)
    ap.add_argument("run_file", type=Path)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("grades", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--protocol", type=Path)
    ap.add_argument("--void", action="append", default=[], metavar="CASE:PROFILE")
    ap.add_argument("--supplementary", nargs=2, type=Path, metavar=("JOURNAL", "RUN_FILE"))
    a = ap.parse_args(argv)
    try:
        return build(a)
    except Refused as e:
        print(f"observations.py: refused: {e}", file=sys.stderr)
        return 2


def build(a) -> int:
    manifest = read_json(a.manifest, "manifest")
    protocol = read_json(a.protocol, "protocol") if a.protocol else {}
    cases = manifest.get("cases") or {}
    unknown = sorted(set(cases) - set(CASES))
    if unknown:
        raise Refused(f"manifest cases {unknown} are not pin, fix or review (the adapter reads only those three)")
    if not a.grades.is_dir():
        raise Refused(f"grades directory not found: {a.grades}")
    truth_ids = list((cases.get("review") or {}).get("findings") or [])
    tier = {c: (cases.get(c) or {}).get("tier", "T1") for c in CASES}
    declared = list(((protocol.get("classification") or {}).get("prongs")) or PRONGS)

    results, errors, retries = load_journal(a.journal)
    run_id, usage, attempts, _, adjs = load_run(a.run_file)
    for lab, n in attempts.items():
        retries[lab] = max(retries[lab], n)

    void = list(dict.fromkeys(a.void))
    for v in void:
        if v.split(":")[0] not in CASES or v.count(":") != 1:
            raise Refused(f"--void {v!r} is not <case>:<profile>")
        if v not in usage and v not in results and v not in errors:
            raise Refused(f"--void {v}: no such cell in the main run")
    if void and not a.supplementary:
        raise Refused(f"void cells {void} need their supplementary re-run (--supplementary JOURNAL RUN_FILE): a void cell is re-run once, never dropped")
    supp_id, supp_usage, supp_adjs, void_record = None, {}, [], {}
    if a.supplementary:
        s_results, s_errors, s_retries = load_journal(a.supplementary[0])
        supp_id, supp_usage, s_attempts, _, supp_adjs = load_run(a.supplementary[1])
        cells = sorted({lab for lab in list(supp_usage) + list(s_results) if label_kind(lab) == "items"})
        stray = [c for c in cells if c not in void]
        if stray:
            raise Refused(f"supplementary cells {stray} were not declared --void")
        for v in void:
            case, prof = v.split(":")
            void_record[v] = {"main-run": {"usage": usage.get(v), "output": results.get(v), "error": errors.get(v),
                                           "self-reported-mistakes": (results.get(v) or {}).get("mistakes") if isinstance(results.get(v), dict) else None,
                                           "grade-usage": usage.get(f"grade:{prof}") if case == "review" else None}}
            for lab in (v, f"grade:{prof}") if case == "review" else (v,):
                results.pop(lab, None)
                errors.pop(lab, None)
                retries.pop(lab, None)
        for lab, r in s_results.items():
            results[lab] = r
        for lab, e in s_errors.items():
            errors[lab] = e
        for lab, n in s_retries.items():
            retries[lab] = n
        for lab, n in s_attempts.items():
            retries[lab] = max(retries[lab], n)

    def cell_usage(lab):
        return supp_usage.get(lab) if lab in supp_usage else (None if lab in void_record else usage.get(lab))

    def grade_usage(prof):
        lab = f"grade:{prof}"
        if f"review:{prof}" in void_record:
            return supp_usage.get(lab)
        return usage.get(lab)

    # profiles: the protocol's order, else the order the labels first appear in
    proto_profiles = [p.get("key") for p in protocol.get("profiles") or []]
    proto_review_only = [p.get("key") for p in protocol.get("review_only_profiles") or []]
    alias = {p.get("key"): p.get("model") for p in (protocol.get("profiles") or []) + (protocol.get("review_only_profiles") or [])}
    seen = list(dict.fromkeys(lab.split(":", 1)[1] for lab in list(usage) + list(results) + list(supp_usage) if label_kind(lab) == "items"))
    order = list(dict.fromkeys(proto_profiles + proto_review_only + seen))
    review_only = set(proto_review_only) if protocol else {p for p in order if not any(f"{c}:{p}" in usage or f"{c}:{p}" in results for c in ("pin", "fix"))}

    merged = merge_adjudications([adjs, supp_adjs], declared)
    by_member = member_map(merged)
    lens_records = [lens for m in merged.values() for lens in m["lenses"]]
    in_schema = [p for p in PRONGS if lens_records and all(p in lens for lens in lens_records)] if lens_records else None

    obs, unclustered = {}, []
    for p in order:
        o = {"profile": p, "review-only": p in review_only, "pin": None, "fix": None, "review": None, "review-grade": None,
             "self-reported-mistakes": {}, "harness-retries": {}, "usage": {}}
        for case in ("pin", "fix"):
            lab = f"{case}:{p}"
            ran = case in cases and (cell_usage(lab) is not None or lab in results or lab in errors)
            g_path = a.grades / f"{case}-{p}.json"
            g = read_json(g_path, "grade") if g_path.is_file() else None
            if ran and (g is None or "error" in g):
                o[case] = {"score": None, "tier": tier[case], "ungraded": (g or {}).get("error") or f"no grade file {g_path.name}"}
            elif ran and case == "pin":
                o["pin"] = {"score": bool(g.get("PASS")), "tier": tier[case], **{k: g.get(k) for k in ("redAtHead", "greenWithFix", "srcClean", "lint", "committed", "atHead", "withAcceptedFix")}}
            elif ran:
                o["fix"] = {"score": bool(g.get("PASS")), "tier": tier[case], **{k: g.get(k) for k in ("candidateGreen", "guardRed", "acceptedPinGreen", "scopeOk", "lint", "committedWithMap", "commits", "srcDiffLines", "candidateTests", "guardRemoved", "acceptedPin")}}
        for case in CASES:
            lab = f"{case}:{p}"
            r = results.get(lab)
            if isinstance(r, dict):
                o["self-reported-mistakes"][case] = r.get("mistakes")
            elif lab in errors:
                o["self-reported-mistakes"][case] = f"no structured output: {str(errors.get(lab))[:160]}"
            else:
                o["self-reported-mistakes"][case] = None
            o["harness-retries"][case] = retries.get(lab, 0)
            o["usage"][case] = cell_usage(lab)
        o["usage"]["grade"] = grade_usage(p)
        r, g = results.get(f"review:{p}"), results.get(f"grade:{p}")
        if isinstance(r, dict):
            o["review"] = {"verdict": r.get("verdict"), "findings": [[f.get("id"), f.get("severity"), str(f.get("problem", ""))[:200]] for f in r.get("findings") or []],
                           "checked": len(r.get("checked") or [])}
        review_ran = "review" in cases and (cell_usage(f"review:{p}") is not None or f"review:{p}" in results or f"review:{p}" in errors)
        if isinstance(g, dict):
            adj_fb = fb3 = 0
            others = []
            for x in g.get("others") or []:
                y = dict(x)
                if BLOCKING.search(str(x.get("severity", ""))):
                    m = by_member.get((p, x.get("id")))
                    if m:
                        y.update(cluster=m["id"], clusterReal=m["real"], clusterVotes=m["realVotes"], clusterThreeProngReal=m["threeProngReal"])
                        y["adjudicated"], real3 = m["real"], m["threeProngReal"]
                    else:
                        y["adjudicated"] = real3 = x.get("classification") == "true"
                        unclustered.append((p, x.get("id"), x.get("classification")))
                    adj_fb += 0 if y["adjudicated"] else 1
                    fb3 += 0 if real3 else 1
                others.append(y)
            truth = {t.get("id"): {k: t.get(k) for k in ("found", "causeNamed", "severity")} for t in g.get("truth") or [] if isinstance(t, dict)}
            o["review-grade"] = {"result": review_result(g, adj_fb, truth_ids), "tier": tier["review"], "rawFalseBlocking": g.get("falseBlocking"),
                                 "adjudicatedFalseBlocking": adj_fb, "threeProngFalseBlocking": fb3,
                                 "threeProngResult": review_result(g, fb3, truth_ids), "truth": truth,
                                 "copiedFromHistory": g.get("copiedFromHistory"), "others": others, "notes": str(g.get("notes", ""))[:500]}
        elif review_ran:
            o["review-grade"] = {"result": None, "tier": tier["review"], "ungraded": "no grader output"}
        obs[p] = o

    # scores
    rates = ((protocol.get("accounting") or {}).get("rates_per_mtok")) if isinstance(protocol.get("accounting"), dict) else None
    rates = rates or {}

    def estimate(p, u):
        tk = (u or {}).get("tokens")
        r = rates.get(alias.get(p) or p.rsplit("-", 1)[0]) or {}
        return {"tokens": tk, "usd_all_input": money(tk, r.get("input")), "usd_all_output": money(tk, r.get("output"))}

    profiles_s, cells, non_pass = {}, collections.defaultdict(lambda: [0, 0, 0]), []
    for p, o in obs.items():
        sp = {}
        for case in ("pin", "fix"):
            t = o[case]
            if t is None:
                continue
            e = {"pass": t["score"] is True, "tier": t["tier"], "estimate": estimate(p, o["usage"][case])}
            if case == "pin":
                e["lint_clean"] = t.get("lint") in ("ok", "none")
            else:
                e["committed_with_map"] = t.get("committedWithMap")
            if "ungraded" in t:
                e["ungraded"] = t["ungraded"]
            if f"{case}:{p}" in void_record:
                e["supplementary_run"] = supp_id
            sp[case] = e
            cells[case][0] += e["pass"]
            cells[case][1] += 1
            if not e["pass"]:
                non_pass.append(f"{case}:{p}")
        rg = o["review-grade"]
        if rg is not None:
            res = rg["result"]
            e = {"result": res, "pass": res == "PASS", "tier": rg["tier"], "estimate": estimate(p, o["usage"]["review"])}
            if "ungraded" in rg:
                e["ungraded"] = rg["ungraded"]
            else:
                wf = res == "PASS" and rg["threeProngResult"] != "PASS"
                e.update(truth=rg["truth"], falseBlocking_raw=rg["rawFalseBlocking"], falseBlocking_adjudicated=rg["adjudicatedFalseBlocking"],
                         true_extra_findings=sum(1 for x in rg["others"] if x.get("adjudicated") is True), copiedFromHistory=rg["copiedFromHistory"],
                         would_fail_under_three_prong=wf)
                if wf:
                    held = [x["id"] for x in rg["others"] if x.get("adjudicated") is True and x.get("clusterThreeProngReal") is False]
                    e["three_prong_false_blocking"] = rg["threeProngFalseBlocking"]
                    e["three_prong_note"] = f"the other findings {held} sit in clusters real by the run's rule but not on all three prongs; under the full three-prong definition this review is {rg['threeProngResult']}"
                cells["review"][2] += res == "PASS" and not wf
            if f"review:{p}" in void_record:
                e["supplementary_run"] = supp_id
            sp["review"] = e
            cells["review"][0] += e["pass"]
            cells["review"][1] += 1
            if not e["pass"]:
                non_pass.append(f"review:{p}")
        profiles_s[p] = sp

    def kinds(u):
        k = collections.Counter()
        for lab, x in u.items():
            k[label_kind(lab)] += x.get("tokens") or 0
        return {"items": k["items"], "graders": k["graders"], "clustering": k["clustering"], "lenses": k["lenses"], "other": k["other"],
                "total": sum(k.values())}

    main_t = kinds(usage)
    main_t["of_which_void_cells"] = sum((usage.get(v) or {}).get("tokens") or 0 for v in void_record)
    main_t["of_which_void_grade"] = sum((usage.get(f"grade:{v.split(':')[1]}") or {}).get("tokens") or 0 for v in void_record if v.startswith("review:"))
    supp_t = kinds(supp_usage) if a.supplementary else None
    judging = lambda t: (t["graders"] + t["clustering"] + t["lenses"]) if t else 0
    both = main_t["total"] + (supp_t["total"] if supp_t else 0)
    tokens = {"main_run": main_t, "supplementary_run": supp_t, "both_runs_total": both,
              "scored_cells_items": main_t["items"] - main_t["of_which_void_cells"] + (supp_t["items"] if supp_t else 0),
              "judging_both_runs": judging(main_t) + judging(supp_t),
              "judging_share_main_run": round(judging(main_t) / main_t["total"], 3) if main_t["total"] else None,
              "judging_share_both_runs": round((judging(main_t) + judging(supp_t)) / both, 3) if both else None,
              "note": "items = the cells; judging = graders + clustering + lenses; other = any agent whose label the kit does not name; scored cells = main items minus the void cells plus the supplementary items"}
    cells_text = {}
    for case in CASES:
        if case not in cells:
            continue
        k, n, k3 = cells[case]
        cells_text[case] = f"{k} of {n} PASS"
        if case == "review" and k3 != k:
            cells_text[case] += f" ({k3} of {n} under the three-prong definition)"
    missing = [p for p in PRONGS if in_schema is not None and p not in in_schema]
    scores = {
        "schema_version": 1, "run_id": run_id, "supplementary_run_id": supp_id,
        "pack": {k: manifest.get(k) for k in ("pack", "pack_version", "kind")},
        "pass_rules": {c: (cases.get(c) or {}).get("pass_rule") for c in CASES if c in cases},
        "accounting_note": (protocol.get("accounting") or {}).get("statement") if isinstance(protocol.get("accounting"), dict)
        else "estimate-only: no rates given (--protocol with accounting.rates_per_mtok), so every usd field is null; not a bill",
        "profiles": profiles_s,
        "void_cells": {v: {"status": "VOID (protocol Item 3.2)", "main_run_tokens": (r["main-run"]["usage"] or {}).get("tokens")} for v, r in void_record.items()},
        "totals": {"cells": cells_text, "tokens": tokens, "non_pass": non_pass},
        "category_mapping": {c: (cases.get(c) or {}).get("category") for c in CASES if c in cases},
        "adjudication_schema": {
            "prongs_in_lens_schema": in_schema, "prongs_in_classification": declared, "missing_prong": missing,
            "vote_rule": "a lens votes real when holds, reachable is not no, and forbidden; a cluster is real on two votes of three",
            "scored_verdict": "the run's own verdict per cluster (its preregistered rule); would_fail_under_three_prong marks a review PASS that fails under the full definition",
            "declared_rule_disagrees": sorted(m["id"] for m in merged.values() if m["declaredRuleDisagrees"]),
        },
    }
    if unclustered:
        scores["unclustered_others"] = [{"profile": p, "id": i, "grader": c} for p, i, c in unclustered]

    a.out.mkdir(parents=True, exist_ok=True)
    write = lambda name, doc: (a.out / name).write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    write("observations.json", obs)
    write("scores.json", scores)
    write("adjudication.json", {"run": run_id, "supplementary-run": supp_id, "declared-prongs": declared, "clusters": list(merged.values())})
    write("void-cells.json", {"run": run_id, "supplementary-run": supp_id, "void-cells": void_record})

    pf = lambda t: "-" if t is None else ("PASS" if t.get("score") is True else "UNGRADED" if t.get("score") is None else "FAIL")
    star = lambda p, case: "*" if f"{case}:{p}" in void_record else ""
    tok = lambda u: "-" if not u else f"{u.get('tokens')}"
    head = ["profile", "pin", "fix", "fix map", "review"] + truth_ids + ["others true/false/unv (grader)", "false S1-3 raw/adj/3-prong", "copied", "tokens pin/fix/review(+grade)"]
    rows = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for p, o in obs.items():
        rg, fx = o["review-grade"], o["fix"]
        graded = rg is not None and "ungraded" not in rg
        cls = collections.Counter(x.get("classification") for x in (rg or {}).get("others") or [])
        cols = [p, pf(o["pin"]), pf(fx), "-" if not fx or fx.get("committedWithMap") is None else ("yes" if fx["committedWithMap"] else "no"),
                "-" if rg is None else (rg["result"] or "UNGRADED") + (" (3-prong: " + rg["threeProngResult"] + ")" if graded and rg["threeProngResult"] != rg["result"] else "")]
        for i in truth_ids:
            t = (rg or {}).get("truth", {}).get(i) if graded else None
            cols.append("-" if not t else f"{t.get('found')}" + ("/cause" if t.get("causeNamed") else ""))
        cols += [f"{cls['true']}/{cls['false']}/{cls['unverifiable']}" if graded else "-",
                 f"{rg['rawFalseBlocking']}/{rg['adjudicatedFalseBlocking']}/{rg['threeProngFalseBlocking']}" if graded else "-",
                 f"{rg['copiedFromHistory']}" if graded else "-",
                 "/".join(tok(o["usage"][c]) + star(p, c) for c in CASES) + f"(+{tok(o['usage']['grade'])}{star(p, 'review')})"]
        rows.append("| " + " | ".join(cols) + " |")
    rows.append("")
    rows.append("`*` a supplementary-run cell replacing a void one. Review: the run's preregistered result, with the three-prong result beside it when they differ.")
    (a.out / "results-table.md").write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")

    crow = ["| cluster | title | members | grader says | lenses (holds/reachable/forbidden) | verdict (run's rule) | three prongs |", "|---|---|---|---|---|---|---|"]
    for m in merged.values():
        ls = "; ".join(f"{x.get('lens')}: {'holds' if x.get('holds') else 'no'}/{x.get('reachable')}/{x.get('forbidden', 'absent')}" for x in m["lenses"])
        crow.append(f"| {m['id']} | {str(m['title'])[:90]} | {', '.join(m['members'])} | {', '.join(str(c) for c in m['graderClassifications'])} | {ls} | "
                    f"{'REAL' if m['real'] else 'not real'} ({m['realVotes']}) | {'REAL' if m['threeProngReal'] else 'not real'} ({m['threeProngVotes']}) |")
    (a.out / "clusters.md").write_text("\n".join(crow) + "\n", encoding="utf-8", newline="\n")

    cost = ["| profile | task | tokens | ms | est. $ (all-input .. all-output) | result |", "|---|---|---|---|---|---|"]
    for p, o in obs.items():
        for case in CASES:
            u = o["usage"][case]
            if not u:
                continue
            e = estimate(p, u)
            usd = "-" if e["usd_all_input"] is None else f"{e['usd_all_input']:.2f} .. {e['usd_all_output']:.2f}"
            res = (profiles_s[p].get(case) or {})
            cost.append(f"| {p} | {case}{star(p, case)} | {u.get('tokens') or 0:,} | {u.get('ms') or 0:,} | {usd} | {res.get('result') or ('PASS' if res.get('pass') else 'FAIL' if res else '-')} |")
    t = tokens["main_run"]
    cost.append("")
    cost.append(f"Main run {run_id}: items {t['items']:,}; graders {t['graders']:,}; clustering {t['clustering']:,}; lenses {t['lenses']:,}; other {t['other']:,}; total {t['total']:,} tokens.")
    if supp_t:
        cost.append(f"Supplementary run {supp_id}: items {supp_t['items']:,}; graders {supp_t['graders']:,}; clustering {supp_t['clustering']:,}; lenses {supp_t['lenses']:,}; total {supp_t['total']:,} tokens.")
    cost.append(f"Both runs: {both:,} tokens; judging {tokens['judging_both_runs']:,}. {scores['accounting_note']}")
    (a.out / "tokens-and-estimates.md").write_text("\n".join(cost) + "\n", encoding="utf-8", newline="\n")

    for case, text in cells_text.items():
        print(f"{case}: {text}")
    if unclustered:
        print(f"UNCLUSTERED S1-S3 others (grader classification used): {unclustered}")
    print(f"written: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
