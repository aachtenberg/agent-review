# agent-review

Agentic pull-request reviews for GitHub Actions, with no vendor lock-in.

[OpenCode](https://github.com/anomalyco/opencode) (MIT) runs as an agent on a full, **read-only** checkout of the PR. It reads the diff, then greps for and reads whatever uses each change: callers in other files, manifests that reference a renamed label, scripts that read a changed config key. It posts a short review as a PR comment:

> - **[high]** `k3s/base/data/postgrest.yml:88` The Service now selects `postgrest-api`, but the pods are labelled `postgrest`, so the Service has no endpoints and every ingest job that calls it fails. Fix: revert the selector.

If it finds nothing, it posts `No issues found.` plus one `Checked:` line saying what it read.

The model is any [OpenCode provider/model](https://opencode.ai/docs/models/). The default is GLM 5.3 Flash via [OpenRouter](https://openrouter.ai), at about **$0.001–0.02 per review**. A local Ollama model can be the fallback, or the main model.

## Quick start

1. Copy [`examples/agent-review.yml`](examples/agent-review.yml) to `.github/workflows/agent-review.yml` in your repo.
2. Keep the `with:` block that matches the repo, and delete the other:
   - **Public repo:** `runner: ubuntu-latest`, a GitHub-hosted runner.
   - **Private repo:** your self-hosted runner, optionally with `fallback_model` and `ollama_base_url` for a local model (see [Self-hosted runners](#self-hosted-runners)).
3. Add the repository secret `OPENROUTER_API_KEY`. You can skip it if `model` is a local `ollama/…` model.
4. Merge. The first review comes on the **next** PR: `pull_request_target` always runs the workflow from the default branch, so the PR that adds it can't review itself.

## When it runs

- **Automatically:** when a PR is opened, reopened, or marked ready for review. Drafts are skipped.
- **On demand:** when the repo owner comments `/review` on a PR. The comment gets 👀 when the run starts, then 🚀 when the review is posted, or 👎 if the run failed. A newer `/review` cancels a run still in progress; the cancelled run posts nothing and gets no reaction.
- **Never** for PRs from forks, and never for `/review` from anyone but the owner.

## Inputs

| Input | Default | Description |
|---|---|---|
| `runner` | `ubuntu-latest` | `runs-on` label |
| `model` | `openrouter/z-ai/glm-5.3-flash` | any OpenCode `provider/model` |
| `fallback_model` | none | retried once if the first attempt fails or the repo has no key |
| `ollama_base_url` | none | OpenAI-compatible endpoint for `ollama/` models, e.g. `http://host:11434/v1` |
| `config_ref` | `v1` | ref of this repo to read `review/` from; keep it equal to the `@ref` in `uses:` |

Secret: `OPENROUTER_API_KEY`, optional, needed for `openrouter/` models.

Bundled `ollama/` models: `gpt-oss:20b` and `hf.co/unsloth/Qwen3.5-35B-A3B-GGUF:UD-IQ4_XS`. To use another, add it under `provider.ollama.models` in [`review/opencode.json`](review/opencode.json).

## The comment

| Heading | Meaning |
|---|---|
| **🔎 Agent review** | The review: findings most severe first (at most 5), or `No issues found.` |
| **🔎 Agent review** with a folded *"Agent's last message (not a review)"* | The agent finished without writing its review block. Its last message is folded away rather than posted; comment `/review` to retry. |
| **⚠️ Agent review failed** | The agent exited with an error, hit its time limit, or couldn't run (for example, no key and no fallback). Any partial output is folded away, and the job fails. |

The footer shows the model that wrote the review, and the reason if it fell back. It also shows the commit, tool calls by type, tokens, cost (when the provider reports it), duration, and a link to the run.

## Repo-specific notes

Add `.github/agent-review.md` to give the reviewer context, such as which files are generated, what usually breaks, or what to ignore. It is appended to the prompt, up to 4,000 characters. It is read from the PR's **base** commit, so a PR can't change its own review instructions.

The agent also reads `README.md`, and `AGENTS.md`, `CLAUDE.md` or `.github/copilot-instructions.md` if present, for the repo's conventions.

## Self-hosted runners

GitHub-hosted runners need nothing extra. A self-hosted runner needs:

- **Docker,** usable by the runner's user. The agent runs in `node:22-bookworm-slim`, pinned by digest, limited to 4 GB of memory and 2 CPUs.
- **`gh`, `python3` and `git`** on the host.
- **Outbound access to:** Docker Hub, `deb.debian.org`, `registry.npmjs.org` (git and OpenCode are installed into the container on every run), GitHub, and the model provider.

Use a self-hosted runner for private repos only. A public repo's workflows can be triggered by anyone who opens a PR, so they belong on GitHub-hosted runners.

The local fallback is only as available as its GPU. If another job holds the VRAM, a fallback review waits, and fails at its time limit.

## Data and privacy

The reviewed code goes to the model provider: OpenRouter, then whichever lab serves the model. For private code, pick a provider whose data policy you accept. Avoid `:free` model variants, which may log prompts. Alternatively, use a local `ollama/…` model so the code never leaves your network. The comment is posted with the job's own `GITHUB_TOKEN`; no third-party GitHub App is involved.

## Isolation

The PR's code is untrusted input to an agent that can run commands:

- **Who can trigger it:** only same-repo PRs, and `/review` only from the owner. The workflow checks this in the caller and again inside.
- **The PR can't change its review:** the prompt, config and tools always come from this repo, at `config_ref`. `OPENCODE_DISABLE_PROJECT_CONFIG` makes OpenCode ignore any `opencode.json` or `AGENTS.md` the PR adds.
- **Where it runs:** a throwaway container, with the checkout mounted **read-only**.
- **What it can do:** read, grep, glob and list inside the checkout, plus one shell command, [`git-ro`](review/git-ro). OpenCode's bash rules match the raw command string, and shell quoting gets past them, so the real boundary is the wrapper. It allows `diff`, `log`, `show`, `blame` and `merge-base` with a fixed set of options, requires every path to resolve inside the checkout, and runs git with an empty environment. The bash rules also refuse `$`, `` ` ``, `<` and `>`.
- **Symlinks:** any symlink in the PR that points outside the checkout is replaced with a placeholder before the checkout is mounted.
- **Secrets:** `OPENROUTER_API_KEY` enters the container only for an `openrouter/` model. `GITHUB_TOKEN` never does; the comment is posted after the container exits.

## Limits

- **Time:** 15 minutes per attempt, so up to 2 attempts with a fallback, and 40 minutes for the job.
- **Length:** the comment body is capped at 60,000 characters.
- **Pinned versions:** OpenCode `1.19.3` and the container image. Updating either is a change to this repo.

## Versioning

`v1` is a moving tag. It is moved to each tested change on `main`, and callers that use `@v1` pick it up on their next run. To freeze a repo on one version, pin both `uses: …@<commit-sha>` and `config_ref: <commit-sha>`.

## Layout

- `.github/workflows/review.yml`: the reusable workflow
- `review/prompt.md`: the review instructions and output format
- `review/opencode.json`: OpenCode providers and permissions
- `review/git-ro`: the read-only git wrapper
- `review/render.py`: turns the agent's events into the comment
- `examples/agent-review.yml`: the caller to copy into each repo
- `.github/workflows/agent-review.yml`: this repo reviewing its own PRs

## License

[MIT](LICENSE). OpenCode, which this runs, is also MIT.
