#!/usr/bin/env bash
# Add the agent reviewer to a repo:   ./deploy/add-repo.sh <repo>
# See what it would do first:         ./deploy/add-repo.sh <repo> --dry-run
#
# Run it on your own machine, from a clone of agent-review. It checks the
# repo and only does what's missing, so it's safe to run again. Use it to
# check a repo, too.
#   1. The OpenRouter key: asks you to paste it if the repo doesn't have it.
#   2. Private repos only: a runner for the repo on ubuntu-itx-01, over ssh.
#      It asks for your sudo password there.
#   3. The workflow: opens a PR that adds it. You merge the PR. If it's
#      there but doesn't grant a permission the reviewer on main asks for,
#      the PR adds that instead.
set -euo pipefail

OWNER=aachtenberg
RUNNER_HOST=ubuntu-itx-01
LABEL=ubuntu-itx-01
RUNNER_VERSION=2.338.2   # used only if the host has no runner download to copy
BRANCH=add-agent-review
UPDATE_BRANCH=agent-review-permissions
WF=.github/workflows/agent-review.yml
HERE=$(cd "$(dirname "$0")/.." && pwd)

# What runs on the runner host to set up a repo's runner. Arguments:
# repo name, owner/repo, registration token, runner name, label, version.
# If anything fails before the runner is registered, its folder is
# removed, so running add-repo.sh again starts clean.
RUNNER_SETUP=$(cat <<'SH'
set -euo pipefail
name=$1 repo=$2 token=$3 runner=$4 label=$5 ver=$6
d=$HOME/actions-runner-$name
if [ -e "$d" ]; then
  echo "$d already exists. Ask the owner to look at it."; exit 1
fi
fail() { echo "$1"; cd "$HOME"; rm -rf "$d"; exit 1; }
mkdir "$d" && cd "$d"
# Reuse another runner's download if there is one: the runner updates
# itself, so its version doesn't matter.
tgz=$(ls "$HOME"/actions-runner-*/actions-runner-linux-x64-*.tar.gz 2>/dev/null | head -1 || true)
if [ -z "$tgz" ]; then
  # Saved under a .part name first, so a cut-off download is never reused.
  curl -sSfLo dl.part "https://github.com/actions/runner/releases/download/v$ver/actions-runner-linux-x64-$ver.tar.gz" \
    || fail "Couldn't download the runner. Check the machine's internet, then run add-repo.sh again."
  tgz=$d/actions-runner-linux-x64-$ver.tar.gz
  mv dl.part "$tgz"
fi
tar xzf "$tgz" \
  || fail "Couldn't unpack $tgz. It may be damaged: delete it, then run add-repo.sh again."
./config.sh --unattended --url "https://github.com/$repo" --token "$token" --name "$runner" --labels "$label" \
  || fail "Couldn't register the runner with GitHub. Run add-repo.sh again; if it fails twice, ask the owner."
sudo ./svc.sh install
sudo ./svc.sh start
SH
)

step() { printf '\n==> %s\n' "$*"; }
ok()   { printf '    ✓ %s\n' "$*"; }
todo() { printf '    • %s\n' "$*"; }
die()  { printf '\n✗ %s\n' "$*" >&2; exit 1; }

