#!/usr/bin/env python3
"""The Review step of review.yml, run with a stand-in for docker.

Run:  python3 -m unittest discover -s tests

The step's shell is taken out of the workflow file and run as it is. The
stand-in `docker` writes canned agent events, chosen by scenario, model and
whether the call is the ask-again (`opencode run --continue`), after a stop
or after the time limit. Checked: which
runs happen, what the step tells the post step ($GITHUB_ENV), and what
render.py then makes of the events.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
MAIN, FALLBACK, KEY = "openrouter/z-ai/glm-5.3-flash", "ollama/gemma4:26b", "sk-or-not-a-real-key"

DOCKER = r'''#!/usr/bin/env bash
echo "docker $*" >> "$STUB_LOG"
[ "$1" = volume ] && exit 0
model="" again=0 prev=""
for a in "$@"; do
  [ "$prev" = --model ] && model=$a
  [ "$a" = --continue ] && again=1
  prev=$a
done
say() { printf '{"type":"text","part":{"text":"%s"}}\n' "$1"; }
review='<<<REVIEW\nNo issues found.\nChecked: the diff, with '"$OPENROUTER_API_KEY"'.\nREVIEW>>>'
case "$SCENARIO:$model:$again" in
  ok:*:0) say "$review" ;;
  stops:*:0) say "Let me examine llm.py." ;;
  stops:*:1) say "$review" ;;
  stuck*:openrouter/*:0) say "Let me examine llm.py." ;;
  stuck*:openrouter/*:1) say "Let me keep looking." ;;
  stuck_fallback:ollama/*:0) say "$review" ;;
  late:*:0) say "partial"; exit 124 ;;
  done_late:*:0) say "$review"; exit 124 ;;
  done_late:*:1) say "<<<REVIEW\nNo issues found.\nChecked: less.\nREVIEW>>>" ;;
  late:*:1) say "$review" ;;
  timeout:openrouter/*:0) say "partial"; exit 124 ;;
  timeout:openrouter/*:1) say "Still reading."; exit 124 ;;
  timeout:ollama/*:0) say "The change looks solid." ;;
  timeout:ollama/*:1) say "$review" ;;
esac
'''


def read(path):
    with open(path) as f:
        return f.read()


def review_step():
    """The `run:` script of the step named Review."""
    lines = read(os.path.join(ROOT, ".github", "workflows", "review.yml")).split("\n")
    i = lines.index("      - name: Review")
    while lines[i].strip() != "run: |":
        i += 1
    indent = len(lines[i]) - len(lines[i].lstrip()) + 2
    body = []
    for line in lines[i + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:])
    return "\n".join(body)


class ReviewStep(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        d = self.dir
        for sub in ("bin", "tmp", "ws/reviewer"):
            os.makedirs(os.path.join(d, sub))
        shutil.copytree(os.path.join(ROOT, "review"), os.path.join(d, "ws/reviewer/review"))
        with open(os.path.join(d, "bin/docker"), "w") as f:
            f.write(DOCKER)
        os.chmod(os.path.join(d, "bin/docker"), 0o755)
        git = ["git", "-C", os.path.join(d, "ws/pr"), "-c", "user.email=t@example.com", "-c", "user.name=t"]
        subprocess.run(["git", "init", "-q", os.path.join(d, "ws/pr")], check=True)
        subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "base"], check=True)
        self.sha = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()

    def run_step(self, scenario, fallback=""):
        """(what the step wrote to $GITHUB_ENV, docker calls, the comment)."""
        d, tmp = self.dir, os.path.join(self.dir, "tmp")
        env = {
            "PATH": os.path.join(d, "bin") + os.pathsep + os.environ["PATH"],
            "STUB_LOG": os.path.join(tmp, "docker.log"), "SCENARIO": scenario,
            "GITHUB_WORKSPACE": os.path.join(d, "ws"), "RUNNER_TEMP": tmp,
            "GITHUB_ENV": os.path.join(tmp, "env"), "AGENT_IMAGE": "image",
            "MODEL": MAIN, "FALLBACK_MODEL": fallback, "OLLAMA_BASE_URL": "",
            "OPENROUTER_API_KEY": KEY, "BASE_SHA": self.sha, "HEAD_SHA": self.sha,
            "BASE_REF": "main", "PR_NUMBER": "1", "GITHUB_REPOSITORY": "o/r", "PREV_SHA": "", "SESSION_VOLUME": "vol",
        }
        p = subprocess.run(["bash", "-e", "-c", review_step()], cwd=os.path.join(d, "ws"),
                           env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        out = dict(l.split("=", 1) for l in read(env["GITHUB_ENV"]).splitlines())
        calls = [l for l in read(env["STUB_LOG"]).splitlines() if l.startswith("docker run ")]
        for name in os.listdir(tmp):  # nothing left in the temp dir holds the key
            if name != "env":
                self.assertNotIn(KEY, read(os.path.join(tmp, name)), name)
        r = subprocess.run([sys.executable, "-I", os.path.join(d, "ws/reviewer/review/render.py"),
                            os.path.join(tmp, "events.jsonl")], capture_output=True, text=True,
                           env={**out, "PATH": os.environ["PATH"], "HEAD_SHA": self.sha, "GITHUB_REPOSITORY": "o/r"})
        return out, calls, r.stdout

    def test_review_first_time(self):
        out, calls, comment = self.run_step("ok")
        self.assertEqual(len(calls), 1)
        self.assertIn("-v vol:/root/.local/share/opencode", calls[0])
        self.assertIn("-e OPENROUTER_API_KEY", calls[0])
        self.assertEqual((out["AGENT_RC"], out["NUDGED"], out["FELL_BACK"]), ("0", "", ""))
        self.assertTrue(comment.startswith("### 🔎 Agent review"))
        self.assertNotIn("asked again", comment)

    def test_stops_early_then_writes_it_when_asked(self):
        out, calls, comment = self.run_step("stops")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("--continue", calls[0])
        self.assertIn("timeout 300 opencode run --model " + MAIN + " --format json --continue", calls[1])
        self.assertEqual((out["AGENT_RC"], out["NUDGED"], out["MODEL_USED"]), ("0", "stopped", MAIN))
        self.assertTrue(comment.startswith("### 🔎 Agent review"))
        self.assertIn("· asked again for the review ·", comment)

    def test_still_no_review_and_no_fallback(self):
        out, calls, comment = self.run_step("stuck")
        self.assertEqual(len(calls), 2)
        self.assertEqual((out["AGENT_RC"], out["AGENT_NOTE"], out["FELL_BACK"]), ("0", "", ""))
        self.assertTrue(comment.startswith("### ⚠️ No review"))

    def test_still_no_review_goes_to_the_fallback(self):
        out, calls, comment = self.run_step("stuck_fallback", FALLBACK)
        self.assertEqual(len(calls), 3)
        self.assertNotIn("-e OPENROUTER_API_KEY", calls[2])
        self.assertEqual((out["MODEL_USED"], out["FELL_BACK"], out["NUDGED"]),
                         (FALLBACK, MAIN + " wrote no review", ""))
        self.assertTrue(comment.startswith("### 🔎 Agent review"))
        self.assertIn("(fallback: " + MAIN + " wrote no review)", comment)

    def test_out_of_time_then_writes_it_when_asked(self):
        # secondlook #8 on 2026-11-12: 50 steps of reading, no review, 124.
        out, calls, comment = self.run_step("late")
        self.assertEqual(len(calls), 2)
        self.assertIn("timeout 300 opencode run --model " + MAIN + " --format json --continue You ran out of time", calls[1])
        self.assertEqual((out["AGENT_RC"], out["NUDGED"], out["AGENT_NOTE"], out["FELL_BACK"]), ("0", "late", "", ""))
        self.assertTrue(comment.startswith("### 🔎 Agent review"))
        self.assertIn("· hit the time limit, then asked for the review ·", comment)

    def test_out_of_time_after_the_review_is_not_asked_again(self):
        out, calls, comment = self.run_step("done_late")
        self.assertEqual(len(calls), 1)
        self.assertEqual((out["AGENT_RC"], out["NUDGED"], out["AGENT_NOTE"]), ("0", "", ""))
        self.assertIn("Checked: the diff", comment)

    def test_out_of_time_twice_goes_to_the_fallback(self):
        out, calls, comment = self.run_step("timeout", FALLBACK)
        self.assertEqual([("--continue" in c, FALLBACK in c) for c in calls],
                         [(False, False), (True, False), (False, True), (True, True)])
        self.assertEqual((out["AGENT_RC"], out["FELL_BACK"], out["NUDGED"]),
                         ("0", MAIN + " exited 124", "stopped"))
        self.assertTrue(comment.startswith("### 🔎 Agent review"))
        self.assertIn("· asked again for the review ·", comment)

    def test_out_of_time_twice_without_a_fallback_fails(self):
        out, calls, comment = self.run_step("timeout")
        self.assertEqual(len(calls), 2)
        self.assertEqual((out["AGENT_RC"], out["AGENT_NOTE"]), ("124", MAIN + " exited 124"))
        self.assertTrue(comment.startswith("### ⚠️ Agent review failed"))

    def test_the_log_says_where_it_ran(self):
        self.run_step("ok")
        first = read(os.path.join(self.dir, "tmp", "agent.log")).splitlines()[0]
        self.assertIn("o/r#1 " + self.sha[:7] + " · full review · image", first)

if __name__ == "__main__":
    unittest.main()
