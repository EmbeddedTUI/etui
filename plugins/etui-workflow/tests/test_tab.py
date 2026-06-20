# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import tempfile
import textwrap
import unittest
from pathlib import Path
from textual.app import App, ComposeResult

from etui_workflow.tab import WorkflowTab
from etui_workflow.engine import StepState, WorkflowEngine
from etui_workflow.loader import list_workflows, load
from etui_workflow.safety import DenylistChecker
from etui_workflow.schema import WorkflowValidationError, build_workflow, resolve


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

    def test_navigation_reset_state(self) -> None:
        e = self._engine()
        e.step_completed(0)
        self.assertEqual(e.state_at(0), StepState.DONE)
        self.assertEqual(e.state_at(1), StepState.ACTIVE)

        self.assertTrue(e.review_previous())
        self.assertEqual(e.state_at(0), StepState.ACTIVE)
        self.assertEqual(e.state_at(1), StepState.PENDING)


class TabTests(unittest.TestCase):
    def test_resolve_cwd_containment(self) -> None:
        tab = WorkflowTab()
        with tempfile.TemporaryDirectory() as d:
            tab.repo_path = Path(d).resolve()
            with tempfile.TemporaryDirectory() as d2:
                wf = load(_write(d2, "demo.yaml", VALID_YAML))
            from etui_workflow.schema import WorkflowStep

            inside = WorkflowStep(id="a", title="A", cwd="sub")
            self.assertTrue(
                tab._resolve_cwd(inside).is_relative_to(tab.repo_path)
            )
            outside = WorkflowStep(id="b", title="B", cwd="../escape")
            with self.assertRaises(ValueError):
                tab._resolve_cwd(outside)

    def test_prepare_sudo_no_password(self) -> None:
        tab = WorkflowTab()
        self.assertEqual(tab._prepare_sudo("sudo apt update"), ("sudo apt update", None))

    def test_prepare_sudo_rewrites_to_stdin(self) -> None:
        import os

        if os.name != "posix":
            self.skipTest("sudo -S handling is POSIX-only")
        tab = WorkflowTab()
        tab._sudo_password = "pw"
        cmd, stdin_data = tab._prepare_sudo("sudo apt update && sudo apt install -y git")
        self.assertEqual(cmd, "sudo -S -p '' apt update && sudo -S -p '' apt install -y git")
        # one password line per sudo invocation
        self.assertEqual(stdin_data, b"pw\npw\n")
        # non-sudo command is untouched
        self.assertEqual(tab._prepare_sudo("echo hi"), ("echo hi", None))

    def test_workflow_dirs_includes_repo_home_and_builtin(self) -> None:
        from etui_workflow.loader import builtin_dir

        tab = WorkflowTab()
        tab.repo_path = Path("/tmp/somerepo")
        dirs = tab._workflow_dirs()
        self.assertIn(Path("/tmp/somerepo") / ".etui" / "workflows", dirs)
        self.assertIn(Path.home() / ".etui" / "workflows", dirs)
        self.assertEqual(dirs[-1], builtin_dir())

    def test_builtin_workflows_discoverable(self) -> None:
        from etui_workflow.loader import builtin_dir, list_workflows

        names = [m.name for m in list_workflows(builtin_dir())]
        self.assertIn("Zephyr Getting Started", names)


class WorkflowTabTestApp(App):
    def compose(self) -> ComposeResult:
        yield WorkflowTab()


class WorkflowConsoleTestApp(App):
    """App that mounts both tabs so Sync can resolve a real pending command."""

    def compose(self) -> ComposeResult:
        from etui.tabs.console import ConsoleTab

        yield WorkflowTab()
        yield ConsoleTab()


class WorkflowTabIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_button_states_and_press(self) -> None:
        from textual.widgets import Button
        app = WorkflowTabTestApp()
        async with app.run_test() as pilot:
            tab = app.query_one(WorkflowTab)
            sync_btn = tab.query_one("#btn-workflow-sync", Button)
            self.assertTrue(sync_btn.disabled)

            tab.busy = True
            tab._current_operation_name = "console-command"
            tab._sync_controls()
            self.assertFalse(sync_btn.disabled)

    async def test_workflow_sync_resolves_pending_console_command(self) -> None:
        """Pressing the Workflow Sync button must actually finish a hung command."""
        import asyncio
        from textual.widgets import Button

        app = WorkflowConsoleTestApp()
        async with app.run_test() as pilot:
            tab = app.query_one(WorkflowTab)
            term = app.query_one("#console-terminal")
            await pilot.pause()

            # Kick off a command that never completes on its own.
            run_task = asyncio.ensure_future(term.run_command("sleep 60"))
            for _ in range(20):
                await pilot.pause()
                if term._pending_commands:
                    break
            self.assertEqual(len(term._pending_commands), 1)

            tab.busy = True
            tab._current_operation_name = "console-command"
            tab._sync_controls()
            self.assertFalse(tab.query_one("#btn-workflow-sync", Button).disabled)

            await pilot.click("#btn-workflow-sync")
            await pilot.pause()

            self.assertEqual(len(term._pending_commands), 0)
            self.assertEqual(await run_task, 0)

    async def test_force_complete_service_resolves_via_bus(self) -> None:
        """The console.force_complete bus service resolves a hung command."""
        import asyncio
        from etui.bus_contract import SVC_CONSOLE_FORCE_COMPLETE, SVC_CONSOLE_RUN

        app = WorkflowConsoleTestApp()
        async with app.run_test() as pilot:
            term = app.query_one("#console-terminal")
            await pilot.pause()
            self.assertTrue(app.bus.has(SVC_CONSOLE_RUN))
            self.assertTrue(app.bus.has(SVC_CONSOLE_FORCE_COMPLETE))

            run_task = asyncio.ensure_future(term.run_command("sleep 60"))
            for _ in range(20):
                await pilot.pause()
                if term._pending_commands:
                    break
            self.assertEqual(len(term._pending_commands), 1)

            await app.bus.call(SVC_CONSOLE_FORCE_COMPLETE, exit_code=0)
            self.assertEqual(len(term._pending_commands), 0)
            self.assertEqual(await run_task, 0)

    async def test_console_force_complete_button_resolves(self) -> None:
        """The Console tab's own Force Complete button resolves a hung command."""
        import asyncio
        from etui.tabs.console import ConsoleTab

        app = WorkflowConsoleTestApp()
        async with app.run_test() as pilot:
            console = app.query_one(ConsoleTab)
            term = app.query_one("#console-terminal")
            console.show_sync_button(True)
            await pilot.pause()

            run_task = asyncio.ensure_future(term.run_command("sleep 60"))
            for _ in range(20):
                await pilot.pause()
                if term._pending_commands:
                    break
            self.assertEqual(len(term._pending_commands), 1)

            await pilot.click("#btn-console-sync")
            await pilot.pause()

            self.assertEqual(len(term._pending_commands), 0)
            self.assertEqual(await run_task, 0)

    async def test_skip_aborted_step(self) -> None:
        from textual.widgets import Button
        from etui_workflow.schema import build_workflow
        app = WorkflowTabTestApp()
        async with app.run_test() as pilot:
            tab = app.query_one(WorkflowTab)
            wf = build_workflow({
                "name": "Test",
                "steps": [
                    {"id": "step1", "title": "Step 1", "commands": ["echo 1"], "allow_skip": False}
                ]
            })
            tab.workflow = wf
            tab.engine = WorkflowEngine(wf)
            tab._aborted_steps = set()
            tab._sync_controls()

            skip_btn = tab.query_one("#btn-workflow-skip", Button)
            self.assertTrue(skip_btn.disabled)

            tab._aborted_steps.add("step1")
            tab._sync_controls()
            self.assertFalse(skip_btn.disabled)

            await pilot.click("#btn-workflow-skip")
            await pilot.pause()
            self.assertEqual(tab.engine.state_at(0), StepState.SKIPPED)

    async def test_consecutive_skips_after_abort(self) -> None:
        from textual.widgets import Button
        from etui_workflow.schema import build_workflow
        app = WorkflowTabTestApp()
        async with app.run_test() as pilot:
            tab = app.query_one(WorkflowTab)
            wf = build_workflow({
                "name": "Test",
                "steps": [
                    {"id": "step1", "title": "Step 1", "commands": ["echo 1"], "allow_skip": False},
                    {"id": "step2", "title": "Step 2", "commands": ["echo 2"], "allow_skip": False}
                ]
            })
            tab.workflow = wf
            tab.engine = WorkflowEngine(wf)
            tab._sync_controls()

            skip_btn = tab.query_one("#btn-workflow-skip", Button)
            self.assertTrue(skip_btn.disabled)

            tab._workflow_aborted = True
            tab._sync_controls()
            self.assertFalse(skip_btn.disabled)

            await pilot.click("#btn-workflow-skip")
            await pilot.pause()
            self.assertEqual(tab.engine.state_at(0), StepState.SKIPPED)

            tab._sync_controls()
            self.assertFalse(skip_btn.disabled)

            await pilot.click("#btn-workflow-skip")
            await pilot.pause()
            self.assertEqual(tab.engine.state_at(1), StepState.SKIPPED)

    async def test_tab_switch_auto_cancel_exception_for_detached(self) -> None:
        """Switching away from Workflow tab cancels normal operations but not detached ones."""
        import asyncio
        import tempfile
        from pathlib import Path
        from etui.main import EtuiApp
        from etui.settings import SettingsManager
        from textual.widgets import TabbedContent

        with tempfile.TemporaryDirectory() as d:
            settings_path = Path(d) / "settings.yaml"
            app = EtuiApp()
            app.settings_manager = SettingsManager(path=settings_path)
            app.workspace_root = app.load_workspace_root()
            
            async with app.run_test() as pilot:
                # Get tabs and switch to workflow first
                workflow_tab = app.query_one(WorkflowTab)
                tabbed_content = app.query_one(TabbedContent)
                
                # 1. Test detached operation (should NOT be cancelled)
                async def fake_detached_op():
                    try:
                        await asyncio.sleep(5)
                    except asyncio.CancelledError:
                        raise
                    
                tabbed_content.active = "plugin-workflow"
                await pilot.pause()
                
                # Start detached operation
                workflow_tab._start_operation(fake_detached_op(), "console-command")
                self.assertTrue(workflow_tab.busy)
                self.assertEqual(workflow_tab._current_operation_name, "console-command")
                
                # Switch away to console
                tabbed_content.active = "console"
                await pilot.pause()
                
                # Detached operation should still be running / busy
                self.assertTrue(workflow_tab.busy)
                self.assertFalse(workflow_tab._operation_worker.is_cancelled)
                
                # Clean up detached operation
                await workflow_tab.cancel_active_operation()
                await pilot.pause()
                
                # 2. Test normal operation (should be cancelled on tab switch)
                async def fake_normal_op():
                    try:
                        await asyncio.sleep(5)
                    except asyncio.CancelledError:
                        raise
                    
                tabbed_content.active = "plugin-workflow"
                await pilot.pause()
                
                # Start normal operation
                workflow_tab._start_operation(fake_normal_op(), "workflow-run")
                self.assertTrue(workflow_tab.busy)
                self.assertEqual(workflow_tab._current_operation_name, "workflow-run")
                
                # Switch away to console
                tabbed_content.active = "console"
                await pilot.pause()
                
                # Normal operation should be cancelled / not busy
                self.assertFalse(workflow_tab.busy)
                self.assertTrue(workflow_tab._operation_worker.is_cancelled)

    async def test_reload_workflow_empty_and_valid(self) -> None:
        """Clicking reload button when no workflow is selected or when a valid one is selected."""
        from textual.widgets import Select
        from etui_workflow.loader import builtin_dir, list_workflows

        app = WorkflowTabTestApp()
        async with app.run_test() as pilot:
            tab = app.query_one(WorkflowTab)
            select = tab.query_one("#workflow-select", Select)
            
            # 1. No workflow selected: select.value should be Select.NULL or Select.BLANK
            self.assertTrue(select.value in (Select.BLANK, Select.NULL))
            self.assertIsNone(tab.workflow)
            
            # Click reload. It should not fail or try to load a Select.NULL file.
            await pilot.click("#btn-workflow-reload")
            await pilot.pause()
            self.assertIsNone(tab.workflow)
            
            # 2. Select a valid workflow and reload it
            metas = list_workflows(builtin_dir())
            if metas:
                valid_path = metas[0].path
                # Simulate selection change
                select.value = str(valid_path)
                await pilot.pause()
                self.assertIsNotNone(tab.workflow)
                
                # Clear workflow model to see if reload reloads it
                tab.workflow = None
                
                # Click reload
                await pilot.click("#btn-workflow-reload")
                await pilot.pause()
                self.assertIsNotNone(tab.workflow)


if __name__ == "__main__":
    unittest.main()
