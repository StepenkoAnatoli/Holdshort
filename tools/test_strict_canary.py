#!/usr/bin/env python3
"""Tests for tools/strict_canary.py — the Layer-3 stale-base refusal probe.

The probe talks to GitHub, so the contract worth pinning is the *verdict logic*
and the safety rules around it. A scripted fake API substitutes for the REST
surface; nothing here touches the network or this repository.

Pinned contracts:
  * a refused stale merge plus a refresh that becomes mergeable is a PASS, and
    the throwaway pull request and branch are cleaned up;
  * a merge that is ACCEPTED is a protection regression, not a pass;
  * a 401/403 refusal is inconclusive (the token cannot merge at all, so a
    refusal proves nothing about staleness), and a status other than the
    recorded 405 is inconclusive too;
  * a head that never reports `behind` fails, and so does a refresh that never
    reaches `clean` — the refusal must be attributable to staleness;
  * the merge is never attempted unless a green required check sits on the head
    (otherwise "refused" could just mean "required check never reported");
  * a step the probe needs being refused for configuration reasons (token scopes,
    or a repository policy blocking Actions-created pull requests) exits 3 as
    "cannot probe" — neither a pass nor a protection verdict;
  * cleanup runs on every path, a cleanup failure fails the run, and no ref is
    deleted when the ref was never created;
  * the pull request, its title/body, the marker and the synthetic check run all
    say what they are, so nobody mistakes them for real work or gate evidence.

The fake API substitutes for the REST surface *after* decoding, so the HTTP
client has its own tests over a stubbed transport: an early version of this tool
decoded only JSON objects and silently discarded the commits listing (an array),
which the scripted fake could not reveal because it hands back parsed payloads.
"""
from __future__ import annotations

import importlib.util
import io
import unittest
import urllib.error
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("strict_canary", TOOLS / "strict_canary.py")
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)

REPO = "o/r"
TIP = "a" * 40
BASE = "b" * 40
HEAD1 = "1" * 40
HEAD2 = "2" * 40


class Clock:
    """Monotonic source that advances on every read, so polls terminate."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        self.t += 1.0
        return self.t


class FakeApi:
    """Scripted stand-in for GitHub's REST API. Records every call."""

    def __init__(
        self,
        *,
        merge_status: int = 405,
        merge_message: str = 'Required status check "regression-gate" is expected',
        states: tuple[str, ...] = ("unknown", "behind"),
        refreshed_state: str = "clean",
        check_runs_green: bool = True,
        create_ref_status: int = 201,
        check_runs_status: int = 201,
        pulls_status: int = 201,
        delete_status: int = 204,
        close_status: int = 200,
        update_branch_status: int = 202,
        compare: tuple[int, int] = (3, 1),
    ):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.merge_status = merge_status
        self.merge_message = merge_message
        self._states = list(states)
        self.refreshed_state = refreshed_state
        self.check_runs_green = check_runs_green
        self.create_ref_status = create_ref_status
        self.check_runs_status = check_runs_status
        self.pulls_status = pulls_status
        self.delete_status = delete_status
        self.close_status = close_status
        self.update_branch_status = update_branch_status
        self.compare = compare
        self.refreshed = False
        self.check_run_heads: list[str] = []
        self._consumed_state = "unknown"

    # --- helpers -----------------------------------------------------------

    def calls_matching(self, method: str, needle: str) -> list[tuple[str, str, dict | None]]:
        return [c for c in self.calls if c[0] == method and needle in c[1]]

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        self.calls.append((method, path, body))
        repo_prefix = f"/repos/{REPO}"

        if method == "GET" and path == f"{repo_prefix}/commits/main":
            return 200, {"sha": TIP}

        if method == "GET" and path.startswith(f"{repo_prefix}/commits?sha=main"):
            return 200, [{"sha": TIP}, {"sha": "f" * 40}, {"sha": BASE}]

        if method == "POST" and path == f"{repo_prefix}/git/refs":
            if self.create_ref_status >= 300:
                return self.create_ref_status, {"message": "Resource not accessible by integration"}
            return self.create_ref_status, {"ref": (body or {}).get("ref", "")}

        if method == "PUT" and path.startswith(f"{repo_prefix}/contents/"):
            return 201, {"commit": {"sha": HEAD1}}

        if method == "GET" and path.startswith(f"{repo_prefix}/compare/"):
            behind, ahead = self.compare
            return 200, {"status": "behind" if behind else "ahead", "behind_by": behind, "ahead_by": ahead}

        if method == "POST" and path == f"{repo_prefix}/check-runs":
            if self.check_runs_status >= 300:
                self.check_run_heads.append((body or {}).get("head_sha", ""))
                return self.check_runs_status, {"message": "Resource not accessible by integration"}
            self.check_run_heads.append((body or {}).get("head_sha", ""))
            return self.check_runs_status, {"id": len(self.check_run_heads)}

        if method == "GET" and path.endswith("/check-runs"):
            if not self.check_runs_green:
                return 200, {"check_runs": []}
            head = path.split("/commits/")[1].split("/check-runs")[0]
            return 200, {
                "check_runs": [
                    {"name": sc.CHECK_NAME, "status": "completed", "conclusion": "success", "head_sha": head}
                ]
            }

        if method == "POST" and path == f"{repo_prefix}/pulls":
            if self.pulls_status >= 300:
                return self.pulls_status, {
                    "message": "GitHub Actions is not permitted to create or approve pull requests."
                }
            return self.pulls_status, {"number": 99, "html_url": "https://example.invalid/pull/99"}

        if method == "PATCH" and path == f"{repo_prefix}/pulls/99":
            return self.close_status, {}

        if method == "PUT" and path == f"{repo_prefix}/pulls/99/merge":
            return self.merge_status, {"message": self.merge_message} if self.merge_status >= 300 else {
                "sha": HEAD1,
                "merged": True,
                "message": "Pull Request successfully merged",
            }

        if method == "PUT" and path == f"{repo_prefix}/pulls/99/update-branch":
            if self.update_branch_status < 300:
                self.refreshed = True
            return self.update_branch_status, {"message": "Updating pull request branch."}

        if method == "GET" and path == f"{repo_prefix}/pulls/99":
            if self.refreshed:
                state = self.refreshed_state
            else:
                state = self._states.pop(0) if self._states else self._consumed_state
                self._consumed_state = state
            return 200, {"number": 99, "mergeable_state": state, "head": {"sha": HEAD2 if self.refreshed else HEAD1}}

        if method == "DELETE" and path.startswith(f"{repo_prefix}/git/refs/heads/"):
            return self.delete_status, {}

        raise AssertionError(f"unscripted call: {method} {path}")


