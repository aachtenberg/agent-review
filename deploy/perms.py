#!/usr/bin/env python3
"""Does a repo's workflow grant every permission review.yml's job asks for?

GitHub won't start a reusable workflow whose job asks for a permission its
caller doesn't grant, so such a repo gets no reviews at all. Moving v1 to a
review.yml that asks for a new permission would do that to every repo whose
workflow hasn't been updated yet. release.sh checks each repo with this
first, and add-repo.sh uses --fix to open a PR that adds what's missing.

usage: perms.py REVIEW_YML CALLER_YML          prints each missing grant, e.g. `statuses: write`
       perms.py REVIEW_YML CALLER_YML --fix    prints the caller with them added

Reads the job's `permissions:` in review.yml, and the caller's: the block
of the job that `uses:` review.yml when it has one (GitHub then ignores the
top-level one for that job), else the top-level one. A block is
`name: level` lines or a shorthand (read-all, write-all, {}). Simple YAML
only, as in examples/agent-review.yml: jobs at the usual two-space indent.
Exits 2 when it can't tell, or when --fix can't add to the block (a
shorthand).
"""
import re
import sys

RANK = {"none": 0, "read": 1, "write": 2}
SHORTHAND = {"read-all": "read", "write-all": "write", "{}": "none"}


def find(lines, indent, lo=0, hi=None):
    """The `permissions:` key at this indent in lines[lo:hi], or None. Returns
    (every, grants, end, pad): `every` is the level a shorthand gives every
    name (None for a mapping, "?" for a value this can't read); grants is
    {name: (level, line index)}; end is the index just past the last grant;
    pad is the grants' indent."""
    hi = len(lines) if hi is None else hi
    head = re.compile(" " * indent + r"permissions:[ \t]*([^\s#]*)[ \t]*(#.*)?")
    start = next((i for i in range(lo, hi) if head.fullmatch(lines[i])), None)
    if start is None:
        return None
    value = head.fullmatch(lines[start]).group(1)
    if value:
        return SHORTHAND.get(value, "?"), {}, None, None
    grants, end, pad = {}, start + 1, None
    for i in range(start + 1, hi):
        l = lines[i]
        if not l.strip() or l.lstrip().startswith("#"):
            continue
        m = re.fullmatch(r"( +)([a-z-]+):[ \t]*(none|read|write)[ \t]*(#.*)?", l)
        # Grants are siblings, all at one indent deeper than the key.
        if not m or len(m.group(1)) <= indent or (pad and m.group(1) != pad):
            break
        pad = m.group(1)
        grants[m.group(2)] = (m.group(3), i)
        end = i + 1
    return None, grants, end, pad or " " * (indent + 2)


def cant(why):
    print(why, file=sys.stderr)
    sys.exit(2)


def main():
    review_path, caller_path, *rest = sys.argv[1:]
    fix = rest == ["--fix"]
    job = find(open(review_path, encoding="utf-8").read().split("\n"), 4)
    if not job or job[0]:
        sys.exit(f"{review_path}: the job has no permissions block of name: level lines")
    need = {k: lvl for k, (lvl, _) in job[1].items()}
    lines = open(caller_path, encoding="utf-8").read().split("\n")
    # The job that uses review.yml runs from its name line (indent 2) to the
    # next job's, or to the next top-level key.
    uses = next((i for i, l in enumerate(lines)
                 if re.fullmatch(r"    uses:\s*\S*\.github/workflows/review\.yml(@\S*)?\s*(#.*)?", l)), None)
    if uses is None:
        cant("no job that uses: review.yml")
    keys = [i for i, l in enumerate(lines) if re.match(r"""(  )?([A-Za-z0-9_-]+|"[^"]*"|'[^']*'):""", l)]
    lo = max((i for i in keys if i < uses), default=0)
    hi = min((i for i in keys if i > uses), default=len(lines))
    found = find(lines, 4, lo, hi) or find(lines, 0)
    if found is None:
        cant("no permissions: block")
    every, have, end, pad = found
    if every == "?":
        cant("a permissions: value this can't read")

    def level(k):
        return every or have.get(k, ("none",))[0]

    missing = [(k, lvl) for k, lvl in need.items() if RANK[level(k)] < RANK[lvl]]
    if not fix:
        for k, lvl in missing:
            print(f"{k}: {lvl}")
        return
    if missing and every:
        cant("permissions: is a shorthand, which can't be added to; list each permission instead")
    for k, lvl in missing:
        if k in have:  # granted, but at a lower level
            lines[have[k][1]] = f"{pad}{k}: {lvl}"
        else:
            lines.insert(end, f"{pad}{k}: {lvl}")
            end += 1
    sys.stdout.write("\n".join(lines))


main()
