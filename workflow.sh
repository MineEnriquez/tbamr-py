#!/usr/bin/env bash
# Branch workflow: feature/<name> -> release -> main.
#   ./workflow.sh start <name>     new feature/<name> branch off release
#   ./workflow.sh review <name>    files and raw diff of feature/<name> against release
#   ./workflow.sh accept <name>    run tests, merge feature/<name> into release
#   ./workflow.sh ship             run tests on release, merge release into main
# Nothing is pushed; run `git push origin release main` yourself when ready.
set -euo pipefail
cd "$(dirname "$0")"

die() { echo "error: $*" >&2; exit 1; }

need_clean() {
  [ -z "$(git status --porcelain)" ] || die "working tree has uncommitted changes; commit or discard them first"
}

need_branch() {
  git show-ref --verify --quiet "refs/heads/$1" || die "branch $1 does not exist"
}

run_tests() {
  local py=python3
  [ -x backend/.venv/bin/python ] && py="$PWD/backend/.venv/bin/python"
  echo "Running tests on $(git branch --show-current)..."
  (cd backend && "$py" -m pytest -q)
}

# Merge $1 into $2 with a merge commit, after the tests pass on $1.
merge_into() {
  local from=$1 into=$2 back
  back=$(git branch --show-current)
  need_clean
  git switch -q "$from"
  run_tests || { git switch -q "$back"; die "tests failed on $from; nothing merged"; }
  git switch -q "$into"
  git merge --no-ff "$from" -m "Merge $from into $into" || { git switch -q "$back"; die "merge conflict; resolve it on $into"; }
  git switch -q "$back"
  echo "Merged $from into $into."
}

cmd=${1:-}
case "$cmd" in
  start)
    name=${2:?usage: ./workflow.sh start <name>}
    need_branch release
    need_clean
    git switch -c "feature/$name" release
    ;;
  review)
    name=${2:?usage: ./workflow.sh review <name>}
    need_branch "feature/$name"
    git log --oneline "release..feature/$name"
    echo
    git diff --stat "release...feature/$name"
    echo
    git diff "release...feature/$name"
    ;;
  accept)
    name=${2:?usage: ./workflow.sh accept <name>}
    need_branch "feature/$name"
    need_branch release
    merge_into "feature/$name" release
    ;;
  ship)
    need_branch release
    echo "Going to main:"
    git log --oneline main..release
    read -r -p "Merge release into main? [y/N] " ok
    [ "$ok" = y ] || [ "$ok" = Y ] || die "cancelled"
    merge_into release main
    ;;
  *)
    sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
