# DeepSeek V4.1 Flash Free, effort `max` — offline preparation

- Date: 2026-10-21
- Repository: `https://github.com/StepenkoAnatoli/Holdshort.git`
- Base commit: `0a6d341beab0e7d4b0448fe30a7b0949e16680c2`
- Mode: offline only. No live model or provider inference call was made for this target, for any
  candidate, or for this assistant. Only official documentation and the local repository were read.
- Status: **PREPARED, NOT QUALIFIED, NOT ROUTABLE.** The protocol is not frozen and no calibration run
  exists. No model is qualified by anything in this note.

## TARGET PROFILE (completed)

| Field | Value | Source |
|---|---|---|
| Display name | DeepSeek V4.1 Flash Free | OpenCode Console model table |
| Canonical model ID / artifact | `deepseek-v4.1-flash-free` in the API body; host selector `opencode/deepseek-v4.1-flash-free`; local profile key `deepseek-v4.1-flash-free-max` | OpenCode docs; models.dev TOML; local profile |
| Provider / endpoint family | OpenCode Console, OpenAI-compatible Chat Completions, `https://opencode.ai/inference/openai/v1/chat/completions` (base `https://opencode.ai/inference/openai/v1`, `@ai-sdk/openai-compatible`) | OpenCode docs; models.dev TOML |
| Effort / reasoning setting | `max`; request `reasoning_effort: "max"` and `thinking: {"type": "enabled"}` | models.dev reasoning options `low`, `high`, `max`; DeepSeek thinking-mode docs |
| Official documentation | `https://opencode.ai/v2/docs/console/models`; pinned models.dev TOML at commit `32bb721dd51673f50ff21812a65902804975fb5c`; `https://api-docs.deepseek.com/guides/thinking_mode`; `https://api-docs.deepseek.com/api/create-chat-completion`; `https://api-docs.deepseek.com/guides/json_mode` | retrieved 2026-10-21 |
| Context / max output | 200,000 context; 32,000 max output | pinned models.dev TOML |
| Input reservation ceiling | 168,000 = 200,000 − 32,000. This is local arithmetic, not a measured tokenization or a provider-enforced input limit | derived, labeled in the profile |
| Vendor list input price | `$0.00` per 1M tokens | pinned models.dev TOML and OpenCode Console (Free) |
| Vendor list cached-input price | `$0.00` per 1M tokens | pinned models.dev TOML and OpenCode Console (Free) |
| Vendor list output price | `$0.00` per 1M tokens | pinned models.dev TOML and OpenCode Console (Free) |
| Conservative price bound | `$0.30` input, `$0.006` cached input, `$1.20` output per 1M tokens, from the metered sibling `deepseek-v4.1-flash`; **not** the target's price | paid sibling TOML; used only so a zero list price cannot hide cost or bypass a gate |
| Capability notes | Reasoning; tools; structured output only `json_object` under DeepSeek's documented conditions; `json_schema` not modeled; temperature has no effect in thinking mode; interleaved reasoning field `reasoning_content` | models.dev TOML; DeepSeek API/JSON/thinking docs |
| Known ambiguities | The OpenCode gateway's exact acceptance of DeepSeek's top-level `thinking` object and `reasoning_effort` is not documented; the free label's duration and future price are not documented; DeepSeek's direct API can default to 128K output under `max` while the free catalog caps output at 32K; JSON Output may return empty content; no OpenCode calibration harness exists | recorded in the profile and protocol |

### Exact source facts

- OpenCode Console lists `DeepSeek V4.1 Flash Free | deepseek-v4.1-flash-free |
  https://opencode.ai/inference/openai/v1/chat/completions | @ai-sdk/openai-compatible` and marks it
  Free.
- The pinned models.dev TOML says `context = 200_000`, `output = 32_000`, `cost input = 0`,
  `output = 0`, `cache_read = 0`, `reasoning_options` type effort with `["low", "high", "max"]`,
  `interleaved.field = "reasoning_content"`, and `structured_output = true`.
- The paid sibling `deepseek-v4.1-flash` TOML says `input = 0.3`, `output = 1.2`,
  `cache_read = 0.006` per 1M tokens with the same base model and provider API. Those are used only
  as the conservative bound.
- DeepSeek's thinking-mode guide says thinking is enabled by default with default effort `high`;
  the OpenAI-format controls are `{"thinking": {"type": "enabled/disabled"}}` and
  `{"reasoning_effort": "low/high/max"}`; requested `max` maps to actual `max`; temperature has no
  effect in thinking mode; and previous `reasoning_content` must be passed back when tools are in
  use.
- DeepSeek's API reference says `reasoning_effort` accepts `none`, `low`, `high`, `max` with default
  `high`; `max_tokens` defaults to 128K under `max`; `required` and named `tool_choice` are rejected
  in thinking mode; `finish_reason` includes `length`, `content_filter`, `insufficient_system_resource`
  and `aborted`; and usage carries prompt/completion/total, cached tokens and reasoning tokens.
