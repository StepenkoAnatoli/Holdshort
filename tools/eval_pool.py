#!/usr/bin/env python3
"""Freeze and check the prospective local evaluation fixtures; never call a model.

The pool is a new engineering proposal, not a change to historical ratification.
Its acceptance scripts execute candidate code. The host must provide suitable
isolation before checking a model-produced workspace; this tool is not a sandbox.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import random
import secrets
import subprocess
import sys
import tempfile

DEFAULT_POOL = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "prospective-eval" / "pool-v1.json"
EXPECTED_MANIFEST_SHA256 = "c6efcd0a114c9a07c1a565f31a0ac5efa518fdd182c03b629168954aa55effd4"
EXPECTED_SCHEDULE_SHA256 = "110b8344e0f6dc93eff08993172f27b5b3813ff0ff57915fdde6fa1f56568d45"
ARMS = ("A", "B", "C", "D")
CELLS = ("T-01", "T-02", "T-03", "T-04", "T-05")
PLAN_REVISION = "d7c00f96a17c35e6c47c5ba1f7e3a9160c966042"


class PoolInvalid(ValueError):
    pass


def canonical_hash(value) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PoolInvalid(f"noncanonical pool data: {exc}") from exc
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def manifest_hash(pool: dict) -> str:
    return canonical_hash({key: value for key, value in pool.items() if key != "manifest_sha256"})


def fixture_hash(fixture: dict) -> str:
    return canonical_hash(fixture)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PoolInvalid(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _safe_name(value) -> bool:
    return (isinstance(value, str) and bool(value) and "\\" not in value
            and ":" not in value and not PurePosixPath(value).is_absolute()
            and all(part not in ("", ".", "..") for part in value.split("/")))


def validate_pool(pool: dict) -> dict:
    if not isinstance(pool, dict) or type(pool.get("schema_version")) is not int or pool["schema_version"] != 1:
        raise PoolInvalid("pool must be a version 1 object")
    if pool.get("pool_id") != "smartrouter-prospective-v1":
        raise PoolInvalid("unknown pool identity")
    if (pool.get("arms") != list(ARMS) or type(pool.get("repeats")) is not int
            or pool["repeats"] != 2 or type(pool.get("observations_per_arm")) is not int
            or pool["observations_per_arm"] != 20):
        raise PoolInvalid("pool must have four arms and two repeats for 20 observations per arm")
    if pool.get("historical_ratification") is not False or pool.get("live_model_qualification") != "pending":
        raise PoolInvalid("the prospective pool must not claim historical or live-model qualification")
    if pool.get("plan_revision") != PLAN_REVISION:
        raise PoolInvalid("unexpected pinned plan revision")
    expected_inputs = {"split": f"{PLAN_REVISION}|seed_holdout_1",
                       "ordering": f"{PLAN_REVISION}|seed_ordering_1"}
    expected_seeds = {key: int(hashlib.sha256(value.encode()).hexdigest()[:16], 16)
                      for key, value in expected_inputs.items()}
    if pool.get("seed_inputs") != expected_inputs or pool.get("seeds") != expected_seeds:
        raise PoolInvalid("seed derivation inputs or values changed")
    fixtures = pool.get("fixtures")
    if not isinstance(fixtures, list) or len(fixtures) != 10:
        raise PoolInvalid("pool needs ten distinct fixtures")
    ids, contents, cells = set(), set(), {cell: 0 for cell in CELLS}
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise PoolInvalid("fixture must be an object")
        identifier = fixture.get("fixture_id")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in ids:
            raise PoolInvalid("fixture identities must be nonempty and unique")
        ids.add(identifier)
        cell = fixture.get("cell")
        if not isinstance(cell, str) or cell not in cells:
            raise PoolInvalid("fixture cell is unknown")
        cells[cell] += 1
        for field in ("title", "category", "prompt", "checks"):
            if not isinstance(fixture.get(field), str) or not fixture[field].strip():
                raise PoolInvalid(f"fixture {identifier} lacks {field}")
        files, reference, writes = (fixture.get(key) for key in ("files", "reference", "writable_paths"))
        if (not isinstance(files, dict) or not files or not isinstance(reference, dict)
                or set(files) != set(reference) or not isinstance(writes, list) or not writes
                or any(not _safe_name(path) for path in writes)
                or len(writes) != len(set(writes)) or any(path not in files for path in writes)):
            raise PoolInvalid(f"fixture {identifier} has invalid file/write contracts")
        if any(not _safe_name(path) or not isinstance(content, str)
               for mapping in (files, reference) for path, content in mapping.items()):
            raise PoolInvalid("fixture paths must stay within their workspace and contents must be text")
        if any(reference[path] != files[path] for path in files if path not in writes):
            raise PoolInvalid("reference changes a read-only file")
        # Ignore the ID, title, and filenames when rejecting renamed duplicates.
        content_key = canonical_hash({"files": sorted(files.values()), "reference": sorted(reference.values()),
                                      "checks": fixture["checks"]})
        if content_key in contents:
            raise PoolInvalid("renamed identical fixture content is not a distinct task")
        contents.add(content_key)
    if any(count != 2 for count in cells.values()) or ids != {f"PE-{i:02}" for i in range(1, 11)}:
        raise PoolInvalid("each category needs two frozen fixture identities")
    digest = manifest_hash(pool)
    if digest != pool.get("manifest_sha256") or digest != EXPECTED_MANIFEST_SHA256:
        raise PoolInvalid("pool manifest changed; amended content/checks need a newly reviewed version")
    return pool


def load_pool(path: Path = DEFAULT_POOL) -> dict:
    try:
        pool = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PoolInvalid(f"pool cannot be read: {exc}") from exc
    return validate_pool(pool)


def freeze_plan(pool: dict) -> dict:
    validate_pool(pool)
    rng = random.Random(pool["seeds"]["split"])
    fixtures = {}
    for cell in CELLS:
        pair = sorted((f for f in pool["fixtures"] if f["cell"] == cell), key=lambda f: f["fixture_id"])
        holdout = rng.randrange(2)
        for index, fixture in enumerate(pair):
            fixtures[fixture["fixture_id"]] = {"cell": cell, "split": "holdout" if index == holdout else "tuning",
                                                "fixture_sha256": fixture_hash(fixture)}
    blocks = [(identifier, repeat) for identifier in sorted(fixtures) for repeat in (1, 2)]
    order = random.Random(pool["seeds"]["ordering"])
    order.shuffle(blocks)
    trials, assignments = [], {}
    for identifier, repeat in blocks:
        arms = list(ARMS)
        order.shuffle(arms)
        for arm in arms:
            task_id = f"{pool['pool_id']}--{identifier}--{arm}--r{repeat}"
            trial = {"trial_id": task_id, "task_id": task_id, "fixture_id": identifier,
                     "arm": arm, "cell": fixtures[identifier]["cell"], "repeat": repeat,
                     "split": fixtures[identifier]["split"], "schedule_index": len(trials) + 1,
                     "manifest_sha256": pool["manifest_sha256"]}
            trials.append(trial)
            assignments[task_id] = {key: value for key, value in trial.items() if key not in ("task_id", "trial_id")}
    schedule_hash = canonical_hash({"fixtures": fixtures, "trials": trials})
    if schedule_hash != EXPECTED_SCHEDULE_SHA256:
        raise PoolInvalid("derived allocation/order differs from the frozen schedule; do not substitute trials")
    return {"pool_id": pool["pool_id"], "manifest_sha256": pool["manifest_sha256"],
            "schedule_sha256": schedule_hash,
            "fixture_qualification": "local-contracts", "live_model_qualification": "pending",
            "fixtures": fixtures, "trials": trials, "assignments": assignments}


def _fixture(pool, identifier):
    for fixture in pool["fixtures"]:
        if fixture["fixture_id"] == identifier:
            return fixture
    raise PoolInvalid(f"unknown fixture {identifier!r}")


def _write_files(destination: Path, files: dict) -> None:
    for name, content in files.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def prepare_trial(pool: dict, trial_id: str, destination: Path) -> dict:
    plan = freeze_plan(pool)
    trial = next((trial for trial in plan["trials"] if trial["trial_id"] == trial_id), None)
    if trial is None:
        raise PoolInvalid("trial ID is not in the frozen schedule")
    if destination.exists() or destination.is_symlink():
        raise PoolInvalid("trial destination must be new; never reset a prior trial")
    fixture = _fixture(pool, trial["fixture_id"])
    destination.mkdir(parents=True)
    _write_files(destination, fixture["files"])
    return {**trial, "workspace": str(destination.resolve()), "prompt": fixture["prompt"],
            "writable_paths": fixture["writable_paths"]}


def _workspace_problem(fixture: dict, workspace: Path) -> str | None:
    if not workspace.is_dir() or workspace.is_symlink():
        return "workspace must be an existing ordinary directory"
    actual = set()
    for path in workspace.rglob("*"):
        if path.is_symlink():
            return "workspace symlinks are outside the fixture contract"
        if path.is_file():
            actual.add(path.relative_to(workspace).as_posix())
    if actual != set(fixture["files"]):
        return "workspace file set changed outside the contract"
    for name, content in fixture["files"].items():
        if name not in fixture["writable_paths"] and (workspace / name).read_bytes() != content.encode("utf-8"):
            return f"read-only file changed: {name}"
    return None


def verify_fixture(pool: dict, fixture_id: str, workspace: Path, *, timeout_s: float = 10) -> dict:
    validate_pool(pool)
    fixture = _fixture(pool, fixture_id)
    try:
        valid_timeout = type(timeout_s) in (int, float) and math.isfinite(timeout_s) and timeout_s > 0
    except OverflowError:
        valid_timeout = False
    if not valid_timeout:
        raise PoolInvalid("acceptance timeout must be finite and positive")
    problem = _workspace_problem(fixture, workspace)
    if problem:
        return {"accepted": False, "reason": problem}
    completion = ("HOLDSHORT_ACCEPTANCE_DONE:" + secrets.token_hex(16)).encode("ascii")
    script = ("import os,sys\nsys.path.insert(0,sys.argv[1])\nos.chdir(sys.argv[1])\n" + fixture["checks"]
              + f"\nprint({completion.decode('ascii')!r}, flush=True)\n")
    try:
        result = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(workspace.resolve())],
                                capture_output=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return {"accepted": False, "reason": "acceptance command timed out"}
    problem = _workspace_problem(fixture, workspace)
    if problem:
        return {"accepted": False, "reason": problem}
    return {"accepted": result.returncode == 0 and completion in result.stdout.splitlines(),
            "exit_code": result.returncode,
            "output": (result.stdout + result.stderr).decode("utf-8", errors="replace")[-4000:]}


def self_check(pool: dict) -> dict:
    """Qualify local acceptance contracts, not model performance or live billing."""
    validate_pool(pool)
    results = []
    for fixture in pool["fixtures"]:
        with tempfile.TemporaryDirectory(prefix="holdshort-eval-") as directory:
            workspace = Path(directory)
            _write_files(workspace, fixture["files"])
            baseline = verify_fixture(pool, fixture["fixture_id"], workspace)
            _write_files(workspace, fixture["reference"])
            reference = verify_fixture(pool, fixture["fixture_id"], workspace)
            results.append({"fixture_id": fixture["fixture_id"], "baseline_rejected": not baseline["accepted"],
                            "reference_accepted": reference["accepted"],
                            "passed": not baseline["accepted"] and reference["accepted"]})
    return {"pool_id": pool["pool_id"], "manifest_sha256": pool["manifest_sha256"],
            "passed": all(result["passed"] for result in results), "fixtures": results,
            "live_model_qualification": "pending", "provider_calls": 0}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan")
    commands.add_parser("self-check")
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--trial-id", required=True)
    prepare.add_argument("--destination", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--fixture-id", required=True)
    verify.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        pool = load_pool(args.pool)
        if args.command == "plan":
            result = freeze_plan(pool)
        elif args.command == "prepare":
            result = prepare_trial(pool, args.trial_id, args.destination)
        elif args.command == "verify":
            result = verify_fixture(pool, args.fixture_id, args.workspace)
        else:
            result = self_check(pool)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0 if result.get("accepted", result.get("passed", True)) else 1
    except (PoolInvalid, OSError) as exc:
        print(f"eval_pool: INVALID — {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
