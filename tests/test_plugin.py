"""End-to-end tests in a throwaway git repository, with stand-ins for the `entire` CLI and the Rehearsal client."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "entire-rehearsal"

FAKE_ENTIRE = """#!/usr/bin/env python3
import json, sys
# entire checkpoint explain <id> --json
print(json.dumps({"checkpoint_id": sys.argv[3], "sessions": [{"agent": "Claude Code", "model": "claude-test", "session_id": "s-" + sys.argv[3]}]}))
"""

# rehearsal.sdk stand-in: runs are read from RUNS_JSON, profiles and evaluations are recorded in CALLS_LOG
FAKE_SDK = """
import json, os
class _Runs:
    def get(self, run_id):
        return json.load(open(os.environ["RUNS_JSON"]))[run_id]
class _Profiles:
    def create(self, name, system_prompt="", **fields):
        open(os.environ["CALLS_LOG"], "a").write(json.dumps({"profile": name, "prompt": system_prompt, **fields}) + "\\n")
        return {"id": "prof_1", "version": 1}
class _Evaluations:
    def create(self, world, profile_ids, splits=None, repeats=None):
        open(os.environ["CALLS_LOG"], "a").write(json.dumps({"world": world, "profiles": profile_ids, "splits": splits, "repeats": repeats}) + "\\n")
        return {"run_id": "run_new", "episodes": 4}
class Rehearsal:
    def __init__(self):
        self.runs, self.profiles, self.evaluations = _Runs(), _Profiles(), _Evaluations()
"""


def overall(rate, finished=6, violations=0, false_done=0):
    return {"finished": finished, "success_rate": rate, "hard_violation_episodes": violations, "false_completions": false_done, "duplicate_effects": 0}


class PluginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        bin_dir, sdk_dir = self.tmp / "bin", self.tmp / "sdk" / "rehearsal" / "sdk"
        bin_dir.mkdir(); sdk_dir.mkdir(parents=True)
        (bin_dir / "entire").write_text(FAKE_ENTIRE); (bin_dir / "entire").chmod(0o755)
        (sdk_dir.parent / "__init__.py").write_text(""); (sdk_dir / "__init__.py").write_text(FAKE_SDK)
        self.runs = self.tmp / "runs.json"
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "PYTHONPATH": str(self.tmp / "sdk"),
                    "ENTIRE_PLUGIN_DATA_DIR": str(self.tmp / "data"), "RUNS_JSON": str(self.runs), "CALLS_LOG": str(self.tmp / "calls.log"),
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test"}
        self.env.pop("ENTIRE_REPO_ROOT", None)
        self.git("init", "-q", "-b", "main")
        self.shas = []
        for i, (text, checkpoint) in enumerate([("Be helpful.", "01CPAAAAAA"), ("Confirm before refunds.", "01CPBBBBBB"), ("Refund at once.", "")]):
            (self.repo / "prompt.md").write_text(text)
            (self.repo / f"other{i}.txt").write_text("x")
            self.git("add", ".")
            message = f"change {i}" + (f"\n\nEntire-Checkpoint: {checkpoint}" if checkpoint else "")
            self.git("commit", "-q", "-m", message)
            self.shas.append(self.git("rev-parse", "HEAD").strip())

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, env=self.env, check=True, capture_output=True, text=True).stdout

    def run_plugin(self, *args, check=True):
        p = subprocess.run([sys.executable, str(PLUGIN), *args], cwd=self.repo, env=self.env, capture_output=True, text=True)
        if check and p.returncode:
            self.fail(f"exit {p.returncode}: {p.stderr}")
        return p

    def test_history_lists_each_change_with_its_checkpoint_and_agent(self):
        out = self.run_plugin("history", "prompt.md").stdout
        self.assertIn("change 1", out)
        self.assertIn("checkpoint 01CPBBBBBB · Claude Code (claude-test)", out)
        self.assertIn("checkpoint — · no checkpoint", out)  # the last change was made without Entire
        self.assertEqual(out.count("checkpoint "), 3)

    def test_attach_and_report_flag_the_regression_and_its_session(self):
        self.runs.write_text(json.dumps({
            "run_a": {"status": "finished", "world_version_id": "wv_1", "summary": {"overall": overall(0.9)}},
            "run_b": {"status": "finished", "world_version_id": "wv_1", "summary": {"overall": overall(0.5, false_done=2)}},
        }))
        self.run_plugin("attach", "run_a", "prompt.md", "--commit", self.shas[1][:8])
        self.run_plugin("attach", "run_b", "prompt.md")  # the latest change
        out = self.run_plugin("report", "prompt.md").stdout
        lines = out.splitlines()
        newest = next(l for l in lines if l.startswith(self.shas[2][:8]))
        older = next(l for l in lines if l.startswith(self.shas[1][:8]))
        self.assertIn("needs work ▼ REGRESSION", newest)
        self.assertIn("2 false 'done'", newest)
        self.assertIn("ready to pilot", older)
        self.assertIn("changed in checkpoint 01CPBBBBBB by Claude Code", out)
        self.assertIn("changed without an Entire checkpoint", out)
        self.assertIn("entire checkpoint explain", out)

    def test_check_refuses_to_spend_without_confirmation(self):
        p = self.run_plugin("check", "prompt.md", "--world", "wv_1", check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--yes", p.stderr)
        self.assertFalse((self.tmp / "calls.log").exists())

    def test_check_rehearses_the_committed_prompt_and_records_it(self):
        self.runs.write_text(json.dumps({"run_new": {"status": "finished", "world_version_id": "wv_1", "summary": {"overall": overall(1.0)}}}))
        out = self.run_plugin("check", "prompt.md", "--world", "wv_1", "--yes", "--name", "support").stdout
        self.assertIn("ready to pilot", out)
        calls = [json.loads(l) for l in (self.tmp / "calls.log").read_text().splitlines()]
        self.assertEqual(calls[0], {"profile": "support", "prompt": "Refund at once."})
        self.assertEqual(calls[1], {"world": "wv_1", "profiles": ["prof_1"], "splits": ["dev"], "repeats": 1})
        self.assertIn("ready to pilot", self.run_plugin("history", "prompt.md").stdout)

    def test_a_file_outside_the_repository_is_refused(self):
        p = self.run_plugin("history", str(self.tmp / "elsewhere.md"), check=False)
        self.assertIn("not inside this repository", p.stderr)


class VerdictTest(unittest.TestCase):
    def setUp(self):
        import importlib.util
        from importlib.machinery import SourceFileLoader
        loader = SourceFileLoader("entire_rehearsal", str(PLUGIN))
        self.m = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(self.m)

    def test_the_readiness_bar(self):
        v = self.m.verdict
        self.assertEqual(v(overall(0.8)), "ready to pilot")
        self.assertEqual(v(overall(0.79)), "needs work")
        self.assertEqual(v(overall(1.0, violations=1)), "needs work")
        self.assertEqual(v(overall(1.0, false_done=1)), "needs work")
        self.assertEqual(v(overall(1.0, finished=2)), "not enough episodes")
        self.assertEqual(v({}), "not enough episodes")


if __name__ == "__main__":
    unittest.main()
