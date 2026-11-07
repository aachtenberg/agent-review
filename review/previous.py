#!/usr/bin/env python3
"""Find the earlier review that a re-review builds on.

A re-review checks the earlier review's findings and reviews only the commits
added since, instead of the whole PR again. It is used when all of these hold:
  - the run was not asked for a full review (`/review full`);
  - an earlier review on the PR was posted by this workflow (by
    github-actions[bot], headed "### 🔎 Agent review") and written by the
    main model. A fallback model's review is too shallow to build on;
  - that review's commit is still in the PR and is not the current head;
  - the commits since it contain no merge. A merge from the base branch
    would put the base's own changes in the diff.
Otherwise the review covers the whole PR, as a first review does.

usage: previous.py COMMENTS_JSONL REPO_DIR HEAD_SHA FINDINGS_OUT

COMMENTS_JSONL holds the PR's comments, oldest first, one {"login", "body"}
object per line. Prints `prev_sha=` (empty for a full review) and `scope=`
(a note for the comment's footer) for $GITHUB_OUTPUT. Writes the earlier
review's findings, back in prompt.md's plain format, to FINDINGS_OUT.
Never fails: on any error it asks for a full review.
"""
import json
import os
import re
import subprocess
import sys

BOT = "github-actions[bot]"
HEADING = "### 🔎 Agent review"
FOOTER = "<sub>OpenCode · "
MAX = 8000  # characters of earlier findings put in the prompt
ICONS = {"🔴 **High** · ": "**[high]** ", "🟠 **Medium** · ": "**[medium]** ", "🟡 **Low** · ": "**[low]** "}


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)


def reviewed_sha(body):
    """The head commit a rendered review was written for."""
    m = re.search(r"<!-- agent-review head=([0-9a-f]{40}) -->", body)
    if m:
        return m.group(1)
    # Comments from before the marker: the short SHA in the footer.
    m = re.search(re.escape(FOOTER) + r"`[^`]+`(?: \([^)]*\))? · `([0-9a-f]{7,40})`", body)
    return m.group(1) if m else None


def plain(body):
    """A rendered review's findings, back in prompt.md's format."""
    text = body[len(HEADING):]
    text = text.split("\n---\n" + FOOTER)[0]
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<summary>.*?</summary>|</?details>", "", text)
    # The count line is render.py's, not the model's.
    text = "\n".join(l for l in text.split("\n")
                     if not re.match(r"\*\*\d+ findings?\*\*:|✅ \*\*Nothing blocking\*\*", l))
    for icon, tag in ICONS.items():
        text = text.replace(icon, tag)
    text = re.sub(r"\[(`[^`]+`)\]\(https://[^)\s]+\)", r"\1", text)  # file:line links
    text = text.replace("✅ ", "").replace("<<<REVIEW", "").replace("REVIEW>>>", "")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:MAX]


def earlier_review(path):
    """The last review this workflow posted with the main model, or None."""
    found = None
    with open(path) as f:
        for line in f:
            try:
                c = json.loads(line)
            except ValueError:
                continue
            body = c.get("body") or ""
            if c.get("login") != BOT or not body.startswith(HEADING) or FOOTER not in body:
                continue
            if "(fallback: " in body.rsplit(FOOTER, 1)[1]:
                continue
            found = body
    return found


def decide(comments, repo, head, out):
    """(prev_sha, footer note). prev_sha is empty for a full review."""
    if re.match(r"\s*/review\s+full\b", os.environ.get("COMMENT_BODY", "")):
        return "", "full review, as asked"
    body = earlier_review(comments)
    if body is None:
        return "", ""  # a first review: nothing to say
    short = reviewed_sha(body)
    r = git(repo, "rev-parse", "--verify", "-q", f"{short}^{{commit}}") if short else None
    if r is None or r.returncode != 0:
        return "", "full review: the last review's commit is no longer in the PR"
    prev = r.stdout.strip()
    if prev == head:
        return "", "full review: no new commits since the last review"
    if git(repo, "merge-base", "--is-ancestor", prev, head).returncode != 0:
        return "", "full review: the PR was rebased since the last review"
    if git(repo, "rev-list", "--merges", f"{prev}..{head}").stdout.strip():
        return "", "full review: a merge came in since the last review"
    with open(out, "w") as f:
        f.write(plain(body) + "\n")
    return prev, f"re-review since `{prev[:7]}`"


def main():
    comments, repo, head, out = sys.argv[1:5]
    open(out, "w").close()
    try:
        prev, scope = decide(comments, repo, head, out)
    except Exception as e:  # never block the review
        prev, scope = "", f"full review: {type(e).__name__} finding the last review"
        open(out, "w").close()
    print(f"prev_sha={prev}")
    print(f"scope={scope}")


if __name__ == "__main__":
    main()
