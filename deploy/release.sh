#!/usr/bin/env bash
# Roll out agent-review's main to every repo:   ./deploy/release.sh
# Undo (go back to an earlier version):         ./deploy/release.sh <commit>
# See what it would do first:                   add --dry-run
#
# Every repo uses agent-review at the v1 tag, so a release just moves v1.
# Before moving it, this shows what's changing and checks that the review
# image runs on ubuntu-itx-01 (its CPU has no AVX2), then asks you to confirm.
# Every repo picks up the change on its next review.
set -euo pipefail

RUNNER_HOST=ubuntu-itx-01
cd "$(dirname "$0")/.."

die() { printf '\n✗ %s\n' "$*" >&2; exit 1; }

dry=0 target=origin/main
for a in "$@"; do
  case "$a" in
    --dry-run) dry=1 ;;
    -*) die "unknown option $a" ;;
    *) target=$a ;;
  esac
done

git fetch -q --tags --force origin
new=$(git rev-parse --verify -q "$target^{commit}") || die "$target isn't a commit here."
old=$(git rev-parse v1^{commit})
git merge-base --is-ancestor "$new" origin/main || die "$target isn't on main. Merge it first."
if [ "$new" = "$old" ]; then
  echo "v1 is already at ${new:0:7}. Nothing to do."
  exit 0
fi

echo "v1 is at ${old:0:7}. Moving it to ${new:0:7}."
if git merge-base --is-ancestor "$old" "$new"; then
  echo "Going out:"
  git log --first-parent --format='  %h %s' "$old..$new"
else
  echo "This goes BACK to an older version. Taken out:"
  git log --first-parent --format='  %h %s' "$new..$old"
fi

img=$(git show "$new:.github/workflows/review.yml" | sed -n 's/^ *AGENT_IMAGE: *//p' | head -1)
case "$img" in
  ghcr.io/aachtenberg/agent-review@sha256:*)
    echo
    echo "Checking the review image runs on $RUNNER_HOST..."
    ssh -o BatchMode=yes -o ConnectTimeout=10 "$RUNNER_HOST" \
      "docker pull -q '$img' >/dev/null && docker run --rm '$img' opencode --version" \
      || die "The image didn't run on $RUNNER_HOST, so the private repos' reviews would fail. Nothing was changed."
    echo "  ✓ it runs" ;;
  *) echo "(This version doesn't use the prebuilt image, so there's no image to check.)" ;;
esac

if [ "$dry" = 1 ]; then
  echo
  echo "Dry run: v1 not moved."
  exit 0
fi

echo
read -rp "Move v1 to ${new:0:7}? Every repo's next review uses it. [y/N] " yn
[ "$yn" = y ] || [ "$yn" = Y ] || die "Not moved."
git tag -f v1 "$new" >/dev/null
git push -q -f origin refs/tags/v1
echo "✓ v1 is at ${new:0:7}."
echo
echo "To undo:  ./deploy/release.sh ${old:0:7}"