dry=0 name=""
for a in "$@"; do
  case "$a" in
    --dry-run) dry=1 ;;
    -*) die "unknown option $a" ;;
    *) name=${a#"$OWNER"/} ;;
  esac
done
[ -n "$name" ] || die "usage: $0 <repo> [--dry-run]    e.g. $0 snow-query"
R=$OWNER/$name
[ "$dry" = 0 ] || echo "Dry run: checking only, changing nothing."

step "Checking $R"
command -v gh >/dev/null || die "Install the GitHub CLI first: https://cli.github.com"
gh auth status >/dev/null 2>&1 || die "Log in first: gh auth login"
gh auth status 2>&1 | grep "'workflow'" >/dev/null \
  || die "Your gh login can't add workflow files. Run: gh auth refresh -s workflow"
info=$(gh repo view "$R" --json visibility,defaultBranchRef,viewerPermission \
  --jq '[.visibility, .defaultBranchRef.name, .viewerPermission] | @tsv' 2>/dev/null) \
  || die "Can't find $R. Check the name."
read -r vis base perm <<<"$info"
[ "$perm" = ADMIN ] || die "You need admin access to $R (you have ${perm:-none}). Ask the owner."
ok "$vis repo, default branch $base"

# --- 1. The OpenRouter key -------------------------------------------------
step "OpenRouter key"
if gh secret list -R "$R" --json name --jq '.[].name' | grep -x OPENROUTER_API_KEY >/dev/null; then
  ok "already set"
elif [ "$dry" = 1 ]; then
  todo "would ask you to paste the OpenRouter API key"
else
  echo "    Paste the OpenRouter API key and press Enter (ask the owner if you don't have it):"
  gh secret set OPENROUTER_API_KEY -R "$R"
  ok "set"
fi

# --- 2. The runner (private repos) -----------------------------------------
if [ "$vis" != PUBLIC ]; then
  step "Runner on $RUNNER_HOST"
  runners=$(gh api "repos/$R/actions/runners" \
    --jq '.runners[] | .status + " " + ([.labels[].name] | join(","))')
  if grep -q "^online .*\b$LABEL\b" <<<"$runners"; then
    ok "online, with the $LABEL label"
  elif [ -n "$runners" ]; then
    die "$R has a runner, but it's offline or missing the $LABEL label:
    $runners
  To start it, on $RUNNER_HOST run:
    sudo systemctl start actions.runner.$OWNER-$name.$RUNNER_HOST"
  elif [ "$dry" = 1 ]; then
    ssh -o BatchMode=yes -o ConnectTimeout=10 "$RUNNER_HOST" true 2>/dev/null \
      && ok "can ssh to $RUNNER_HOST" || todo "can't ssh to $RUNNER_HOST yet; ask the owner for access"
    todo "would install a runner in ~/actions-runner-$name on $RUNNER_HOST"
  else
    ssh -o BatchMode=yes -o ConnectTimeout=10 "$RUNNER_HOST" true 2>/dev/null \
      || die "Can't ssh to $RUNNER_HOST. Ask the owner for access, then run this again."
    token=$(gh api -X POST "repos/$R/actions/runners/registration-token" --jq .token)
    echo "    Installing. It will ask for your sudo password on $RUNNER_HOST."
    ssh -t "$RUNNER_HOST" "bash -c $(printf %q "$RUNNER_SETUP") _ $(printf '%q ' \
      "$name" "$R" "$token" "$RUNNER_HOST" "$LABEL" "$RUNNER_VERSION")"
    for _ in $(seq 12); do
      gh api "repos/$R/actions/runners" --jq '.runners[].status' | grep -x online >/dev/null && break
      sleep 5
    done
    gh api "repos/$R/actions/runners" --jq '.runners[].status' | grep -x online >/dev/null \
      || die "The runner was installed but isn't online. On $RUNNER_HOST run:
    sudo systemctl status actions.runner.$OWNER-$name.$RUNNER_HOST"
    ok "installed and online"
  fi
fi

# --- 3. The workflow ---------------------------------------------------------
# open_pr BRANCH FILE TITLE BODY [BLOB]: a PR in $R that writes FILE to $WF.
# BLOB is the sha of the $WF it replaces; without it, the PR can only add
# $WF, and GitHub refuses it if $WF is already there. Prints the PR's URL.
open_pr() {
  local branch=$1 file=$2 title=$3 body=$4 blob=${5:-} sha replace=()
  gh api "repos/$R/branches/$branch" >/dev/null 2>&1 \
    && die "$R already has a branch named $branch. Merge or close its PR, delete the branch, and run this again."
  sha=$(gh api "repos/$R/git/ref/heads/$base" --jq .object.sha)
  gh api -X POST "repos/$R/git/refs" -f ref="refs/heads/$branch" -f sha="$sha" >/dev/null
  [ -z "$blob" ] || replace=(-f sha="$blob")
  gh api -X PUT "repos/$R/contents/$WF" -f branch="$branch" -f message="$title (aachtenberg/agent-review)" \
    -f content="$(base64 < "$file" | tr -d '\n')" "${replace[@]}" >/dev/null
  gh pr create -R "$R" --base "$base" --head "$branch" --title "$title" --body "$body"
}

step "Workflow"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
if gh api "repos/$R/contents/$WF?ref=$base" --jq .content 2>/dev/null | base64 -d > "$tmp/cur.yml" 2>/dev/null; then
  # Already there. It must grant everything the reviewer on main asks for,
  # or GitHub won't start the reviewer once main is released to v1.
  missing=$(python3 -I "$HERE/deploy/perms.py" "$HERE/.github/workflows/review.yml" "$tmp/cur.yml") \
    || die "$WF in $R has no top-level permissions: block, so this script can't check it. Make it match examples/agent-review.yml by hand."
  if [ -z "$missing" ]; then
    ok "already on $base, with the permissions it needs"
    step "Done"
    echo "    $R is set up. Every new PR gets a review; comment /review on a PR to run one by hand."
    exit 0
  fi
  todo "it's on $base, but doesn't grant: $(tr '\n' ' ' <<<"$missing")"
  if [ "$dry" = 1 ]; then
    todo "would open a PR in $R that adds that to $WF"
    step "Dry run done. Nothing was changed."
    exit 0
  fi
  python3 -I "$HERE/deploy/perms.py" "$HERE/.github/workflows/review.yml" "$tmp/cur.yml" --fix > "$tmp/wf.yml"
  blob=$(gh api "repos/$R/contents/$WF?ref=$base" --jq .sha)
  pr=$(open_pr "$UPDATE_BRANCH" "$tmp/wf.yml" "Update the agent reviewer's permissions" \
    "Adds \`$(tr '\n' ' ' <<<"$missing" | sed 's/ $//')\` to \`$WF\`. The next version of [agent-review](https://github.com/$OWNER/agent-review) asks for it, to set an \`agent-review\` status on each PR. GitHub won't run the reviewer for a workflow that grants less than it asks for, so merge this before that version is released." \
    "$blob")
  ok "opened $pr"
  step "Done. One step left: merge the PR."
  echo "    $pr"
  exit 0
fi

if [ "$vis" = PUBLIC ]; then
  cp "$HERE/examples/agent-review.yml" "$tmp/wf.yml"
else
  # The Ollama address isn't in this public repo; take it from homelab-infra.
  url=$(gh api "repos/$OWNER/homelab-infra/contents/$WF" --jq .content 2>/dev/null \
    | base64 -d | sed -n 's/^ *ollama_base_url: *//p' | head -1 || true)
  [ -n "$url" ] || read -rp "    Ollama URL (like http://host:11434/v1): " url
  [ -n "$url" ] || die "No Ollama URL, so the fallback model wouldn't work. Ask the owner for it, then run this again."
  # Keep the example's private `with:` block, uncommented, and drop the public one.
  python3 -I - "$HERE/examples/agent-review.yml" "$url" > "$tmp/wf.yml" <<'PY'
import re, sys
t = open(sys.argv[1]).read()
pub = re.search(r"^    # Public repo:.*\n    with:\n      runner: ubuntu-latest\n", t, re.M)
priv = re.search(r"^    # Private repo:.*\n((?:    #.*\n)+)", t, re.M)
if not (pub and priv):
    sys.exit("examples/agent-review.yml no longer has the blocks this script expects")
block = "".join(re.sub(r"^    # ?", "    ", l) for l in priv.group(1).splitlines(True))
t = t.replace(pub.group(0), "").replace(priv.group(1), block)
sys.stdout.write(t.replace("http://<ollama-host>:11434/v1", sys.argv[2]))
PY
fi

if [ "$dry" = 1 ]; then
  todo "would open a PR in $R that adds $WF:"
  sed -n '/^ *uses:/,$p' "$tmp/wf.yml" | sed 's/^/        /'
  step "Dry run done. Nothing was changed."
  exit 0
fi

pr=$(open_pr "$BRANCH" "$tmp/wf.yml" "Add the agent reviewer" \
  "Adds \`$WF\` from [agent-review](https://github.com/$OWNER/agent-review). After this merges, every new PR gets a review comment. This PR can't review itself, because GitHub runs the workflow from \`$base\`.")
ok "opened $pr"

step "Done. One step left: merge the PR."
echo "    $pr"
echo "    After that, every new PR in $R gets a review. Comment /review on a PR to run one by hand."
