#!/usr/bin/env bash
# List every repo that has the agent reviewer:   ./deploy/list-repos.sh
# It checks each repo directly, because GitHub's code search misses some.
set -euo pipefail

OWNER=aachtenberg
WF=.github/workflows/agent-review.yml

printf '%-28s %-8s %-6s %s\n' REPO VISIBLE REF RUNNER
gh repo list "$OWNER" -L 500 --no-archived --source --json name,visibility \
  --jq '.[] | .name + " " + .visibility' | sort | while read -r name vis; do
  f=$(gh api "repos/$OWNER/$name/contents/$WF" --jq .content 2>/dev/null | base64 -d 2>/dev/null) || continue
  [ -n "$f" ] || continue
  ref=$(sed -n 's/.*agent-review\/.github\/workflows\/review.yml@\([^ ]*\).*/\1/p' <<<"$f" | head -1)
  runner=$(sed -n 's/^ *runner: *//p' <<<"$f" | head -1)
  printf '%-28s %-8s %-6s %s\n' "$name" "$vis" "${ref:-local}" "${runner:-ubuntu-latest}"
done
