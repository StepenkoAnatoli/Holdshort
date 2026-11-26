#!/usr/bin/env bash
# Lineage: the host-pack counterpart of ../../shared/make-repo.sh. The shared pack builds its repository from trees it
# ships; this host pack ships no MoonAliza code, so it builds its repository from a MoonAliza clone the host provides,
# copying two trees from it as git objects (as historyless-checkout.sh copies a base tree) under fixed commit metadata.
#
# usage: make-repo.sh MOONALIZA_CLONE TARGET
#
#   MOONALIZA_CLONE  a clone of MoonAliza holding the commits 16f637f and 01a8604 (branch build/github-sign-in), read
#                    only: nothing is written there (its objects are read with git cat-file and pack-objects)
#   TARGET           where the pack repository is built, a bare repository; must not exist. A host builds it outside
#                    the kit's tree and outside every checkout root, beside a copy of manifest.json, so the manifest's
#                    `repository` ("repo") resolves when TARGET is <pack dir>/repo; built anywhere else, the host writes
#                    TARGET into its copy of the manifest.
#
# The repository holds two root commits, each on its own branch and tagged:
#   base0      MoonAliza 16f637f's tree without its docs/orchestration/ directory: the fix case's base (X2-1 present)
#   accepted0  MoonAliza 01a8604's tree without its docs/orchestration/ directory, plus this pack's accepted journey test
#              at tests/zz_accepted_x2_1.test.ts: the accepted fix of X2-1 (fix-x2-1), and the test grade.sh places in a
#              candidate's checkout
# docs/orchestration/ is left out of both trees (lead decision D-IC3-1, integration check 3 IC3-1). It holds MoonAliza's
# orchestration records, not subject code, and in 16f637f those records name X2-1, state its cause and give the accepted
# fix line by line, while a candidate's checkout is base0's tree and the candidate may read all of it. The whole directory
# goes, not a list of its files: any record there may describe the fix. Only the objects the two filtered trees reach are
# copied into the pack repository, so the records are not in it at all, and base0..accepted0 (the journey test aside) is
# checked to be 16f637f..01a8604 outside docs/orchestration/.
# Neither commit has a parent, so neither carries MoonAliza's history. The ids depend on nothing on the host: every tree
# but the two root trees and the two docs trees is MoonAliza's own tree object, those four are written by git mktree from
# MoonAliza's entries (content-addressed), the test is stored as its bytes (no filter, no line-ending conversion) with
# mode 100644, and the identity, dates, messages and encoding of each commit are fixed here.
#
# Prints "<tag> <commit id>" for each commit. Exit 0 when the ids equal manifest.json's (or there is no manifest beside
# this script); 1 when git fails, the clone lacks an object, a tree has no docs/orchestration/ directory, the diff check
# fails or the ids differ from the manifest's, and TARGET is then removed, so a rerun is not refused; 2 on a bad argument,
# an existing TARGET or a clone without the two commits.
set -euo pipefail

