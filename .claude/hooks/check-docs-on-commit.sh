#!/usr/bin/env bash
# PreToolUse hook (Bash / git commit): before a commit goes through, check
# whether code changed without the project documentation being touched.
#
# "Code" = Python sources outside tests/.  "Docs" = README.md, USER_GUIDE.md,
# USER_GUIDE_GER.md (the only docs we care about keeping in sync).
#
# When code is committed but none of the docs are, the hook emits a non-blocking
# reminder (systemMessage) to verify the docs — the commit always proceeds.
# Otherwise it stays silent.

input=$(cat)

# Self-guard: only act on actual `git commit` commands (in case the settings
# "if" filter is ever absent, this prevents gating unrelated Bash calls).
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)
case "$cmd" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

# Files the commit will include: staged files, or — for `git commit -a` with
# nothing pre-staged — all modified tracked files.
files=$(git diff --cached --name-only 2>/dev/null)
[ -z "$files" ] && files=$(git diff HEAD --name-only 2>/dev/null)

code=$(printf '%s\n' "$files" | grep -E '\.py$' | grep -vE '^tests/')
docs=$(printf '%s\n' "$files" | grep -E '^(README|USER_GUIDE|USER_GUIDE_GER)\.md$')

if [ -n "$code" ] && [ -z "$docs" ]; then
  list=$(printf '%s' "$code" | tr '\n' ' ')
  reason="Code changed (${list}) without updating the docs. Check whether README.md / USER_GUIDE.md / USER_GUIDE_GER.md need updating."
  jq -cn --arg m "⚠ Docs check: ${reason}" '{systemMessage:$m}'
fi

exit 0
