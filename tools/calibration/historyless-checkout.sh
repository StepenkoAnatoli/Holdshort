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
#   TARGET       the candidate's checkout; must not exist, and must not be inside any git repository (TARGET's parent
#                or one of its real ancestors is one, tested as for --link DIR below): through '..' the checkout would
#                reach that repository's files and history (Item 2). Its missing parents are made only after every
#                check has passed, as spelled, so that part may hold no '.' or '..' segment, and nor may its last
#                segment (TARGET/.. names another directory than the one made for it)
#   BRANCH       the branch the single commit is on
#   --link NAME=DIR  symlink DIR (an installed dependency tree, a build cache) into TARGET/NAME and list NAME in
#                TARGET/.git/info/exclude so a candidate's `git add -A` never commits it; repeatable. DIR must be
#                installed outside the pack and outside every git repository (proposal Item 2: no path from a
#                checkout reaches the accepted fix). Refused when its real path is inside SOURCE_REPO or PACK_DIR or
#                holds either, and when it is inside a git repository: DIR or one of its real ancestors holds a .git
#                entry (a directory, or the file of a linked worktree or submodule) or may be a git directory (it
#                holds an entry named HEAD, commondir or gitdir, or both an objects and a refs entry, each of any
#                type: a bare repository, a linked worktree's admin directory; a rule wider than git's own, see
#                is_repo below) - through '..' the checkout reaches that repository's files and history, such as a
#                subject clone's accepted fix and orchestration records (IC4-1). Each symlink among DIR's own entries
#                (its top level, dot entries too) is checked the same way on the real path it resolves to (followed
#                hop by hop as a POSIX kernel does: a linked directory before the '..' after it), and one that does
#                not resolve is refused; both layers below do this, the native one on every path the shell resolves
#                too. Nothing deeper is checked: a symlink or a repository further down inside DIR is not followed,
#                and is the host's to avoid. NAME is a plain relative path (no leading '/', no '..', no '\' or ':'),
#                and none of its segments may name .git in any spelling Windows resolves to it (any case, trailing
#                dots or spaces, GIT~1). Each link is made only where NAME does not exist yet in the checkout and its
#                real parent lies inside TARGET and outside TARGET/.git, in both layers: a symlink the base tree
#                tracks (checked out as one with core.symlinks=true, such as g -> .git) or an earlier --link can lead
#                it elsewhere (LC5-3). Refused otherwise, and the checkout made so far is removed, never through a link
#   --pack DIR   refuse when TARGET is inside DIR or DIR inside TARGET (proposal Item 2: no candidate checkout shares
#                a filesystem path with the pack), in both layers below
#
# What the guard covers, and what it cannot: no path the checkout gets from this script - TARGET's own parents, each
# DIR and its parents, each link at DIR's top and the parents of where it leads - reaches a git repository, the pack
# or SOURCE_REPO, by any spelling native programs resolve (both layers below). It knows a repository only by its
# markers (is_repo), and the pack and SOURCE_REPO only by the paths given. So these are the host's duty, and the
# guard cannot see them: a plain copy or export (git archive) of the subject's files, a work tree whose git directory
# lies elsewhere (core.worktree, which leaves no .git in the tree), a link or a repository deeper inside DIR, and
# anything else it could know only by its content. A refusal never means "remove the .git and retry": a stripped
# clone of the subject still hands over its files (orchestration records, a brief). Install dependencies where no
# subject file is, such as a history-less checkout of the case base made outside the pack.
#
# How paths are compared: "inside" and "holds" are decided by identity ([ -ef ]) along a path's ancestors, not by
# spelling, so another spelling of the same directory (another case on a case-insensitive filesystem) cannot pass. A
# UNC path (//host/share/...) is refused wherever a check needs it - DIR, a symlink's target, SOURCE_REPO and PACK_DIR
# when they are compared, TARGET's parent: its spellings need not compare as one directory and '..' at a share root
# differs between the shell and Windows, so it cannot be checked reliably. Every check runs in two layers, and a path
# must pass both:
#   the shell layer: the physical path the shell resolves (pwd -P; a symlink followed hop by hop, as a POSIX kernel
#                does) and the parents '..' reaches from it in the shell's namespace, plus, where cygpath exists (Git
#                Bash, Cygwin), the parents of its Windows spelling (cygpath -m: a mount such as Git Bash's / or /tmp
#                has Windows parents the shell does not show). This is what bash and the MSYS tools a candidate runs
#                see, and on a POSIX host it is also what every other program sees.
#   the native layer (Windows only: Git Bash, MSYS2, Cygwin): each path - SOURCE_REPO (always: git reads it),
#                PACK_DIR, each DIR, each entry at DIR's top that is a symlink, junction or other reparse point, every
#                path the shell layer resolves a symlink at DIR's top to, TARGET's nearest existing parent, the
#                checkout once made, and each link's parent in the checkout - resolved the way native programs (git,
#                node, Python) resolve it, by a Windows Python's os.path.realpath(path, strict=True)
#                (GetFinalPathNameByHandle), and the same checks (identity with os.path.samefile, the .git walk) run
#                on that final path and its parents. Git Bash
#                cannot see some links native programs follow: one to a volume-GUID or GLOBALROOT path is a plain
#                directory to it (no -L, no readlink, pwd -P keeps the link's own path), and only this layer follows it
#                (LC3-1). And some links only Git Bash sees: an MSYS sys or shortcut symlink (MSYS=winsymlinks:sys or
#                :lnk) is a plain file to Windows, yet it can lead to such a path, which the shell then checks in its
#                own view, so the path the shell resolved it to is checked here again (LC5-1). It fails closed: a path
#                it cannot resolve, or that resolves to anything but a drive-letter path (a UNC path, a volume with no
#                drive letter), is refused, and so is every checkout when no
#                Windows Python 3.10+ (python3 or python; os.path.realpath has strict since 3.10) is on PATH. Its
#                refusals say "as native programs resolve it".
# The host's git repository variables (GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, ...: git rev-parse --local-env-vars)
# are dropped, so every git command works on the repository it names and none on another; and git init copies no
# template (--template=), so neither GIT_TEMPLATE_DIR nor init.templateDir can add objects/info/alternates (another
# repository's objects) or hooks to the checkout. The final proof counts every object the checkout's git can read.
# The globbing the checks rely on is set here (set +f, shopt -u nullglob failglob), so SHELLOPTS or BASHOPTS from the
# environment cannot turn off the loop over DIR's top (LC5-2).
#
# Exit 0 with one "ok" line when TARGET holds exactly one commit whose tree is COMMIT's tree, and no object but that
# commit and the objects of that tree; 2 on bad arguments or a refused target (nothing is made then: a refusal after
# the checkout is made removes it); 1 when git fails or the proof does not hold.
set -euo pipefail
# bash takes SHELLOPTS and BASHOPTS from the environment: with noglob the loop over DIR's top saw only its literal
# patterns and checked no entry, with failglob it died on the first unmatched one (LC5-2). Set the globbing the loops
# rely on: patterns expand, and one that matches nothing stays literal
set +f
shopt -u nullglob failglob
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
# Every path the checks below read is a string the shell made of a path ($(pwd -P), $(dirname), $(basename),
# $(readlink), $(cygpath -m)), and a command substitution drops every trailing newline: the string made of a path whose
# name ends in a newline names another file, or none, and the checks of it, in both layers, checked that other path
# (LC6-1). So no such string is checked or handed on unless it is proved, by file identity, to name the file it came
# from ([ a -ef b ]: the same device and inode, each followed to the end of its links as stat(2) does), and the path is
# refused when that fails or cannot be proved. Two strings name a file that does not exist yet (TARGET, a link's
# NAME), so there is nothing to compare them with: their spelling is kept exactly (spell_dir, spell_base), and the
# part of them that exists is proved. The native layer proves its own strings the same way (final, below)
UNPROVED="is not proved to name the file it came from: the string made of it (a command substitution drops a trailing newline; Windows drops a trailing space or dot) names another file or none, so it cannot be checked (LC6-1)"
# unproved HOW STATUS WHAT ELSE: refuse with HOW (refuse, or refuse_made once the checkout is made) "WHAT $UNPROVED"
# when STATUS is 3 (phys, physd, resolve and ancestors report so a string they could not prove), else ELSE
unproved() { if [ "$2" -eq 3 ]; then "$1" "$3 $UNPROVED"; fi; "$1" "$4"; }
# spell_dir VAR P / spell_base VAR P: set VAR to what dirname / basename print for P, exactly: each prints a sentinel
# line after its result, so the substitution drops only the sentinel's newline, and the sentinel is cut off
spell_dir() { local r; r=$(dirname -- "$2"; echo .); printf -v "$1" '%s' "${r%$'\n.'}"; }
spell_base() { local r; r=$(basename -- "$2"; echo .); printf -v "$1" '%s' "${r%$'\n.'}"; }
# phys DIR: the physical path of DIR (canon of pwd -P), proved to name DIR (status 3 when it does not; 1 when DIR is no
# directory). cd's own output (a CDPATH match) is dropped; a CDPATH match is another directory than DIR, so not proved
phys() { local p; p=$(cd -- "$1" >/dev/null 2>&1 && pwd -P) || return 1; [ "$p" -ef "$1" ] || return 3; canon "$p"; }
SRC_ABS=$(phys "$SRC") || unproved refuse $? "the source repository $SRC" "no source repository: $SRC"
# within A B: A is B or lies under it (both physical paths from phys, so the root is spelled '/' and holds everything)
within() { [ "$2" = / ] && return 0; case "$1/" in "$2"/*) return 0 ;; esac; return 1; }
# is_repo D: D may be a git repository, by a rule at least as wide as git's own (LC4-1). Git's discovery (setup.c,
# setup_git_directory_gently_1) takes a directory whose .git entry is a gitfile (read_gitfile_gently) or a directory
# is_git_directory accepts, or a directory is_git_directory accepts itself (a bare repository, the inside of a .git
# directory, a linked worktree's admin directory). is_git_directory needs a HEAD that validate_headref accepts (a
# symlink into refs/, even a dangling one, or a file holding a ref or an object id), then objects and refs in the
# common directory, which a commondir file, GIT_COMMON_DIR or GIT_OBJECT_DIRECTORY can move, and which Git for Windows
# tests with an access() that ignores X_OK, so a file named refs passes. Only the HEAD entry is needed under every
# environment a candidate may run with, so D counts as a repository when it holds any entry, of any type, named .git,
# HEAD, commondir or gitdir (a linked worktree's admin files), or both an objects and a refs entry (objects a '..'
# reaches and reads without git, even with HEAD gone). It reads the filesystem only: git's own discovery stops at a
# filesystem boundary, refuses a repository another user owns, and honours GIT_CEILING_DIRECTORIES and
# safe.bareRepository, none of which stop a '..' (IC4-1)
has() { [ -e "${1%/}/$2" ] || [ -L "${1%/}/$2" ]; }
is_repo() {
  has "$1" .git || has "$1" HEAD || has "$1" commondir || has "$1" gitdir || { has "$1" objects && has "$1" refs; }
}
WINDOWS=""
case "$(uname -s 2>/dev/null)" in CYGWIN* | MINGW* | MSYS*) WINDOWS=1 ;; esac
WINPATHS=""
if command -v cygpath >/dev/null 2>&1; then
  WINPATHS=1
elif [ -n "$WINDOWS" ]; then
  refuse "cygpath is missing: the Windows parents of a path cannot be checked"
fi
# NATIVE_PY: on Windows, the first of python3 and python that is a Windows Python 3.10+ (os.name nt: its
# os.path.realpath resolves through GetFinalPathNameByHandle, as native programs do; an MSYS2 or Cygwin Python resolves
# as the shell does). With none, the native layer cannot run, and the checkout is refused (fail closed)
NATIVE_PY=""
if [ -n "$WINDOWS" ]; then
  for py in python3 python; do
    command -v "$py" >/dev/null 2>&1 || continue
    probe=$("$py" -I -c 'import os, sys; sys.stdout.write(os.name if sys.version_info >= (3, 10) else "old")' 2>/dev/null) || continue
    if [ "$probe" = nt ]; then NATIVE_PY=$py; break; fi
  done
  [ -n "$NATIVE_PY" ] || refuse "no native path resolver: on Windows the checks also resolve each path as native programs do, which needs a Windows Python 3.10+ (os.path.realpath's strict argument) on PATH as python3 or python (an MSYS2 or Cygwin Python resolves as the shell does)"
fi
# ancestors P: set ANC to the physical path P and every directory above it, nearest first, as '..' reaches them: in
# the shell's spelling, then (with cygpath) in the Windows spelling cygpath -m gives, which native programs walk (a
# mount such as Git Bash's / or /tmp is a directory whose Windows parents differ from the shell's). Status 1 when a
# spelling is not a local absolute path: a UNC path //host/share/... (its spellings need not compare as one directory,
# and '..' at a share root differs between the shell and Windows - LC2-1), or anything else unexpected; status 3 when
# the Windows spelling names another file than P (LC6-1)
ancestors() {
  local p q w=""
  local -a spell=("$1")
  ANC=()
  if [ -n "$WINPATHS" ]; then
    w=$(cygpath -m -- "$1") || return 1
    spell+=("$w")
  fi
  for p in "${spell[@]}"; do
    case "$p" in //*) return 1 ;; /* | [A-Za-z]:/*) ;; *) return 1 ;; esac
  done
  # the Windows spelling names P, by file identity: a mount's Windows spelling is the same directory under other
  # parents, and one that names another directory is no spelling of P (status 3). A path that does not exist yet (a
  # target's parent) has nothing to compare with; its existing part is proved as the T item below
  if [ -n "$w" ] && [ -e "$1" ] && ! [ "$w" -ef "$1" ]; then return 3; fi
  for p in "${spell[@]}"; do
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
# kernel reaches), proved to name D as phys does (status 3 when it does not; 1 when D is no directory)
physd() { local p; p=$(cd -P -- "$1" >/dev/null 2>&1 && pwd -P) || return 1; [ "$p" -ef "$1" ] || return 3; canon "$p"; }
# resolve E: print the physical path the symlink E resolves to: a directory through physd, a file as its directory's
# physical path and its name, following a chain of links (at most 40) hop by hop, each hop's directory made physical
# before a relative target is joined to it, as the kernel does; status 1 when E does not resolve. Each string it makes
# ($(dirname) and $(basename) joined, and each link's $(readlink) target) must name the file the link it replaces leads
# to ([ -ef ] follows both to the end of the chain); status 3 when one does not (LC6-1)
resolve() {
  local p=$1 q t n=0 d
  [ -e "$p" ] || return 1
  if [ -d "$p" ]; then physd "$p"; return; fi
  while :; do
    d=$(physd "$(dirname -- "$p")") || return
    q=${d%/}/$(basename -- "$p")
    [ "$q" -ef "$p" ] || return 3
    p=$q
    [ -L "$p" ] || break
    n=$((n + 1))
    [ "$n" -le 40 ] || return 1
    t=$(readlink -- "$p") || return 1
    case "$t" in /*) q=$t ;; *) q=${d%/}/$t ;; esac
    [ "$q" -ef "$p" ] || return 3
    p=$q
  done
  printf '%s' "$p"
}

# G_OF / G_ANC: the guarded paths (SOURCE_REPO when there are links, PACK_DIR) paired with each of their ancestors
G_OF=()
G_ANC=()
# add_guard G WHAT: record the physical path G and its ancestors as guarded; refuse when G is not a local path
add_guard() {
  local a
  ancestors "$1" || unproved refuse $? "$2 $1: its Windows spelling" "$2 $1 $LOCAL_ONLY"
  for a in "${ANC[@]}"; do G_OF+=("$1"); G_ANC+=("$a"); done
}
[ ${#LINKS[@]} -eq 0 ] || add_guard "$SRC_ABS" "the source repository"
PACK_ABS=""
if [ -n "$PACK" ]; then
  PACK_ABS=$(phys "$PACK") || unproved refuse $? "the pack $PACK" "no pack directory: $PACK"
  add_guard "$PACK_ABS" "the pack"
fi
# guard_link NAME P WHAT: refuse when the physical path P is not a local path, shares a path with SOURCE_REPO or
# PACK_DIR (it is one of them or lies under it - one of its ancestors is the same directory - or holds one - one of
# the guarded path's ancestors is P), or is inside a git repository (it or one of its ancestors is one); WHAT names P
guard_link() {
  local a g i
  ancestors "$2" || unproved refuse $? "--link $1: $3: its Windows spelling" "--link $1: $3 $LOCAL_ONLY"
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
# REAL_NAMES / REAL_SHOWN / REAL_PATHS: each symlink at a DIR's top the shell resolved, and the path it resolved to,
# which the native layer checks again (LC5-1)
REAL_NAMES=()
REAL_SHOWN=()
REAL_PATHS=()
for spec in ${LINKS[@]+"${LINKS[@]}"}; do
  case "$spec" in
    *=*) ;;
    *) refuse "--link takes NAME=DIR, a dependency directory installed outside the pack: $spec" ;;
  esac
  name=${spec%%=*}
  case "$name" in
    "" | /* | *..* | *\\* | *:* ) refuse "--link takes a plain relative name: $name" ;;
  esac
  # no segment of NAME may name .git, by any spelling Windows resolves to it (any case, trailing dots or spaces, the
  # 8.3 name GIT~1): the link would land in the checkout's own git directory (hooks a candidate's commit would run)
  # or be a nested repository's .git (LC4-4)
  rest=$name
  while [ -n "$rest" ]; do
    seg=${rest%%/*}
    case "$rest" in */*) rest=${rest#*/} ;; *) rest="" ;; esac
    while :; do case "$seg" in *. | *' ') seg=${seg%?} ;; *) break ;; esac; done
    case "$seg" in
      .[Gg][Ii][Tt] | [Gg][Ii][Tt]~1) refuse "--link $name: a link name may not name .git (in any case or spelling): it would sit in the checkout's git directory or be a repository's .git" ;;
    esac
  done
  dep=$(phys "${spec#*=}") || unproved refuse $? "--link $name: ${spec#*=}" "--link $name: no directory ${spec#*=}"
  guard_link "$name" "$dep" "$dep"
  for entry in "$dep"/* "$dep"/.[!.]* "$dep"/..?*; do  # an unmatched pattern stays literal and is no symlink
    [ -L "$entry" ] || continue
    real=$(resolve "$entry") || unproved refuse $? "--link $name: $entry, a symlink in $dep: the path it resolves to" "--link $name: $entry, a symlink in $dep, does not resolve"
    guard_link "$name" "$real" "$entry, a symlink in $dep resolving to $real,"
    REAL_NAMES+=("$name")
    REAL_SHOWN+=("$entry, a symlink in $dep resolving to $real")
    REAL_PATHS+=("$real")
  done
  LINK_NAMES+=("$name")
  LINK_DIRS+=("$dep")
done

# the target: every check runs before anything is made (LC3-3). EXIST is TARGET's nearest existing parent; the parents
# under it do not exist yet, so they hold no link and no repository, and they are made as spelled (no '.' or '..', so
# that the spelling is the path; each part spelled exactly, a trailing newline kept - LC6-1)
spell_dir PARENT "$DIR"
spell_base TNAME "$DIR"
case "$TNAME" in
  . | ..) refuse "target $DIR: its last segment is '$TNAME'; spell it without '.' or '..'" ;;
esac
EXIST=$PARENT
REST=""
while ! [ -d "$EXIST" ]; do
  if [ -e "$EXIST" ] || [ -L "$EXIST" ]; then refuse "target $DIR: $EXIST is not a directory"; fi
  spell_base part "$EXIST"
  case "$part" in
    . | ..) refuse "target $DIR: the part of its parent that does not exist yet holds a '$part' segment; spell it without '.' or '..'" ;;
  esac
  REST=$part${REST:+/$REST}
  spell_dir next "$EXIST"
  [ "$next" != "$EXIST" ] || refuse "target $DIR: no parent of it exists"
  EXIST=$next
done
EXIST_ABS=$(phys "$EXIST") || unproved refuse $? "target $DIR: its nearest existing parent $EXIST" "target $DIR: no directory $EXIST"
PARENT_ABS=${EXIST_ABS%/}${REST:+/$REST}
PARENT_ABS=${PARENT_ABS:-/}
TARGET_ABS=${PARENT_ABS%/}/$TNAME
# TARGET does not exist, so it is inside a directory exactly when its parent is that directory or lies under it
ancestors "$PARENT_ABS" || unproved refuse $? "target $TARGET_ABS: its parent's Windows spelling" "target $TARGET_ABS: its parent $LOCAL_ONLY"
if [ -n "$PACK_ABS" ]; then
  for a in "${ANC[@]}"; do
    if [ "$a" -ef "$PACK_ABS" ]; then refuse "target $TARGET_ABS is inside the pack $PACK_ABS"; fi
  done
  within "$PACK_ABS" "$TARGET_ABS" && refuse "the pack $PACK_ABS is inside the target $TARGET_ABS"
fi
for a in "${ANC[@]}"; do
  if is_repo "$a"; then
    refuse "target $TARGET_ABS is inside the git repository $a; a checkout inside a repository reaches that repository's history and files through '..' (Item 2)"
  fi
done

# native_guard ITEM...: the native layer (see the header). Each ITEM is four words, KIND NAME SHOWN PATH: KIND is S (the
# source repository), P (the pack), L (a --link DIR, NAME its name), E (the path the shell resolved a symlink at that
# DIR's top to: a link only the shell sees, such as an MSYS sys or shortcut symlink, may lead to a path only native
# programs resolve - LC5-1), T (the target, PATH its nearest existing parent), C (the checkout, once made) or K (the
# parent a --link's symlink is about to be made in, which must lie inside the checkout C and outside its .git -
# LC5-3); SHOWN is the path as the shell spells it, for the messages; PATH is its Windows spelling. Exit 0 when every
# check passes; 2 with the refusal on stdout; anything else is a failure of the check itself, and refused as well.
# native_guard --discard PATH removes the directory PATH (see discard below)
native_guard() {
  MSYS2_ARG_CONV_EXCL='*' "$NATIVE_PY" -I - "$@" <<'PY'
import os
import stat
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace", newline="\n")
AS = "as native programs resolve it"
LOCAL = "which is not a local path (a UNC path, or a volume with no drive letter), whose parents cannot be checked reliably (Item 2)"
THROUGH = "that repository's history and files through '..' (Item 2)"
UNPROVED = "is not proved to name the file it came from: Windows drops a trailing space or dot from the name, so the string names another file or none, and cannot be checked (LC6-1)"


class Refused(Exception):
    pass


def drive(path):
    """path is spelled with a drive letter, a colon and a separator (a slash or a backslash)"""
    return len(path) >= 3 and path[0].isascii() and path[0].isalpha() and path[1] == ":" and path[2] in "/\\"


def literal(path):
    """path's literal spelling (the "\\\\?\\" prefix: Windows reads the name as it is, as the shell does, and drops no
    trailing space or dot); None when path has no drive letter"""
    return "\\\\?\\" + path.replace("/", "\\") if drive(path) else None


def final(path, what):
    """path with every link of any kind followed, as native programs follow it (GetFinalPathNameByHandle), spelled
    with a drive letter; refused when it does not resolve or resolves to another form, and when what native programs
    reach by the string is not, by file identity (the volume and the file id), what its literal spelling names: then
    the string names another file than the shell's, and the shell's checks do not hold for it (LC6-1)"""
    try:
        real = os.path.realpath(path, strict=True)
    except (OSError, ValueError) as e:
        raise Refused(f"{what}, {AS}, does not resolve ({e})")
    if not drive(real) or real[2] != os.sep:
        raise Refused(f"{what} resolves, {AS}, to {real}, {LOCAL}")
    lit = literal(path)
    try:
        proved = lit is not None and os.path.samestat(os.stat(lit), os.stat(real))
    except (OSError, ValueError):
        proved = False
    if not proved:
        raise Refused(f"{what}, {AS} ({real}), {UNPROVED}")
    return real


def parents(real):
    """real and every directory above it, nearest first: those '..' reaches from a final path"""
    out = [real]
    while os.path.dirname(real) != real:
        real = os.path.dirname(real)
        out.append(real)
    return out


REPOS = {}


def has(d, name):
    """d holds an entry name of any type (a dangling link too); one that cannot be read counts as held"""
    try:
        os.lstat(os.path.join(d, name))
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        return True
    return True


def is_repo(d):
    """d may be a git repository, by the rule of is_repo in the shell layer (wider than git's own test): any entry
    named .git, HEAD, commondir or gitdir, or both an objects and a refs entry"""
    if d not in REPOS:
        REPOS[d] = any(has(d, n) for n in (".git", "HEAD", "commondir", "gitdir")) or (has(d, "objects") and has(d, "refs"))
    return REPOS[d]


def same(a, b):
    if os.path.normcase(a) == os.path.normcase(b):
        return True
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def is_link(entry):
    """a symlink, a junction or any other reparse point; an entry that cannot be read counts as one"""
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return True
    return entry.is_symlink() or bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def run(items):
    if os.name != "nt":
        raise Refused("no native path resolver: this Python is not a Windows one")
    guards = [(kind, shown, final(path, ("the source repository " if kind == "S" else "the pack ") + shown))
              for kind, name, shown, path in items if kind in ("S", "P")]

    def check(prefix, what, real):
        for kind, shown, g in guards:
            if any(same(a, g) for a in parents(real)) or any(same(a, real) for a in parents(g)):
                raise Refused(f"{prefix}{what}, {AS} ({real}), shares a path with {shown}, which holds the accepted fix (Item 2)")
        for a in parents(real):
            if is_repo(a):
                raise Refused(f"{prefix}{what}, {AS} ({real}), is inside the git repository {a}; a dependency tree inside a repository lets the checkout reach {THROUGH}")

    made = None
    for kind, name, shown, path in items:
        if kind == "L":
            prefix = f"--link {name}: "
            real = final(path, prefix + shown)
            check(prefix, shown, real)
            with os.scandir(real) as it:
                entries = sorted(it, key=lambda e: e.name)
            for e in entries:
                if is_link(e):
                    what = f"{e.path}, a link at the top of {shown}"
                    check(prefix, what, final(e.path, prefix + what))
        elif kind == "E":
            prefix = f"--link {name}: "
            check(prefix, shown, final(path, prefix + shown))
        elif kind == "C":
            made = final(path, f"the checkout {shown}")
        elif kind == "K":
            prefix = f"--link {name}: "
            real = final(path, prefix + shown)
            if any(same(a, os.path.join(made, ".git")) for a in parents(real)):
                raise Refused(f"{prefix}{shown}, {AS} ({real}), is inside the checkout's git directory; a link there would sit among its hooks and objects")
            if not any(same(a, made) for a in parents(real)):
                raise Refused(f"{prefix}{shown}, {AS} ({real}), is not inside the checkout {made}; the link would be made in a host directory")
        elif kind == "T":
            real = final(path, f"target {shown}: its nearest existing parent")
            for k, gshown, g in guards:
                if k == "P" and any(same(a, g) for a in parents(real)):
                    raise Refused(f"target {shown}, {AS} (its parent lies in {real}), is inside the pack {gshown}")
            for a in parents(real):
                if is_repo(a):
                    raise Refused(f"target {shown}, {AS} (its parent lies in {real}), is inside the git repository {a}; a checkout inside a repository reaches {THROUGH}")


def discard(d):
    """remove the directory d (a literal spelling, so that a trailing space or dot is kept: the directory the shell
    made, never a host directory Windows reads the string as) and everything under it, never through a link: a
    symlink, junction or other reparse point (or an entry that cannot be read) is removed as an entry, never entered"""
    with os.scandir(d) as it:
        entries = list(it)
    for e in entries:
        if is_link(e):
            try:
                os.unlink(e.path)
            except OSError:
                os.rmdir(e.path)
        elif e.is_dir(follow_symlinks=False):
            discard(e.path)
        else:
            try:
                os.unlink(e.path)
            except PermissionError:
                os.chmod(e.path, stat.S_IWRITE)
                os.unlink(e.path)
    os.rmdir(d)


args = sys.argv[1:]
if args[:1] == ["--discard"]:
    if literal(args[1]) is None:
        sys.exit(1)
    discard(literal(args[1]))
    sys.exit(0)
try:
    run([args[i:i + 4] for i in range(0, len(args), 4)])
except Refused as r:
    sys.stdout.write(str(r))
    sys.exit(2)
PY
}
# add_native HOW KIND NAME SHOWN P: add one item for native_guard to NARGS, with the Windows spelling of the shell's
# physical path P, proved to name P (the native layer then proves that native programs read it as the same file);
# refused with HOW (refuse, or refuse_made) when it has none or it names another file
add_native() {
  local w what
  case "$2" in
    S) what="the source repository $4" ;;
    P) what="the pack $4" ;;
    T) what="target $4: its nearest existing parent $5" ;;
    C) what="the checkout $4" ;;
    *) what="--link $3: $4" ;;
  esac
  w=$(cygpath -m -- "$5") || "$1" "$what: no Windows spelling"
  [ "$w" -ef "$5" ] || "$1" "$what: its Windows spelling $w $UNPROVED"
  NARGS+=("$2" "$3" "$4" "$w")
}
# native_check HOW: run native_guard on NARGS; refused with HOW when it refuses or fails
native_check() {
  NOUT=$(native_guard "${NARGS[@]}") && NRC=0 || NRC=$?
  NOUT=${NOUT%$'\r'}
  case $NRC in
    0) ;;
    2) "$1" "$NOUT" ;;
    *) "$1" "the native path check failed (exit $NRC), so the paths cannot be checked as native programs resolve them${NOUT:+: $NOUT}" ;;
  esac
}
# GIT_SRC: the source repository as git is given it: on Windows its proved Windows spelling (the S item, always: git
# reads the source by that string), elsewhere its physical path
GIT_SRC=$SRC_ABS
if [ -n "$WINDOWS" ]; then
  NARGS=()
  add_native refuse S - "$SRC_ABS" "$SRC_ABS"
  GIT_SRC=${NARGS[3]}
  [ -z "$PACK_ABS" ] || add_native refuse P - "$PACK_ABS" "$PACK_ABS"
  for i in ${LINK_NAMES[@]+"${!LINK_NAMES[@]}"}; do add_native refuse L "${LINK_NAMES[$i]}" "${LINK_DIRS[$i]}" "${LINK_DIRS[$i]}"; done
  for i in ${REAL_NAMES[@]+"${!REAL_NAMES[@]}"}; do add_native refuse E "${REAL_NAMES[$i]}" "${REAL_SHOWN[$i]}" "${REAL_PATHS[$i]}"; done
  add_native refuse T - "$TARGET_ABS" "$EXIST_ABS"
  native_check refuse
fi

# the source lookup follows the path checks, so a UNC source is refused as one (git itself reports "dubious ownership")
TREE=$(git -C "$GIT_SRC" rev-parse --verify --quiet "$COMMIT^{tree}") || refuse "not a commit in $SRC: $COMMIT"
git check-ref-format --branch "$BRANCH" >/dev/null 2>&1 || refuse "not a branch name: $BRANCH"

# MADE: the first directory this run makes (TARGET, or the first of its parents that does not exist yet), which discard
# removes when a check that needs the checkout refuses
MADE=$TARGET_ABS
[ -z "$REST" ] || MADE=${EXIST_ABS%/}/${REST%%/*}
# discard: remove MADE, never through a link. Git Bash's rm -rf walks into a symlink to a volume-GUID path, which it
# takes for a plain directory, and deletes the files where it leads (a base tree may track such a symlink), so on
# Windows the native layer's Python removes the tree, each link as an entry; elsewhere rm -rf, which follows no symlink
discard() {
  local w
  if [ -n "$WINDOWS" ]; then
    # the Windows spelling of MADE, proved to name it; the native layer removes it by its literal spelling, so a
    # trailing space or dot is kept (Windows reads 'co ' as a host directory 'co' - LC6-1)
    { w=$(cygpath -m -- "$MADE") && [ "$w" -ef "$MADE" ] && native_guard --discard "$w"; } || { echo "historyless-checkout: could not remove $MADE" >&2; exit 1; }
  else
    rm -rf -- "$MADE"
  fi
}
# refuse_made REASON: refuse after the checkout was made: remove it, then refuse (nothing is left)
refuse_made() {
  discard
  refuse "$@"
}
mkdir -p -- "$PARENT_ABS"
# TARGET is made by the shell, as spelled, and git is given a string proved to name it (GIT_TARGET): git init once made
# it at its own reading of the string, and on Windows that drops a trailing space or dot, so a target 'co ' beside a
# host directory 'co' was made in 'co', and reset --hard wrote the base tree there (LC6-1)
mkdir -- "$TARGET_ABS"
GIT_TARGET=$TARGET_ABS
if [ -n "$WINDOWS" ]; then
  NARGS=()
  add_native refuse_made C - "$TARGET_ABS" "$TARGET_ABS"
  native_check refuse_made
  GIT_TARGET=${NARGS[3]}
fi
# no template (--template=): GIT_TEMPLATE_DIR or init.templateDir could copy objects/info/alternates, naming another
# repository's objects, or hooks into the new .git (LC3-2)
git init -q --template= -b "$BRANCH" "$GIT_TARGET" || refuse_made "git init failed in $TARGET_ABS (Git for Windows refuses a path with a segment that ends in a space or dot)"
# the base tree and every tree and blob under it, and nothing else: no commit of the source is copied
OBJECTS=$({ echo "$TREE"; git -C "$GIT_SRC" ls-tree -r -t "$TREE" | awk '$2 != "commit" { print $3 }'; } | LC_ALL=C sort -u)
printf '%s\n' "$OBJECTS" | git -C "$GIT_SRC" pack-objects --stdout -q | git -C "$GIT_TARGET" unpack-objects -q
BASE=$(git -C "$GIT_TARGET" -c user.name=calibration -c user.email=calibration@localhost \
  commit-tree --no-gpg-sign -m "calibration base: a tree with no history" "$TREE")
git -C "$GIT_TARGET" update-ref "refs/heads/$BRANCH" "$BASE"
git -C "$GIT_TARGET" reset -q --hard "$BASE"
# each link lands inside the checkout and outside its .git (LC5-3): NAME's spelling is checked above, but the base tree
# may track a symlink (with core.symlinks=true it is checked out as one, g -> .git say), and an earlier --link is a
# symlink to a host directory, so NAME's parent is checked where it really is, in both layers, before each link is
# made; and NAME must not exist yet, since ln -s puts the link inside an existing directory, or where a symlink to one
# leads
for i in ${LINK_NAMES[@]+"${!LINK_NAMES[@]}"}; do
  name=${LINK_NAMES[$i]}
  at=$TARGET_ABS/$name
  if [ -e "$at" ] || [ -L "$at" ]; then
    refuse_made "--link $name: the checkout already holds $name (from the base tree or an earlier --link); the link would be made inside it or where it leads"
  fi
  spell_dir up "$at"
  real=$(physd "$up") || unproved refuse_made $? "--link $name: its parent $up" "--link $name: its parent $up is no directory in the checkout"
  ancestors "$real" || unproved refuse_made $? "--link $name: its parent $real: its Windows spelling" "--link $name: its parent $real $LOCAL_ONLY"
  inside=""
  for a in "${ANC[@]}"; do
    if [ "$a" -ef "$TARGET_ABS/.git" ]; then
      refuse_made "--link $name: its parent $real is inside the checkout's git directory; a link there would sit among its hooks and objects"
    fi
    if [ "$a" -ef "$TARGET_ABS" ]; then inside=1; fi
  done
  [ -n "$inside" ] || refuse_made "--link $name: its parent $real is not inside the checkout $TARGET_ABS; the link would be made in a host directory"
  if [ -n "$WINDOWS" ]; then
    NARGS=()
    add_native refuse_made C - "$TARGET_ABS" "$TARGET_ABS"
    add_native refuse_made K "$name" "$real" "$real"
    native_check refuse_made
  fi
  ln -s "${LINK_DIRS[$i]}" "$at"
  mkdir -p -- "$TARGET_ABS/.git/info"
  printf '/%s\n' "${LINK_NAMES[$i]}" >> "$TARGET_ABS/.git/info/exclude"
done

# proof: exactly one commit reachable from any ref, its tree is the base tree, and the checkout's git can read no object
# but that commit and the objects of that tree (--batch-all-objects reads alternates too)
[ "$(git -C "$GIT_TARGET" rev-list --all --count)" = 1 ] || { echo "historyless-checkout: more than one commit in $TARGET_ABS" >&2; exit 1; }
[ "$(git -C "$GIT_TARGET" rev-parse HEAD^{tree})" = "$TREE" ] || { echo "historyless-checkout: tree differs from $COMMIT" >&2; exit 1; }
[ "$(git -C "$GIT_TARGET" cat-file --batch-all-objects --batch-check='%(objectname)' | LC_ALL=C sort -u)" = "$(printf '%s\n%s\n' "$OBJECTS" "$BASE" | LC_ALL=C sort -u)" ] \
  || { echo "historyless-checkout: $TARGET_ABS can read objects other than the base commit and its tree (objects/info/alternates?)" >&2; exit 1; }
echo "ok $TARGET_ABS: one commit, the tree of $COMMIT, branch $BRANCH"
