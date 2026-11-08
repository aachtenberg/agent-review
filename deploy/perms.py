#!/usr/bin/env python3
"""Does a repo's workflow grant every permission review.yml's job asks for?

GitHub won't start a reusable workflow whose job asks for a permission its
caller doesn't grant, so such a repo gets no reviews at all. Moving v1 to a
review.yml that asks for a new permission would do that to every repo whose
workflow hasn't been updated yet. release.sh checks each repo with this
first, and add-repo.sh uses --fix to open a PR that adds what's missing.

usage: perms.py REVIEW_YML CALLER_YML          prints each missing grant, e.g. `statuses: write`
       perms.py REVIEW_YML CALLER_YML --fix    prints the caller with them added

Reads the job's `permissions:` block in review.yml and the caller's
top-level one: plain `name: level` lines, as in examples/agent-review.yml.
Exits 2 when the caller has no such block, which it can't check or fix.
"""
import re
import sys

RANK = {"none": 0, "read": 1, "write": 2}


def block(lines, indent):
    """The first `permissions:` mapping at this indent, as {name: (level, line index)},
    and the index just past its last entry. (None, None) when there isn't one."""
    pad = " " * indent
    start = next((i for i, l in enumerate(lines) if re.fullmatch(pad + r"permissions:\s*(#.*)?", l)), None)
    if start is None:
        return None, None
    grants, end = {}, start + 1
    for i in range(start + 1, len(lines)):
        l = lines[i]
        if not l.strip() or l.lstrip().startswith("#"):
            continue
        m = re.fullmatch(pad + r"  ([a-z-]+):\s*(none|read|write)\s*(#.*)?", l)
        if not m:
            break
        grants[m.group(1)] = (m.group(2), i)
        end = i + 1
    return grants, end


def main():
    review_path, caller_path, *rest = sys.argv[1:]
    fix = rest == ["--fix"]
    need, _ = block(open(review_path, encoding="utf-8").read().split("\n"), 4)
    if need is None:
        sys.exit(f"{review_path}: the job has no permissions block")
    caller = open(caller_path, encoding="utf-8").read()
    lines = caller.split("\n")
    if re.search(r"^permissions:\s*write-all\b", caller, re.M):
        have, end = {k: ("write", None) for k in need}, None
    else:
        have, end = block(lines, 0)
        if have is None:
            print("no top-level permissions: block", file=sys.stderr)
            sys.exit(2)
    missing = [(k, lvl) for k, (lvl, _) in need.items() if RANK[have.get(k, ("none",))[0]] < RANK[lvl]]
    if not fix:
        for k, lvl in missing:
            print(f"{k}: {lvl}")
        return
    for k, lvl in missing:
        if k in have:  # granted, but only `read`
            lines[have[k][1]] = f"  {k}: {lvl}"
        else:
            lines.insert(end, f"  {k}: {lvl}")
            end += 1
    sys.stdout.write("\n".join(lines))


main()