- DeepSeek's JSON Output guide requires `response_format: {"type": "json_object"}`, the word `json`
  in a system or user prompt, an example, and a reasonable `max_tokens`; it warns that the API may
  return empty content.

No number above is a measured target observation. The prices are vendor list prices; the limits are
vendor catalog limits; the mock tests below use synthetic token counts only.

## Tested locally (verified)

These are local regression and mock checks only. Passing them does not qualify the target, the
endpoint, the gateway's wire behavior, or any model.

| Check | Result |
|---|---|
| `python tools/test_offline_deepseek_adapter.py` | 39 tests, OK. Scripted `MockTransport` only; every usage number is a synthetic fixture. (41 after the 2026-10-26 review fixes, which pin the cost bound's value.) |
| `python tools/offline_deepseek_adapter.py --check self-check` | `offline self-check: 8/8 passed; no network; no live model qualification` |
| `python tools/offline_deepseek_adapter.py --check profile` | Prints identity, effort `max`, 200,000/32,000, 168,000 reservation, `"qualified": false`, price revision and hash; exit 0. |
| `python tools/dispatch_adapter.py --check key` | Exit 2: no `ANTHROPIC_API_KEY` found; existing live dispatch refused. This is the old Anthropic-only adapter, not an OpenCode approval. |
| `python tools/offline_deepseek_adapter.py --check live` | Exit 2: `REFUSED` — offline adapter only; no target credential, no OpenCode endpoint approval, no target spend authorization, no qualified judging profile. |
| `python tools/check_secrets.py` | `clean (0 hits)` |
| Shared pack build via `make-repo.sh repo` | Built `review0 46c1cb9c…`, `base0 b41a7f9c…`, `accepted0 da71a8e3…`; `make-repo: the ids equal manifest.json's`. |
| Four history-less checkouts outside the repository | Each has exactly one commit and the expected base tree: pin/fix at `b41a7f9c…`, review/adjudication at `46c1cb9c…`; branches `dsv41free/{pin,fix,review,adjudication}-…`. |
| Pack tests in the pin checkout | `python3 tests/run.py tests/test_bounded.py` → 12 tests, OK. |
| Pack tests at the accepted tree | `python3 tests/run.py tests/test_bounded.py` → 12 tests, OK. |
| Actual filled protocol through the launch gate | Refused before the first agent: `calibration launch refused: the protocol is not frozen (frozen_at is empty or a placeholder): Item 3.1`; `calls: 0`. |
| Placeholder-qualification copy through the launch gate | Refused before the first agent: `calibration launch refused: judging_profile carries neither its qualification nor the bootstrap limitation line (...): Item 3.3`; `calls: 0`. |
| `python -m unittest test_calibration_kit.RunTemplate -v` | 11 tests, OK. |
| New adapter test registered in `tools/run_regression.py` | Added one line after `test_billing_qualification`; the kit's gate-order test still passes. |

The two launch-refusal checks were run sequentially; they both write the same prep-root
`filled-run.mjs`, so running them in parallel would race on that file. Each reported `calls: 0`.

The mock covers: request mapping pinned to the profile (model, max_tokens, `reasoning_effort: max`,
thinking enabled, no key), tools and `tool_choice: auto`, required/named tool choice refusal, tool
history requiring `reasoning_content`, JSON Output conditions and `json_schema` refusal, empty/truncated
JSON refusal with preserved usage, missing usage refusal, inconsistent usage refusal, over-ceiling usage
refusal, partial `finish_reason` failure with preserved usage and cost bound, the exact value of the cost bound (including a cached rate above the input rate), transport exception with no
retry, no scripted response refusal, non-mock transport refusal, response model identity, wrong choice
shape, invalid tool-call arguments, price/hash tamper, CRLF-insensitive price hashing, qualified-profile refusal, spend-authorization
refusal, zero conservative bound refusal, and no network client import.

## Evidence-folder check (expected pre-run failures)

`python tools/check_calibration_evidence.py docs/evidence/2026-10-21/deepseek-v4.1-flash-free-max`
exits 1. This is the correct result for a folder with no run:

```text
LIMIT ... judging-profile-named: bootstrap: judging profile not independently qualified, host-declared by the host owner; no reviewer has been selected
FAIL ... scores-derivable: scores.json is missing
FAIL ... scores-derivable: observations.json is missing
FAIL ... prongs-declared: adjudication.json is missing
FAIL ... protocol-frozen: status 'prepared; not frozen (no freeze commit, no run)' is not one of the template's two values
FAIL ... protocol-frozen: run_id is not recorded
FAIL ... protocol-frozen: frozen_at is not recorded
check_calibration_evidence: 1 folder(s), 6 failure(s), 1 limitation(s)
```

The folder is deliberately named `deepseek-v4.1-flash-free-max`, not `*-calibration-*`, so the default
qualification-table discovery cannot mistake it for a run. Its protocol is in
`docs/evidence/2026-10-21/deepseek-v4.1-flash-free-max/protocol.json`; it is prepared but **not
frozen**.

## Default gates: clean checkout and the author's checkout

On a clean checkout of this branch both default gates pass:
`python tools/check_calibration_evidence.py` reports 3 folder(s), 0 failure(s), 14 limitation(s) and
exits 0, and `python tools/qualification_table.py --check` reports that
`docs/evidence/qualification-table.md` is the generated table.

The results below were observed on the author's checkout, not on the repository. That checkout also
held an untracked folder, `docs/evidence/2026-10-21/nemotron3-free-calibration-1`, which is not in the
repository. It contained a protocol and `BLOCKED.md` but no `scores.json`, `observations.json` or
`adjudication.json`, and had `run_id: null`. It is not part of this DeepSeek work and was not modified.

```text
python tools/check_calibration_evidence.py
FAIL docs/evidence/2026-10-21/nemotron3-free-calibration-1 scores-derivable: scores.json is missing
FAIL docs/evidence/2026-10-21/nemotron3-free-calibration-1 scores-derivable: observations.json is missing
FAIL docs/evidence/2026-10-21/nemotron3-free-calibration-1 prongs-declared: adjudication.json is missing
FAIL docs/evidence/2026-10-21/nemotron3-free-calibration-1 protocol-frozen: run_id is not recorded
check_calibration_evidence: 4 folder(s), 4 failure(s), 15 limitation(s)
```

Consequences on the author's checkout only:

- `python tools/qualification_table.py --check` refused for the same four failures and wrote nothing.
- `python tools/check_calibration_evidence.py` with only the three original folders → 3 folder(s),
  0 failure(s), 14 limitation(s), exit 0. The original evidence check still passes for its original
  folders; only default discovery was broken, by the extra untracked `nemotron3-free-calibration-1`
  folder.
- `python tools/qualification_table.py --check docs/evidence/2026-10-17/claude-code-calibration
  docs/evidence/2026-10-17/claude-code-calibration-2
  docs/evidence/2026-10-18/claude-code-calibration-3` → `docs/evidence/qualification-table.md is the
  generated table`, exit 0. The three previously valid folders and the committed table are unaffected.
- `python tools/test_qualification_table.py` → 20 tests, 3 failures, 17 OK. The three failures all
  invoked the default discovery and hit the same untracked `nemotron3-free-calibration-1` folder.
- `python tools/test_check_calibration_evidence.py` was **not completed** on this host (killed after
  300 s). Two failures were observed before the timeout: default discovery expects exactly the three
  historical folders and now sees the fourth; and the committed-evidence fixtures differ from a
  regenerated tree by CRLF vs LF line endings. Neither was counted as a pass.
- `python tools/test_calibration_kit.py` (full file, default PATH) → 60 tests, 14 errors, 2 skipped.
  Every error is `FileNotFoundError: [WinError 2]` for `bash` because Git Bash is not on this Python
  process's PATH. This is a host environment limitation, not a failure of the new adapter.
- `python tools/test_calibration_kit.py` with Git Bash and the `python3` shim on PATH → it passed the
  Bash-dependent tests, but `SharedPack.test_grade_pin_a_wrong_pin_fails` failed in-suite and the suite
  timed out at 600 s during `test_grade_pin_the_accepted_pin_passes`. The failed test passes alone
  (1 test, 77.8 s). This host's full suite is slow/order-sensitive; it was **not** counted as a clean
  pass. The 11-test `RunTemplate` class passes separately.

## What the protocol still lacks (rules 1–3)

1. **Rule 1, preregistration / freeze.** The protocol is filled but not frozen: `status` is
   `prepared; not frozen (no freeze commit, no run)`, `frozen_at` is `null`, `run_id` is `null`, and no
   freeze commit was made. The preparation commit is not a freeze. The filled `run.js` does not exist;
   `sources_missing` records why. The launch gate refuses it, as shown above.
2. **Rule 2, no operator chat.** `relayed_operator_text.text` is `null` and the statement is recorded.
   No harness was launched, so there is no run in which the statement was exercised. This is a
   declaration, not run evidence.
3. **Rule 3, judging-profile qualification.** No independently qualified judging profile exists. The
   protocol names no judge (`model` and `effort` are `not selected`) and carries only the bootstrap
   limitation line. That is a caveat, not qualification; any future review results would be caveated
   and excluded from the table's pass count.

Additional blockers, outside rules 1–3:

- No OpenCode calibration harness exists in this repository; `tools/calibration/run.template.js` is
  written for the Claude Code workflow harness.
- No target credential is wired; the existing live adapter reads only `ANTHROPIC_API_KEY`.
- The OpenCode endpoint is not in the live billing qualification record, and
  `tools/live_billing_qualification.json` remains deliberately unqualified and Anthropic-bound. It was
  not edited.
- No target-specific spend ceiling was supplied. The existing pilot caps cover a different,
  Anthropic-only scope.
- The OpenCode gateway's exact `reasoning_effort: "max"` / `thinking` acceptance is documented by
  DeepSeek for its own API, not by OpenCode for the free gateway. No live probe was made, so the wire
  behavior is unverified.
- No live model/token/cost/latency/usage observation exists for the target.

## What is not claimed

- No model is qualified, eligible, approved, routable, or authorized for spend.
- The target's `$0.00` is a vendor list price, not a measured cost and not a promise of free capacity.
- The 168,000 reservation ceiling is arithmetic, not a token count from a provider tokenizer.
- The 200,000/32,000 values are vendor catalog limits, not locally measured limits.
- The mock's 12/7 token usage and its cost arithmetic are synthetic test fixtures, not observations.
- The passing pack tests and launch-refusal tests are local regressions, not calibration evidence.
- No live inference request was made; reading official documentation is not an inference call.

## Files added or changed

Repository:

- `tools/offline_deepseek_adapter.py` — offline profile loader, fail-closed mock transport contract,
  request/response checks, price bound arithmetic, `--check profile|live|self-check`.
- `tools/test_offline_deepseek_adapter.py` — 41 hermetic tests, no network (39 at preparation; the
  2026-10-26 review fixes added two that pin the cost bound's value).
- `tools/profiles/deepseek-v4.1-flash-free-max.json` — the target profile and documented ambiguities.
- `tools/prices-deepseek-v4.1-flash-free-max.json` — target list price `$0.00` plus the metered-sibling
  conservative bound and an explicit `spend_authorization.authorized: false`.
- `tools/run_regression.py` — one new check line for the adapter tests.
- `docs/evidence/2026-10-21/deepseek-v4.1-flash-free-max/protocol.json` — filled, unfrozen protocol.
- `docs/evidence/2026-10-21/deepseek-v4.1-flash-free-max/README.md` — why this is not a calibration
  record.
- `docs/evidence/2026-10-21/deepseek-v4.1-flash-free-max-prep.md` — this note.
- `docs/evidence/2026-10-21/profile-unresolved-prep-blocked.md` — marked superseded; retained for
  history.

Outside the repository (not committed), under a preparation directory written here as `<prep-root>`:

- `<prep-root>\pack\` — the built shared pack and its `repo`.
- `<prep-root>\checkouts\` — the four history-less checkouts.
- `<prep-root>\bin\python3.exe` — host shim for the pack's
  `python3` command, because this Windows host's `python3` alias is not executable from Git Bash.
- `<prep-root>\filled-run.mjs` — the last test copy used to
  demonstrate launch refusal. It is **not** evidence and is not a launchable run.

Pre-existing untracked work on the author's checkout that was **not** modified and is not in the
repository: `checkouts/`, `pack-repo/`, `tools/nemotron3_adapter.py`,
`docs/evidence/2026-10-21/nemotron3-*`. In particular, the untracked `nemotron3-free-calibration-1`
folder is why the default evidence check and qualification table failed on that checkout; on a clean
checkout they pass.

## What would unblock a future run

1. A host-reviewed OpenCode calibration harness, or a documented decision that the Claude Code template
   is being adapted; the template cannot be claimed as an OpenCode run as-is.
2. Host authorization of the target credential, the OpenCode endpoint, a target-specific spend ceiling,
   and an independent review-qualified judging profile (or an explicit acceptance of the bootstrap
   caveat).
3. A completed `run.js` whose hash is recorded in the protocol's `sources`, then a commit of the
   evidence folder. That commit is the freeze; only then may `run_id` be recorded and a run start.
4. A live wire check of the OpenCode gateway's `reasoning_effort: "max"` and `thinking` handling, with
   the result captured as evidence. Until then the mapping remains documented-but-unverified.
5. Observations, scores, results table and clusters in the evidence folder, followed by a passing
   `check_calibration_evidence.py` and `qualification_table.py --check`.

## Bottom line

The target profile and price bound are prepared from official vendor documentation. The mock adapter
and its tests pass (41 since the 2026-10-26 review fixes), the pack and four history-less checkouts are built, and both launch-refusal
paths were exercised with `calls: 0`. The protocol is intentionally unfrozen, the target is unqualified,
and the default evidence/qualification gates pass on a clean checkout (on the author's checkout they
failed only because of an unrelated untracked Nemotron calibration folder). **No model was qualified in this work.**
