# agent-review

Agentic pull-request reviews for GitHub, with no vendor lock-in.

[OpenCode](https://github.com/anomalyco/opencode) (MIT) runs as an agent on a full, read-only checkout of the PR. It reads the diff, then greps for and reads whatever uses each change, so it can catch a broken Service selector or a caller in another file. It then posts a short review as a PR comment:

```
- **[high]** `k3s/base/data/postgrest.yml:88` The Service now selects `postgrest-api`, but the pods
  are labelled `postgrest`, so the Service has no endpoints. Fix: revert the selector.
```

or `No issues found.` with one line on what was checked.

## Use it in a repo

Copy [`examples/agent-review.yml`](examples/agent-review.yml) to `.github/workflows/agent-review.yml`, keep the `with:` block that fits, and add the `OPENROUTER_API_KEY` secret.

- **Public repos** run on GitHub-hosted runners with GLM 5.3 Flash via OpenRouter, at about $0.001–0.02 per review.
- **Private repos** run on a self-hosted runner and can set `fallback_model` to a local Ollama model, used when the first model fails or there is no key.

A review runs when a PR is opened, reopened or marked ready (not drafts), or when the repo owner comments `/review` on a PR. That comment gets 👀 when the run starts, then 🚀 when the review is posted or 👎 when it failed.

### Inputs

| Input | Default | |
|---|---|---|
| `runner` | `ubuntu-latest` | `runs-on` label |
| `model` | `openrouter/z-ai/glm-5.3-flash` | any OpenCode `provider/model` |
| `fallback_model` | none | model to retry with once |
| `ollama_base_url` | none | e.g. `http://host:11434/v1`, for `ollama/` models |
| `config_ref` | `v1` | ref of this repo to read `review/` from; keep it equal to the `@ref` in `uses:` |

### Repo-specific notes

A repo can add `.github/agent-review.md` with things the reviewer should know, such as which files are generated or what usually breaks. It is appended to the prompt. It is read from the PR's **base** commit, so a PR cannot change its own review instructions.

## Isolation

The PR's code is untrusted input to an agent that can run commands:

- **Who can trigger it:** only same-repo PRs (never forks), and `/review` only from the owner. The prompt, config and tools always come from this repo, never from the PR. `OPENCODE_DISABLE_PROJECT_CONFIG` makes OpenCode ignore any `opencode.json` or `AGENTS.md` the PR adds.
- **Where it runs:** a throwaway container, with the checkout mounted **read-only**.
- **What it can do:** read, grep, glob and list inside the checkout, plus one shell command, [`git-ro`](review/git-ro). OpenCode's bash rules match the raw command string, and shell quoting gets past them, so the real boundary is the wrapper. It allows `diff`, `log`, `show`, `blame` and `merge-base` with a fixed set of options, requires every path to resolve inside the checkout, and runs git with an empty environment. The bash rules also refuse `$`, `` ` ``, `<` and `>`.
- **Symlinks:** any symlink in the PR that points outside the checkout is replaced with a placeholder before the checkout is mounted.
- **Secrets:** `OPENROUTER_API_KEY` enters the container only for an `openrouter/` model. `GITHUB_TOKEN` never does; the comment is posted after the container exits.

## Layout

- `.github/workflows/review.yml`: the reusable workflow
- `review/`: the prompt, the OpenCode config, `git-ro`, and `render.py` (turns the agent's events into the comment)
- `examples/agent-review.yml`: the caller to copy into each repo
