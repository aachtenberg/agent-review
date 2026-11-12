#!/usr/bin/env python3
"""Turn `opencode run --format json` events into the PR comment body.

The review is the text between <<<REVIEW and REVIEW>>> in the agent's output.
Markers count only on a line of their own, in either case; a ```review fence
opens a block too. A closing marker the model
mangled (a bare `REVIEW` line, or none) still counts: the block then runs to that line or to the end.

With no opening marker, the agent's last message is still the review when it
has the review's own shape (see unmarked): "No issues found." followed by a
"Checked:" line, or a list of findings tagged [high], [medium] or [low].
Models often write a finished review and forget the markers. Anything else
is folded into <details> under a note, since it is usually the model
thinking aloud rather than a review. A block that is a
verbatim copy of one of prompt.md's examples (a model quoting its prompt) is
not a review either, and is skipped. The footer reports
the model, commit, tool calls, tokens/cost (when the provider reports them)
and duration (and "asked again for the review" when the agent had stopped
without one and wrote it only when asked, or "hit the time limit, then asked
for the review": NUDGED, from review.yml), so reviews from different models can be compared, plus what
the review covered (REVIEW_SCOPE, from previous.py) and a hidden marker with
the full head SHA, which previous.py reads to build the next re-review on.

Low findings are folded into <details> below the high and medium ones: they
are real but don't block a merge. With only low findings the count line says
so ("Nothing blocking"), so the author knows another round isn't needed.

A failed comment quotes the last error OpenCode reported from the model's
provider (an expired key, no credit, a rate limit), which is otherwise seen
nowhere: OpenCode writes it as an event and exits 1.

AGENT_RC is the agent's exit code. When it is not 0 (or unset: the agent
never ran), the comment says the review failed. When it is 0 but there is no
review block, the comment says there is no review. Either way any output is
folded away, so half-finished reasoning is never posted as a review, and the
heading starts with ⚠️, which the workflow treats as a failed run.

usage: render.py EVENTS_JSONL          print the comment
       render.py --check EVENTS_JSONL  exit 0 if the events hold a review,
                                       1 if not; prints nothing. The
                                       workflow uses it to decide whether to
                                       ask the agent again.

With SUMMARY_OUT set, a one-line summary for the workflow's commit status
is written there: the count line ("2 findings: 1 high, 1 low"), or why
there is no review.
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
    it look the same on every run. High and medium findings come first, then
    the low ones folded under <details>, numbered in that order. Lines that
    are not findings stay with the finding above them.

    Returns the decorated review and the count line in plain text.
    """
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    head = os.environ.get("HEAD_SHA", "")
    counts = {"high": 0, "medium": 0, "low": 0}
    findings = []  # [severity, list prefix, [first line without its prefix, more lines...]]
    preamble = []
    for line in review.split("\n"):
        m = FINDING.match(line)
        if not m:
            (findings[-1][2] if findings else preamble).append(line)
            continue
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
        findings.append([sev, m.group(1), [rest]])
    n = sum(counts.values())
    pre = "\n".join(preamble).strip()
    if not n:
        if pre.startswith("No issues found"):
            # Keep "Checked:" on its own line; Markdown joins adjacent lines.
            return "✅ " + pre.replace("\n", "\n\n", 1), "No issues found"
        return pre, "No findings"

    def plural(k, word="finding"):
        return f"{k} {word}{'s' if k != 1 else ''}"

    blocking = [f for f in findings if f[0] != "low"]
    lows = [f for f in findings if f[0] == "low"]
    if blocking:
        parts = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
        out = [f"**{plural(n)}**: {parts}"]
        status = f"{plural(n)}: {parts}"
    else:
        out = [f"✅ **Nothing blocking**: {plural(n, 'low finding')}, folded below."]
        status = f"Nothing blocking: {plural(n, 'low finding')}"
    if pre:
        out.append(pre)
    num = 0
    def show(f):
        nonlocal num
        num += 1
        sev, prefix, lines = f
        # Renumber a numbered list; a bulleted one keeps its bullet, so its
        # sub-bullets stay indented under it.
        prefix = f"{num}. " if prefix.strip()[0].isdigit() else prefix.lstrip()
        first = f"{prefix}{SEVERITY[sev]} · {lines[0]}"
        more = "\n".join(lines[1:]).strip("\n")
        return first + ("\n" + more if more else "")
    out += [show(f) for f in blocking]
    if lows:
        summary = plural(len(lows), "low finding") + (", not blocking" if blocking else "")
        out.append(f"<details><summary>{summary}</summary>")
        out += [show(f) for f in lows]
        out.append("</details>")
    return "\n\n".join(out), status


args = [a for a in sys.argv[1:] if a != "--check"]
check_only = len(args) != len(sys.argv) - 1

events = []
try:
    with open(args[0]) as f:
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


