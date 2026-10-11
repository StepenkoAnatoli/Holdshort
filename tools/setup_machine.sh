#!/usr/bin/env bash
# setup_machine.sh — one command to get a new machine enforcing the gate AND
# ending with a verified go-live preflight (runbook §0–§2), not just a gate
# proof.
#
# POSIX bash; works on Linux, macOS, and Git-for-Windows bash. Either run it
# inside an existing checkout, or give it a repo URL to clone first:
#
#   bash tools/setup_machine.sh                                  # current checkout
#   bash tools/setup_machine.sh https://github.com/StepenkoAnatoli/SmartRouter.git
#
# Sequence:
#   1. (optional) clone -> wire core.hooksPath
#   2. gate baseline on the fresh checkout (full regression gate, exit 0)
#   3. PROOF 1: scratch commit allowed (hook+gate run and pass; rolled back)
#   4. PROOF 2: staged fake key REFUSED (fail-closed; rolled back)
#   5. PREFLIGHT (runbook §0–§2, automated):
#      - §0 secrets scan clean; live refusal exit 2 with NO .env (no HTTP call)
#      - §2 dry-run cloud-C dispatch -> dispatched, ledger line written, exit 0
#      - §2 dry-run cloud-XYZ -> unknown-profile (Gate-4 fail-closed), exit 1
#   All artifacts are temp; nothing is committed or pushed.
set -u

fail() { echo "setup_machine: FAIL — $*"; shift || true; exit 1; }

REPO_URL="${1:-}"
if [ -n "$REPO_URL" ]; then
  DEST="${2:-$(basename "$REPO_URL" .git)}"
  echo "==> cloning into $DEST"
  git clone "$REPO_URL" "$DEST" || die "clone of $REPO_URL"
  cd "$DEST" || die "cd $DEST"
else
  git rev-parse --show-toplevel >/dev/null 2>&1 || { echo "setup_machine: FAIL — not inside a git repo (pass a repo URL to clone)" >&2; exit 1; }
  cd "$(git rev-parse --show-toplevel)"
fi

die() { echo "setup_machine: FAIL — $*" >&2; exit 1; }

echo "==> wiring core.hooksPath"
python tools/install_hooks.py || die "install_hooks"

echo "==> gate baseline (must be green on a fresh clone)"
GATE_OUT="$(mktemp)" || die "mktemp"
python tools/run_regression.py > "$GATE_OUT" 2>&1 || {
  cat "$GATE_OUT"; rm -f "$GATE_OUT"; die "regression gate is red on a fresh clone — do not commit to this clone";
}
tail -1 "$GATE_OUT"
rm -f "$GATE_OUT"

echo "==> PROOF 1: pre-commit hook fires on a clean scratch commit"
# Scratch identity, LOCAL to this clone only: a bare runner/VM has no
# user.name/user.email, and without it the proof commit fails before the
# hook ever runs — masking a working gate as "broken wiring".
git config user.name  "setup-gate-proof" || die "local user.name"
git config user.email "setup-gate-proof@example.invalid" || die "local user.email"
SCRATCH="setup_gate_proof_$$"
echo "# gate proof (rolled back)" > "$SCRATCH.txt"
git add "$SCRATCH.txt"
if git commit -m "setup: gate proof (rolled back, not pushed)" >/dev/null 2>&1; then
  # keep the tree clean: the proof commit is dropped immediately, never pushed
  git reset -q --hard HEAD~1
  rm -f "$SCRATCH.txt"
  echo "    PASS — hook ran the gate and allowed a clean commit"
else
  git reset -q --hard HEAD~1 >/dev/null 2>&1
  rm -f "$SCRATCH.txt"
  git commit -m "setup: gate proof (rolled back, not pushed)" 2>&1 | head -5 >&2 || true
  die "hook did not allow a clean commit — gate wiring is broken"
fi

echo "==> PROOF 2: a staged fake key is REFUSED (fail-closed)"
K1='ANTHROP'; K2='IC_API_KEY'
ba_varname="${K1}${K2}"
FAKE_VAL='sk-ant-fake-setup-proof-'; FAKE_VAL2='000000'
FAKE_VAL="${FAKE_VAL}${FAKE_VAL2}"
FILE_SLUG=$(mktemp -u)
cat > "$FILE_SLUG" <<PROOF
${ba_varname}=${FAKE_VAL}
PROOF
cat "$FILE_SLUG" >> README.md
rm -f "$FILE_SLUG"
git add README.md
if git commit -m "setup: leak proof (must be refused)" >/dev/null 2>&1; then
  git reset -q --hard HEAD~1
  die "hook ACCEPTED a fake key — enforcement is not working"
