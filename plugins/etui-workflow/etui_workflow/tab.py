# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

"""Workflow tab: YAML-defined, multi-step command runner (Workflow Wizard)."""

from __future__ import annotations

import asyncio
import os
import re
import signal
import time
from pathlib import Path

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    ListItem,
    ListView,
    Markdown,
    RichLog,
    Select,
    Static,
)
from textual.worker import Worker, WorkerCancelled

from .engine import ICONS, StepState, WorkflowEngine
from .loader import WorkflowMeta, builtin_dir, list_workflows, load
from .safety import DenylistChecker
from .schema import Workflow, WorkflowStep, WorkflowValidationError, resolve

from etui.plugin import CancelOnLeaveMixin, BusMixin, NoProvider, RpcError
from etui.bus_contract import SVC_CONSOLE_FORCE_COMPLETE, SVC_CONSOLE_RUN, WorkspaceChanged
from etui.contracts import on_workspace_changed, workspace_get_root


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


class PasswordDialog(ModalScreen[str | None]):
    """Masked prompt used to collect a sudo password for a workflow step."""

    DEFAULT_CSS = """
    PasswordDialog {
        align: center middle;
        background: rgba(0, 0, 0, 0.5);
    }

    #workflow-pw-dialog {
        width: 60;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: thick $accent;
    }

    #workflow-pw-dialog Label {
        margin-bottom: 1;
    }

    #workflow-pw-dialog Button {
        margin-right: 2;
    }
    """

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self.prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="workflow-pw-dialog"):
            yield Label(self.prompt)
            yield Input(password=True, id="workflow-pw-input")
            with Horizontal():
                yield Button("OK", id="btn-workflow-pw-ok", variant="primary")
                yield Button("Cancel", id="btn-workflow-pw-cancel")

    def on_mount(self) -> None:
        self.query_one("#workflow-pw-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Stop the event so it does not bubble to the app-level handler, which
        # would otherwise run the password as a console command.
        event.stop()
        self.dismiss(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-workflow-pw-ok":
            self.dismiss(self.query_one("#workflow-pw-input", Input).value)
        else:
            self.dismiss(None)


# Matches a `sudo` command word not already given an askpass/non-interactive flag.
_SUDO_RE = re.compile(r"\bsudo\b(?!\s+-[AnKk])")


class WorkflowTab(CancelOnLeaveMixin, BusMixin, Vertical):
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
        # sudo support: password cached for the session, fed to `sudo -S`.
        self._sudo_password: str | None = None
        self._current_operation_name: str | None = None
        self._aborted_steps: set[str] = set()
        self._workflow_aborted: bool = False
        self._workspace_disposer = None

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
            yield Button("Console", id="btn-workflow-console", disabled=True)
            yield Button("Skip", id="btn-workflow-skip", disabled=True)
            yield Button("Sync", id="btn-workflow-sync", disabled=True)
            yield Button("Abort", id="btn-workflow-abort", variant="warning", disabled=True)
            yield Button("Prev", id="btn-workflow-prev", disabled=True)

    async def on_mount(self) -> None:
        super().on_mount()
        try:
            root = await workspace_get_root(self.bus)
            self._on_workspace_changed(WorkspaceChanged(root=root))
        except Exception:
            pass
        self._workspace_disposer = on_workspace_changed(
            self.bus,
            self._on_workspace_changed,
        )
        self._sync_controls()
        if self.repo_path is None:
            self._scan_workflows()

    async def on_unmount(self) -> None:
        if self._workspace_disposer is not None:
            self._workspace_disposer()
            self._workspace_disposer = None
        await self.cancel_active_operation()
        super().on_unmount()

    def survives_leave(self) -> bool:
        return self.active_operation_detached

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

    def _on_workspace_changed(self, event) -> None:
        self.repo_path = Path(event.root).resolve()
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
        if event.value in (Select.BLANK, Select.NULL):
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
        self._aborted_steps = set()
        self._workflow_aborted = False
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
        if not self.busy:
            self._current_operation_name = None
        has_engine = self.engine is not None
        try:
            run_all_btn = self.query_one("#btn-workflow-run-all", Button)
            run_btn = self.query_one("#btn-workflow-run", Button)
            console_btn = self.query_one("#btn-workflow-console", Button)
            skip_btn = self.query_one("#btn-workflow-skip", Button)
            sync_btn = self.query_one("#btn-workflow-sync", Button)
            abort_btn = self.query_one("#btn-workflow-abort", Button)
            prev_btn = self.query_one("#btn-workflow-prev", Button)
            reload_btn = self.query_one("#btn-workflow-reload", Button)
            select = self.query_one("#workflow-select", Select)
        except Exception:
            return

        abort_btn.disabled = not self.busy
        reload_btn.disabled = self.busy
        select.disabled = self.busy
        sync_btn.disabled = not (self.busy and getattr(self, "_current_operation_name", None) == "console-command")

        if not has_engine or self.busy:
            run_all_btn.disabled = self.busy or not has_engine
            run_btn.disabled = True
            console_btn.disabled = True
            skip_btn.disabled = True
            prev_btn.disabled = True
            return

        # "Console" sends the currently viewed step's commands to the Console
        # tab — available for any loaded step with commands.
        console_btn.disabled = not bool(self.engine.current_step().commands)

        engine = self.engine
        complete = engine.complete
        active = engine.active_step()
        viewing_active = engine.is_viewing_active()

        run_all_btn.disabled = complete
        run_btn.disabled = complete or not viewing_active or active is None or active.mode != "manual"
        is_aborted = getattr(self, "_workflow_aborted", False) or (active is not None and active.id in getattr(self, "_aborted_steps", set()))
        skip_btn.disabled = (
            complete or not viewing_active or active is None or not (active.allow_skip or is_aborted)
        )
        prev_btn.disabled = engine.current_index == 0

    @property
    def active_operation_detached(self) -> bool:
        """True when the busy operation runs in another tab (the console
        command) and so must survive the user navigating away from Workflow."""
        return getattr(self, "_current_operation_name", None) == "console-command"

    # ------------------------------------------------------------ execution
    def _start_operation(self, coro, name: str) -> None:
        if self.busy:
            coro.close()
            return
        self.busy = True  # synchronous race guard
        self._current_operation_name = name
        if name in ("workflow-run", "console-command"):
            self._workflow_aborted = False
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

        # If any command needs sudo, collect a password up front.
        if any(_SUDO_RE.search(c) for c in resolved_cmds) and self._sudo_password is None:
            pw = await self.app.push_screen_wait(
                PasswordDialog("This step runs sudo. Enter your password:")
            )
            if pw is None:
                log.write("[yellow]Step cancelled (no password).[/yellow]")
                self.busy = False
                self.run_all = False
                self._sync_controls()
                return
            self._sudo_password = pw

        engine.mark_running()
        self._refresh_step_labels()
        self._update_status_for_current()
        log.write(f"[bold]── Step: {escape(step.title)} ──[/bold]")
        timeout = step.timeout or self.default_timeout

        failed = False
        try:
            for cmd in resolved_cmds:
                log.write(f"[bold cyan]$ {escape(cmd)}[/bold cyan]")
                run_cmd, stdin_data = self._prepare_sudo(cmd)
                ret = await self._capture_command(
                    run_cmd, cwd=workdir, timeout=timeout, log=log, stdin_data=stdin_data
                )
                if ret != 0:
                    # A bad sudo password should not be cached for later steps.
                    if stdin_data is not None:
                        self._sudo_password = None
                    log.write(f"[red]Command failed (exit {ret}).[/red]")
                    failed = True
                    break
        except asyncio.CancelledError:
            log.write("\n[bold yellow]Step aborted by user.[/bold yellow]")
            engine.mark_active()
            self._aborted_steps.add(step.id)
            self.run_all = False
            raise
        finally:
            self.busy = False

        if failed:
            policy = engine.step_failed(ret)
            if policy == "prompt":
                self.run_all = False
                cont = await self.app.push_screen_wait(
                    ConfirmDialog(
                        "Step failed — continue anyway?",
                        [f"Step '{step.id}' failed (exit {ret})."],
                        dangerous=False,
                    )
                )
                engine.resolve_prompt(cont)
                if cont:
                    log.write("[yellow]Continuing after failure.[/yellow]")
                else:
                    log.write("[red]Workflow stopped due to failure.[/red]")
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

    def _prepare_sudo(self, cmd: str) -> tuple[str, bytes | None]:
        """Rewrite ``sudo`` to read the password from stdin and return the
        bytes to feed it.

        Returns the original command and ``None`` when no sudo is present or no
        password has been collected. Uses ``sudo -S`` (read from stdin) with an
        empty prompt; works with both classic sudo and sudo-rs.
        """
        if os.name != "posix" or self._sudo_password is None:
            return cmd, None
        count = len(_SUDO_RE.findall(cmd))
        if count == 0:
            return cmd, None
        run_cmd = _SUDO_RE.sub("sudo -S -p ''", cmd)
        # Feed one password line per sudo invocation; cached calls simply
        # ignore the extra lines.
        stdin_data = (self._sudo_password + "\n").encode() * count
        return run_cmd, stdin_data

    async def _capture_command(
        self,
        cmd: str,
        *,
        cwd: Path,
        timeout: int,
        log: RichLog,
        stdin_data: bytes | None = None,
    ) -> int:
        process = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(cwd),
            stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=(os.name == "posix"),
        )
        if stdin_data is not None and process.stdin is not None:
            try:
                process.stdin.write(stdin_data)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()
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

    def _send_step_to_console(self) -> None:
        """Send the currently viewed step's commands to the Console tab.

        Useful when a step needs an interactive shell (e.g. to answer a sudo
        or apt prompt) instead of the wizard's non-interactive runner.
        """
        if self.engine is None:
            return
        step = self.engine.current_step()
        if not step.commands:
            return
        resolved = [resolve(c, self.engine.workflow.variables) for c in step.commands]
        combined = " && ".join(resolved)
        if not self.bus.has(SVC_CONSOLE_RUN):
            self.query_one("#workflow-step-output", RichLog).write(
                "[red]Console is unavailable.[/red]"
            )
            return
        self._start_operation(
            self._run_step_in_console(combined),
            name="console-command",
        )

    async def _run_step_in_console(self, combined: str) -> None:
        engine = self.engine
        if engine is None:
            self.busy = False
            return
        step = engine.active_step()
        if step is None:
            self.busy = False
            return

        engine.mark_running()
        self._refresh_step_labels()
        self._update_status_for_current()

        log = self.query_one("#workflow-step-output", RichLog)
        log.write(f"[bold]── Step: {escape(step.title)} (Console) ──[/bold]")
        log.write(f"[bold cyan]$ {escape(combined)}[/bold cyan]")

        try:
            ret = await self.bus.call(SVC_CONSOLE_RUN, command=combined, timeout=None)
        except asyncio.CancelledError:
            engine.mark_active()
            self._aborted_steps.add(step.id)
            self.run_all = False
            raise
        except NoProvider:
            engine.mark_active()
            log.write("[red]Console is unavailable.[/red]")
            self.busy = False
            self._after_step_update()
            return
        finally:
            self.busy = False

        if ret != 0:
            policy = engine.step_failed(ret)
            if policy == "prompt":
                self.run_all = False
                cont = await self.app.push_screen_wait(
                    ConfirmDialog(
                        "Step failed — continue anyway?",
                        [f"Step '{step.id}' failed (exit {ret})."],
                        dangerous=False,
                    )
                )
                engine.resolve_prompt(cont)
                if cont:
                    log.write("[yellow]Continuing after failure.[/yellow]")
                else:
                    log.write("[red]Workflow stopped due to failure.[/red]")
            elif policy == "stop":
                self.run_all = False
                log.write("[red]Workflow stopped due to failure.[/red]")
        else:
            engine.step_completed(0)
            log.write(f"[green]Step '{escape(step.title)}' complete.[/green]")

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
            self._workflow_aborted = True
            await self.cancel_active_operation()
            self._after_step_update()
            return
        if bid == "btn-workflow-sync":
            try:
                await self.bus.call(SVC_CONSOLE_FORCE_COMPLETE, exit_code=0)
            except RpcError as exc:
                self.query_one("#workflow-step-output", RichLog).write(
                    f"[red]Sync failed: {escape(str(exc))}[/red]"
                )
            return
        if bid == "btn-workflow-reload":
            await self.cancel_active_operation()
            path = self._current_path()
            self._scan_workflows()
            if path is not None:
                try:
                    select = self.query_one("#workflow-select", Select)
                    if str(path) in [str(m.path) for m in self.metas]:
                        select.value = str(path)
                except Exception:
                    pass
                await self.load_workflow(path)
            return
        if self.busy or self.engine is None:
            return
        if bid == "btn-workflow-console":
            self._send_step_to_console()
        elif bid == "btn-workflow-run":
            self._started_at = self._started_at or time.monotonic()
            self._start_operation(self._run_active_step(), "workflow-run")
        elif bid == "btn-workflow-run-all":
            self.run_all = True
            self._started_at = time.monotonic()
            self._start_operation(self._run_active_step(), "workflow-run")
        elif bid == "btn-workflow-skip":
            active = self.engine.active_step()
            force = getattr(self, "_workflow_aborted", False) or (active is not None and active.id in getattr(self, "_aborted_steps", set()))
            if self.engine.skip_current(force=force):
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
        if value in (Select.BLANK, Select.NULL):
            return None
        return Path(str(value))
