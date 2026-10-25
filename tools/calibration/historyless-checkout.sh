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
#                installed outside the pack and outside every git repository (proposal Item 2: no path from a
#                checkout reaches the accepted fix). Refused when its real path is inside SOURCE_REPO or PACK_DIR or
#                holds either, and when it is inside a git repository: DIR or one of its real ancestors holds a .git
#                entry (a directory, or the file of a linked worktree or submodule) or is a git directory (HEAD,
#                objects/ and refs/, as in a bare repository) - through '..' the checkout reaches that repository's
#                files and history, such as a subject clone's accepted fix and orchestration records (IC4-1). Each
#                symlink among DIR's own entries (its top level, dot entries too) is checked the same way on the
#                real path it resolves to (followed hop by hop as a POSIX kernel does: a linked directory before the
#                '..' after it), and one that does not resolve is refused. Nothing deeper is checked: a symlink or a
#                repository further down inside DIR is not followed, and is the host's to avoid.
#   --pack DIR   refuse when TARGET is inside DIR or DIR inside TARGET (proposal Item 2: no candidate checkout shares
#                a filesystem path with the pack)
#
# How paths are compared: "inside" and "holds" are decided by identity ([ -ef ]) along a path's ancestors, not by
# spelling, so another spelling of the same directory (another case on a case-insensitive filesystem) cannot pass. The
# ancestors are those '..' reaches in the shell's namespace and, where cygpath exists (Git Bash, Cygwin), in the
# Windows spelling native programs walk (a mount such as Git Bash's / or /tmp has Windows parents the shell does not
# show). A UNC path (//host/share/...) is refused wherever a check needs it - DIR, a symlink's target, SOURCE_REPO and
# PACK_DIR when they are compared, TARGET's parent under --pack: its spellings need not compare as one directory and
# '..' at a share root differs between the shell and Windows, so it cannot be checked reliably. The host's git
# repository variables (GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, ...: git rev-parse --local-env-vars) are dropped, so
# every git command works on the repository it names and none on another.
#
# Exit 0 with one "ok" line when TARGET holds exactly one commit whose tree is COMMIT's tree; 2 on bad arguments or a
# refused target; 1 when git fails or the proof does not hold.
set -euo pipefail
# git honours GIT_DIR and the like over -C: with them naming another repository, git init re-initialised it and
# update-ref and reset --hard rewrote it (LC2-3). Drop every variable git itself lists as local to a repository.
GIT_LOCAL_VARS=$(git rev-parse --local-env-vars) || { echo "historyless-checkout: git rev-parse --local-env-vars failed" >&2; exit 1; }
# shellcheck disable=SC2086 # one variable name per word
unset $GIT_LOCAL_VARS

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
# canon P: P with the leading '//' that bash keeps from pwd -P resolved: '//' alone is the root (N3; on Git Bash the
# network root, which a check of '/' refuses all the same, since '/' holds everything), and '//x...' becomes '/x...'
# only when both name the same directory (POSIX: '//x' is '/x'). On Git Bash '//host/share/...' is a UNC path and
# '/host/share/...' another path, so it is kept, for ancestors to refuse (LC2-1)
canon() {
  case "$1" in
    //) printf / ;;
    //*) if [ "$1" -ef "${1#/}" ]; then printf '%s' "${1#/}"; else printf '%s' "$1"; fi ;;
    *) printf '%s' "$1" ;;
  esac
}
# phys DIR: the physical path of DIR (canon of pwd -P)
phys() { local p; p=$(cd -- "$1" 2>/dev/null && pwd -P) || return 1; canon "$p"; }
SRC_ABS=$(phys "$SRC") || refuse "no source repository: $SRC"
# within A B: A is B or lies under it (both physical paths from phys, so the root is spelled '/' and holds everything)
within() { [ "$2" = / ] && return 0; case "$1/" in "$2"/*) return 0 ;; esac; return 1; }
# is_repo D: the directory D holds a .git entry (a directory, the file of a linked worktree or submodule, or a link) or
# is a git directory (HEAD, objects/ and refs/, the test git itself applies: a bare repository, or the inside of a .git
# directory). It reads the filesystem only: git's own discovery stops at a filesystem boundary, refuses a repository
# another user owns, and honours GIT_CEILING_DIRECTORIES, none of which stop a '..' (IC4-1)
is_repo() {
  [ -e "${1%/}/.git" ] || [ -L "${1%/}/.git" ] || { [ -f "${1%/}/HEAD" ] && [ -d "${1%/}/objects" ] && [ -d "${1%/}/refs" ]; }
}
WINPATHS=""
if command -v cygpath >/dev/null 2>&1; then
  WINPATHS=1
else
  case "$(uname -s 2>/dev/null)" in CYGWIN* | MINGW* | MSYS*) refuse "cygpath is missing: the Windows parents of a path cannot be checked" ;; esac
fi
# ancestors P: set ANC to the physical path P and every directory above it, nearest first, as '..' reaches them: in
# the shell's spelling, then (with cygpath) in the Windows spelling cygpath -m gives, which native programs walk (a
# mount such as Git Bash's / or /tmp is a directory whose Windows parents differ from the shell's). Status 1 when a
# spelling is not a local absolute path: a UNC path //host/share/... (its spellings need not compare as one directory,
# and '..' at a share root differs between the shell and Windows - LC2-1), or anything else unexpected
ancestors() {
  local p q
  local -a spell=("$1")
  ANC=()
  if [ -n "$WINPATHS" ]; then
    q=$(cygpath -m -- "$1") || return 1
    spell+=("$q")
  fi
  for p in "${spell[@]}"; do
    case "$p" in //*) ANC=(); return 1 ;; /* | [A-Za-z]:/*) ;; *) ANC=(); return 1 ;; esac
    case "$p" in / | [A-Za-z]:/) ;; */) p=${p%/} ;; esac
    while :; do
      ANC+=("$p")
      q=${p%/*}
      case "$q" in "") q=/ ;; [A-Za-z]:) q=$q/ ;; esac
      [ "$q" = "$p" ] && break
      p=$q
    done
  done
  return 0
}
LOCAL_ONLY="is not a local path (a UNC path //host/share/..., or a mount of one), whose parents cannot be checked reliably (Item 2)"
# physd D: the physical path of the directory D the way the kernel walks it: cd -P follows each link before the '..'
# after it (phys's plain cd drops 'link/..' by spelling first, so 'link/../y' could name a different y than the
# kernel reaches)
physd() { local p; p=$(cd -P -- "$1" 2>/dev/null && pwd -P) || return 1; canon "$p"; }
# resolve E: print the physical path the symlink E resolves to: a directory through physd, a file as its directory's
# physical path and its name, following a chain of links (at most 40) hop by hop, each hop's directory made physical
# before a relative target is joined to it, as the kernel does; status 1 when E does not resolve
resolve() {
  local p=$1 t n=0 d
  [ -e "$p" ] || return 1
  if [ -d "$p" ]; then physd "$p"; return; fi
  while :; do
    d=$(physd "$(dirname -- "$p")") || return 1
    p=${d%/}/$(basename -- "$p")
    [ -L "$p" ] || break
    n=$((n + 1))
    [ "$n" -le 40 ] || return 1
    t=$(readlink -- "$p") || return 1
    case "$t" in /*) p=$t ;; *) p=${d%/}/$t ;; esac
  done
  printf '%s' "$p"
}

# G_OF / G_ANC: the guarded paths (SOURCE_REPO when there are links, PACK_DIR) paired with each of their ancestors
G_OF=()
G_ANC=()
# add_guard G WHAT: record the physical path G and its ancestors as guarded; refuse when G is not a local path
add_guard() {
  local a
  ancestors "$1" || refuse "$2 $1 $LOCAL_ONLY"
  for a in "${ANC[@]}"; do G_OF+=("$1"); G_ANC+=("$a"); done
}
[ ${#LINKS[@]} -eq 0 ] || add_guard "$SRC_ABS" "the source repository"
PACK_ABS=""
if [ -n "$PACK" ]; then
  PACK_ABS=$(phys "$PACK") || refuse "no pack directory: $PACK"
  add_guard "$PACK_ABS" "the pack"
fi
# the source lookup follows the checks above, so a UNC source is refused as one (git itself reports "dubious ownership")
TREE=$(git -C "$SRC_ABS" rev-parse --verify --quiet "$COMMIT^{tree}") || refuse "not a commit in $SRC: $COMMIT"
git check-ref-format --branch "$BRANCH" >/dev/null 2>&1 || refuse "not a branch name: $BRANCH"
# guard_link NAME P WHAT: refuse when the physical path P is not a local path, shares a path with SOURCE_REPO or
# PACK_DIR (it is one of them or lies under it - one of its ancestors is the same directory - or holds one - one of
# the guarded path's ancestors is P), or is inside a git repository (it or one of its ancestors is one); WHAT names P
guard_link() {
  local a g i
  ancestors "$2" || refuse "--link $1: $3 $LOCAL_ONLY"
  for g in "$SRC_ABS" ${PACK_ABS:+"$PACK_ABS"}; do
    for a in "${ANC[@]}"; do
      if [ "$a" -ef "$g" ]; then refuse "--link $1: $3 shares a path with $g, which holds the accepted fix (Item 2)"; fi
    done
  done
  for i in ${G_OF[@]+"${!G_OF[@]}"}; do
    if [ "${G_ANC[$i]}" -ef "$2" ]; then refuse "--link $1: $3 shares a path with ${G_OF[$i]}, which holds the accepted fix (Item 2)"; fi
  done
  for a in "${ANC[@]}"; do
    if is_repo "$a"; then
      refuse "--link $1: $3 is inside the git repository $a; a dependency tree inside a repository lets the checkout reach that repository's history and files through '..' (Item 2)"
    fi
  done
  return 0
}
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
  dep=$(phys "${spec#*=}") || refuse "--link $name: no directory ${spec#*=}"
  guard_link "$name" "$dep" "$dep"
  for entry in "$dep"/* "$dep"/.[!.]* "$dep"/..?*; do  # an unmatched pattern stays literal and is no symlink
    [ -L "$entry" ] || continue
    real=$(resolve "$entry") || refuse "--link $name: $entry, a symlink in $dep, does not resolve"
    guard_link "$name" "$real" "$entry, a symlink in $dep resolving to $real,"
  done
  LINK_NAMES+=("$name")
  LINK_DIRS+=("$dep")
done

PARENT=$(dirname -- "$DIR")
mkdir -p -- "$PARENT"
PARENT_ABS=$(phys "$PARENT")
TARGET_ABS="$PARENT_ABS/$(basename -- "$DIR")"
if [ -n "$PACK_ABS" ]; then
  # TARGET does not exist, so it is inside the pack exactly when its parent is the pack or lies under it
  ancestors "$PARENT_ABS" || refuse "target $TARGET_ABS: its parent $LOCAL_ONLY"
  for a in "${ANC[@]}"; do
    if [ "$a" -ef "$PACK_ABS" ]; then refuse "target $TARGET_ABS is inside the pack $PACK_ABS"; fi
  done
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
