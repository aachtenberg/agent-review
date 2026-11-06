#!/usr/bin/env python3
"""Turn `opencode run --format json` events into the PR comment body.

The review is the text between <<<REVIEW and REVIEW>>> in the agent's output.
Markers count only on a line of their own. A closing marker the model
mangled (a bare `REVIEW` line, or none) still counts: the block then runs to that line or to the end. With no opening
marker, the last text part is folded into <details> under a note, since it is
usually the model thinking aloud rather than a review. A block that is a
verbatim copy of one of prompt.md's examples (a model quoting its prompt) is
not a review either, and is skipped. The footer reports
the model, commit, tool calls, tokens/cost (when the provider reports them)
and duration, so reviews from different models can be compared.

AGENT_RC is the agent's exit code. When it is not 0 (or unset: the agent
never ran), the comment says the review failed. When it is 0 but there is no
review block, the comment says there is no review. Either way any output is
folded away, so half-finished reasoning is never posted as a review, and the
heading starts with ⚠️, which the workflow treats as a failed run.
"""
import json
import os
import re
import sys
from urllib.parse import quote

MAX = 60000  # GitHub caps a comment body at 65536 characters

SEVERITY = {"high": "🔴 **High**", "medium": "🟠 **Medium**", "low": "🟡 **Low**"}
FINDING = re.compile(r"^(\s*(?:\d+\.|[-*])\s+)(?:\*\*)?\[(high|medium|low)\](?:\*\*)?\s*", re.I)
LOCATION = re.compile(r"`([^`\s:]+):(\d+)(?:-(\d+))?`")


def decorate(review):
    """Severity icons, file:line links to the PR head, and a count line.

    Only presentation: the model writes the structure (prompt.md), this makes
    it look the same on every run. Lines that are not findings are untouched.
    """
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    head = os.environ.get("HEAD_SHA", "")
    counts = {"high": 0, "medium": 0, "low": 0}
    out = []
    for line in review.split("\n"):
        m = FINDING.match(line)
        if m:
            sev = m.group(2).lower()
            counts[sev] += 1
            rest = line[m.end():]
            if repo and head:
                def link(loc):
                    path, a, b = loc.group(1), loc.group(2), loc.group(3)
                    if path.startswith("/") or ".." in path.split("/"):
                        return loc.group(0)
                    anchor = f"#L{a}-L{b}" if b else f"#L{a}"
                    return f"[{loc.group(0)}](https://github.com/{repo}/blob/{head}/{quote(path)}{anchor})"
                rest = LOCATION.sub(link, rest, count=1)
            line = f"{m.group(1)}{SEVERITY[sev]} · {rest}"
        out.append(line)
    n = sum(counts.values())
    body = "\n".join(out)
    if n:
        parts = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
        return f"**{n} finding{'s' if n != 1 else ''}**: {parts}\n\n{body}"
    if body.startswith("No issues found"):
        # Keep "Checked:" on its own line; Markdown joins adjacent lines.
        return "✅ " + body.replace("\n", "\n\n", 1)
    return body


events = []
try:
    with open(sys.argv[1]) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
except FileNotFoundError:
    pass

texts = [(e.get("part") or {}).get("text", "") for e in events if e.get("type") == "text"]
tools = [e for e in events if e.get("type") == "tool_use"]
tool_names = {}
for e in tools:
    name = (e.get("part") or {}).get("tool", "?")
    tool_names[name] = tool_names.get(name, 0) + 1

tokens_in = tokens_out = 0
cost = 0.0
for e in events:
    if e.get("type") != "step_finish":
        continue
    part = e.get("part") or {}
    tok = part.get("tokens") or {}
    tokens_in += int(tok.get("input") or 0) + int((tok.get("cache") or {}).get("read") or 0)
    tokens_out += int(tok.get("output") or 0) + int(tok.get("reasoning") or 0)
    cost += float(part.get("cost") or 0)

agent_rc = os.environ.get("AGENT_RC", "")
failed = agent_rc != "0"
marked = False

