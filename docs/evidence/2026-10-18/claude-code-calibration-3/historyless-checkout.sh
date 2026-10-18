#!/bin/bash
# History-less checkout for a calibration candidate (run 3's answer to the "accepted answers exist in git history" limit).
# usage: cal-historyless-checkout.sh <source-repo> <commit> <target-dir> <branch-name>
# The target holds the tree of <commit> as a single root commit with no parent, in a fresh repository: no git history,
# no other refs, no reflog that could reach the accepted fix. node_modules and .build are symlinked from the source repo.
set -euo pipefail
SRC=$1; COMMIT=$2; DIR=$3; BRANCH=$4
[ -e "$DIR" ] && { echo "exists: $DIR" >&2; exit 2; }
mkdir -p "$DIR"
git -C "$SRC" archive --format=tar "$COMMIT" | tar -x -C "$DIR"
git -C "$DIR" init -q -b "$BRANCH"
git -C "$DIR" -c user.name=calibration -c user.email=calibration@localhost add -A
git -C "$DIR" -c user.name=calibration -c user.email=calibration@localhost commit -q -m "calibration base: the tree of $COMMIT, no history" 
ln -s "$SRC/node_modules" "$DIR/node_modules"; ln -s "$SRC/.build" "$DIR/.build"
# proof: exactly one commit, no other refs
[ "$(git -C "$DIR" rev-list --all --count)" = 1 ] && echo "ok $DIR: one commit, tree of $COMMIT, branch $BRANCH"
