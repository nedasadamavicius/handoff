#!/bin/sh
# Enforces the project rules: conventional commits, plain ASCII, no AI attribution.
# No dependencies beyond git and POSIX sh, so it runs the same locally and in CI.
#
# Usage:
#   check-rules.sh msg <file>           check a commit message (or PR title) file
#   check-rules.sh text <file>          check free text (e.g. a PR description)
#   check-rules.sh staged               check lines added in staged changes
#   check-rules.sh range <base> <head>  check commits and added lines in base..head
#
# Paths that may contain non-ASCII (e.g. translations) go in .asciiignore, one glob per line.

set -eu
export LC_ALL=C

NONASCII=$(printf '[\200-\377]')
TYPES='feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert'
SUBJECT_RE="^($TYPES)(\([^()]+\))?!?: [^ ].*"
GIT_GENERATED_RE='^(Merge |Revert "|fixup! |squash! |amend! )'
AI='(claude|anthropic|openai|chatgpt|codex|copilot|gemini|grok|xai|x\.ai|devin|aider)'
ATTRIB_RE="(co-authored-by|signed-off-by):.*$AI|(generated|written|created) (with|by|using) .*$AI|(generated|written|created) (with|by|using) (an? )?ai([^a-z]|$)|noreply@anthropic\.com"

status=0
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

err() { printf 'rules: %s\n' "$*" >&2; status=1; }

check_text() { # <file> <label>
  if grep -Eiq "$ATTRIB_RE" "$1"; then
    err "$2: AI attribution is not allowed:"
    grep -Ein "$ATTRIB_RE" "$1" | sed 's/^/    /' >&2
  fi
  if grep -q "$NONASCII" "$1"; then
    err "$2: only plain ASCII is allowed:"
    grep -n "$NONASCII" "$1" | sed 's/^/    /' >&2
  fi
}

check_msg() { # <file> <label>
  grep -v '^#' "$1" > "$tmp" || true
  subject=$(grep -m 1 . "$tmp" || true)
  if ! printf '%s\n' "$subject" | grep -Eq "$SUBJECT_RE" &&
     ! printf '%s\n' "$subject" | grep -Eq "$GIT_GENERATED_RE"; then
    err "$2: not a conventional commit: \"$subject\""
    err "    expected <type>(<optional scope>): <description>, type one of: $(echo "$TYPES" | tr '|' ' ')"
  fi
  check_text "$tmp" "$2"
}

check_diff() { # <git diff args...>
  set -f
  excludes=""
  if [ -f .asciiignore ]; then
    while IFS= read -r p; do
      case "$p" in ''|'#'*) ;; *) excludes="$excludes :(exclude,glob)$p" ;; esac
    done < .asciiignore
  fi
  # shellcheck disable=SC2086
  git diff "$@" -U0 --no-color --no-ext-diff --diff-filter=ACMR -- . $excludes |
    awk -v pat="$NONASCII" '
      /^\+\+\+ /   { f = substr($0, 7); next }
      /^@@/        { split($3, a, ","); n = substr(a[1], 2) + 0; next }
      /^\+/        { if ($0 ~ pat) print "    " f ":" n ": " substr($0, 2); n++ }
    ' > "$tmp"
  set +f
  if [ -s "$tmp" ]; then
    err "added lines must be plain ASCII (list exceptions in .asciiignore):"
    cat "$tmp" >&2
  fi
}

case "${1:-}" in
  msg)    check_msg "$2" "commit message" ;;
  text)   check_text "$2" "text" ;;
  staged) check_diff --cached ;;
  range)
    base=$2 head=$3
    for c in $(git rev-list --no-merges "$base..$head"); do
      git log -1 --format=%B "$c" > "$tmp.msg"
      check_msg "$tmp.msg" "commit $(git rev-parse --short "$c")"
      rm -f "$tmp.msg"
    done
    check_diff "$base...$head"
    ;;
  *) echo "usage: check-rules.sh msg <file> | text <file> | staged | range <base> <head>" >&2; exit 2 ;;
esac

if [ "$status" -ne 0 ]; then
  echo "rules: see AGENTS.md (Project rules). Do not bypass with --no-verify; CI runs the same checks." >&2
fi
exit "$status"
