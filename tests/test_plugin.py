"""Every command, end to end, in throwaway git repositories, with stand-ins for the `entire` CLI and the Rehearsal client."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "entire-rehearsal"

# `entire checkpoint explain ID --json|--short` and `entire graph diff ... --json -- PATHS`
FAKE_ENTIRE = r"""#!/usr/bin/env python3
import json, sys
a = sys.argv[1:]
if a[:2] == ["checkpoint", "explain"]:
    cp = a[2]
    if "--json" in a:
        print(json.dumps({"checkpoint_id": cp, "sessions": [{"agent": "Claude Code", "model": "claude-test", "session_id": "s-" + cp}]}))
    else:
        print(f"● Checkpoint {cp}\n## Intent\n\nmake refunds faster for {cp}\n\n## Summary\nshort")
elif a[:2] == ["graph", "diff"]:
    paths = a[a.index("--") + 1:]
    print(json.dumps({"base": "x", "head": "y", "files": [{"path": paths[0] + "/refunds.py", "status": "M", "changes": [
        {"type": "body_changed", "kind": "function", "name": "lookup_order", "dependents_count": 1},
        {"type": "signature_changed", "kind": "function", "name": "refund_order", "dependents_count": 5}]}]}))
else:
    sys.exit(2)
"""

# rehearsal.sdk stand-in: runs come from RUNS_JSON; profile and evaluation calls are appended to CALLS_LOG
FAKE_SDK = """
import json, os
class RehearsalError(Exception):
    pass
class _Runs:
    def get(self, run_id):
        runs = json.load(open(os.environ["RUNS_JSON"]))
        if run_id not in runs:
            raise RehearsalError(f"404 run {run_id} not found")
        return runs[run_id]
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
        if os.environ.get("NOT_SIGNED_IN"):
            raise ValueError("no Rehearsal API key: run `rehearsal login`, or set REHEARSAL_API_KEY")
        self.runs, self.profiles, self.evaluations = _Runs(), _Profiles(), _Evaluations()