def run_probe(api: FakeApi, **kwargs) -> tuple[sc.StrictCanary, int]:
    canary = sc.StrictCanary(
        api,
        REPO,
        run_id="test-run",
        poll_timeout=6.0,
        poll_interval=1.0,
        sleep=lambda _seconds: None,
        monotonic=Clock(),
        **kwargs,
    )
    return canary, canary.run()


class RefusalProbe(unittest.TestCase):
    def test_refused_stale_merge_then_mergeable_refresh_passes(self):
        api = FakeApi()
        canary, code = run_probe(api)
        self.assertEqual(code, 0, canary.failure)
        self.assertTrue(canary.ok)
        joined = " | ".join(canary.steps)
        self.assertIn("head-is-stale", joined)
        self.assertIn("merge-refused", joined)
        self.assertIn("refreshed-state", joined)

    def test_cleanup_closes_the_pr_and_deletes_the_branch(self):
        api = FakeApi()
        _, code = run_probe(api)
        self.assertEqual(code, 0)
        self.assertEqual(len(api.calls_matching("PATCH", "/pulls/99")), 1)
        self.assertEqual(len(api.calls_matching("DELETE", "/git/refs/heads/")), 1)

    def test_merge_is_attempted_exactly_once(self):
        api = FakeApi()
        run_probe(api)
        self.assertEqual(len(api.calls_matching("PUT", "/merge")), 1)

    def test_green_check_is_placed_on_both_heads(self):
        api = FakeApi()
        run_probe(api)
        self.assertEqual(api.check_run_heads, [HEAD1, HEAD2])


class ProtectionRegressed(unittest.TestCase):
    def test_accepted_merge_is_not_a_pass(self):
        api = FakeApi(merge_status=200)
        canary, code = run_probe(api)
        self.assertEqual(code, 1)
        self.assertTrue(canary.merged)
        self.assertIn("PROTECTION REGRESSED", canary.failure)
        self.assertIn(sc.MARKER_PATH, canary.failure)

    def test_cleanup_still_runs_after_a_regression(self):
        api = FakeApi(merge_status=200)
        run_probe(api)
        self.assertEqual(len(api.calls_matching("PATCH", "/pulls/99")), 1)
        self.assertEqual(len(api.calls_matching("DELETE", "/git/refs/heads/")), 1)

    def test_regression_is_banner_in_the_rendered_report(self):
        api = FakeApi(merge_status=200)
        canary, _ = run_probe(api)
        report = sc.render(canary)
        self.assertIn("!!", report)
        self.assertIn("\nstrict-canary: FAIL", report)


