#!/usr/bin/env python3
"""Strict-mode canary — self-prove the stale-base refusal, the way the onboarding
proof self-proves the hook path.

Why this exists
---------------
Layer 3 of the protection stack is server-side: branch protection on `main`
requires the `regression-gate` check *and* strict mode, so a pull request whose
base moved after its check ran must re-run the gate before it can merge. That
property was proved once by hand on 2026-10-11 — marker `edc782f`, refusal,
refresh `35d36ca`, revert `ef2aff1`, recorded in docs/PROJECT_COMPLETION.md §6b
— and nothing has re-proved it since. A protection setting is configuration: it
can be switched off, and a switch verified only in prose is a switch nobody is
watching.

What one run does
-----------------
Everything happens on a throwaway branch and pull request that are deleted at
the end, on every path:

1. Branch off an older commit of `main` and add a disposable marker commit. The
   head is then *behind* `main` while still carrying a commit `main` lacks — a
   plain ancestor head cannot be used, because GitHub refuses to open a pull
   request with no commits between base and head.
2. Put a green `regression-gate` check run on that head SHA. This precondition
   is what makes the probe mean anything: the refusal must not be explainable as
   "the required check never reported". The check run is created through the API
   by this tool rather than by CI — events authored by `GITHUB_TOKEN` do not
   start workflow runs, so CI cannot be relied on here — and its output text says
   plainly that it is synthetic and not gate evidence.
3. Assert the head really is behind `main` (compare API) and that GitHub reports
   the pull request as `behind` (the stale state itself).
4. Attempt the merge. Strict mode must refuse it — HTTP 405, the status the
   2026-10-11 test observed.
5. Positive control: `update-branch` (the remedy used that day), a fresh green
   check on the new head, and then assert the pull request leaves `behind` and
   becomes mergeable (`clean`, or `unstable` when some non-required check is
   pending — GitHub says `blocked`, not `unstable`, when a required check is the
   obstacle). That separates "staleness was refused" from "this token cannot
   merge anything", which is the failure mode that would make a refusal
   meaningless.
6. Close the pull request and delete the branch.

The probe never merges on purpose: every path stops at the merge being
*attempted*. A 2xx from that attempt is treated as a protection regression — the
run fails loudly, names the pull request, and warns that the marker file may now
be on `main`. The marker is one inert line, so the blast radius is a revertible
commit and the failure itself is the alarm.

Exit status
-----------
0  every assertion held — Layer 3 is live.
1  the probe ran and the verdict is not PASS: a refusal with an unexpected
   status, a state that never becomes `behind`, a merge that succeeds, or a
   cleanup that fails. An inconclusive canary must never read as a passing one.
2  misconfiguration — no token at all.
3  the environment refuses a step the probe needs (token scopes, or a repository
   policy such as `can_approve_pull_request_reviews=false`, which blocks
   `GITHUB_TOKEN` from opening pull requests even with `pull-requests: write`).
   That is a configuration gap to close, not a protection verdict, and it is
   reported as such rather than as a pass or as a regression.

Token
-----
`GH_TOKEN` (or `GITHUB_TOKEN`), needing `contents: write` (throwaway branch
refs), `pull-requests: write` (open, close, update-branch) and `checks: write`
(the synthetic green check). In CI that is the workflow's own `github.token`,
unless the repository forbids Actions-created pull requests — then a dedicated
token (`CANARY_TOKEN`) is the alternative to opening that repository setting.

Usage:
    GH_TOKEN=... python tools/strict_canary.py --repo owner/name
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

API_ROOT = "https://api.github.com"
DEFAULT_REPO = "StepenkoAnatoli/Holdshort"

#: Disposable marker written on the throwaway branch. Its appearance on `main`
#: is the visible trace of a protection regression, so keep the path clearly
#: canary-owned.
MARKER_PATH = "canary/strict-probe.md"

#: How far behind `main` the throwaway head is cut from. Any ancestor works;
#: going a couple of commits back makes the staleness unambiguous in the log.
STALE_BASE_DEPTH = 2

#: Must equal the branch-protection required context, which is also the CI job's
#: check-run name. Nothing here pins that name again — if it drifts, step 3's
#: `behind` assertion stops holding and the canary fails loudly.
CHECK_NAME = "regression-gate"

#: The stale state GitHub reports under strict mode, and the states that mean
#: staleness is no longer holding the merge up. `unstable` is legitimate here:
#: GitHub uses it for "mergeable, but some non-required check is pending or
#: failing" — it reports `blocked`, not `unstable`, when a *required* check is the
#: obstacle, so it cannot be read as strict mode still refusing.
STATE_BEHIND = "behind"
STATE_CLEAN = "clean"
STATE_UNSTABLE = "unstable"
STATE_MERGEABLE = (STATE_CLEAN, STATE_UNSTABLE)

#: The refusal status observed on 2026-10-11 (PR #21's record). 401/403 mean the
#: token cannot merge at all, which makes any refusal meaningless — an
#: inconclusive probe, not a pass.
MERGE_REFUSED_STATUS = 405

SYNTHETIC_DISCLOSURE = (
    "Synthetic check run created by tools/strict_canary.py. It is NOT gate "
    "evidence: it exists so this throwaway head carries a green required check, "
    "which is what makes the merge refusal attributable to strict mode instead "
    "of to a check that never reported."
)


class TransportError(RuntimeError):
    """The request produced no HTTP response at all."""


class ProbeError(RuntimeError):
    """The probe cannot reach a verdict (or reached the wrong one)."""


class EnvironmentBlocked(ProbeError):
    """A step the probe needs was refused for configuration reasons — token scopes
    or a repository policy — rather than by branch protection. Kept distinct so
    the run reports "cannot probe" instead of "protection regressed" or a plain
    failure: the remedy is configuration, and calling it anything else would
    either hide a real gap or cry wolf."""


def _decode(raw: bytes):
    """Parse a response body. List endpoints are legitimate (the commits listing
    is an array), so an array must survive decoding rather than collapse to {}. """
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def _field(payload, key: str, default=None):
    """Read `key` from a JSON object; arrays and error bodies simply yield the
    default, so callers never assume the shape they hoped for."""
    return payload.get(key, default) if isinstance(payload, dict) else default


class GitHub:
    """Minimal REST client. HTTP statuses are returned, never raised, so the
    probe can assert a refusal instead of catching an exception to see one."""

    def __init__(self, token: str, *, api_root: str = API_ROOT, timeout: float = 30.0, opener=None):
        if not token:
            raise ValueError("a token is required")
        self._token = token
        self._api_root = api_root.rstrip("/")
        self._timeout = timeout
        self._opener = opener or urllib.request.urlopen

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self._api_root + path, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self._token}")
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("User-Agent", "holdshort-strict-canary")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self._opener(request, timeout=self._timeout) as response:
                return response.status, _decode(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, _decode(exc.read())
        except urllib.error.URLError as exc:
            raise TransportError(f"{method} {path}: {exc.reason}") from exc


def marker_text(run_id: str) -> str:
    return (
        "Disposable marker for the strict-mode canary.\n"
        "\n"
        f"Written by tools/strict_canary.py (run {run_id}) on a throwaway branch that\n"
        "the probe deletes before it exits. See it on `main` and the branch\n"
        "protection that requires a green `regression-gate` check in strict mode has\n"
        "regressed: a stale base was allowed to merge.\n"
    )


def pr_title(run_id: str) -> str:
    return f"[canary] strict-mode stale-base refusal probe ({run_id}) — throwaway, auto-closed"


def pr_body(run_id: str, branch: str, head: str, base: str) -> str:
    return (
        "**Throwaway. Opened, probed, and closed automatically by `tools/strict_canary.py`.**\n"
        "\n"
        f"Run `{run_id}` — branch `{branch}`, head `{head[:7]}`, cut from `{base[:7]}` on `main`.\n"
        "\n"
        "It exists to prove Layer 3 of the protection stack is still live: with a green\n"
        "`regression-gate` check sitting on a head that is *behind* `main`, the merge API\n"
        "must refuse; after `update-branch` the same pull request must become mergeable.\n"
        "The probe then closes this pull request and deletes the branch.\n"
        "\n"
        "Nothing here asks anyone to merge it, and the green check on its head is\n"
        "synthetic (the probe places it deliberately) — not a gate result.\n"
    )


class StrictCanary:
    """One probe run. `api` is any object with `call(method, path, body)` ->
    `(status, payload)`, which is what the tests substitute."""

    def __init__(
        self,
        api,
        repo: str = DEFAULT_REPO,
        *,
        run_id: str | None = None,
        poll_timeout: float = 240.0,
        poll_interval: float = 5.0,
        sleep=time.sleep,
        monotonic=time.monotonic,
    ):
        self.api = api
        self.repo = repo
        self.run_id = run_id or os.environ.get("GITHUB_RUN_ID") or time.strftime(
            "%Y%m%dT%H%M%SZ", time.gmtime()
        )
        self.branch = f"canary/strict-probe-{self.run_id}"
        self.poll_timeout = poll_timeout
        self.poll_interval = poll_interval
        self._sleep = sleep
        self._monotonic = monotonic

        self.steps: list[str] = []
        self.cleanup: list[str] = []
        self.failure: str | None = None
        self.merged = False
        self.cleanup_failed = False
        self.pr: int | None = None
        self.pr_url: str | None = None
        self.head: str | None = None
        self.branch_created = False
        self.blocked = False

    # ---------------------------------------------------------------- plumbing

    @property
    def ok(self) -> bool:
        return self.failure is None

    def _step(self, name: str, detail: str = "") -> None:
        self.steps.append(f"{name}: {detail}" if detail else name)

    def _require(self, condition: bool, message: str) -> None:
        if not condition:
            raise ProbeError(message)

    def _wait_state(self, accept: set[str], what: str) -> str:
        deadline = self._monotonic() + self.poll_timeout
        last = "unknown"
        while True:
            status, pr = self.api.call("GET", f"/repos/{self.repo}/pulls/{self.pr}")
            self._require(status == 200, f"GET pulls/{self.pr} -> HTTP {status}")
            last = _field(pr, "mergeable_state") or "unknown"
            if last in accept:
                return last
            if self._monotonic() >= deadline:
                return last
            self._sleep(self.poll_interval)

    # ------------------------------------------------------------------ probe

    def run(self) -> int:
        try:
            self._probe()
        except EnvironmentBlocked as exc:
            self.blocked = True
            self._fail(str(exc))
        except (ProbeError, TransportError) as exc:
            self._fail(str(exc))
        finally:
            self._cleanup()
        if self.ok:
            return 0
        return 3 if self.blocked else 1

    def _fail(self, message: str) -> None:
        if self.failure is None:
            self.failure = message
        else:
            self.failure = f"{self.failure} | additionally: {message}"

    def _probe(self) -> None:
        tip, base = self._pick_base()
        self._create_branch(base)
        self._create_marker_commit()
        self._assert_behind(tip)
        self._synthetic_green_check(self.head, "pre-merge")
        self._open_pr(base)
        state = self._wait_state({STATE_BEHIND}, "stale head")
        self._require(
            state == STATE_BEHIND,
            f"head never reported {STATE_BEHIND!r} (last state {state!r}): either strict mode is "
            "off, or protection is blocking this pull request for some other reason",
        )
        self._step("stale-state", f"mergeable_state={STATE_BEHIND!r}")
        self._attempt_merge()
        new_head = self._refresh()
        self._synthetic_green_check(new_head, "post-refresh")
        state = self._wait_state(set(STATE_MERGEABLE), "refreshed head")
        status, pr = self.api.call("GET", f"/repos/{self.repo}/pulls/{self.pr}")
        mergeable = _field(pr, "mergeable") if status == 200 else None
        self._require(
            state in STATE_MERGEABLE and mergeable is not False,
            f"after refresh the pull request reports {state!r} (mergeable={mergeable!r}), not "
            f"{' or '.join(STATE_MERGEABLE)}: the refusal cannot be attributed to staleness rather "
            f"than to a blanket block — {self._pending_work()}",
        )
        self._step("refreshed-state", f"mergeable_state={state!r}, mergeable={mergeable!r}")

    def _pending_work(self) -> str:
        """What the refreshed head is actually waiting on. Without this a failed
        positive control says only which state came back, and the operator cannot
        tell a pending non-required check from a genuine block."""
        bits = []
        status, runs = self.api.call("GET", f"/repos/{self.repo}/commits/{self.head}/check-runs")
        if status == 200 and isinstance(runs, dict):
            entries = [
                f"{run.get('name')}={run.get('status')}/{run.get('conclusion')}"
                for run in (runs.get("check_runs") or [])
            ]
            bits.append("checks on head: " + (", ".join(entries) if entries else "none"))
        else:
            bits.append(f"check-runs lookup -> HTTP {status}")
        return "; ".join(bits)

    def _pick_base(self) -> tuple[str, str]:
        status, tip_payload = self.api.call("GET", f"/repos/{self.repo}/commits/main")
        self._require(status == 200, f"GET commits/main -> HTTP {status}")
        tip = _field(tip_payload, "sha")
        self._require(bool(tip), "commits/main returned no sha")

        status, listing = self.api.call(
            "GET", f"/repos/{self.repo}/commits?sha=main&per_page={STALE_BASE_DEPTH + 1}"
        )
        self._require(status == 200, f"GET commits?sha=main -> HTTP {status}")
        self._require(
            isinstance(listing, list) and len(listing) > STALE_BASE_DEPTH,
            f"main history is too short to cut a stale base ({STALE_BASE_DEPTH} back)",
        )
        base = _field(listing[STALE_BASE_DEPTH], "sha")
        self._require(bool(base), "history entry carried no sha")
        self._require(base != tip, "picked base equals main's tip, so the head could not be stale")
        self._step("base-picked", f"main {tip[:7]}, stale base {base[:7]}")
        return tip, base

    def _create_branch(self, base: str) -> None:
        status, payload = self.api.call(
            "POST",
            f"/repos/{self.repo}/git/refs",
            {"ref": f"refs/heads/{self.branch}", "sha": base},
        )
        if status in (401, 403):
            raise EnvironmentBlocked(
                f"cannot create the throwaway branch (HTTP {status}): the token needs "
                "`contents: write`"
            )
        self._require(200 <= status < 300, f"POST git/refs -> HTTP {status}: {payload}")
        self.branch_created = True
        self._step("branch-created", self.branch)

    def _create_marker_commit(self) -> None:
        content = base64.b64encode(marker_text(self.run_id).encode("utf-8")).decode("ascii")
        status, payload = self.api.call(
            "PUT",
            f"/repos/{self.repo}/contents/{MARKER_PATH}",
            {
                "message": f"canary: disposable strict-mode probe marker (run {self.run_id})",
                "branch": self.branch,
                "content": content,
            },
        )
        self._require(200 <= status < 300, f"PUT contents/{MARKER_PATH} -> HTTP {status}: {payload}")
        sha = _field(_field(payload, "commit", {}) or {}, "sha")
        self._require(bool(sha), "marker commit carried no sha")
        self.head = sha
        self._step("marker-commit", f"{MARKER_PATH} at {sha[:7]}")

    def _assert_behind(self, tip: str) -> None:
        status, compare = self.api.call(
            "GET", f"/repos/{self.repo}/compare/main...{self.branch}"
        )
        self._require(status == 200, f"GET compare/main...{self.branch} -> HTTP {status}")
        behind = compare.get("behind_by", 0)
        ahead = compare.get("ahead_by", 0)
        self._require(
            behind >= 1 and ahead >= 1,
            f"throwaway head is not stale-with-a-commit (behind_by={behind}, ahead_by={ahead})",
        )
        self._step("head-is-stale", f"behind_by={behind}, ahead_by={ahead}, head={self.head[:7]}")

    def _synthetic_green_check(self, head: str, label: str) -> None:
        status, payload = self.api.call(
            "POST",
            f"/repos/{self.repo}/check-runs",
            {
                "name": CHECK_NAME,
                "head_sha": head,
                "status": "completed",
                "conclusion": "success",
                "output": {"title": "synthetic check — not gate evidence", "summary": SYNTHETIC_DISCLOSURE},
            },
        )
        if status in (401, 403):
            raise EnvironmentBlocked(
                f"cannot place the green {CHECK_NAME} check on the throwaway head (HTTP {status}): "
                "the token needs `checks: write`, without which staleness cannot be separated from "
                "a required check that never reported"
            )
        self._require(200 <= status < 300, f"POST check-runs -> HTTP {status}: {payload}")

        status, runs = self.api.call("GET", f"/repos/{self.repo}/commits/{head}/check-runs")
        self._require(status == 200, f"GET commits/{head[:7]}/check-runs -> HTTP {status}")
        green = [
            run
            for run in (runs.get("check_runs") or [])
            if run.get("name") == CHECK_NAME and run.get("conclusion") == "success"
        ]
        self._require(
            bool(green),
            f"no green {CHECK_NAME} check run on {head[:7]} after creating one — the probe "
            "would not be able to tell a stale refusal from a missing check",
        )
        self._step(f"green-check({label})", f"{len(green)}x {CHECK_NAME}=success on {head[:7]}")

    def _open_pr(self, base: str) -> None:
        status, payload = self.api.call(
            "POST",
            f"/repos/{self.repo}/pulls",
            {
                "title": pr_title(self.run_id),
                "head": self.branch,
                "base": "main",
                "body": pr_body(self.run_id, self.branch, self.head, base),
            },
        )
        if status in (401, 403):
            raise EnvironmentBlocked(
                f"cannot open the throwaway pull request (HTTP {status}): either the token lacks "
                "`pull-requests: write`, or the repository forbids Actions from creating pull "
                "requests (`can_approve_pull_request_reviews=false` is the case when a job-level "
                "`pull-requests: write` still answers 403). Close it by enabling that repository "
                "setting, or point this job at a dedicated token via `CANARY_TOKEN`."
            )
        self._require(200 <= status < 300, f"POST pulls -> HTTP {status}: {payload}")
        self.pr = _field(payload, "number")
        self.pr_url = _field(payload, "html_url")
        self._require(bool(self.pr), "pull request carried no number")
        self._step("pr-opened", f"#{self.pr} {self.pr_url or ''}".strip())

    def _attempt_merge(self) -> None:
        status, payload = self.api.call(
            "PUT",
            f"/repos/{self.repo}/pulls/{self.pr}/merge",
            {"merge_method": "merge", "sha": self.head},
        )
        message = str(payload.get("message", "")) if isinstance(payload, dict) else ""

        if 200 <= status < 300:
            self.merged = True
            raise ProbeError(
                f"PROTECTION REGRESSED: the merge of a stale head was ACCEPTED (HTTP {status}, "
                f"pull request #{self.pr}). Strict mode is not being enforced. The marker "
                f"{MARKER_PATH} may now be on main — revert the canary merge ({payload})."
            )
        if status in (401, 403):
            raise ProbeError(
                f"inconclusive: the merge was refused with HTTP {status} ({message!r}), which is a "
                "permission refusal rather than the strict-mode one; this token cannot prove "
                "anything about staleness"
            )
        self._require(
            status == MERGE_REFUSED_STATUS,
            f"inconclusive: the merge was refused with HTTP {status} ({message!r}), but the "
            f"strict-mode refusal observed on 2026-10-11 was {MERGE_REFUSED_STATUS}",
        )
        self._step("merge-refused", f"HTTP {status}: {message}")

    def _refresh(self) -> str:
        status, payload = self.api.call(
            "PUT",
            f"/repos/{self.repo}/pulls/{self.pr}/update-branch",
            {"expected_head_sha": self.head},
        )
        if status in (401, 403):
            raise EnvironmentBlocked(
                f"update-branch was refused (HTTP {status}): the token needs `pull-requests: write` "
                "and write access to this repository"
            )
        if status in (404, 405, 422):
            raise ProbeError(
                f"inconclusive: update-branch -> HTTP {status} "
                f"({payload.get('message') if isinstance(payload, dict) else ''!r}); without the "
                "positive control a refusal cannot be separated from a blanket block"
            )
        self._require(200 <= status < 300, f"PUT update-branch -> HTTP {status}: {payload}")

        # update-branch answers 202 and moves the branch shortly afterwards, so the
        # head has to be waited for. Reading it immediately reports the old SHA and
        # looks like the refresh silently failed (it did, on the first CI run).
        deadline = self._monotonic() + self.poll_timeout
        new_head = self.head
        while new_head == self.head:
            get_status, pr = self.api.call("GET", f"/repos/{self.repo}/pulls/{self.pr}")
            self._require(get_status == 200, f"GET pulls/{self.pr} -> HTTP {get_status}")
            new_head = _field(_field(pr, "head", {}) or {}, "sha") or self.head
            if new_head != self.head or self._monotonic() >= deadline:
                break
            self._sleep(self.poll_interval)
        self._require(
            new_head != self.head,
            f"update-branch answered HTTP {status} but the head never moved from {self.head[:7]} "
            f"within {self.poll_timeout:.0f}s: the positive control needs the refreshed head, so "
            "this run cannot separate staleness from a blanket block",
        )
        self._step("refreshed", f"head {self.head[:7]} -> {new_head[:7]}")
        self.head = new_head
        return new_head

    def _cleanup(self) -> None:
        if self.pr is not None:
            status, payload = self._quiet("PATCH", f"/repos/{self.repo}/pulls/{self.pr}", {"state": "closed"})
            self.cleanup.append(f"close PR #{self.pr}: HTTP {status}")
            if not 200 <= status < 300:
                self.cleanup_failed = True
                self._fail(f"cleanup failed: closing PR #{self.pr} -> HTTP {status} {payload}")
        if self.branch_created:
            status, payload = self._quiet("DELETE", f"/repos/{self.repo}/git/refs/heads/{self.branch}")
            self.cleanup.append(f"delete branch {self.branch}: HTTP {status}")
            if not 200 <= status < 300:
                self.cleanup_failed = True
                self._fail(
                    f"cleanup failed: deleting {self.branch} -> HTTP {status} {payload} — a stale "
                    "head with a green check must not be left behind"
                )

    def _quiet(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        try:
            return self.api.call(method, path, body)
        except TransportError as exc:
            self.cleanup_failed = True
            return 0, {"message": str(exc)}


def render(canary: StrictCanary) -> str:
    lines = [
        f"strict-canary: repo={canary.repo} run={canary.run_id} branch={canary.branch}",
    ]
    for step in canary.steps:
        lines.append(f"  OK   {step}")
    for entry in canary.cleanup:
        lines.append(f"  done {entry}")
    if canary.merged:
        lines.append("  !!   a stale merge was accepted — protection is not being enforced")
        lines.append(f"  !!   revert the canary merge; marker: {MARKER_PATH}")
    if canary.ok:
        lines.append("strict-canary: PASS — stale head refused, refreshed head mergeable")
    elif canary.blocked:
        lines.append(f"strict-canary: CANNOT PROBE (exit 3) — {canary.failure}")
        lines.append("  Layer 3 is unproven until this is fixed; that is a gap, not a pass.")
    else:
        lines.append(f"strict-canary: FAIL — {canary.failure}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Self-prove the strict-mode stale-base refusal.")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO),
                        help="owner/name (default: $GITHUB_REPOSITORY or the canonical repo)")
    parser.add_argument("--run-id", default=None, help="label for the throwaway branch/PR")
    parser.add_argument("--timeout", type=float, default=240.0,
                        help="seconds to wait for each mergeable_state transition")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--api-root", default=API_ROOT, help="for tests/GHES")
    args = parser.parse_args(argv)

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("strict-canary: no token in GH_TOKEN/GITHUB_TOKEN — refusing to guess", file=sys.stderr)
        return 2

    canary = StrictCanary(
        GitHub(token, api_root=args.api_root),
        args.repo,
        run_id=args.run_id,
        poll_timeout=args.timeout,
        poll_interval=args.poll_interval,
    )
    code = canary.run()
    print(render(canary))
    return code


if __name__ == "__main__":
    sys.exit(main())
