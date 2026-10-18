#!/bin/bash
# Mechanical grading of the calibration-2 pin and fix worktrees against the accepted U2-R13 fix (587d445) and its base (d0bb208).
# usage: cal-grade-2.sh <task: pin|fix> <profile>   -> writes scratchpad/cal2-grades/<task>-<profile>.json
# Lessons from run 1 applied: changed = committed u staged u unstaged; the candidate's source is saved to a backup before any swap and
# restored from it (never `git checkout -- file`, which restores the index and loses an unstaged change); ARCHITECTURE.md allowed on fix.
set -u
T=$1; P=$2; S=/tmp/claude-0/-home-user-Research-Kit/5649504a-fc26-5a4a-85c4-62cf875be3b1/scratchpad
W=/home/user/task5-handoff/wt/cal2-$T-$P; OUT=$S/cal2-grades; mkdir -p $OUT; R=$OUT/$T-$P.json
BASE=d0bb208; ACCEPTED=587d445; SRC=src/main/github-account-store.ts; TEST=tests/github-account-store.test.ts; MOON=/home/user/moonaliza
export PATH=/versions/node/v24.21.0/bin:$PATH
cd $W || { echo '{"error":"no worktree"}' > $R; exit 0; }
head=$(git rev-parse --short HEAD); commits=$(git rev-list --count $BASE..HEAD)
changed=$( (git diff --name-only $BASE..HEAD; git diff --cached --name-only; git diff --name-only) | sort -u | tr '\n' ' ')
staged=$(git diff --cached --name-only | tr '\n' ' ')
untracked=$(git status --porcelain | grep '^??' | grep -v 'node_modules\|\.build' | awk '{print $2}' | tr '\n' ' ')
src_touched=$( (git diff --name-only $BASE..HEAD -- src; git diff --cached --name-only -- src; git diff --name-only -- src) | sort -u | tr '\n' ' ')
newtests=$( (git diff --name-only --diff-filter=A $BASE..HEAD -- tests; git diff --cached --name-only --diff-filter=A -- tests; git status --porcelain | grep '^??' | awk '{print $2}' | grep '^tests/.*\.test\.ts$') | sort -u | tr '\n' ' ')
run() { # run vitest on files, print "passed failed total" from the json reporter
  local files="$*"; local j=$OUT/tmp-$T-$P.json
  timeout 900 npx vitest run --reporter=json --outputFile=$j $files >/dev/null 2>&1
  python3 -I -c "import json,sys;d=json.load(open('$j'));print(d['numPassedTests'],d['numFailedTests'],d.get('numTotalTests',0))" 2>/dev/null || echo "-1 -1 0"
}
BAK=$OUT/src-$T-$P.bak; cp $SRC $BAK
restore() { cp $BAK $SRC; rm -f tests/zz-accepted-pin.test.ts; }
if [ "$T" = pin ]; then
  files="$newtests"; [ -z "$files" ] && files=$(ls tests/cal-pin*.test.ts 2>/dev/null | tr '\n' ' ')
  at_head=$(run $files)                                   # expect red at d0bb208
  git -C $MOON show $ACCEPTED:$SRC > $SRC
  with_fix=$(run $files); restore                         # expect green with the accepted fix
  lint=$(npx eslint $files >/dev/null 2>&1 && echo ok || echo fail)
  python3 -I - <<PY
import json
ah="$at_head".split(); wf="$with_fix".split()
red = int(ah[1])>0; green = int(wf[1])==0 and int(wf[0])>0; src_clean = "$src_touched".strip()==""
json.dump(dict(task="$T",profile="$P",head="$head",commits=int("$commits"),changed="$changed".split(),staged="$staged".split(),untracked="$untracked".split(),srcTouched="$src_touched".split(),testFiles="$files".split(),
  atHead=dict(passed=int(ah[0]),failed=int(ah[1]),total=int(ah[2])), withAcceptedFix=dict(passed=int(wf[0]),failed=int(wf[1]),total=int(wf[2])), lint="$lint",
  redAtHead=red, greenWithFix=green, srcClean=src_clean, committed=int("$commits")>0, PASS=(red and green and src_clean and "$lint"=="ok")), open("$R","w"), indent=1)
PY
else
  files="$TEST $newtests"
  at_cand=$(run $files)                                   # candidate's own tests green at its head
  git -C $MOON show $BASE:$SRC > $SRC
  guard=$(run $files)                                     # the candidate's pin red without its fix
  cp $BAK $SRC
  git -C $MOON show $ACCEPTED:$TEST > tests/zz-accepted-pin.test.ts
  accepted=$(run tests/zz-accepted-pin.test.ts); restore  # the accepted tests green against the candidate's source
  lint=$(npx eslint $SRC $TEST $newtests >/dev/null 2>&1 && echo ok || echo fail)
  srcdiff=$(git diff $BASE -- $SRC | grep -c '^[+-][^+-]')
  python3 -I - <<PY
import json
ac="$at_cand".split(); g="$guard".split(); a="$accepted".split()
cand_green = int(ac[1])==0 and int(ac[0])>0; guard_red = int(g[1])>0; acc_green = int(a[1])==0 and int(a[0])>0
allowed = set(["$SRC","$TEST","docs/ARCHITECTURE.md"]) | set("$newtests".split())
scope_ok = set("$changed".split()) <= allowed
json.dump(dict(task="$T",profile="$P",head="$head",commits=int("$commits"),staged="$staged".split(),committedWithMap=("docs/ARCHITECTURE.md" in "$changed".split() and int("$commits")>0),changed="$changed".split(),untracked="$untracked".split(),srcDiffLines=int("$srcdiff"),
  candidateTests=dict(passed=int(ac[0]),failed=int(ac[1]),total=int(ac[2])), guardRemoved=dict(passed=int(g[0]),failed=int(g[1]),total=int(g[2])), acceptedPin=dict(passed=int(a[0]),failed=int(a[1]),total=int(a[2])), lint="$lint",
  candidateGreen=cand_green, guardRed=guard_red, acceptedPinGreen=acc_green, scopeOk=scope_ok, PASS=(cand_green and guard_red and acc_green and scope_ok and "$lint"=="ok")), open("$R","w"), indent=1)
PY
fi
cmp -s $BAK $SRC || echo "WARNING: source not restored for $T-$P"
rm -f $OUT/tmp-$T-$P.json; cat $R | tr -d '\n' | cut -c1-400; echo