class InconclusiveIsNotAPass(unittest.TestCase):
    def test_permission_refusal_is_inconclusive(self):
        api = FakeApi(merge_status=403)
        canary, code = run_probe(api)
        self.assertEqual(code, 1)
        self.assertIn("inconclusive", canary.failure)
        self.assertIn("permission refusal", canary.failure)

    def test_unexpected_refusal_status_is_inconclusive(self):
        api = FakeApi(merge_status=422)
        canary, code = run_probe(api)
        self.assertEqual(code, 1)
        self.assertIn("inconclusive", canary.failure)
        self.assertIn(str(sc.MERGE_REFUSED_STATUS), canary.failure)

    def test_state_that_never_becomes_behind_fails(self):
        api = FakeApi(states=("clean",))
        canary, code = run_probe(api)
        self.assertEqual(code, 1)
        self.assertIn(sc.STATE_BEHIND, canary.failure)
        self.assertEqual(api.calls_matching("PUT", "/merge"), [], "must not attempt a merge when not stale")

    def test_refresh_that_never_becomes_clean_fails(self):
        api = FakeApi(refreshed_state="blocked")
        canary, code = run_probe(api)
        self.assertEqual(code, 1)
        self.assertIn("blocked", canary.failure)
        self.assertIn("staleness", canary.failure)

    def test_update_branch_refusal_is_inconclusive(self):
        api = FakeApi(update_branch_status=422)
        canary, code = run_probe(api)
        self.assertEqual(code, 1)
        self.assertIn("inconclusive", canary.failure)
        self.assertIn("positive control", canary.failure)


class SafetyRules(unittest.TestCase):
    def test_merge_is_never_attempted_without_a_green_check(self):
        api = FakeApi(check_runs_green=False)
        canary, code = run_probe(api)
        self.assertEqual(code, 1)
        self.assertIn(sc.CHECK_NAME, canary.failure)
        self.assertEqual(api.calls_matching("PUT", "/merge"), [])
        self.assertEqual(api.calls_matching("POST", "/pulls"), [])

    def test_cleanup_failure_fails_an_otherwise_passing_run(self):
        api = FakeApi(delete_status=403)
        canary, code = run_probe(api)
        self.assertEqual(code, 1)
        self.assertTrue(canary.cleanup_failed)
        self.assertIn("cleanup failed", canary.failure)
        self.assertIn("must not be left behind", canary.failure)

    def test_ref_creation_failure_is_reported_with_the_needed_permission(self):
        api = FakeApi(create_ref_status=403)
        canary, code = run_probe(api)
        self.assertEqual(code, 3, "scopes/policy are an environment gap, not a verdict")
        self.assertTrue(canary.blocked)
        self.assertIn("contents: write", canary.failure)
        self.assertEqual(api.calls_matching("DELETE", "/git/refs/heads/"), [],
                         "no ref was created, so none may be deleted")

    def test_compare_saying_not_stale_fails_before_any_pr(self):
        api = FakeApi(compare=(0, 1))
        canary, code = run_probe(api)
        self.assertEqual(code, 1)
        self.assertIn("not stale-with-a-commit", canary.failure)
        self.assertEqual(api.calls_matching("POST", "/pulls"), [])


class DisposableArtifacts(unittest.TestCase):
    def test_marker_lives_under_a_canary_owned_path(self):
        self.assertTrue(sc.MARKER_PATH.startswith("canary/"), sc.MARKER_PATH)

    def test_marker_says_what_its_presence_on_main_would_mean(self):
        text = sc.marker_text("run-1")
        self.assertIn("run-1", text)
        self.assertIn("Disposable", text)
        self.assertIn("regressed", text)

    def test_pr_title_and_body_say_throwaway_and_auto_closed(self):
        title = sc.pr_title("run-1")
        body = sc.pr_body("run-1", "canary/strict-probe-run-1", HEAD1, BASE)
        self.assertIn("canary", title)
        self.assertIn("throwaway", title)
        self.assertIn("auto-closed", title)
        self.assertIn("Throwaway", body)
        self.assertIn("closes this pull request", body)
        self.assertIn("synthetic", body)

    def test_synthetic_check_discloses_it_is_not_gate_evidence(self):
        api = FakeApi()
        run_probe(api)
        payloads = [
            body
            for method, path, body in api.calls
            if method == "POST" and path.endswith("/check-runs")
        ]
        self.assertEqual(len(payloads), 2)
        for payload in payloads:
            self.assertEqual(payload["name"], sc.CHECK_NAME)
            self.assertIn("NOT gate evidence", payload["output"]["summary"])

    def test_branch_name_carries_the_run_id(self):
        canary = sc.StrictCanary(FakeApi(), REPO, run_id="abc123")
        self.assertIn("abc123", canary.branch)


