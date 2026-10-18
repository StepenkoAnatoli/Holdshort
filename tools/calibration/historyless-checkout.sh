#!/usr/bin/env bash
# Lineage: generalises calibration run 3's history-less checkout (one root commit holding the base tree, so the
# accepted fix is not an object the candidate's git can reach). Changes from run 3: the dependency symlinks are opt-in
# (--link), point at a directory outside the pack (run 3 linked into the pack repository, a path to the accepted fix)
# and are hidden from git status; the tree is copied as git objects, not through git archive, so export-ignore and
# export-subst attributes cannot change it; --pack refuses a target that shares a path with the subject pack.
#
# usage: historyless-checkout.sh [--link NAME=DIR]... [--pack PACK_DIR] SOURCE_REPO COMMIT TARGET BRANCH
#
#   SOURCE_REPO  the pack's git repository (it holds COMMIT and, elsewhere in its history, the accepted fix)
#   COMMIT       the case's base revision
#   TARGET       the candidate's checkout; must not exist
#   BRANCH       the branch the single commit is on
#   --link NAME=DIR  symlink DIR (an installed dependency tree, a build cache) into TARGET/NAME and list NAME in
#                TARGET/.git/info/exclude so a candidate's `git add -A` never commits it; repeatable. DIR must be
#                installed outside the pack: refused when its real path is inside SOURCE_REPO or PACK_DIR or holds
#                either (proposal Item 2: no path from a checkout reaches the accepted fix). Symlinks inside DIR are
#                not followed: a dependency tree that links back into the pack is the host's to avoid.
#   --pack DIR   refuse when TARGET is inside DIR or DIR inside TARGET (proposal Item 2: no candidate checkout shares
#                a filesystem path with the pack)
#
# Exit 0 with one "ok" line when TARGET holds exactly one commit whose tree is COMMIT's tree; 2 on bad arguments or a
# refused target; 1 when git fails or the proof does not hold.
set -euo pipefail

usage() {
  echo "usage: historyless-checkout.sh [--link NAME=DIR]... [--pack PACK_DIR] SOURCE_REPO COMMIT TARGET BRANCH" >&2
  exit 2
}
refuse() {
  echo "historyless-checkout: refused: $*" >&2
  exit 2
}

LINKS=()
PACK=""
while [ $# -gt 0 ]; do
  case "$1" in
    --link) [ $# -ge 2 ] || usage; LINKS+=("$2"); shift 2 ;;
    --pack) [ $# -ge 2 ] || usage; PACK=$2; shift 2 ;;
    --) shift; break ;;
    -*) echo "historyless-checkout: unknown option $1" >&2; usage ;;
    *) break ;;
  esac
done
[ $# -eq 4 ] || usage
SRC=$1
COMMIT=$2
DIR=$3
BRANCH=$4

[ -e "$DIR" ] || [ -L "$DIR" ] && refuse "target exists: $DIR"
SRC_ABS=$(cd -- "$SRC" 2>/dev/null && pwd -P) || refuse "no source repository: $SRC"
TREE=$(git -C "$SRC_ABS" rev-parse --verify --quiet "$COMMIT^{tree}") || refuse "not a commit in $SRC: $COMMIT"
git check-ref-format --branch "$BRANCH" >/dev/null 2>&1 || refuse "not a branch name: $BRANCH"
# within A B: A is B or lies under it (both physical paths; pwd -P ends in '/' only for the root, which holds everything)
within() { [ "$2" = / ] && return 0; case "$1/" in "$2"/*) return 0 ;; esac; return 1; }

PACK_ABS=""
if [ -n "$PACK" ]; then
  PACK_ABS=$(cd -- "$PACK" 2>/dev/null && pwd -P) || refuse "no pack directory: $PACK"
fi
LINK_NAMES=()
LINK_DIRS=()
for spec in ${LINKS[@]+"${LINKS[@]}"}; do
  case "$spec" in
    *=*) ;;
    *) refuse "--link takes NAME=DIR, a dependency directory installed outside the pack: $spec" ;;
  esac
  name=${spec%%=*}
  case "$name" in
    "" | /* | *..* ) refuse "--link takes a plain relative name: $name" ;;
  esac
  dep=$(cd -- "${spec#*=}" 2>/dev/null && pwd -P) || refuse "--link $name: no directory ${spec#*=}"
  for guarded in "$SRC_ABS" ${PACK_ABS:+"$PACK_ABS"}; do
    if within "$dep" "$guarded" || within "$guarded" "$dep"; then
      refuse "--link $name: $dep shares a path with $guarded, which holds the accepted fix (Item 2)"
    fi
  done
  LINK_NAMES+=("$name")
  LINK_DIRS+=("$dep")
done

PARENT=$(dirname -- "$DIR")
mkdir -p -- "$PARENT"
TARGET_ABS="$(cd -- "$PARENT" && pwd -P)/$(basename -- "$DIR")"
if [ -n "$PACK_ABS" ]; then
  within "$TARGET_ABS" "$PACK_ABS" && refuse "target $TARGET_ABS is inside the pack $PACK_ABS"
  within "$PACK_ABS" "$TARGET_ABS" && refuse "the pack $PACK_ABS is inside the target $TARGET_ABS"
fi

git init -q -b "$BRANCH" "$TARGET_ABS"
# the base tree and every tree and blob under it, and nothing else: no commit of the source is copied
{ echo "$TREE"; git -C "$SRC_ABS" ls-tree -r -t "$TREE" | awk '$2 != "commit" { print $3 }'; } \
  | git -C "$SRC_ABS" pack-objects --stdout -q | git -C "$TARGET_ABS" unpack-objects -q
BASE=$(git -C "$TARGET_ABS" -c user.name=calibration -c user.email=calibration@localhost \
  commit-tree --no-gpg-sign -m "calibration base: a tree with no history" "$TREE")
git -C "$TARGET_ABS" update-ref "refs/heads/$BRANCH" "$BASE"
git -C "$TARGET_ABS" reset -q --hard "$BASE"
for i in ${LINK_NAMES[@]+"${!LINK_NAMES[@]}"}; do
  ln -s "${LINK_DIRS[$i]}" "$TARGET_ABS/${LINK_NAMES[$i]}"
  printf '/%s\n' "${LINK_NAMES[$i]}" >> "$TARGET_ABS/.git/info/exclude"
done

# proof: exactly one commit reachable from any ref, and its tree is the base tree
[ "$(git -C "$TARGET_ABS" rev-list --all --count)" = 1 ] || { echo "historyless-checkout: more than one commit in $TARGET_ABS" >&2; exit 1; }
[ "$(git -C "$TARGET_ABS" rev-parse HEAD^{tree})" = "$TREE" ] || { echo "historyless-checkout: tree differs from $COMMIT" >&2; exit 1; }
echo "ok $TARGET_ABS: one commit, the tree of $COMMIT, branch $BRANCH"
