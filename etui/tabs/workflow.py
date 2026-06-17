# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

"""Workflow tab: YAML-defined, multi-step command runner (Workflow Wizard)."""

from __future__ import annotations

import asyncio
import os
import signal
import time
from pathlib import Path

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Label,
    ListItem,
    ListView,
    Markdown,
    RichLog,
    Select,
    Static,
)
from textual.worker import Worker, WorkerCancelled

if __package__:
    from ..workflow.engine import ICONS, StepState, WorkflowEngine
    from ..workflow.loader import WorkflowMeta, builtin_dir, list_workflows, load
    from ..workflow.safety import DenylistChecker
    from ..workflow.schema import Workflow, WorkflowStep, WorkflowValidationError, resolve
else:  # pragma: no cover - fallback for non-package execution
    from workflow.engine import ICONS, StepState, WorkflowEngine
    from workflow.loader import WorkflowMeta, builtin_dir, list_workflows, load
    from workflow.safety import DenylistChecker
    from workflow.schema import Workflow, WorkflowStep, WorkflowValidationError, resolve


class ConfirmDialog(ModalScreen[bool]):
    """Confirmation dialog shown for confirm/denylisted steps."""

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
        background: rgba(0, 0, 0, 0.5);
    }

    #workflow-confirm-dialog {
        width: 70;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: thick $accent;
    }

    #workflow-confirm-dialog Label {
        margin-bottom: 1;
    }

    #workflow-confirm-dialog Button {
        margin-right: 2;
    }
    """

    def __init__(self, title: str, commands: list[str], *, dangerous: bool) -> None:
        super().__init__()
        self.dialog_title = title
        self.commands = commands
        self.dangerous = dangerous

    def compose(self) -> ComposeResult:
        with Vertical(id="workflow-confirm-dialog"):
            if self.dangerous:
                yield Label("[bold red]⚠ Potentially destructive command(s) detected.[/bold red]")
            yield Label(f"Run step '{self.dialog_title}'?")
            yield Static("\n".join(escape(c) for c in self.commands))
            with Horizontal():
                yield Button("Yes, Run", id="btn-workflow-confirm-yes", variant="primary")
                yield Button("Cancel", id="btn-workflow-confirm-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-workflow-confirm-yes")


class WorkflowTab(Vertical):
    """YAML-defined, multi-step command workflow runner."""

    DEFAULT_CSS = """
    WorkflowTab {
        height: 1fr;
    }

    WorkflowTab #workflow-header-bar {
        height: 3;
        background: $surface;
        border-bottom: solid $accent;
        padding: 0 1;
        align: left middle;
    }

    WorkflowTab #workflow-select {
        width: 40;
    }

    WorkflowTab #workflow-header-bar Button {
        margin-left: 1;
    }

    WorkflowTab #workflow-main-split {
        height: 1fr;
    }

    WorkflowTab #workflow-steps-view {
        width: 25%;
        height: 1fr;
        border-right: solid $accent;
    }

    WorkflowTab #workflow-step-pane {
        width: 75%;
        height: 1fr;
        padding: 0 1;
    }

    WorkflowTab #workflow-step-desc {
        height: auto;
        max-height: 30%;
    }

    WorkflowTab #workflow-step-commands {
        height: auto;
        color: $text-muted;
    }

    WorkflowTab #workflow-step-output {
        height: 1fr;
        background: $boost;
    }

    WorkflowTab #workflow-status-bar {
        height: 1;
        color: $text-muted;
    }

    WorkflowTab #workflow-action-bar {
        height: 3;
        padding: 0 1;
        align: left middle;
        border-top: solid $accent;
    }

    WorkflowTab #workflow-action-bar Button {
        margin-right: 1;
    }
    """

    def __init__(self, *, safety_level: str = "strict", default_timeout: int = 60) -> None:
        super().__init__()
        self.repo_path: Path | None = None
        self.metas: list[WorkflowMeta] = []
        self.workflow: Workflow | None = None
        self.engine: WorkflowEngine | None = None
        self.denylist = DenylistChecker(level=safety_level)
        self.default_timeout = default_timeout
        self.busy: bool = False
        self.run_all: bool = False
        self._active_subprocess: asyncio.subprocess.Process | None = None
        self._operation_worker: Worker[None] | None = None
        self._started_at: float = 0.0

    # ------------------------------------------------------------------ UI
    def compose(self) -> ComposeResult:
        with Horizontal(id="workflow-header-bar"):
            yield Label("Workflow: ", classes="control-label")
            yield Select([], id="workflow-select", prompt="Select a workflow")
            yield Button("Reload", id="btn-workflow-reload")
            yield Button("Run All", id="btn-workflow-run-all", variant="primary", disabled=True)
        with Horizontal(id="workflow-main-split"):
            yield ListView(id="workflow-steps-view")
            with Vertical(id="workflow-step-pane"):
                yield Markdown("", id="workflow-step-desc")
                yield Static("", id="workflow-step-commands")
                yield RichLog(id="workflow-step-output", highlight=True, markup=True)
                yield Static("", id="workflow-status-bar")
        with Horizontal(id="workflow-action-bar"):
            yield Button("Run", id="btn-workflow-run", disabled=True)
            yield Button("Skip", id="btn-workflow-skip", disabled=True)
            yield Button("Abort", id="btn-workflow-abort", variant="warning", disabled=True)
            yield Button("Prev", id="btn-workflow-prev", disabled=True)

    def on_mount(self) -> None:
        self._sync_controls()
        if self.repo_path is None:
            self._scan_workflows()

    async def on_unmount(self) -> None:
        await self.cancel_active_operation()

    # -------------------------------------------------------- repo context
    async def change_repository(self, repo_path: Path) -> None:
        await self.cancel_active_operation()
        self.repo_path = repo_path.resolve()
        self.workflow = None
        self.engine = None
        self.run_all = False
        try:
            self.query_one("#workflow-step-output", RichLog).clear()
            self.query_one("#workflow-steps-view", ListView).clear()
            self.query_one("#workflow-step-desc", Markdown).update("")
            self.query_one("#workflow-step-commands", Static).update("")
        except Exception:
            pass
        self._scan_workflows()
        self._sync_controls()

    def _workflow_dirs(self) -> list[Path]:
        dirs: list[Path] = []
        if self.repo_path is not None:
            dirs.append(self.repo_path / ".etui" / "workflows")
        dirs.append(Path.home() / ".etui" / "workflows")
        dirs.append(builtin_dir())  # workflows bundled with the package
        return dirs

    def _scan_workflows(self) -> None:
        metas: list[WorkflowMeta] = []
        seen: set[Path] = set()
        for d in self._workflow_dirs():
            for meta in list_workflows(d):
                if meta.path in seen:
                    continue
                seen.add(meta.path)
                metas.append(meta)
        self.metas = metas
        try:
            select = self.query_one("#workflow-select", Select)
            select.set_options([(m.name, str(m.path)) for m in metas])
        except Exception:
            pass
        status = self._status()
        if status is not None and not metas:
            status.update(
                "No workflows found. Add *.yaml files under .etui/workflows/."
            )

    # -------------------------------------------------------- load / select
    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        await self.load_workflow(Path(str(event.value)))

    async def load_workflow(self, path: Path) -> bool:
        log = self.query_one("#workflow-step-output", RichLog)
        log.clear()
        try:
            self.workflow = load(path)
        except WorkflowValidationError as exc:
            self.workflow = None
            self.engine = None
            log.write(f"[red]Invalid workflow: {escape(str(exc))}[/red]")
            self._sync_controls()
            return False
        self.engine = WorkflowEngine(self.workflow)
        self.run_all = False
        await self._render_steps()
        self._show_step(self.engine.current_index)
        self._sync_controls()
        log.write(f"[green]Loaded workflow:[/green] {escape(self.workflow.name)}")
        return True

    # ------------------------------------------------------------ rendering
    def _status(self) -> Static | None:
        try:
            return self.query_one("#workflow-status-bar", Static)
        except Exception:
            return None

    async def _render_steps(self) -> None:
        if self.engine is None:
            return
        view = self.query_one("#workflow-steps-view", ListView)
        await view.clear()
        for i, step in enumerate(self.engine.workflow.steps):
            icon = ICONS[self.engine.state_at(i)]
            await view.append(ListItem(Label(f"{icon} {step.label}"), id=f"wf-step-{i}"))

    def _refresh_step_labels(self) -> None:
        if self.engine is None:
            return
        view = self.query_one("#workflow-steps-view", ListView)
        for i, item in enumerate(view.children):
            if i >= len(self.engine.workflow.steps):
                break
            step = self.engine.workflow.steps[i]
            icon = ICONS[self.engine.state_at(i)]
            try:
                item.query_one(Label).update(f"{icon} {step.label}")
            except Exception:
                pass

    def _show_step(self, index: int) -> None:
        if self.engine is None:
            return
        step = self.engine.step_at(index)
        self.query_one("#workflow-step-desc", Markdown).update(
            step.description or f"### {step.title}"
        )
        lines = [f"  {n}  {cmd}" for n, cmd in enumerate(step.commands, 1)]
        self.query_one("#workflow-step-commands", Static).update(
            "Commands:\n" + ("\n".join(lines) if lines else "  (none)")
        )

    def _update_status_for_current(self) -> None:
        status = self._status()
        if status is None or self.engine is None:
            return
        idx = self.engine.current_index
        state = self.engine.state_at(idx)
        total = len(self.engine.workflow.steps)
        status.update(
            f"{ICONS[state]} {state.value.title()}  (step {idx + 1} of {total})"
        )

    # ------------------------------------------------------------ controls
    def _sync_controls(self) -> None:
        has_engine = self.engine is not None
        try:
            run_all_btn = self.query_one("#btn-workflow-run-all", Button)
            run_btn = self.query_one("#btn-workflow-run", Button)
            skip_btn = self.query_one("#btn-workflow-skip", Button)
            abort_btn = self.query_one("#btn-workflow-abort", Button)
            prev_btn = self.query_one("#btn-workflow-prev", Button)
            reload_btn = self.query_one("#btn-workflow-reload", Button)
            select = self.query_one("#workflow-select", Select)
        except Exception:
            return

        abort_btn.disabled = not self.busy
        reload_btn.disabled = self.busy
        select.disabled = self.busy

        if not has_engine or self.busy:
            run_all_btn.disabled = self.busy or not has_engine
            run_btn.disabled = True
            skip_btn.disabled = True
            prev_btn.disabled = True
            return

        engine = self.engine
        complete = engine.complete
        active = engine.active_step()
        viewing_active = engine.is_viewing_active()

        run_all_btn.disabled = complete
        run_btn.disabled = complete or not viewing_active or active is None or active.mode != "manual"
        skip_btn.disabled = (
            complete or not viewing_active or active is None or not active.allow_skip
        )
        prev_btn.disabled = engine.current_index == 0

    # ------------------------------------------------------------ execution
    def _start_operation(self, coro, name: str) -> None:
        if self.busy:
            coro.close()
            return
        self.busy = True  # synchronous race guard
        self._sync_controls()
        self._operation_worker = self.run_worker(
            coro, name=name, group="workflow-ops", exclusive=True, exit_on_error=False
        )

    def _resolve_cwd(self, step: WorkflowStep) -> Path:
        base = self.repo_path or Path.cwd()
        if not step.cwd:
            return base
        resolved = (base / step.cwd).resolve()
        if not resolved.is_relative_to(base):
            raise ValueError("Step cwd must remain inside the repository root")
        return resolved

    async def _run_active_step(self) -> None:
        engine = self.engine
        if engine is None:
            self.busy = False
            return
        step = engine.active_step()
        if step is None:
            self.busy = False
            return

        log = self.query_one("#workflow-step-output", RichLog)
        try:
            workdir = self._resolve_cwd(step)
        except ValueError as exc:
            log.write(f"[red]{escape(str(exc))}[/red]")
            self.busy = False
            self.run_all = False
            self._sync_controls()
            return

        resolved_cmds = [resolve(c, engine.workflow.variables) for c in step.commands]
        dangerous = any(self.denylist.requires_confirm(c) for c in resolved_cmds)
        if step.confirm or dangerous:
            confirmed = await self.app.push_screen_wait(
                ConfirmDialog(step.title, resolved_cmds, dangerous=dangerous)
            )
            if not confirmed:
                log.write("[yellow]Step cancelled.[/yellow]")
                self.busy = False
                self.run_all = False
                self._sync_controls()
                return

        engine.mark_running()
        self._refresh_step_labels()
        self._update_status_for_current()
        log.write(f"[bold]── Step: {escape(step.title)} ──[/bold]")
        timeout = step.timeout or self.default_timeout

        failed = False
        try:
            for cmd in resolved_cmds:
                log.write(f"[bold cyan]$ {escape(cmd)}[/bold cyan]")
                ret = await self._capture_command(cmd, cwd=workdir, timeout=timeout, log=log)
                if ret != 0:
                    log.write(f"[red]Command failed (exit {ret}).[/red]")
                    failed = True
                    break
        except asyncio.CancelledError:
            log.write("\n[bold yellow]Step aborted by user.[/bold yellow]")
            engine.mark_active()
            self.run_all = False
            raise
        finally:
            self.busy = False

        if failed:
            policy = engine.step_failed(ret)
            if policy == "prompt":
                self.run_all = False
                self.post_message(self.PromptDecision(step.id, ret))
            elif policy == "stop":
                self.run_all = False
                log.write("[red]Workflow stopped due to failure.[/red]")
        else:
            engine.step_completed(0)
            log.write(f"[green]Step '{escape(step.title)}' complete.[/green]")

        self._after_step_update()

    def _after_step_update(self) -> None:
        if self.engine is None:
            return
        self._refresh_step_labels()
        self._show_step(self.engine.current_index)
        self._update_status_for_current()
        self._sync_controls()
        if self.engine.complete:
            self._show_completion_summary()
            self.run_all = False
            return
        # Continue Run-All or auto steps.
        if self.run_all and not self.busy:
            self._maybe_run_next()
        elif not self.busy:
            active = self.engine.active_step()
            if active is not None and active.mode == "auto":
                self._maybe_run_next()

    def _maybe_run_next(self) -> None:
        # one-frame delay so the UI repaints before the next step runs
        self.set_timer(0.05, lambda: self._start_operation(
            self._run_active_step(), "workflow-run"
        ))

    def _show_completion_summary(self) -> None:
        if self.engine is None:
            return
        total, done, failed, skipped = self.engine.summary()
        elapsed = time.monotonic() - self._started_at if self._started_at else 0.0
        mins, secs = divmod(int(elapsed), 60)
        log = self.query_one("#workflow-step-output", RichLog)
        verb = "with failures" if failed else "successfully"
        colour = "yellow" if failed else "green"
        log.write(
            f"\n[bold {colour}]✓ {escape(self.engine.workflow.name)} finished {verb}.[/bold {colour}]"
        )
        log.write(f"Steps: {done} done  {failed} failed  {skipped} skipped")
        log.write(f"Elapsed: {mins} m {secs} s")
        status = self._status()
        if status is not None:
            status.update(f"Complete — {done} done, {failed} failed, {skipped} skipped")

    async def _capture_command(self, cmd: str, *, cwd: Path, timeout: int, log: RichLog) -> int:
        process = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=(os.name == "posix"),
        )
        self._active_subprocess = process

        async def pump() -> None:
            assert process.stdout is not None
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                log.write(escape(line.decode(errors="replace").rstrip()))

        try:
            await asyncio.wait_for(pump(), timeout=timeout)
            await process.wait()
            return process.returncode or 0
        except (TimeoutError, asyncio.TimeoutError):
            await self._terminate_active_subprocess()
            log.write(f"[red]Command timed out after {timeout}s.[/red]")
            return -1
        except asyncio.CancelledError:
            await self._terminate_active_subprocess()
            raise
        finally:
            if self._active_subprocess is process:
                self._active_subprocess = None

    async def cancel_active_operation(self) -> None:
        worker = self._operation_worker
        if worker is not None and not worker.is_finished:
            worker.cancel()
        await self._terminate_active_subprocess()
        if worker is not None:
            try:
                await worker.wait()
            except WorkerCancelled:
                pass
        self.busy = False
        self.run_all = False

    async def _terminate_active_subprocess(self) -> None:
        process = self._active_subprocess
        if process is None or process.returncode is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=3.0)
        except (TimeoutError, asyncio.TimeoutError):
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                return
            await process.wait()

    # --------------------------------------------------------- prompt flow
    class PromptDecision(Message):
        def __init__(self, step_id: str, exit_code: int) -> None:
            super().__init__()
            self.step_id = step_id
            self.exit_code = exit_code

    async def on_workflow_tab_prompt_decision(self, message: "WorkflowTab.PromptDecision") -> None:
        log = self.query_one("#workflow-step-output", RichLog)
        cont = await self.app.push_screen_wait(
            ConfirmDialog(
                "Step failed — continue anyway?",
                [f"Step '{message.step_id}' failed (exit {message.exit_code})."],
                dangerous=False,
            )
        )
        if self.engine is not None:
            self.engine.resolve_prompt(cont)
            if cont:
                log.write("[yellow]Continuing after failure.[/yellow]")
            else:
                log.write("[red]Workflow stopped due to failure.[/red]")
            self._after_step_update()

    # ------------------------------------------------------------ events
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if self.engine is None or event.item.id is None:
            return
        if not event.item.id.startswith("wf-step-"):
            return
        index = int(event.item.id.removeprefix("wf-step-"))
        if self.engine.select(index):
            self._show_step(index)
            self._update_status_for_current()
            self._sync_controls()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-workflow-abort":
            await self.cancel_active_operation()
            self._after_step_update()
            return
        if bid == "btn-workflow-reload":
            await self.cancel_active_operation()
            self._scan_workflows()
            path = self._current_path()
            if path is not None:
                await self.load_workflow(path)
            return
        if self.busy or self.engine is None:
            return
        if bid == "btn-workflow-run":
            self._started_at = self._started_at or time.monotonic()
            self._start_operation(self._run_active_step(), "workflow-run")
        elif bid == "btn-workflow-run-all":
            self.run_all = True
            self._started_at = time.monotonic()
            self._start_operation(self._run_active_step(), "workflow-run")
        elif bid == "btn-workflow-skip":
            if self.engine.skip_current():
                self._after_step_update()
        elif bid == "btn-workflow-prev":
            if self.engine.review_previous():
                self._show_step(self.engine.current_index)
                self._update_status_for_current()
                self._sync_controls()

    def _current_path(self) -> Path | None:
        try:
            value = self.query_one("#workflow-select", Select).value
        except Exception:
            return None
        if value is Select.BLANK:
            return None
        return Path(str(value))
