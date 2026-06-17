# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import tempfile
import textwrap
import unittest
from pathlib import Path

from etui.tabs.workflow import WorkflowTab
from etui.workflow.engine import StepState, WorkflowEngine
from etui.workflow.loader import list_workflows, load
from etui.workflow.safety import DenylistChecker
from etui.workflow.schema import WorkflowValidationError, build_workflow, resolve


VALID_YAML = textwrap.dedent(
    """
    name: "Demo"
    description: "A demo workflow"
    variables:
      GREETING: "hi"
    steps:
      - id: one
        title: "Step One"
        description: "First step"
        commands:
          - "echo $GREETING"
        mode: manual
        allow_skip: true
      - id: two
        title: "Step Two"
        commands:
          - "echo done"
        on_failure: continue
    """
)


def _write(tmpdir: str, name: str, content: str) -> Path:
    path = Path(tmpdir) / name
    path.write_text(content)
    return path


class LoaderTests(unittest.TestCase):
    def test_load_valid(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "demo.yaml", VALID_YAML)
            wf = load(path)
            self.assertEqual(wf.name, "Demo")
            self.assertEqual(len(wf.steps), 2)
            self.assertTrue(wf.steps[0].allow_skip)
            self.assertEqual(wf.steps[1].on_failure, "continue")

    def test_duplicate_ids(self) -> None:
        bad = VALID_YAML.replace('id: two', 'id: one')
        with self.assertRaises(WorkflowValidationError):
            build_workflow(__import__("yaml").safe_load(bad))

    def test_unknown_top_key(self) -> None:
        with self.assertRaises(WorkflowValidationError):
            build_workflow({"name": "x", "steps": [{"id": "a", "title": "A"}], "bogus": 1})

    def test_no_steps(self) -> None:
        with self.assertRaises(WorkflowValidationError):
            build_workflow({"name": "x", "steps": []})

    def test_bad_mode(self) -> None:
        with self.assertRaises(WorkflowValidationError):
            build_workflow(
                {"name": "x", "steps": [{"id": "a", "title": "A", "mode": "weird"}]}
            )

    def test_list_workflows_skips_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _write(d, "good.yaml", VALID_YAML)
            _write(d, "bad.yaml", "name: x\nsteps: []\n")
            metas = list_workflows(Path(d))
            self.assertEqual(len(metas), 1)
            self.assertEqual(metas[0].name, "Demo")


class ResolveTests(unittest.TestCase):
    def test_variable_override(self) -> None:
        self.assertEqual(resolve("echo $X", {"X": "a"}), "echo a")

    def test_unknown_left_intact(self) -> None:
        self.assertEqual(resolve("echo $NOPE_XYZ", {}), "echo $NOPE_XYZ")


class SafetyTests(unittest.TestCase):
    def test_denylist_matches(self) -> None:
        chk = DenylistChecker("strict")
        self.assertTrue(chk.requires_confirm("rm -rf /tmp/x"))
        self.assertTrue(chk.requires_confirm("dd if=/dev/zero of=/dev/sda"))
        self.assertTrue(chk.requires_confirm("git reset --hard origin/main"))
        self.assertFalse(chk.requires_confirm("echo hello"))
        self.assertFalse(chk.requires_confirm("ls -la"))

    def test_permissive_bypasses(self) -> None:
        chk = DenylistChecker("permissive")
        self.assertFalse(chk.requires_confirm("rm -rf /"))
        self.assertTrue(chk.matches("rm -rf /"))


class EngineTests(unittest.TestCase):
    def _engine(self) -> WorkflowEngine:
        with tempfile.TemporaryDirectory() as d:
            wf = load(_write(d, "demo.yaml", VALID_YAML))
        return WorkflowEngine(wf)

    def test_initial_state(self) -> None:
        e = self._engine()
        self.assertEqual(e.state_at(0), StepState.ACTIVE)
        self.assertEqual(e.state_at(1), StepState.PENDING)
        self.assertFalse(e.can_select(1))

    def test_complete_flow(self) -> None:
        e = self._engine()
        e.step_completed(0)
        self.assertEqual(e.state_at(0), StepState.DONE)
        self.assertEqual(e.state_at(1), StepState.ACTIVE)
        e.step_completed(0)
        self.assertTrue(e.complete)
        total, done, failed, skipped = e.summary()
        self.assertEqual((total, done, failed, skipped), (2, 2, 0, 0))

    def test_skip(self) -> None:
        e = self._engine()
        self.assertTrue(e.skip_current())
        self.assertEqual(e.state_at(0), StepState.SKIPPED)

    def test_on_failure_continue(self) -> None:
        e = self._engine()
        e.step_completed(0)  # step one done, now on step two (continue policy)
        policy = e.step_failed(1)
        self.assertEqual(policy, "continue")
        self.assertEqual(e.state_at(1), StepState.FAILED)
        self.assertTrue(e.complete)

    def test_on_failure_stop(self) -> None:
        e = self._engine()
        policy = e.step_failed(1)  # step one default on_failure=stop
        self.assertEqual(policy, "stop")
        self.assertEqual(e.state_at(0), StepState.FAILED)


class TabTests(unittest.TestCase):
    def test_resolve_cwd_containment(self) -> None:
        tab = WorkflowTab()
        with tempfile.TemporaryDirectory() as d:
            tab.repo_path = Path(d).resolve()
            with tempfile.TemporaryDirectory() as d2:
                wf = load(_write(d2, "demo.yaml", VALID_YAML))
            from etui.workflow.schema import WorkflowStep

            inside = WorkflowStep(id="a", title="A", cwd="sub")
            self.assertTrue(
                tab._resolve_cwd(inside).is_relative_to(tab.repo_path)
            )
            outside = WorkflowStep(id="b", title="B", cwd="../escape")
            with self.assertRaises(ValueError):
                tab._resolve_cwd(outside)

    def test_workflow_dirs_includes_repo_and_home(self) -> None:
        tab = WorkflowTab()
        tab.repo_path = Path("/tmp/somerepo")
        dirs = tab._workflow_dirs()
        self.assertIn(Path("/tmp/somerepo") / ".etui" / "workflows", dirs)
        self.assertEqual(dirs[-1], Path.home() / ".etui" / "workflows")


if __name__ == "__main__":
    unittest.main()