def provider_error():
    """What the last `error` event says, in one short line, or "".

    OpenCode reports a refused or failed model call (an expired key, no
    credit, a rate limit) as an event on stdout and exits 1; nothing reaches
    stderr. Without this the comment says only "exited with code 1".
    """
    for e in reversed(events):
        if e.get("type") != "error":
            continue
        err = e.get("error") or {}
        data = err.get("data") if isinstance(err, dict) else None
        data = data if isinstance(data, dict) else {}
        msg = data.get("message") or (err.get("message") if isinstance(err, dict) else "") or \
            (err.get("name") if isinstance(err, dict) else str(err)) or ""
        msg = " ".join(str(msg).replace("`", "'").split())[:200].rstrip(".")
        code = data.get("statusCode")
        if msg and isinstance(code, int):
            msg += f" (HTTP {code})"
        return msg
    return ""


said = provider_error()
agent_rc = os.environ.get("AGENT_RC", "")
failed = agent_rc != "0"
marked = False

full = "\n".join(texts)
def block_end(review):
    """A block cut at its closing marker; `review` starts after the opening."""
    # Stop at a line starting with REVIEW>>> (anything after it on that line
    # is dropped), else at a bare REVIEW line, else run to the end minus a
    # trailing ``` the model wrapped the block in.
    # A lowercase review>>> closes too; a bare line must be REVIEW exactly.
    for end in (r"^[ \t]*(?i:REVIEW)>>>?", r"^[ \t]*REVIEW[ \t]*\r?$"):
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
# two angle brackets instead of three, which small models write. So does a
# lowercase marker, and a ```review fence in place of the marker.
opens = list(re.finditer(r"(?:<<<?|```)(?i:REVIEW)[ \t]*\r?$", full, re.M))
for m in reversed(opens):
    block = block_end(full[m.end():])
    if squash(block) not in TEMPLATES:
        marked, review = True, block
        break


def unmarked(text):
    """The review in a message that has no markers, or None.

    Only a message with the review's own shape counts, so thinking aloud is
    still not posted: "No issues found." on a line of its own with a
    "Checked:" line right after it (whatever came before is dropped), or a
    list of findings, taken from the first one to the end of the message.
    """
    m = re.search(r"^[ \t]*No issues found\.?[ \t]*\r?\n(?:[ \t]*\r?\n)*[ \t]*(Checked:[^\r\n]*)", text, re.M)
    if m:
        return "No issues found.\n" + m.group(1).rstrip()
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if FINDING.match(line):
            return block_end("\n".join(lines[i:])) or None
    return None


if not marked and texts:
    found = unmarked(texts[-1])
    if found and squash(found) not in TEMPLATES:
        marked, review = True, found
if not marked:
    # No review: what's there is usually the model thinking aloud.
    review = texts[-1].strip() if texts else ""

if check_only:
    sys.exit(0 if marked else 1)

if len(review) > MAX:
    review = review[:MAX] + "\n\n_(truncated)_"

model = os.environ.get("MODEL_USED") or os.environ.get("MODEL", "?")
fell_back = os.environ.get("FELL_BACK", "")
sha = os.environ.get("HEAD_SHA", "")[:7]
elapsed = os.environ.get("ELAPSED", "?")
# The agent was asked once more for the review (review.yml): it had stopped
# without one, or ("late") hit its time limit, so it may not have read all
# it meant to.
nudged = {"": "", "late": " · hit the time limit, then asked for the review"}.get(
    os.environ.get("NUDGED", ""), " · asked again for the review")
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
    status = f"Review failed: {said or why}"
    print("### ⚠️ Agent review failed\n")
    print(f"No review: {why}. The [run log]({run_url}) has the details. "
          "Comment `/review` to retry.")
    if said:
        print(f"\nThe model's provider said: `{said}`")
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
    status = f"No review: the agent finished {what}"
    print(f"The agent finished {what}. The [run log]({run_url}) has the "
          "details. Comment `/review` to retry.")
    if said:
        print(f"\nThe model's provider said: `{said}`")
    if texts:
        print("\n<details><summary>Agent's last message (not a review)</summary>\n")
        print(review)
        print("\n</details>")
else:
    body, status = decorate(review)
    print("### 🔎 Agent review\n")
    print(body)
scope = os.environ.get("REVIEW_SCOPE", "").strip()
print("\n---")
print(f"<sub>OpenCode · `{model}`{' (fallback: ' + fell_back + ')' if fell_back else ''} · `{sha}` · {len(tools)} tool calls ({tool_summary}) · "
      f"{usage} · {elapsed}s{nudged} · {scope + ' · ' if scope else ''}[run]({run_url}) · "
      f"comment `/review` to re-run, `/review full` for the whole PR</sub>")
# Read by previous.py: the commit this review covers, for the next re-review.
full_sha = os.environ.get("HEAD_SHA", "")
if re.fullmatch(r"[0-9a-f]{40}", full_sha):
    print(f"<!-- agent-review head={full_sha} -->")

# GitHub refuses a status description over 140 characters.
summary_out = os.environ.get("SUMMARY_OUT")
if summary_out:
    with open(summary_out, "w", encoding="utf-8") as f:
        f.write(status if len(status) <= 140 else status[:139] + "…")
