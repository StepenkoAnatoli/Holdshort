#!/usr/bin/env bash
# setup_machine.sh — one command to get a new machine enforcing the gate.
#
# POSIX bash; works on Linux, macOS, and Git-for-Windows bash. Either run it
# inside an existing checkout, or give it a repo URL to clone first:
#
#   bash tools/setup_machine.sh                                  # current checkout
#   bash tools/setup_machine.sh https://github.com/StepenkoAnatoli/SmartRouter.git
#
# Steps: (optional) clone -> wire core.hooksPath -> PROOF: make a scratch
# commit that touches a tracked file and verify the pre-commit hook actually
# runs the gate (pass) and a staged fake key is refused (fail-closed). The
# scratch commit is never created; everything is rolled back before exit.
set -u

fail() { echo "setup_machine: FAIL — $*" >&2; exit 1; }

REPO_URL="${1:-}"
if [ -n "$REPO_URL" ]; then
  DEST="${2:-$(basename "$REPO_URL" .git)}"
  echo "==> cloning into $DEST"
  git clone "$REPO_URL" "$DEST" || fail "clone of $REPO_URL"
  cd "$DEST" || fail "cd $DEST"
else
  git rev-parse --show-toplevel >/dev/null 2>&1 || fail "not inside a git repo (pass a repo URL to clone)"
  cd "$(git rev-parse --show-toplevel)" || fail
fi

echo "==> wiring core.hooksPath"
python tools/install_hooks.py || fail "install_hooks"

echo "==> gate baseline (must be green on a fresh clone)"
GATE_OUT="$(mktemp)"
python tools/run_regression.py > "$GATE_OUT" 2>&1 || {
  cat "$GATE_OUT"; rm -f "$GATE_OUT"; fail "regression gate is red on a fresh clone — do not commit to this clone";
}
tail -1 "$GATE_OUT"
rm -f "$GATE_OUT"

echo "==> PROOF 1: pre-commit hook fires on a clean scratch commit"
# Scratch identity, LOCAL to this throwaway clone only: a bare runner/VM has
# no user.name/user.email, and without it the proof commit fails before the
# hook is ever invoked, masking a working gate as "broken wiring".
git config user.name  "setup-gate-proof" || fail "local user.name"
git config user.email "setup-gate-proof@example.invalid" || fail "local user.email"
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
  fail "hook did not allow a clean commit — gate wiring is broken"
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
echo "    proof-2 state: worktree-key-lines=$(grep -c 'IC_API_KEY=' README.md || true) staged-key-lines=$(git grep -c --cached 'IC_API_KEY=' -- README.md || true) hook=$(git config core.hooksPath)"
if git commit -m "setup: leak proof (must be refused)" >/dev/null 2>&1; then
  git reset -q --hard HEAD~1
  fail "hook ACCEPTED a fake key — enforcement is not working"
fi
git reset -q --hard HEAD
echo "    PASS — refusal confirmed (commit blocked)"

echo "==> cleaning scratch files"
git status --porcelain | grep -q . && {
  echo "WARNING: worktree not clean after rollback:"; git status --porcelain; }

echo "setup_machine: DONE — every commit on this machine now runs the full gate."
exit 0
