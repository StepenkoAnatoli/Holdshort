#!/usr/bin/env python3
"""Assemble and validate host-owned billing qualification records.

This tool never fetches a URL or sends a prompt. It validates captured local
evidence and helps a host assemble a qualification record. Artifact hashes
establish integrity, not the truth of captured provider claims; the host must
review evidence before marking a record qualified.

Subcommands:
  validate PATH [--prices PATH]   Validate an existing record; exit 0 on success.
  synthetic OUTDIR                Write a conspicuously synthetic qualified record
                                 (for CI/tests only) and validate it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

try:
    import billing_qualification as bq
except ImportError:
    from tools import billing_qualification as bq

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRICES = REPO_ROOT / "tools" / "prices-2.json"
DEFAULT_QUALIFICATION = REPO_ROOT / "tools" / "live_billing_qualification.json"

MODELS = {"cloud-S": "claude-sonnet-5-5", "cloud-C": "claude-haiku-5-5",
          "cloud-O": "claude-opus-5-5", "cloud-F": "claude-fable-5-1"}
PRICE_MODELS = {"cloud-S": "Claude Sonnet 5.5", "cloud-C": "Claude Haiku 5.5",
                "cloud-O": "Claude Opus 5.5", "cloud-F": "Claude Fable 5.1"}
ENDPOINT = "https://api.anthropic.com"


def cmd_validate(args) -> int:
    record_path = Path(args.record)
    prices_path = Path(args.prices) if args.prices else DEFAULT_PRICES
    try:
        bq.load_qualification(record_path, prices_path, endpoint=ENDPOINT,
                              models=MODELS, price_models=PRICE_MODELS,
                              now=args.now)
    except bq.BillingQualificationError as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2
    print("OK: qualification record is valid and fresh")
    return 0


def cmd_synthetic(args) -> int:
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    price_path = outdir / "synthetic-prices.json"
    price_path.write_bytes(DEFAULT_PRICES.read_bytes())
    price_bytes = price_path.read_bytes()
    refs = []
    for kind in sorted(bq.EVIDENCE_KINDS):
        artifact = outdir / (kind + ".txt")
        body = ("SYNTHETIC TEST ONLY: no provider qualification or real ceiling established. " + kind).encode()
        artifact.write_bytes(body)
        refs.append({"kind": kind, "path": artifact.name,
                     "sha256": hashlib.sha256(body).hexdigest()})
    import time
    now = time.time()
    record = {"schema_version": 1, "qualified": True,
              "qualification_scope": bq.QUALIFICATION_SCOPE,
              "final_bill_guaranteed": False, "endpoint": ENDPOINT,
              "request_mode": bq.REQUEST_MODE,
              "price_revision": json.loads(price_bytes)["revision"],
              "price_sha256": hashlib.sha256(price_bytes).hexdigest(),
              "verified_at": now - 10, "expires_at": now + 3600,
              "evidence_refs": refs,
              "note": "SYNTHETIC TEST ONLY, never use for live dispatch",
              "profiles": {}}
    for profile, model in MODELS.items():
        record["profiles"][profile] = {
            "model_id": model, "price_model": PRICE_MODELS[profile],
            "input_token_ceiling": 10000, "max_output_tokens": 4096,
            "bound_kind": "provider-enforced-token-ceiling",
            "evidence_refs": [dict(r) for r in refs],
        }
    record_path = outdir / "synthetic-qualification.json"
    record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    # validate
    try:
        bq.load_qualification(record_path, price_path, endpoint=ENDPOINT,
                              models=MODELS, price_models=PRICE_MODELS, now=now)
    except bq.BillingQualificationError as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2
    print(f"Wrote synthetic record: {record_path}")
    print("WARNING: synthetic record is NOT provider evidence.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Billing qualification helper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="validate a record")
    v.add_argument("record", help="path to qualification JSON")
    v.add_argument("--prices", help="path to prices JSON (default prices-2.json)")
    v.add_argument("--now", type=float, default=None, help="override current time (epoch)")
    s = sub.add_parser("synthetic", help="write a synthetic record (CI only)")
    s.add_argument("outdir", help="output directory")
    args = ap.parse_args(argv)
    if getattr(args, "now", None) is None:
        import time
        args.now = time.time()
    if args.cmd == "validate":
        return cmd_validate(args)
    if args.cmd == "synthetic":
        return cmd_synthetic(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
PY