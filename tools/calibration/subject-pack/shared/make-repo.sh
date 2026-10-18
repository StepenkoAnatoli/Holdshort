#!/usr/bin/env bash
# Lineage: the pack repository calibration runs 1-3 committed by hand (a base tree, the accepted fix after it), built
# here from the shared pack's trees so that every host gets the same three commit ids, which manifest.json carries.
#
# usage: make-repo.sh TARGET
#
#   TARGET  where the pack repository is built; must not exist. A host builds it outside the kit's tree (for example
#           beside its checkout root) and copies manifest.json beside it, so the manifest's `repository` ("repo")
#           resolves when TARGET is <pack dir>/repo; built anywhere else, the host writes TARGET into its copy.
#
# The repository holds one branch, main, of three commits, each tagged:
#   review0    trees/review    (D-1 and D-2 present): the review case's base
#   base0      trees/base      (D-2 present): the pin and fix cases' base
#   accepted0  trees/accepted  (neither): the accepted fix of D-2 with its pin, tests/test_pin.py
# The ids depend on nothing on the host: every file is stored as its bytes (no filter, no line-ending conversion) with
# mode 100644, and the identity, dates, messages and encoding of each commit are fixed here.
#
# Prints "<tag> <commit id>" for each commit. Exit 0 when the ids equal manifest.json's (or there is no manifest beside
# this script); 1 when git fails or the ids differ from the manifest's (the pack's files changed since it was written);
# 2 on a bad argument or an existing TARGET.
set -euo pipefail

refuse() {
  echo "make-repo: refused: $*" >&2
  exit 2
}
[ $# -eq 1 ] || refuse "usage: make-repo.sh TARGET"
TARGET=$1
[ -e "$TARGET" ] || [ -L "$TARGET" ] && refuse "target exists: $TARGET"
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
for t in review base accepted; do
  [ -d "$HERE/trees/$t" ] || refuse "no tree $HERE/trees/$t"
done

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
export GIT_AUTHOR_NAME="Calibration Kit" GIT_AUTHOR_EMAIL="shared-pack@calibration.invalid"
export GIT_COMMITTER_NAME="Calibration Kit" GIT_COMMITTER_EMAIL="shared-pack@calibration.invalid"

mkdir -p -- "$(dirname -- "$TARGET")"
git init -q --object-format=sha1 -b main -- "$TARGET"
REPO=$(cd -- "$TARGET" && pwd -P)
INDEX="$REPO/.git/make-repo.index"

# tree DIR: the id of a tree holding every file under DIR (bytecode caches left out) as its bytes, mode 100644
tree() {
  rm -f -- "$INDEX"
  while IFS= read -r -d '' f; do
    f=${f#./}
    blob=$(git -C "$REPO" hash-object -w --no-filters -- "$1/$f")
    GIT_INDEX_FILE=$INDEX git -C "$REPO" update-index --add --cacheinfo "100644,$blob,$f"
  done < <(cd -- "$1" && find . -name __pycache__ -prune -o -type f -print0 | LC_ALL=C sort -z)
  GIT_INDEX_FILE=$INDEX git -C "$REPO" write-tree
  rm -f -- "$INDEX"
}

# commit TREE DATE MESSAGE [PARENT]: a commit with this script's identity and date, unsigned, its message in UTF-8
commit() {
  GIT_AUTHOR_DATE=$2 GIT_COMMITTER_DATE=$2 git -C "$REPO" -c i18n.commitEncoding=UTF-8 \
    commit-tree --no-gpg-sign ${4:+-p "$4"} -m "$3" "$1"
}

REVIEW=$(commit "$(tree "$HERE/trees/review")" "1767225600 +0000" \
  "bounded: read_bounded, its specification and its harness")
BASE=$(commit "$(tree "$HERE/trees/base")" "1767312000 +0000" \
  "fix(bounded): D-1 - a memoryview chunk is read as a bytes-like chunk, never rejected" "$REVIEW")
ACCEPTED=$(commit "$(tree "$HERE/trees/accepted")" "1767398400 +0000" \
  "fix(bounded): D-2 - a str chunk's bytes count against the limit, with its two-row pin in tests/test_pin.py" "$BASE")

git -C "$REPO" update-ref refs/heads/main "$ACCEPTED"
git -C "$REPO" tag review0 "$REVIEW"
git -C "$REPO" tag base0 "$BASE"
git -C "$REPO" tag accepted0 "$ACCEPTED"
git -C "$REPO" -c core.autocrlf=false -c core.eol=lf read-tree -u --reset main
printf 'review0 %s\nbase0 %s\naccepted0 %s\n' "$REVIEW" "$BASE" "$ACCEPTED"

[ -f "$HERE/manifest.json" ] || exit 0
python3 -I - "$HERE/manifest.json" "$REVIEW" "$BASE" "$ACCEPTED" <<'PY'
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
review, base, accepted = sys.argv[2:5]
want = {"cases.review.base": review, "cases.pin.base": base, "cases.fix.base": base, "accepted_fix": accepted}
have = {"cases.review.base": m["cases"]["review"]["base"], "cases.pin.base": m["cases"]["pin"]["base"],
        "cases.fix.base": m["cases"]["fix"]["base"], "accepted_fix": m["accepted_fix"]}
bad = [f"{k}: manifest {have[k]}, built {v}" for k, v in want.items() if have[k] != v]
if bad:
    print("make-repo: the built ids differ from manifest.json (the pack's files changed since it was written):", file=sys.stderr)
    print("\n".join("  " + b for b in bad), file=sys.stderr)
    sys.exit(1)
print("make-repo: the ids equal manifest.json's", file=sys.stderr)
PY
