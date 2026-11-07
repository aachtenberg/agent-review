This is a re-review. An earlier review of this PR, at commit {{PREV_SHA}},
covered the PR up to that commit. Its findings are at the end of this section.
Since then the author has added commits, usually to fix those findings.

Your job is narrower than a first review:
1. Check each earlier **high** or **medium** finding against the code at
   {{HEAD_SHA}}. If the problem is still there, in that place or any other
   it listed, report it again with the same severity. If it is fixed, leave
   it out.
2. Review what changed since the earlier review, as carefully as a first
   review. Start with these two bash commands:
   `git-ro diff {{PREV_SHA}}..{{HEAD_SHA}}` and
   `git-ro log --oneline {{PREV_SHA}}..{{HEAD_SHA}}`. A fix can break
   something else, so follow each new change to what uses it.
3. Don't review the rest of the PR again: the earlier review covered it.
   Read older code only to judge the new changes. The whole PR is
   `git-ro diff {{BASE_SHA}}...{{HEAD_SHA}}` if you need it.
4. Don't report an earlier **low** finding again, fixed or not.

The earlier review's findings:

{{PREV_FINDINGS}}

(End of the earlier findings.)
