# Deploy guide

There are three jobs: add the reviewer to a repo, roll out a change to every repo, and roll back.

## Add it to a repo

### Public repo

Public repos use a GitHub-hosted runner, so there's nothing to install.

1. **Add the workflow** on a branch in the target repo. The example's default `with:` block is already the public one, so the file works as is:
   ```sh
   mkdir -p .github/workflows
   curl -sSfo .github/workflows/agent-review.yml \
     https://raw.githubusercontent.com/aachtenberg/agent-review/main/examples/agent-review.yml
   ```
2. **Add the key** (it asks you to paste the value):
   ```sh
   gh secret set OPENROUTER_API_KEY -R aachtenberg/<repo>
   ```
3. **Open a PR and merge it.** That PR won't get a review, because GitHub runs the workflow from the default branch. The next PR will.

### Private repo

Private repos run on the self-hosted runner `ubuntu-itx-01`, so the code is never on a shared machine. This takes the same three steps, plus two:

4. **Use the private `with:` block.** In `.github/workflows/agent-review.yml`, delete the public `with:` block and uncomment the private one. Fill in the Ollama host.
5. **Register a runner for the repo.** On a personal GitHub account, a runner serves one repo, so each private repo gets its own runner on `ubuntu-itx-01`, in `~/actions-runner-<repo>`.

   First, get a registration token from any machine with `gh`. It's valid for an hour:
   ```sh
   gh api -X POST repos/aachtenberg/<repo>/actions/runners/registration-token --jq .token
   ```
   Then, on `ubuntu-itx-01`:
   ```sh
   R=<repo>
   mkdir ~/actions-runner-$R && cd ~/actions-runner-$R
   # Any copy of the runner works; it updates itself on first start.
   tar xzf "$(ls ~/actions-runner-*/actions-runner-linux-x64-*.tar.gz | head -1)"
   # --labels matters: the workflow targets the label, not the name.
   ./config.sh --unattended --url https://github.com/aachtenberg/$R --token <token> \
     --name ubuntu-itx-01 --labels ubuntu-itx-01
   sudo ./svc.sh install && sudo ./svc.sh start
   ```
   Check that it's online with the label:
   ```sh
   gh api repos/aachtenberg/<repo>/actions/runners \
     --jq '.runners[] | .name + " " + .status + " " + ([.labels[].name] | join(","))'
   ```
   The output should end in `online self-hosted,Linux,X64,ubuntu-itx-01`.

## Roll out a change to every repo

Every repo calls `@v1`, so a rollout is just moving the `v1` tag.

1. **Open a PR in this repo.** The agent reviews it automatically. Reply on the PR to each finding, saying what you fixed or why you didn't. Comment `/review` to re-run it.

   That review runs `main`'s workflow, not the PR's. A change to `review/` or `review.yml` first runs for real on the next PR after it merges.
2. **If you changed `image/`:**
   - Pushing the branch makes [`image.yml`](.github/workflows/image.yml) build and push the image. Copy the digest from that run's summary into `AGENT_IMAGE` in `review.yml`, and push again.
   - Test the image on `ubuntu-itx-01` before merging. Its CPU has no AVX2, which is why the image uses OpenCode's baseline build. Keep it that way.
     ```sh
     ssh ubuntu-itx-01 'docker run --rm ghcr.io/aachtenberg/agent-review@sha256:<digest> opencode --version'
     ```
3. **Merge**, then comment `/review` on an open PR in this repo. That run uses the new `main`.
4. **Move `v1`**, after writing down where it points now, in case you need to roll back:
   ```sh
   git fetch --tags origin
   git rev-parse --short v1          # write this down
   git tag -f v1 origin/main && git push -f origin refs/tags/v1
   ```
5. **Check one public and one private repo:** comment `/review` on an open PR in each. Every repo picks up the change on its next run, so there's nothing to restart.

## Roll back

Point `v1` back at the commit you wrote down:

```sh
git tag -f v1 <old-sha> && git push -f origin refs/tags/v1
```

If you didn't write it down, the earlier merge commits are in `git log --first-parent --oneline main`.

## Which repos use it

```sh
gh search code "agent-review/.github/workflows/review.yml" --owner aachtenberg \
  --json repository --jq '.[].repository.nameWithOwner' | sort -u
```

## When something's wrong

| What you see | Why | Fix |
|---|---|---|
| No review on a PR | It's a draft, from a fork, or the PR that added the workflow | Mark it ready, or comment `/review` |
| `/review` does nothing | It was posted by someone other than the owner or an org member | Have the owner comment |
| Private repo's job stays queued | That repo's runner is offline, or lacks the `ubuntu-itx-01` label | `systemctl status actions.runner.aachtenberg-<repo>.ubuntu-itx-01` on `ubuntu-itx-01`, and check its labels as in step 5 |
| ⚠️ Agent review failed: no `OPENROUTER_API_KEY` | The repo has no key and no fallback | `gh secret set OPENROUTER_API_KEY -R aachtenberg/<repo>` |
| The fallback hits its time limit | The Ollama host's GPU is busy | Retry later with `/review` |
| `docker: … denied` pulling the image | The GHCR package isn't public | Make it public in the package's settings on GitHub |
