#!/bin/bash
# Mechanical grading of the calibration pin and fix worktrees against the accepted U5-R16 fix (4151a25) and its base (d87f796).
# usage: cal-grade.sh <task: pin|fix> <profile>   -> writes scratchpad/cal-grades/<task>-<profile>.json
set -u
T=$1; P=$2; S=/tmp/claude-0/-home-user-Research-Kit/5649504a-fc26-5a4a-85c4-62cf875be3b1/scratchpad
W=/home/user/task5-handoff/wt/cal-$T-$P; OUT=$S/cal-grades; mkdir -p $OUT; R=$OUT/$T-$P.json
export PATH=/versions/node/v24.21.0/bin:$PATH
cd $W || { echo '{"error":"no worktree"}' > $R; exit 0; }
head=$(git rev-parse --short HEAD); commits=$(git rev-list --count d87f796..HEAD)
changed=$(git diff --name-only d87f796..HEAD | tr '\n' ' '); untracked=$(git status --porcelain | grep '^??' | grep -v 'node_modules\|\.build' | awk '{print $2}' | tr '\n' ' ')
src_touched=$(git diff --name-only d87f796..HEAD -- src | tr '\n' ' ')
newtests=$(git diff --name-only --diff-filter=A d87f796..HEAD -- tests | tr '\n' ' ')
run() { # run vitest on files, print "passed failed" (numbers) from the json reporter
  local files="$*"; local j=$S/cal-grades/tmp-$T-$P.json
  timeout 600 npx vitest run --reporter=json --outputFile=$j $files >/dev/null 2>&1
  python3 -I -c "import json,sys;d=json.load(open('$j'));print(d['numPassedTests'],d['numFailedTests'],d.get('numTotalTests',0))" 2>/dev/null || echo "-1 -1 0"
}
restore() { git checkout -q -- src/main/github-signin.ts 2>/dev/null; rm -f tests/zz-accepted-pin.test.ts; }
if [ "$T" = pin ]; then
  files="$newtests"; [ -z "$files" ] && files=$(ls tests/cal-pin*.test.ts 2>/dev/null | tr '\n' ' ')
  at_head=$(run $files)                                   # expect red at d87f796
  git -C /home/user/moonaliza show 4151a25:src/main/github-signin.ts > src/main/github-signin.ts
  with_fix=$(run $files); restore                         # expect green with the accepted fix
  lint=$(npx eslint $files >/dev/null 2>&1 && echo ok || echo fail)
  python3 -I - <<PY
import json
ah="$at_head".split(); wf="$with_fix".split()
red = int(ah[1])>0; green = int(wf[1])==0 and int(wf[0])>0
json.dump(dict(task="$T",profile="$P",head="$head",commits=int("$commits"),changed="$changed".split(),untracked="$untracked".split(),srcTouched="$src_touched".split(),testFiles="$files".split(),
  atHead=dict(passed=int(ah[0]),failed=int(ah[1])), withAcceptedFix=dict(passed=int(wf[0]),failed=int(wf[1])), lint="$lint",
  redAtHead=red, greenWithFix=green, srcClean=("$src_touched".strip()==""), PASS=(red and green and "$src_touched".strip()=="" and "$lint"=="ok")), open("$R","w"), indent=1)
PY
else
  files="tests/github-signin-refresh.test.ts tests/github-signin.test.ts $newtests"
  at_cand=$(run $files)                                   # candidate's own tests green at its HEAD
  git -C /home/user/moonaliza show d87f796:src/main/github-signin.ts > src/main/github-signin.ts
  guard=$(run tests/github-signin-refresh.test.ts $newtests)   # the candidate's pin red without its fix
  git checkout -q -- src/main/github-signin.ts
  git -C /home/user/moonaliza show 4151a25:tests/github-signin-refresh.test.ts > tests/zz-accepted-pin.test.ts
  accepted=$(run tests/zz-accepted-pin.test.ts); restore  # the accepted pin green against the candidate's source
  lint=$(npx eslint src/main/github-signin.ts tests/github-signin-refresh.test.ts $newtests >/dev/null 2>&1 && echo ok || echo fail)
  srcdiff=$(git diff d87f796..HEAD -- src/main/github-signin.ts | grep -c '^[+-][^+-]')
  python3 -I - <<PY
import json
ac="$at_cand".split(); g="$guard".split(); a="$accepted".split()
cand_green = int(ac[1])==0 and int(ac[0])>0; guard_red = int(g[1])>0; acc_green = int(a[1])==0 and int(a[0])>0
allowed = set(["src/main/github-signin.ts","tests/github-signin-refresh.test.ts"]) | set("$newtests".split())
scope_ok = set("$changed".split()) <= allowed
json.dump(dict(task="$T",profile="$P",head="$head",commits=int("$commits"),changed="$changed".split(),untracked="$untracked".split(),srcDiffLines=int("$srcdiff"),
  candidateTests=dict(passed=int(ac[0]),failed=int(ac[1])), guardRemoved=dict(passed=int(g[0]),failed=int(g[1])), acceptedPin=dict(passed=int(a[0]),failed=int(a[1])), lint="$lint",
  candidateGreen=cand_green, guardRed=guard_red, acceptedPinGreen=acc_green, scopeOk=scope_ok, PASS=(cand_green and guard_red and acc_green and scope_ok and "$lint"=="ok")), open("$R","w"), indent=1)
PY
fi
rm -f $S/cal-grades/tmp-$T-$P.json; cat $R | tr -d '\n' | cut -c1-400; echo
