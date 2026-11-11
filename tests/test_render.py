#!/usr/bin/env python3
"""What render.py takes for a review, and what it doesn't.

Run:  python3 -m unittest discover -s tests

The cases under "a week of no-reviews" are the shapes of the agent's last
message in the twelve runs that ended in "⚠️ No review" between 2026-11-07
and 2026-11-11. Half of them were finished reviews that the renderer threw
away because the markers were missing. Those must now be posted, and the
ones that really are not reviews must still be refused. The wording is
shortened, and rewritten where the run was in a private repo.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

RENDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "review", "render.py")
HEAD = "a" * 40


def render(*texts, rc="0", check=False):
    """(exit code, comment) for an agent run that wrote these messages."""
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for t in texts:
            f.write(json.dumps({"type": "text", "part": {"text": t}}) + "\n")
    try:
        env = {"PATH": os.environ.get("PATH", ""), "AGENT_RC": rc, "HEAD_SHA": HEAD,
               "GITHUB_REPOSITORY": "o/r", "MODEL": "test/model"}
        cmd = [sys.executable, "-I", RENDER] + (["--check"] if check else []) + [f.name]
        p = subprocess.run(cmd, capture_output=True, text=True, env=env)
        return p.returncode, p.stdout
    finally:
        os.unlink(f.name)


class Case(unittest.TestCase):
    def review(self, *texts):
        """The comment, after checking it is a review."""
        rc, out = render(*texts)
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("### 🔎 Agent review"), out)
        self.assertEqual(render(*texts, check=True), (0, ""))
        return out

    def no_review(self, *texts):
        """The comment, after checking it is not a review."""
        rc, out = render(*texts)
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("### ⚠️ No review"), out)
        self.assertEqual(render(*texts, check=True), (1, ""))
        return out


class Marked(Case):
    def test_clean(self):
        out = self.review("<<<REVIEW\nNo issues found.\nChecked: the diff and its callers.\nREVIEW>>>")
        self.assertIn("✅ No issues found.\n\nChecked: the diff and its callers.", out)

    def test_findings(self):
        out = self.review("thinking\n<<<REVIEW\n1. **[high]** `a/b.py:3`: breaks.\n"
                          "   - **Breaks:** x.\n   - **Fix:** y.\nREVIEW>>>")
        self.assertIn("**1 finding**: 1 high", out)
        self.assertIn(f"[`a/b.py:3`](https://github.com/o/r/blob/{HEAD}/a/b.py#L3)", out)

    def test_quoted_example_is_not_a_review(self):
        self.no_review("<<<REVIEW\nNo issues found.\nChecked: <one line: what you read and traced>\nREVIEW>>>")

    def test_failed_agent(self):
        rc, out = render("<<<REVIEW\nNo issues found.\nChecked: x.\nREVIEW>>>", rc="124")
        self.assertTrue(out.startswith("### ⚠️ Agent review failed"), out)


class AWeekOfNoReviews(Case):
    # Finished reviews without the markers: posted now.

    def test_clean_without_markers(self):
        # agent-review #15, esp32-lora-sensor #5
        out = self.review("Let me read the caller.",
                          "No issues found.\nChecked: one commit since ac91bd5 (deploy/perms.py only); "
                          "traced its job detection against examples/agent-review.yml.")
        self.assertIn("✅ No issues found.\n\nChecked: one commit since ac91bd5", out)
        self.assertNotIn("Let me read the caller", out)

    def test_clean_with_a_blank_line_before_checked(self):
        out = self.review("No issues found.\n\nChecked: the diff, the full manifest and both overlays.")
        self.assertIn("✅ No issues found.\n\nChecked: the diff, the full manifest and both overlays.", out)

    def test_clean_after_stray_headings(self):
        out = self.review("Recommendation\n\nKey takeways\n\n\nFindings\n\nEvidence\n\nDecision:\n\n"
                          "No issues found.\nChecked: the full diff and the workflow's history.")
        self.assertIn("✅ No issues found.\n\nChecked: the full diff", out)
        self.assertNotIn("Key takeways", out)

    def test_fence_and_lowercase_marker(self):
        out = self.review("# 回复\n\n```review\n未发现问题。\n已检查：diff 与四条提交记录。\nreview>>>")
        self.assertIn("未发现问题。", out)
        self.assertNotIn("review>>>", out)
        self.assertNotIn("```", out)

    # Not reviews: still refused.

    def test_stopped_mid_investigation(self):
        # secondlook #6, the run that prompted this
        out = self.no_review("Let me examine llm.py and chat.py to verify the tool-calling conventions.")
        self.assertIn("Agent's last message (not a review)", out)

    def test_nothing_written(self):
        self.assertIn("without writing anything", self.no_review())

    def test_tool_calls_written_as_text(self):
        self.no_review("** bash**\n* Command: `git-ro diff aaa...bbb`\n* Workdir: `/work`\n* Timeout: `120000 (ms)`")

    def test_prose_verdict(self):
        self.no_review("I have reviewed the changes in `ansible/deploy.yml`.\n\n"
                       "The plan to move the storage looks solid.")

    def test_no_issues_without_a_checked_line(self):
        self.no_review("`No issues found.` verified against full context:\n\n- Read `poller.py` end-to-end.")


class Unmarked(Case):
    def test_findings_without_markers(self):
        out = self.review("Done reading.\n\n1. **[medium]** `x.py:9`: wrong default.\n   - **Breaks:** a.\n"
                          "   - **Fix:** b.\n\n2. **[low]** `y.py:1`: stale comment.\n   - **Breaks:** c.\n   - **Fix:** d.")
        self.assertIn("**2 findings**: 1 medium, 1 low", out)
        self.assertNotIn("Done reading", out)

    def test_only_the_last_message_counts(self):
        # "No issues found" said along the way is not the verdict.
        self.no_review("No issues found.\nChecked: the first file.", "Let me look at the second file.")

    def test_no_issues_mid_sentence(self):
        self.no_review("So far no issues found. Checked: nothing yet, let me read on.")

    def test_a_marked_block_wins(self):
        out = self.review("<<<REVIEW\n1. **[high]** `a.py:1`: bad.\n   - **Breaks:** x.\n   - **Fix:** y.\nREVIEW>>>",
                          "No issues found.\nChecked: something else.")
        self.assertIn("1 high", out)


if __name__ == "__main__":
    unittest.main()
