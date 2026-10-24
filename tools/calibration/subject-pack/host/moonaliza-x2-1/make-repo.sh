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
#   base0      MoonAliza 16f637f's tree, unchanged: the fix case's base (X2-1 present)
#   accepted0  MoonAliza 01a8604's tree plus this pack's accepted journey test at tests/zz_accepted_x2_1.test.ts: the
#              accepted fix of X2-1 (fix-x2-1), and the test grade.sh places in a candidate's checkout
# Neither commit has a parent, so neither carries MoonAliza's history. The ids depend on nothing on the host: the trees
# are MoonAliza's tree objects (content-addressed), the test is stored as its bytes (no filter, no line-ending
# conversion) with mode 100644, and the identity, dates, messages and encoding of each commit are fixed here.
#
# Prints "<tag> <commit id>" for each commit. Exit 0 when the ids equal manifest.json's (or there is no manifest beside
# this script); 1 when git fails, the clone lacks an object, or the ids differ from the manifest's; 2 on a bad argument,
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
git init -q --bare --object-format=sha1 -- "$TARGET"
REPO=$(cd -- "$TARGET" && pwd -P)
INDEX="$REPO/make-repo.index"

# copy TREE: TREE and every tree and blob under it, from the clone into the pack repository (no commit is copied)
copy() {
  { echo "$1"; git -C "$SRC" ls-tree -r -t "$1" | awk '$2 != "commit" { print $3 }'; } \
    | git -C "$SRC" pack-objects --stdout -q | git -C "$REPO" unpack-objects -q
}
copy "$BASE_TREE"
copy "$ACCEPTED_TREE"

# the accepted tree with the journey test added as its bytes, mode 100644
rm -f -- "$INDEX"
GIT_INDEX_FILE=$INDEX git -C "$REPO" read-tree "$ACCEPTED_TREE"
BLOB=$(git -C "$REPO" hash-object -w --no-filters -- "$TEST")
GIT_INDEX_FILE=$INDEX git -C "$REPO" update-index --add --cacheinfo "100644,$BLOB,tests/zz_accepted_x2_1.test.ts"
WITH_TEST=$(GIT_INDEX_FILE=$INDEX git -C "$REPO" write-tree)
rm -f -- "$INDEX"

# commit TREE DATE MESSAGE: a root commit with this script's identity and date, unsigned, its message in UTF-8
commit() {
  GIT_AUTHOR_DATE=$2 GIT_COMMITTER_DATE=$2 git -C "$REPO" -c i18n.commitEncoding=UTF-8 \
    commit-tree --no-gpg-sign -m "$3" "$1"
}
BASE=$(commit "$BASE_TREE" "1767225600 +0000" \
  "base: the tree of MoonAliza 16f637f, before fix-x2-1")
ACCEPTED=$(commit "$WITH_TEST" "1767312000 +0000" \
  "accepted: the tree of MoonAliza 01a8604 (fix-x2-1) with the pack's accepted journey test, tests/zz_accepted_x2_1.test.ts")

# plain refs: `git tag` turns into a signed annotated tag on a host with tag.gpgSign set
git -C "$REPO" update-ref refs/heads/base "$BASE"
git -C "$REPO" update-ref refs/heads/accepted "$ACCEPTED"
git -C "$REPO" update-ref refs/tags/base0 "$BASE"
git -C "$REPO" update-ref refs/tags/accepted0 "$ACCEPTED"
git -C "$REPO" symbolic-ref HEAD refs/heads/accepted
printf 'base0 %s\naccepted0 %s\n' "$BASE" "$ACCEPTED"

[ -f "$HERE/manifest.json" ] || exit 0
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
