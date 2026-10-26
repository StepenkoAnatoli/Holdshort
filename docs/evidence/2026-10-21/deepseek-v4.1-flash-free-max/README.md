# DeepSeek V4.1 Flash Free — pre-run preparation, not a calibration record

This folder holds the filled protocol for the `deepseek-v4.1-flash-free-max` profile. It is **not** a
completed calibration evidence folder and must not be added to the qualification table.

- The protocol is prepared but **not frozen**: `status` is not `frozen`, `frozen_at` is `null`, `run_id` is
  `null`, and no freeze commit was made. The preparation commit is not a freeze.
- No calibration dispatch, agent, model, or provider was run for this profile. The offline adapter's
  `MockTransport` was exercised only by local tests; its responses are scripted synthetic fixtures, not
  observations. No scores, adjudications, grades, measured token counts, costs, or latency were
  produced.
- The folder name deliberately does not match the evidence checker's calibration-folder discovery
  (`*-calibration-*`), so it cannot be mistaken for a run. It does not affect the default
  `qualification_table.py --check`, which passes on a clean checkout. (On the author's checkout it
  failed for an unrelated untracked `nemotron3-free-calibration-1` folder that is not in the
  repository; see the prep note.)
- The shared pack's `manifest.json` hash is `0840bd6eac9baa6bf9e6b552949ddd7c5e3758a8102a28d5b5890f5a8573c565`
  under the protocol's CRLF-normalized convention.
- The target profile is in `tools/profiles/deepseek-v4.1-flash-free-max.json`; its conservative
  price bound is in `tools/prices-deepseek-v4.1-flash-free-max.json`. The target's vendor list price is
  `$0.00`; the bound uses the metered sibling's published list price only so a zero list price cannot
  bypass a gate.
- The protocol's `sources` hashes cover the kit files, the offline adapter, and the profile/price files. `sources_missing`
  records why no filled `run.js` exists: the kit's only workflow template is Claude Code-specific and this
  repository has no OpenCode calibration harness.

## What the evidence check says

Run explicitly:

```bash
python tools/check_calibration_evidence.py docs/evidence/2026-10-21/deepseek-v4.1-flash-free-max
```

It exits 1 with the expected pre-run failures: the protocol is not frozen (`status`, `run_id`,
`frozen_at`), and `scores.json`, `observations.json` and `adjudication.json` do not exist. The
`judging-profile-named` line is a limitation, not a qualification: no independent judging profile exists.
Those failures are the correct result for a folder with no run.

## What must happen before this becomes evidence

1. A host must select and authorize the target credential, the OpenCode endpoint, a target-specific
   spend ceiling, and an independent judging profile (or accept the bootstrap limitation).
2. A host must provide an OpenCode calibration harness. The current `run.template.js` is written for the
   Claude Code workflow harness and cannot be claimed as an OpenCode harness.
3. The protocol must be completed with a filled `run.js`, its hash added to `sources`, and the whole
   evidence folder committed. That commit is the freeze; only then may a run start and record `run_id`.
4. The run's observations, scores, results table and clusters must be added, and
   `check_calibration_evidence.py` must pass before the profile can be considered for policy.

Until all of that happens, the profile is **unqualified**. The mock adapter's passing tests prove local
routing behavior only; they are not qualification evidence.