full = "\n".join(texts)
def block_after(m):
    review = full[m.end():]
    # Stop at a line starting with REVIEW>>> (anything after it on that line
    # is dropped), else at a bare REVIEW line, else run to the end minus a
    # trailing ``` the model wrapped the block in.
    for end in (r"^[ \t]*REVIEW>>>?", r"^[ \t]*REVIEW[ \t]*\r?$"):
        parts = re.split(end, review, maxsplit=1, flags=re.M)
        if len(parts) == 2:
            review = parts[0]
            break
    else:
        review = re.sub(r"\n[ \t]*```[ \t]*\Z", "", review.rstrip())
    return review.strip()


def squash(s):
    return " ".join(s.split())


# The example blocks in prompt.md. A model that quotes the prompt writes one
# of these verbatim; that is not its review, so such a block is skipped and
# the one before it counts, or none (⚠️ No review). Only an exact copy, up to
# whitespace, is skipped, so a real review that mentions the examples counts.
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt.md")) as f:
        prompt = f.read()
    TEMPLATES = {squash(b) for b in re.findall(r"^<<<REVIEW\n(.*?)^REVIEW>>>", prompt, re.M | re.S)}
except OSError:
    TEMPLATES = set()

# Markers count only at the end (open) or start (close) of a line: a review
# can mention them mid-sentence (a "Checked:" line about this very parser
# did), and that must not be taken for the start or end of the block.
# A marker also counts at the end of a line ("…output.<<<REVIEW"), and with
# two angle brackets instead of three, which small models write.
opens = list(re.finditer(r"<<<?REVIEW[ \t]*\r?$", full, re.M))
for m in reversed(opens):
    block = block_after(m)
    if squash(block) not in TEMPLATES:
        marked, review = True, block
        break
if not marked:
    # No marked block: what's there is usually the model thinking aloud.
    review = texts[-1].strip() if texts else ""

if len(review) > MAX:
    review = review[:MAX] + "\n\n_(truncated)_"

model = os.environ.get("MODEL_USED") or os.environ.get("MODEL", "?")
fell_back = os.environ.get("FELL_BACK", "")
sha = os.environ.get("HEAD_SHA", "")[:7]
elapsed = os.environ.get("ELAPSED", "?")
tool_summary = ", ".join(f"{k}×{v}" for k, v in sorted(tool_names.items())) or "none"
usage = f"{tokens_in:,} in / {tokens_out:,} out tokens"
if cost:
    usage += f", ${cost:.4f}"

run_url = os.environ.get("RUN_URL", "")
if failed:
    note = os.environ.get("AGENT_NOTE", "")
    if note:
        why = f"{note}, and no fallback model is configured"
    elif not agent_rc:
        why = "the agent did not run"
    elif agent_rc == "124":
        why = "the agent hit its time limit"
    else:
        why = f"the agent exited with code {agent_rc} before finishing"
    print("### ⚠️ Agent review failed\n")
    print(f"No review: {why}. The [run log]({run_url}) has the details. "
          "Comment `/review` to retry.")
    if texts:
        partial = full.strip()
        if len(partial) > MAX:
            partial = partial[-MAX:]
        print("\n<details><summary>Partial agent output (not a review)</summary>\n")
        print(partial)
        print("\n</details>")
elif not marked:
    # The agent exited cleanly but wrote no review block: either nothing at
    # all, or unstructured text (usually thinking aloud). Never post that as
    # the review. The heading starts with ⚠️, which the workflow's post step
    # treats as a failed run (👎 on /review).
    print("### ⚠️ No review\n")
    what = "without writing a review" if texts else "without writing anything"
    print(f"The agent finished {what}. The [run log]({run_url}) has the "
          "details. Comment `/review` to retry.")
    if texts:
        print("\n<details><summary>Agent's last message (not a review)</summary>\n")
        print(review)
        print("\n</details>")
else:
    print("### 🔎 Agent review\n")
    print(decorate(review))
print("\n---")
print(f"<sub>OpenCode · `{model}`{' (fallback: ' + fell_back + ')' if fell_back else ''} · `{sha}` · {len(tools)} tool calls ({tool_summary}) · "
      f"{usage} · {elapsed}s · [run]({run_url}) · "
      f"comment `/review` to re-run</sub>")