class CannotProbeIsItsOwnVerdict(unittest.TestCase):
    """Configuration refusals exit 3 and never read as PASS or as a regression."""

    def test_blocked_pr_creation_names_the_repository_policy(self):
        api = FakeApi(pulls_status=403)
        canary, code = run_probe(api)
        self.assertEqual(code, 3)
        self.assertTrue(canary.blocked)
        self.assertIn("can_approve_pull_request_reviews", canary.failure)
        self.assertIn("CANARY_TOKEN", canary.failure)
        self.assertEqual(api.calls_matching("PUT", "/merge"), [],
                         "nothing may be merged when the PR could not even be opened")

    def test_blocked_check_placement_exits_three(self):
        api = FakeApi(check_runs_status=403)
        canary, code = run_probe(api)
        self.assertEqual(code, 3)
        self.assertIn("checks: write", canary.failure)

    def test_blocked_run_is_not_rendered_as_pass_or_fail(self):
        canary, _ = run_probe(FakeApi(pulls_status=403))
        report = sc.render(canary)
        self.assertIn("CANNOT PROBE", report)
        self.assertIn("unproven", report)
        self.assertNotIn("strict-canary: FAIL", report)
        self.assertNotIn("strict-canary: PASS", report)

    def test_cleanup_still_runs_when_blocked(self):
        api = FakeApi(pulls_status=403)
        run_probe(api)
        self.assertEqual(len(api.calls_matching("DELETE", "/git/refs/heads/")), 1,
                         "a blocked probe must not leave its throwaway branch behind")


class _Response(io.BytesIO):
    """Minimal urlopen() result: context manager with .status and .read()."""

    def __init__(self, status: int, body: bytes):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class HttpClient(unittest.TestCase):
    """Pins the transport layer the scripted fake skips over."""

    def _client(self, responder):
        self.requests = []

        def opener(request, timeout=None):
            self.requests.append(request)
            return responder(request)

        return sc.GitHub("tok", api_root="https://api.example.invalid", opener=opener)

    def test_array_payloads_survive_decoding(self):
        # The regression this test exists for: a JSON array (the commits listing)
        # must not be collapsed into an empty object. Fixed 2026-10-12.
        api = self._client(lambda _req: _Response(200, b'[{"sha": "x"}, {"sha": "y"}]'))
        status, payload = api.call("GET", "/repos/o/r/commits?sha=main")
        self.assertEqual(status, 200)
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 2)

    def test_object_payloads_still_parse(self):
        api = self._client(lambda _req: _Response(200, b'{"sha": "abc"}'))
        status, payload = api.call("GET", "/repos/o/r/commits/main")
        self.assertEqual((status, payload), (200, {"sha": "abc"}))

    def test_empty_and_unparseable_bodies_do_not_raise(self):
        for raw in (b"", b"<html>not json</html>"):
            api = self._client(lambda _req, raw=raw: _Response(204, raw))
            status, payload = api.call("DELETE", "/repos/o/r/git/refs/heads/x")
            self.assertEqual((status, payload), (204, {}))

    def test_error_status_is_returned_not_raised(self):
        def responder(request):
            raise urllib.error.HTTPError(
                request.full_url, 405, "Method Not Allowed", {}, io.BytesIO(b'{"message": "refused"}')
            )

        api = self._client(responder)
        status, payload = api.call("PUT", "/repos/o/r/pulls/1/merge", {})
        self.assertEqual((status, payload), (405, {"message": "refused"}))

    def test_transport_failure_is_its_own_error(self):
        def responder(_request):
            raise urllib.error.URLError("name resolution failed")

        api = self._client(responder)
        with self.assertRaises(sc.TransportError):
            api.call("GET", "/repos/o/r/commits/main")

    def test_token_travels_in_the_auth_header_only(self):
        api = self._client(lambda _req: _Response(200, b"{}"))
        api.call("GET", "/repos/o/r/commits/main")
        request = self.requests[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer tok")
        self.assertNotIn("tok", request.full_url)
        self.assertEqual(request.get_method(), "GET")

    def test_body_is_json_encoded_for_writes(self):
        import json

        api = self._client(lambda _req: _Response(201, b"{}"))
        api.call("POST", "/repos/o/r/git/refs", {"ref": "refs/heads/x", "sha": "1" * 40})
        request = self.requests[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")), {"ref": "refs/heads/x", "sha": "1" * 40}
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