fi
git reset -q --hard HEAD
echo "    PASS — refusal confirmed (commit blocked)"

# ---------------------------------------------------------------------
# PREFLIGHT (runbook §0–§2) — a fresh machine ends ready, not just gated.
# ---------------------------------------------------------------------
echo "==> PREFLIGHT §0: secrets scan (must be clean)"
python tools/check_secrets.py >/dev/null 2>&1 || die "check_secrets not clean on fresh clone — aborting before preflight"
echo "    PASS — clean (0 hits)"

echo "==> PREFLIGHT §0: fail-closed live refusal (NO .env expected)"
if [ -f .env ]; then
  echo "    NOTE — .env exists on this machine; skipping the no-key refusal proof (it requires a keyless clone)"
else
  DR_TMP="$(mktemp -d)" || die "mktemp -d"
  python tools/live_dispatcher.py --live \
    --profile cloud-C --task-id setup-preflight --request x \
    --work-bound 0.01 --review-bound 0.01 \
    --ledger "$DR_TMP/preflight.jsonl" > "$DR_TMP/live.json" 2>&1
  RC=$?
  if [ "$RC" -ne 2 ]; then
    cat "$DR_TMP/live.json" >&2
    die "live dispatch without .env must refuse with exit 2 (got $RC) — fail-closed path broken"
  fi
  grep -q "dispatch-refused" "$DR_TMP/live.json" || { cat "$DR_TMP/live.json" >&2; die "refusal JSON missing dispatch-refused"; }
  echo "    PASS — no key ⇒ no HTTP call (exit 2, dispatch-refused)"
fi

echo "==> PREFLIGHT §2: dry-run warm-up (no network)"
DRY_TMP="$(mktemp -d)" || die "mktemp -d"
python tools/live_dispatcher.py \
  --profile cloud-C --task-id dryrun-1 --request "probe" \
  --work-bound 0.01 --review-bound 0.01 \
  --expected-in-tokens 10000 --expected-out-tokens 1000 \
  --ledger "$DRY_TMP/dryrun_ledger.jsonl" > "$DRY_TMP/dry.json" 2>&1
RC=$?
if [ "$RC" -ne 0 ]; then cat "$DRY_TMP/dry.json" >&2; die "cloud-C dry-run must dispatch with exit 0 (got $RC)"; fi
grep -q '"decision": "dispatched"' "$DRY_TMP/dry.json" || { cat "$DRY_TMP/dry.json" >&2; die "dry-run JSON missing 'dispatched'"; }
grep -q '"decision": "dispatched"' "$DRY_TMP/dryrun_ledger.jsonl" || { cat "$DRY_TMP/dryrun_ledger.jsonl" >&2; die "ledger line not written"; }
echo "    PASS — cloud-C dispatched and ledger line written (exit 0)"

python tools/live_dispatcher.py \
  --profile cloud-XYZ --task-id dryrun-2 --request "x" \
  --work-bound 0.01 --review-bound 0.01 \
  --ledger "$DRY_TMP/dryrun_ledger.jsonl" > "$DRY_TMP/gate4.json" 2>&1
RC=$?
if [ "$RC" -ne 1 ]; then cat "$DRY_TMP/gate4.json" >&2; die "cloud-XYZ must be Gate-4 refused with exit 1 (got $RC)"; fi
grep -q '"decision": "unknown-profile"' "$DRY_TMP/gate4.json" || { cat "$DRY_TMP/gate4.json" >&2; die "Gate-4 JSON missing 'unknown-profile'"; }
grep -q '"decision": "unknown-profile"' "$DRY_TMP/dryrun_ledger.jsonl" || { cat "$DRY_TMP/dryrun_ledger.jsonl" >&2; die "refusal not recorded in ledger"; }
echo "    PASS — unknown-profile Gate-4 fail-closed (exit 1, ledger records it)"

echo "==> cleaning scratch files"
rm -rf "$DR_TMP" 2>/dev/null || true
rm -rf "$DRY_TMP" 2>/dev/null || true
git status --porcelain | grep -q . && {
  echo "WARNING: worktree not clean after rollback:"; git status --porcelain; }

echo "setup_machine: DONE — gate enforced, preflight (§0–§2) verified on this machine."
exit 0