"""


def overall(rate, finished=6, violations=0, false_done=0):
    return {"finished": finished, "success_rate": rate, "hard_violation_episodes": violations, "false_completions": false_done, "duplicate_effects": 0}


def run(rate, **kw):
    return {"status": "finished", "world_version_id": "wv_1", "summary": {"overall": overall(rate, **kw)}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        bin_dir, sdk_dir = self.tmp / "bin", self.tmp / "sdk" / "rehearsal" / "sdk"
        bin_dir.mkdir(); sdk_dir.mkdir(parents=True)
        (bin_dir / "entire").write_text(FAKE_ENTIRE); (bin_dir / "entire").chmod(0o755)
        (sdk_dir.parent / "__init__.py").write_text(""); (sdk_dir / "__init__.py").write_text(FAKE_SDK)
        self.runs = self.tmp / "runs.json"
        self.runs.write_text("{}")
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "PYTHONPATH": str(self.tmp / "sdk"),
                    "RUNS_JSON": str(self.runs), "CALLS_LOG": str(self.tmp / "calls.log"), "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(self.tmp),
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test"}
        self.env.pop("ENTIRE_REPO_ROOT", None)
        self.repo = self.make_repo(self.tmp / "repo")

    def make_repo(self, path: Path) -> Path:
        path.mkdir()
        self.git(path, "init", "-q", "-b", "main")
        (path / "tools").mkdir()
        steps = [  # (file, text, checkpoint)
            ("prompt.md", "Be helpful.", "01CPAAAAAA"),
            ("tools/refunds.py", "def refund_order(order): ...", "01CPBBBBBB"),
            ("prompt.md", "Confirm before refunds.", "01CPCCCCCC"),
            ("prompt.md", "Refund at once.", ""),
            ("README.md", "unrelated", "01CPDDDDDD"),
        ]
        self.shas = []
        for i, (name, text, cp) in enumerate(steps):
            (path / name).write_text(text)
            self.git(path, "add", ".")
            self.git(path, "commit", "-q", "-m", f"change {i}" + (f"\n\nEntire-Checkpoint: {cp}" if cp else ""))
            self.shas.append(self.git(path, "rev-parse", "HEAD").strip())
        return path

    def git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True, capture_output=True, text=True).stdout

    def cmd(self, *args, cwd=None, code=0):
        p = subprocess.run([sys.executable, str(PLUGIN), *args], cwd=cwd or self.repo, env=self.env, capture_output=True, text=True)
        if code is not None and p.returncode != code:
            self.fail(f"{args}: exit {p.returncode} (wanted {code})\nstdout: {p.stdout}\nstderr: {p.stderr}")
        return p

    def runs_are(self, **runs):
        self.runs.write_text(json.dumps(runs))

    def notes(self, repo=None) -> str:
        p = subprocess.run(["git", "notes", "--ref=rehearsal", "list"], cwd=repo or self.repo, env=self.env, capture_output=True, text=True)
        return p.stdout.strip()


class InitAndHistory(Base):
    def test_history_of_one_file_lists_each_change_with_its_checkpoint_and_agent(self):
        out = self.cmd("history", "prompt.md").stdout
        self.assertEqual(out.count("checkpoint "), 3)  # the tool and README commits did not touch prompt.md
        self.assertIn("checkpoint 01CPCCCCCC · Claude Code (claude-test)", out)
        self.assertIn("checkpoint — · no checkpoint", out)

    def test_init_describes_the_agent_and_history_covers_its_tool_code_with_the_graph(self):
        out = self.cmd("init", "prompt.md", "--code", "tools", "--world", "wv_1").stdout
        self.assertIn("wrote .entire/rehearsal.json", out)
        cfg = json.loads((self.repo / ".entire/rehearsal.json").read_text())
        self.assertEqual(cfg, {"instructions": "prompt.md", "code": ["tools"], "world": "wv_1", "split": "dev"})
        out = self.cmd("history").stdout
        self.assertIn("[code]  change 1", out)
        self.assertIn("code       refund_order signature changed (5 dependents), lookup_order changed (1 dependents)", out)
        self.assertNotIn("change 4", out)  # README is not part of the agent
        rows = json.loads(self.cmd("history", "--json").stdout)
        self.assertEqual([r["parts"] for r in rows], [["instructions"], ["instructions"], ["code"], ["instructions"]])
        self.assertNotIn("refund_order", self.cmd("history", "--no-graph").stdout)

    def test_init_refuses_missing_paths(self):
        self.assertIn("does not exist", self.cmd("init", "nope.md", code=1).stderr)
        self.assertIn("does not exist", self.cmd("init", "prompt.md", "--code", "missing", code=1).stderr)

    def test_without_a_file_or_config_it_says_what_to_do(self):
        self.assertIn("entire rehearsal init", self.cmd("history", code=1).stderr)

    def test_a_file_outside_the_repository_is_refused(self):
        self.assertIn("not inside this repository", self.cmd("history", str(self.tmp / "elsewhere.md"), code=1).stderr)

    def test_works_from_a_subdirectory(self):
        self.assertIn("Changes to the agent (prompt.md)", self.cmd("history", "../prompt.md", cwd=self.repo / "tools").stdout)

    def test_outside_a_repository_it_says_so(self):
        self.assertIn("inside a git repository", self.cmd("history", "x.md", cwd=self.tmp, code=1).stderr)


class Results(Base):
    def setUp(self):
        super().setUp()
        self.cmd("init", "prompt.md", "--code", "tools", "--world", "wv_1")

    def test_status_lists_untested_changes_until_the_current_version_is_rehearsed(self):
        out = self.cmd("status").stdout
        self.assertIn("Last rehearsed:  never", out)
        self.assertIn("4 changes not rehearsed yet", out)
        self.assertIn("code: refund_order signature changed", out)
        self.runs_are(run_a=run(0.9))
        self.cmd("attach", "run_a", "--commit", self.shas[1][:8])  # the tool change
        state = json.loads(self.cmd("status", "--json").stdout)
        self.assertFalse(state["tested"])
        self.assertEqual([c["commit"] for c in state["untested_changes"]], [self.shas[3], self.shas[2]])
        self.assertEqual(state["last_rehearsed"]["commit"], self.shas[1])
        self.runs_are(run_b=run(1.0))
        self.cmd("attach", "run_b")
        self.assertIn("The current version is rehearsed.", self.cmd("status").stdout)
        self.assertTrue(json.loads(self.cmd("status", "--json").stdout)["tested"])

    def test_results_are_git_notes_on_the_rehearsed_commit(self):
        self.runs_are(run_a=run(0.9))
        self.cmd("attach", "run_a")
        note = json.loads(self.git(self.repo, "notes", "--ref=rehearsal", "show", self.shas[3]).strip())
        self.assertEqual((note["agent"], note["run_id"], note["verdict"]), ("prompt.md", "run_a", "ready to pilot"))

    def test_report_flags_a_regression_with_the_session_and_what_was_asked(self):
        self.runs_are(run_a=run(0.9), run_b=run(0.5, false_done=2), run_c=run(0.9))
        self.cmd("attach", "run_c", "--commit", self.shas[0][:8])
        self.cmd("attach", "run_b", "--commit", self.shas[1][:8])  # the tool change made it worse
        self.cmd("attach", "run_a", "--commit", self.shas[2][:8])
        out = self.cmd("report").stdout
        line = {l[:8]: l for l in out.splitlines() if l[:8] in {s[:8] for s in self.shas}}
        self.assertIn("needs work ▼ REGRESSION", line[self.shas[1][:8]])
        self.assertIn("2 false 'done'", line[self.shas[1][:8]])
        self.assertIn("ready to pilot ▲ better", line[self.shas[2][:8]])
        self.assertIn("ready to pilot  90%", line[self.shas[0][:8]])
        self.assertIn('asked for: "make refunds faster for 01CPBBBBBB"', out)
        self.assertIn("changed in checkpoint 01CPBBBBBB by Claude Code (claude-test)", out)
        self.assertIn("entire checkpoint explain", out)
        rows = json.loads(self.cmd("report", "--json").stdout)
        self.assertEqual([r["change"] for r in rows], ["better", "regression", None])

    def test_report_without_results_says_how_to_get_one(self):
        self.assertIn("entire rehearsal check", self.cmd("report", code=1).stderr)

    def test_attach_refuses_unfinished_unknown_or_unrelated(self):
        self.runs_are(run_q={"status": "running", "summary": {}})
        self.assertIn("is running", self.cmd("attach", "run_q", code=1).stderr)
        self.assertIn("Rehearsal refused the request", self.cmd("attach", "run_missing", code=1).stderr)
        self.assertIn("did not change the agent", self.cmd("attach", "run_q", "--commit", self.shas[4][:8], code=1).stderr)
        self.assertEqual(self.notes(), "")

    def test_without_a_sign_in_it_says_how_to_sign_in(self):
        self.env["NOT_SIGNED_IN"] = "1"
        err = self.cmd("attach", "run_a", code=1).stderr
        self.assertIn("rehearsal login", err)
        self.assertIn("ENTIRE_PLUGIN_ENV='REHEARSAL_*'", err)
        self.assertNotIn("Traceback", err)
        self.assertNotIn("Traceback", self.cmd("check", "--yes", code=1).stderr)

    def test_without_the_client_it_says_how_to_install_it(self):
        if importlib.util.find_spec("rehearsal") is not None:
            self.skipTest("rehearsal-kit is installed in this interpreter")
        self.env["PYTHONPATH"] = str(self.tmp / "nothing")
        self.assertIn("pip install rehearsal-kit", self.cmd("attach", "run_a", code=1).stderr)

    def test_gate_passes_only_a_rehearsed_ready_current_version(self):
        self.assertIn("has not been rehearsed", self.cmd("gate", code=1).stderr)
        self.runs_are(run_a=run(0.83))
        self.cmd("attach", "run_a")
        self.assertIn("ready to pilot", self.cmd("gate", code=0).stdout)
        self.assertIn("needs work", self.cmd("gate", "--min-success", "0.9", code=1).stdout)
        self.runs_are(run_b=run(1.0, violations=1))
        self.cmd("attach", "run_b")
        self.cmd("gate", code=1)

    def test_check_asks_before_spending_and_records_the_result(self):
        self.assertIn("--yes", self.cmd("check", code=1).stderr)
        self.assertFalse((self.tmp / "calls.log").exists())
        self.runs_are(run_new=run(1.0))
        out = self.cmd("check", "--yes", "--name", "support").stdout
        self.assertIn("rehearsing support v1 on wv_1 (dev): run run_new, 4 episodes", out)
        self.assertIn("ready to pilot", out)
        calls = [json.loads(l) for l in (self.tmp / "calls.log").read_text().splitlines()]
        self.assertEqual(calls, [{"profile": "support", "prompt": "Refund at once."},
                                 {"world": "wv_1", "profiles": ["prof_1"], "splits": ["dev"], "repeats": 1}])
        self.cmd("gate", code=0)

    def test_check_needs_a_world(self):
        self.assertIn("--world", self.cmd("check", "README.md", "--yes", code=1).stderr)

    def test_check_marks_uncommitted_changes_as_dirty(self):
        (self.repo / "prompt.md").write_text("Edited, not committed.")
        self.runs_are(run_new=run(1.0))
        self.assertIn("marked dirty", self.cmd("check", "--yes").stderr)
        note = json.loads(self.git(self.repo, "notes", "--ref=rehearsal", "show", self.shas[3]).strip())
        self.assertTrue(note["dirty"])

    def test_check_no_wait_starts_the_run_and_records_nothing_yet(self):
        self.runs_are(run_new={"status": "running", "summary": {}})
        self.assertIn("entire rehearsal attach run_new", self.cmd("check", "--yes", "--no-wait").stdout)
        self.assertEqual(self.notes(), "")


class Sync(Base):
    def test_results_travel_to_a_teammate_through_the_remote(self):
        remote = self.tmp / "remote.git"
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", str(remote))
        self.git(self.repo, "remote", "add", "origin", str(remote))
        self.git(self.repo, "push", "-q", "origin", "main")
        self.assertIn("no results to share", self.cmd("sync", code=1).stderr)
        self.runs_are(run_a=run(0.9))
        self.cmd("attach", "run_a", "prompt.md")
        self.assertIn("shared rehearsal results with origin", self.cmd("sync").stdout)
        mate = self.tmp / "mate"
        self.git(self.tmp, "clone", "-q", str(remote), str(mate))
        self.assertIn("no rehearsal results", self.cmd("report", "prompt.md", cwd=mate, code=1).stderr)
        self.cmd("sync", cwd=mate)
        self.assertIn("ready to pilot", self.cmd("report", "prompt.md", cwd=mate).stdout)


class Pure(unittest.TestCase):
    def setUp(self):
        loader = SourceFileLoader("entire_rehearsal", str(PLUGIN))
        self.m = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(self.m)

    def test_the_readiness_bar(self):
        v = self.m.verdict
        self.assertEqual(v(overall(0.8)), "ready to pilot")
        self.assertEqual(v(overall(0.79)), "needs work")
        self.assertEqual(v(overall(0.79), min_success=0.7), "ready to pilot")
        self.assertEqual(v(overall(1.0, violations=1)), "needs work")
        self.assertEqual(v(overall(1.0, false_done=1)), "needs work")
        self.assertEqual(v(overall(1.0, finished=2)), "not enough episodes")
        self.assertEqual(v({}), "not enough episodes")

    def test_code_change_summary(self):
        found = [{"name": f"f{i}", "type": "body_changed", "dependents": i} for i in range(5)]
        self.assertEqual(self.m.describe_code(found), "f0 changed (0 dependents), f1 changed (1 dependents), f2 changed (2 dependents), +2 more")
        module = [{"name": "agent/llm.py", "kind": "module", "type": "body_changed", "dependents": 0}]
        self.assertEqual(self.m.describe_code(module), "top-level code in agent/llm.py changed")


if __name__ == "__main__":
    unittest.main()