refuse() {
  echo "make-repo: refused: $*" >&2
  exit 2
}
[ $# -eq 2 ] || refuse "usage: make-repo.sh MOONALIZA_CLONE TARGET"
CLONE=$1
TARGET=$2
[ -e "$TARGET" ] || [ -L "$TARGET" ] && refuse "target exists: $TARGET"
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
TEST="$HERE/zz_accepted_x2_1.test.ts"
[ -f "$TEST" ] || refuse "no accepted journey test $TEST"
SRC=$(cd -- "$CLONE" 2>/dev/null && pwd -P) || refuse "no clone directory: $CLONE"

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
BASE_SRC=16f637f1a1eaf9879933a0020d676971a26b3c4b       # base: before fix-x2-1
ACCEPTED_SRC=01a8604fa9c60fae9ae906e1e949a3f2cadb07de   # accepted: fix-x2-1's last commit (F1-F4)
BASE_TREE=$(git -C "$SRC" rev-parse --verify --quiet "$BASE_SRC^{tree}") || refuse "$CLONE has no commit $BASE_SRC (MoonAliza build/github-sign-in)"
ACCEPTED_TREE=$(git -C "$SRC" rev-parse --verify --quiet "$ACCEPTED_SRC^{tree}") || refuse "$CLONE has no commit $ACCEPTED_SRC (MoonAliza build/github-sign-in)"

export GIT_AUTHOR_NAME="Calibration Kit" GIT_AUTHOR_EMAIL="host-pack@calibration.invalid"
export GIT_COMMITTER_NAME="Calibration Kit" GIT_COMMITTER_EMAIL="host-pack@calibration.invalid"

mkdir -p -- "$(dirname -- "$TARGET")"
# TARGET did not exist (checked above): from here on, a failure removes what this run built
trap 'rm -rf -- "$TARGET"; echo "make-repo: failed; removed $TARGET" >&2' EXIT
git init -q --bare --object-format=sha1 -- "$TARGET"
REPO=$(cd -- "$TARGET" && pwd -P)
INDEX="$REPO/make-repo.index"

EXCLUDED=docs/orchestration   # left out of both trees (D-IC3-1)

fail() {
  echo "make-repo: $*" >&2
  exit 1
}

# filter TREE: prints the id of TREE without EXCLUDED, written into the pack repository. First every object that tree
# reaches is copied from the clone: each entry of TREE's recursive listing except the docs tree itself and EXCLUDED with
# everything under it (an object that also sits at another path is copied for that path; no commit is copied). Then the
# docs tree without its orchestration entry, and the root tree with that docs tree, are written with git mktree from the
# clone's own entries. The clone is only read (cat-file, ls-tree, pack-objects --stdout). It runs in a command
# substitution, where bash does not inherit errexit, so each step checks its own status (pipefail holds).
filter() {
  local tree=$1 rec path meta rest docs
  [ "$(git -C "$SRC" cat-file -t "$tree:$EXCLUDED" 2>/dev/null)" = tree ] || fail "tree $tree has no $EXCLUDED/ directory"
  git -C "$SRC" ls-tree -r -t -z "$tree" | while IFS= read -r -d '' rec; do
    path=${rec#*$'\t'}
    case $path in docs | "$EXCLUDED" | "$EXCLUDED"/*) continue ;; esac
    meta=${rec%%$'\t'*}   # <mode> <type> <id>
    rest=${meta#* }
    [ "${rest%% *}" = commit ] || echo "${meta##* }"
  done | git -C "$SRC" pack-objects --stdout -q | git -C "$REPO" unpack-objects -q || fail "could not copy the objects of $tree"
  docs=$(git -C "$SRC" ls-tree -z "$tree:docs" | while IFS= read -r -d '' rec; do
    [ "${rec#*$'\t'}" = "${EXCLUDED#docs/}" ] || printf '%s\0' "$rec"
  done | git -C "$REPO" mktree -z) || fail "could not write the docs tree of $tree"
  git -C "$SRC" ls-tree -z "$tree" | while IFS= read -r -d '' rec; do
    if [ "${rec#*$'\t'}" = docs ]; then printf '040000 tree %s\tdocs\0' "$docs"; else printf '%s\0' "$rec"; fi
  done | git -C "$REPO" mktree -z
}
BASE_FILTERED=$(filter "$BASE_TREE")
ACCEPTED_FILTERED=$(filter "$ACCEPTED_TREE")

# the accepted tree with the journey test added as its bytes, mode 100644
rm -f -- "$INDEX"
GIT_INDEX_FILE=$INDEX git -C "$REPO" read-tree "$ACCEPTED_FILTERED"
BLOB=$(git -C "$REPO" hash-object -w --no-filters -- "$TEST")
GIT_INDEX_FILE=$INDEX git -C "$REPO" update-index --add --cacheinfo "100644,$BLOB,tests/zz_accepted_x2_1.test.ts"
WITH_TEST=$(GIT_INDEX_FILE=$INDEX git -C "$REPO" write-tree)
rm -f -- "$INDEX"

# commit TREE DATE MESSAGE: a root commit with this script's identity and date, unsigned, its message in UTF-8
commit() {
  GIT_AUTHOR_DATE=$2 GIT_COMMITTER_DATE=$2 git -C "$REPO" -c i18n.commitEncoding=UTF-8 \
    commit-tree --no-gpg-sign -m "$3" "$1"
}
BASE=$(commit "$BASE_FILTERED" "1767225600 +0000" \
  "base: the tree of MoonAliza 16f637f without docs/orchestration/, before fix-x2-1")
ACCEPTED=$(commit "$WITH_TEST" "1767312000 +0000" \
  "accepted: the tree of MoonAliza 01a8604 (fix-x2-1) without docs/orchestration/, with the pack's accepted journey test, tests/zz_accepted_x2_1.test.ts")

# the change from base0 to accepted0, the journey test aside, is MoonAliza's 16f637f..01a8604 outside docs/orchestration/
# (raw recursive diffs, NUL-separated, compared by their hash; the diff is not empty)
diff_hash() {
  git -C "$1" diff-tree -r -z --no-renames "$2" "$3" -- . ":(exclude)$4" | git -C "$REPO" hash-object --stdin
}
WANT=$(diff_hash "$SRC" "$BASE_TREE" "$ACCEPTED_TREE" "$EXCLUDED")
HAVE=$(diff_hash "$REPO" "$BASE" "$ACCEPTED" tests/zz_accepted_x2_1.test.ts)
[ "$WANT" = "$HAVE" ] || fail "base0..accepted0 is not 16f637f..01a8604 outside $EXCLUDED/"
[ "$WANT" != "$(git -C "$REPO" hash-object --stdin </dev/null)" ] || fail "16f637f..01a8604 outside $EXCLUDED/ is empty"
echo "make-repo: base0..accepted0 is 16f637f..01a8604 outside $EXCLUDED/" >&2

# plain refs: `git tag` turns into a signed annotated tag on a host with tag.gpgSign set
git -C "$REPO" update-ref refs/heads/base "$BASE"
git -C "$REPO" update-ref refs/heads/accepted "$ACCEPTED"
git -C "$REPO" update-ref refs/tags/base0 "$BASE"
git -C "$REPO" update-ref refs/tags/accepted0 "$ACCEPTED"
git -C "$REPO" symbolic-ref HEAD refs/heads/accepted
printf 'base0 %s\naccepted0 %s\n' "$BASE" "$ACCEPTED"

[ -f "$HERE/manifest.json" ] || { trap - EXIT; exit 0; }
python3 -I - "$HERE/manifest.json" "$BASE" "$ACCEPTED" <<'PY'
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
base, accepted = sys.argv[2:4]
want = {"cases.fix.base": base, "accepted_fix": accepted}
have = {"cases.fix.base": m["cases"]["fix"]["base"], "accepted_fix": m["accepted_fix"]}
for f in m["findings"]:
    want[f"findings[{f['id']}].present_at"], have[f"findings[{f['id']}].present_at"] = [base], f["present_at"]
    want[f"findings[{f['id']}].accepted_fix"], have[f"findings[{f['id']}].accepted_fix"] = accepted, f["accepted_fix"]
bad = [f"{k}: manifest {have[k]}, built {v}" for k, v in want.items() if have[k] != v]
if bad:
    print("make-repo: the built ids differ from manifest.json (the pack's files changed since it was written):", file=sys.stderr)
    print("\n".join("  " + b for b in bad), file=sys.stderr)
    sys.exit(1)
print("make-repo: the ids equal manifest.json's", file=sys.stderr)
PY
trap - EXIT
