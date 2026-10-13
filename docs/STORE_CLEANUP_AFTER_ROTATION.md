# Store cleanup after credential rotation — scrubbing baselined digests

The app-DB baseline (`tools/app_db_secrets_baseline.json`) silences digests by
*subject* (sha256 of the matched string), never by value. After a rotation the
underlying value is dead, but the digest row must not be deleted blindly: if
the store still holds the text, pruning re-arms the alert and the next commit
fails. This procedure decides per digest, with the check itself as the oracle.

## 0. Preconditions (in order)

1. The rotation is finished per `docs/CREDENTIAL_ROTATION_RUNBOOK.md` §3 —
   replacement proven in use (§5.2), old value revoked **at the provider**
   (invariant 2: revocation is the only invalidation; deleting a copy is cleanup).
2. `python tools/run_regression.py` is green before you start, so a red end
   state is attributable to this procedure.

## 1. Per-digest disposition loop

For each digest row, back the baseline up first (`cp` to a timestamped copy
outside the repo), then classify:

| Case | Meaning | Action |
|---|---|---|
| A. Revoked and gone | Value revoked; app store no longer holds the text (expired by retention, thread deleted via the app's own data controls) | Prune the row (§2), re-run the check: exit 0 confirms |
| B. Revoked but retained | Value revoked; the text is still in a live transcript the app owns | **Keep the row**, rewrite its note to `revoked <date>; retained text, inert` — the baseline now documents a dead secret, not a live one |
| C. Fixture fragment | Note says TEST DATA / RAW-BYTE FRAGMENTS of our own synthetic fixtures | Prune only if the fixture text changed AND the re-run stays green; otherwise keep — our own rendered test output still trips the scanner by design |
| D. Live or unknown | Underlying value not proven revoked, or provenance unclear | Do not touch. Rotate first (runbook §3), then re-enter this loop |

Never prune to turn a red check green. A prune is valid only with a green
re-run as proof (§2).

## 2. The prune-and-prove step (one digest at a time)

```bash
cp tools/app_db_secrets_baseline.json /tmp/app_db_baseline.bak-<date>
# remove exactly one digest row with python -c (keyed edit, no retyping):
python -c "import json; p='tools/app_db_secrets_baseline.json'; d=json.load(open(p)); d['digests'].pop('<full-digest>', None); json.dump(d, open(p,'w'), indent=2)"
python tools/check_app_db_secrets.py   # exit 0 = case A confirmed, move on
```

- Exit 0: the store no longer holds that string. Done with this digest.
- Exit 1 naming the same digest: the text is still in the store — restore the
  row from backup (or re-add with a case-B note) and stop pruning it. Do NOT
  edit the app database to force the green: the app owns it and is usually
  running (runbook §4). The supported levers are the app's own data controls
  plus retention; rotation already made every retained copy worthless.

## 3. Close-out

- `last_update_note` must describe the latest disposition pass (what was
  pruned, what was kept as case B/C, and the revocation dates).
- Full gate green: `python tools/run_regression.py` → all checks PASS.
- Commit the baseline with an audit-style message naming each pruned digest's
  prefix, its case (A/B/C), and the revocation evidence — same discipline as
  `tools/credential_hygiene_baseline.json` §5.3.

## 4. Blind spots (stated, not solved here)

The check scans the app stores on *this* machine only. Other checkouts,
backups, exports, shell history and any other machine are the runbook §4
manual cover and are verified by class-counts there, never by this baseline.
A revoked value in an old archive is already inert; a live value anywhere
else restarts this whole procedure at §3 of the runbook.
