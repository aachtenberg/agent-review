# Deploy guide

Three scripts do the work. You run them on your own computer, and each says what it's doing and what to do if something's wrong.

| I want to… | Run |
|---|---|
| Add the reviewer to a repo | `./deploy/add-repo.sh <repo>` |
| Check a repo is set up right | `./deploy/add-repo.sh <repo> --dry-run` |
| Send a change out to every repo | `./deploy/release.sh` |
| Undo that | `./deploy/release.sh <commit>` (it prints the exact command) |
| See which repos have it | `./deploy/list-repos.sh` |

Add `--dry-run` to `add-repo.sh` or `release.sh` to see what it would do without changing anything.

## Before you start (once)

1. **Install the GitHub CLI** from https://cli.github.com, then log in and allow it to add workflow files:
   ```sh
   gh auth login
   gh auth refresh -s workflow
   ```
   You need **admin** access to the repos you'll set up. Ask the owner if you don't have it.
2. **Get this repo:**
   ```sh
   gh repo clone aachtenberg/agent-review
   cd agent-review
   ```
3. **Check you can reach the runner machine,** `ubuntu-itx-01`. Private repos and releases need it. This should print nothing, with no error:
   ```sh
   ssh ubuntu-itx-01 true
   ```
   If it fails, ask the owner for access. For private repos you'll also need your `sudo` password on that machine.
4. **Have the OpenRouter API key ready.** The script asks for it only if the repo doesn't have it yet. Ask the owner for it.

## Add the reviewer to a repo

```sh
./deploy/add-repo.sh snow-query
```

It checks the repo, then does only what's missing:

1. **The OpenRouter key.** If the repo doesn't have it, it asks you to paste it.
2. **A runner (private repos only).** It sets one up for the repo on `ubuntu-itx-01`, and asks for your `sudo` password there.
3. **The workflow.** It opens a PR in the repo that adds `.github/workflows/agent-review.yml`.

**Then merge that PR.** That's it. Every new PR in the repo gets a review comment. The PR that adds the workflow doesn't get one, which is normal.

To check it works, open a small PR in the repo, like a typo fix. A review comment shows up on it within a few minutes.

## Send a change out to every repo

Every repo uses the version of agent-review tagged `v1`. "Releasing" means moving that tag to the latest `main`.

1. **Get your change merged into `main`** with a normal PR in this repo. The agent reviews that PR too. Reply on the PR to each finding, saying what you fixed or why you didn't.
2. **Open a small PR in this repo,** like a typo fix, and wait for its review comment. That review uses the new `main`, so it's your test. Close the PR afterwards.
3. **Release:**
   ```sh
   ./deploy/release.sh
   ```
   It shows what's going out and checks that the review image runs on `ubuntu-itx-01`. Then it asks `Move v1 …? [y/N]`. Type `y`.
4. **Write down the undo command it prints,** like `./deploy/release.sh 30bc83b`.

Every repo uses the new version on its next review. There's nothing to restart.

## Undo a release

Run the undo command that `release.sh` printed:

```sh
./deploy/release.sh 30bc83b
```

Lost it? `git log --first-parent --oneline origin/main` lists every version. Pick the one before yours.

## Changing the container image

You only need this if you edit something in `image/` (like a new OpenCode version):

1. Push your branch. GitHub builds the image, and the **Agent image** run's summary shows a line like `AGENT_IMAGE: ghcr.io/aachtenberg/agent-review@sha256:…`.
2. Paste that line over the `AGENT_IMAGE:` line in `.github/workflows/review.yml`, and push again.
3. Then follow [Send a change out](#send-a-change-out-to-every-repo). `release.sh` won't release an image that doesn't run on `ubuntu-itx-01`.

Keep `opencode-linux-x64-baseline` in `image/package.json`. `ubuntu-itx-01`'s CPU can't run the regular build.

## Something's wrong

| What you see | What to do |
|---|---|
| No review on a PR | **A draft:** mark it ready for review. **From a fork:** skipped on purpose; nothing to do. **The PR that adds the workflow:** normal; reviews start once it's merged. |
| `/review` does nothing | Only the repo owner can use `/review`. Anyone else can close the PR and reopen it, which runs a new review. |
| A private repo's review stays "Queued" | Its runner is down. Run `./deploy/add-repo.sh <repo> --dry-run`; it says what's wrong and how to fix it. |
| ⚠️ **Agent review failed** … no `OPENROUTER_API_KEY` | Run `./deploy/add-repo.sh <repo>`. It asks for the key. |
| ⚠️ **Agent review failed** … time limit | The model was slow or the local GPU was busy. Try again: `/review` (owner), or close and reopen the PR. |
| ⚠️ **No review** | The model didn't finish its answer. Try again the same way. |
| A script stops with ✗ | Read the line after ✗. It says what to do. |

Still stuck? Open the run link in the review comment's footer, or under the PR's **Checks** tab, and send it to the owner.
