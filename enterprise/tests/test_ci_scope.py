"""Exercise full Git diffs and fail-safe CI selection without application startup."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("ci_scope", ROOT / "enterprise/tests/check_ci_scope.py")
SCOPE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCOPE)


class ScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ice-ci-scope-")
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@invalid")
        self.git("config", "user.name", "CI scope fixture")
        self.git("config", "core.autocrlf", "false")
        self.write("main.py", "pass\n")
        self.base = self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo).decode("utf-8").strip()

    def write(self, path, text="reference\n"):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def select(self, head=None, event="pull_request", base=None):
        return SCOPE.plan(self.repo, event, base or self.base, head or self.commit())

    def test_collaboration_and_wiki_only(self):
        for path in (*SCOPE.DOC_PATHS, "docs/code-wiki/中文 reference.md"):
            self.write(path)
        result = self.select()
        self.assertFalse(result["full_suite"])
        self.assertEqual(len(result["files"]), len(SCOPE.DOC_PATHS) + 1)

    def test_unknown_runtime_security_build_and_prompt_paths_run_full(self):
        for path in ("main.py", "enterprise/db.py", "enterprise/gateway.py",
                     "enterprise/providers/zhenzhen.py", "runtime/windows/requirements.lock",
                     "installer/windows/InfiniteCanvasEnterprise.iss", "requirements.txt",
                     "prompts/task.md", "LICENSE.md", "docs/decisions/contract.md",
                     ".github/workflows/documentation-checks.yml", "new-file.md"):
            with self.subTest(path=path):
                previous = self.git("rev-parse", "HEAD")
                self.write(path, "changed\n")
                self.assertTrue(self.select(base=previous)["full_suite"])

    def test_more_than_300_paths_cannot_hide_runtime_change(self):
        for index in range(350):
            self.write(f"docs/code-wiki/page-{index}.md")
        self.write("enterprise/gateway.py", "pass\n")
        result = self.select()
        self.assertEqual(len(result["files"]), 351)
        self.assertTrue(result["full_suite"])

    def test_move_runtime_file_to_documentation_still_runs_full(self):
        self.git("mv", "main.py", "CONTRIBUTING.md")
        result = self.select()
        self.assertIn("main.py", result["files"])
        self.assertTrue(result["full_suite"])

    def test_removed_document_and_runtime_file_are_distinguished(self):
        self.write("CONTRIBUTING.md")
        base = self.commit()
        (self.repo / "CONTRIBUTING.md").unlink()
        self.assertFalse(self.select(base=base)["full_suite"])
        (self.repo / "main.py").unlink()
        self.assertTrue(self.select()["full_suite"])

    def test_missing_history_empty_diff_and_non_pr_run_full(self):
        self.assertTrue(self.select(head=self.base)["full_suite"])
        self.assertTrue(self.select(head=self.base, base="f" * 40)["full_suite"])
        self.assertTrue(self.select(head=self.base, base="--invalid")["full_suite"])
        for event in ("push", "workflow_dispatch", "unknown"):
            self.write("CONTRIBUTING.md", event)
            self.assertTrue(self.select(event=event)["full_suite"])

    def test_symlink_executable_and_malformed_diff_run_full(self):
        for modes in (("100644", "120000"), ("100644", "100755")):
            raw = f":{modes[0]} {modes[1]} aaaaaaa bbbbbbb T\0CONTRIBUTING.md\0".encode()
            with patch.object(SCOPE.subprocess, "run"), patch.object(
                    SCOPE.subprocess, "check_output", return_value=raw):
                self.assertTrue(SCOPE.plan(self.repo, "pull_request", self.base, self.base)["full_suite"])
        with patch.object(SCOPE.subprocess, "run"), patch.object(
                SCOPE.subprocess, "check_output", return_value=b"broken\0"):
            self.assertTrue(SCOPE.plan(self.repo, "pull_request", self.base, self.base)["full_suite"])

    def test_non_ancestor_comparison_runs_full(self):
        self.write("CONTRIBUTING.md")
        later = self.commit()
        self.assertTrue(self.select(head=self.base, base=later)["full_suite"])

    def test_advisory_finds_errors_without_executing_or_changing_files(self):
        self.write("bad.py", "value = missing_name\n")
        self.write("bad.js", "require('fs').writeFileSync('executed', 'unsafe'); const x = ;\n")
        before = {name: (self.repo / name).read_bytes() for name in ("bad.py", "bad.js")}
        result = SCOPE.changed_code(self.repo, ["bad.py", "bad.js"])
        self.assertEqual(result["mode"], "advisory")
        self.assertEqual(result["checked_files"], 2)
        self.assertEqual({o["path"] for o in result["observations"]}, {"bad.py", "bad.js"})
        self.assertFalse((self.repo / "executed").exists())
        self.assertEqual(before, {name: (self.repo / name).read_bytes() for name in before})

    def test_workflow_retains_full_suites_and_opt_in(self):
        workflow = (ROOT / ".github/workflows/enterprise-checks.yml").read_text(encoding="utf-8")
        self.assertEqual(workflow.count("needs: change-scope"), 2)
        self.assertEqual(workflow.count("needs.change-scope.outputs.full_suite != 'false'"), 2)
        self.assertIn("python -m pytest -q enterprise/tests", workflow)
        self.assertIn("enterprise/tests/test_handoff_commit.py", workflow)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.fixed_exe_gates", workflow)
        self.assertIn("continue-on-error: true", workflow)


if __name__ == "__main__":
    unittest.main()
