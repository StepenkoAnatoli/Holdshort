#!/bin/bash
# Mechanical grading of the calibration-3 pin and fix checkouts against the accepted U1-R11 fix (348aa2d) and its base (e68583c).
# Candidates work in HISTORY-LESS checkouts (one root commit), so the base for diffs is each checkout's root commit, and the
# accepted/base file contents come from the source repository. usage: cal-grade-3.sh <pin|fix> <profile>
set -u
T=$1; P=$2; S=/tmp/claude-0/-home-user-Research-Kit/5649504a-fc26-5a4a-85c4-62cf875be3b1/scratchpad
W=/home/user/task5-handoff/wt/cal3-$T-$P; OUT=$S/cal3-grades; mkdir -p $OUT; R=$OUT/$T-$P.json
BASE=e68583c; ACCEPTED=348aa2d; SRC=src/main/github-oauth.ts; TEST=tests/github-oauth.test.ts; MOON=/home/user/moonaliza
export PATH=/versions/node/v24.21.0/bin:$PATH
cd $W || { echo '{"error":"no checkout"}' > $R; exit 0; }
ROOT=$(git rev-list --max-parents=0 HEAD); head=$(git rev-parse --short HEAD); commits=$(git rev-list --count $ROOT..HEAD)
changed=$( (git diff --name-only $ROOT..HEAD; git diff --cached --name-only; git diff --name-only) | sort -u | tr '\n' ' ')
staged=$(git diff --cached --name-only | tr '\n' ' ')
untracked=$(git status --porcelain | grep '^??' | grep -v 'node_modules\|\.build' | awk '{print $2}' | tr '\n' ' ')
src_touched=$( (git diff --name-only $ROOT..HEAD -- src; git diff --cached --name-only -- src; git diff --name-only -- src) | sort -u | tr '\n' ' ')
newtests=$( (git diff --name-only --diff-filter=A $ROOT..HEAD -- tests; git diff --cached --name-only --diff-filter=A -- tests; git status --porcelain | grep '^??' | awk '{print $2}' | grep '^tests/.*\.test\.ts$') | sort -u | tr '\n' ' ')
run() { local files="$*"; local j=$OUT/tmp-$T-$P.json
  timeout 900 npx vitest run --reporter=json --outputFile=$j $files >/dev/null 2>&1
  python3 -I -c "import json,sys;d=json.load(open('$j'));print(d['numPassedTests'],d['numFailedTests'],d.get('numTotalTests',0))" 2>/dev/null || echo "-1 -1 0"; }
BAK=$OUT/src-$T-$P.bak; cp $SRC $BAK
restore() { cp $BAK $SRC; rm -f tests/zz-accepted-pin.test.ts; }
if [ "$T" = pin ]; then
  files="$newtests"; [ -z "$files" ] && files=$(ls tests/cal-pin*.test.ts 2>/dev/null | tr '\n' ' ')
  at_head=$(run $files); git -C $MOON show $ACCEPTED:$SRC > $SRC; with_fix=$(run $files); restore
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
  files="$TEST $newtests"; at_cand=$(run $files)
  git -C $MOON show $BASE:$SRC > $SRC; guard=$(run $files); cp $BAK $SRC
  git -C $MOON show $ACCEPTED:$TEST > tests/zz-accepted-pin.test.ts; accepted=$(run tests/zz-accepted-pin.test.ts); restore
  lint=$(npx eslint $SRC $TEST $newtests >/dev/null 2>&1 && echo ok || echo fail)
  srcdiff=$(git diff $ROOT -- $SRC | grep -c '^[+-][^+-]')
  python3 -I - <<PY
import json
ac="$at_cand".split(); g="$guard".split(); a="$accepted".split()
cand_green = int(ac[1])==0 and int(ac[0])>0; guard_red = int(g[1])>0; acc_green = int(a[1])==0 and int(a[0])>0
allowed = set(["$SRC","$TEST","docs/ARCHITECTURE.md"]) | set("$newtests".split()); scope_ok = set("$changed".split()) <= allowed
json.dump(dict(task="$T",profile="$P",head="$head",commits=int("$commits"),staged="$staged".split(),committedWithMap=("docs/ARCHITECTURE.md" in "$changed".split() and int("$commits")>0),changed="$changed".split(),untracked="$untracked".split(),srcDiffLines=int("$srcdiff"),
  candidateTests=dict(passed=int(ac[0]),failed=int(ac[1]),total=int(ac[2])), guardRemoved=dict(passed=int(g[0]),failed=int(g[1]),total=int(g[2])), acceptedPin=dict(passed=int(a[0]),failed=int(a[1]),total=int(a[2])), lint="$lint",
  candidateGreen=cand_green, guardRed=guard_red, acceptedPinGreen=acc_green, scopeOk=scope_ok, PASS=(cand_green and guard_red and acc_green and scope_ok and "$lint"=="ok")), open("$R","w"), indent=1)
PY
fi
cmp -s $BAK $SRC || echo "WARNING: source not restored for $T-$P"; rm -f $OUT/tmp-$T-$P.json; cat $R | tr -d '\n' | cut -c1-300; echo
