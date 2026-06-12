# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
import json
import shlex
import shutil
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Label, RichLog
from textual.worker import Worker


class VenvTab(Vertical):
    """Manage an explicitly selected external PDM project."""

    DEFAULT_CSS = """
    VenvTab {
        height: 1fr;
    }

    VenvTab #venv-project-select {
        height: 3;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $accent;
        align: left middle;
    }

    VenvTab #venv-project-path {
        width: 1fr;
    }

    VenvTab #venv-info-bar {
        height: 3;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $accent;
        align: left middle;
    }

    VenvTab #venv-main-split {
        height: 1fr;
    }

    VenvTab #venv-package-table {
        width: 50%;
        height: 1fr;
        border-right: solid $accent;
    }

    VenvTab #venv-controls {
        width: 50%;
        padding: 1;
    }

    VenvTab #venv-package-input {
        width: 1fr;
    }

    VenvTab #venv-action-log {
        height: 1fr;
        margin-top: 1;
        background: $boost;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.project_path: Path | None = None
        self._pdm_path: str | None = None
        self._busy = False
        self._cancel_requested = False
        self._active_subprocess: asyncio.subprocess.Process | None = None
        self._operation_worker: Worker[None] | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="venv-project-select"):
            yield Label("Project Root: ")
            yield Input(
                placeholder="Path containing pyproject.toml",
                id="venv-project-path",
            )
            yield Button("Open", id="venv-open-project")

        with Horizontal(id="venv-info-bar"):
            yield Label("Checking for PDM...", id="venv-info")

        with Horizontal(id="venv-main-split"):
            yield DataTable(id="venv-package-table")
            with Vertical(id="venv-controls"):
                with Horizontal():
                    yield Input(
                        placeholder="package (for example requests>=2.0)",
                        id="venv-package-input",
                        disabled=True,
                    )
                    yield Button(
                        "Install",
                        id="venv-add",
                        variant="primary",
                        disabled=True,
                    )
                    yield Button(
                        "Uninstall",
                        id="venv-remove",
                        variant="error",
                        disabled=True,
                    )
                with Horizontal():
                    yield Button(
                        "Update All",
                        id="venv-update-all",
                        disabled=True,
                    )
                    yield Button(
                        "Cancel",
                        id="venv-cancel",
                        variant="warning",
                        disabled=True,
                    )
                yield RichLog(id="venv-action-log", highlight=True, markup=True)

    @property
    def is_busy(self) -> bool:
        return self._busy

    def on_mount(self) -> None:
        self.query_one("#venv-package-table", DataTable).add_columns(
            "Package",
            "Version",
        )
        self._pdm_path = shutil.which("pdm")
        if self._pdm_path is None:
            self._set_status("[red]pdm executable not found on host[/red]")
            self._set_project_selection_enabled(False)
            return
        self._set_status("Select an external PDM project to begin.")

    async def on_unmount(self) -> None:
        await self.cancel_active_operation()
        if self._operation_worker is not None:
            self._operation_worker.cancel()

    @staticmethod
    def build_pdm_command(
        pdm_path: str,
        action: str,
        project_path: Path,
        package_spec: str | None = None,
    ) -> list[str]:
        """Build a non-interactive PDM command for one explicit project."""
        args = [
            pdm_path,
            "--non-interactive",
            action,
            "--project",
            str(project_path),
        ]
        if package_spec is not None:
            args.extend(["--", package_spec])
        return args

    @staticmethod
    def validate_package_spec(package_spec: str, *, remove: bool = False) -> str:
        """Validate a PEP 508 requirement and normalize removal to its name."""
        spec = package_spec.strip()
        if not spec or spec.startswith("-"):
            raise InvalidRequirement("invalid package specification")
        requirement = Requirement(spec)
        return requirement.name if remove else str(requirement)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "venv-open-project":
            await self._select_project()
        elif button_id == "venv-cancel":
            await self.cancel_active_operation()
        elif button_id == "venv-update-all":
            self._start_mutation("update")
        elif button_id in {"venv-add", "venv-remove"}:
            self._start_package_mutation(button_id)

    async def _select_project(self) -> None:
        if self._busy:
            self.notify("A package operation is already running", severity="warning")
            return
        if self._pdm_path is None:
            self.notify("PDM is not available on PATH", severity="error")
            return

        raw_path = self.query_one("#venv-project-path", Input).value.strip()
        if not raw_path:
            return

        candidate = Path(raw_path).expanduser().resolve()
        if not candidate.is_dir() or not (candidate / "pyproject.toml").is_file():
            self._invalidate_project("Invalid project path: pyproject.toml not found")
            return

        self._set_project_selection_enabled(False)
        self._set_mutation_enabled(False)
        self._set_status("Validating PDM project...")
        command = self.build_pdm_command(
            self._pdm_path,
            "info",
            candidate,
        )
        command.append("--json")

        returncode, stdout, stderr = await self._capture_command(command)
        self._set_project_selection_enabled(True)
        if returncode != 0:
            detail = stderr.strip() or stdout.strip() or "PDM validation failed"
            self._invalidate_project(detail)
            return

        try:
            info = json.loads(stdout)
            interpreter = info["python"]["interpreter"]
            version = info["python"]["version"]
            project_root = Path(info["project"]["root"]).resolve()
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            self._invalidate_project(f"Invalid PDM project information: {error}")
            return

        if project_root != candidate:
            self._invalidate_project(
                f"PDM selected a different project root: {project_root}"
            )
            return
        if not interpreter:
            self._invalidate_project("PDM did not report a project interpreter")
            return

        self.project_path = candidate
        self._set_status(
            f"[green]Project:[/green] {candidate}  "
            f"[green]Python:[/green] {version}  "
            f"[green]Interpreter:[/green] {interpreter}"
        )
        self._set_mutation_enabled(True)
        await self.load_installed_packages()

    async def load_installed_packages(self) -> None:
        if self.project_path is None or self._pdm_path is None:
            return

        command = self.build_pdm_command(
            self._pdm_path,
            "list",
            self.project_path,
        )
        command.extend(["--json", "--fields", "name,version"])
        returncode, stdout, stderr = await self._capture_command(command)
        if returncode != 0:
            self._write_log(stderr.strip() or "Unable to list project packages", "red")
            return

        try:
            packages = json.loads(stdout)
        except json.JSONDecodeError as error:
            self._write_log(f"Invalid package list returned by PDM: {error}", "red")
            return

        table = self.query_one("#venv-package-table", DataTable)
        table.clear()
        for package in sorted(packages, key=lambda item: item.get("name", "").lower()):
            table.add_row(
                package.get("name", ""),
                package.get("version", ""),
            )

    def _start_package_mutation(self, button_id: str) -> None:
        package_input = self.query_one("#venv-package-input", Input)
        raw_spec = package_input.value
        action = "add" if button_id == "venv-add" else "remove"
        try:
            package_spec = self.validate_package_spec(
                raw_spec,
                remove=action == "remove",
            )
        except InvalidRequirement:
            self.notify("Invalid PEP 508 package specification", severity="error")
            return

        package_input.value = ""
        self._start_mutation(action, package_spec)

    def _start_mutation(
        self,
        action: str,
        package_spec: str | None = None,
    ) -> None:
        if self.project_path is None or self._pdm_path is None:
            self.notify("Select a valid PDM project first", severity="error")
            return
        if self._busy:
            self.notify("A package operation is already running", severity="warning")
            return

        self._busy = True
        self._cancel_requested = False
        self._set_project_selection_enabled(False)
        self._set_mutation_enabled(False)
        self.query_one("#venv-cancel", Button).disabled = False
        self._operation_worker = self.run_worker(
            self._run_mutation(action, package_spec),
            name=f"pdm-{action}",
            group="venv-ops",
            exit_on_error=False,
        )

    async def _run_mutation(
        self,
        action: str,
        package_spec: str | None,
    ) -> None:
        assert self.project_path is not None
        assert self._pdm_path is not None

        command = self.build_pdm_command(
            self._pdm_path,
            action,
            self.project_path,
            package_spec,
        )
        log = self.query_one("#venv-action-log", RichLog)
        log.clear()
        log.write(f"[bold cyan]Running:[/bold cyan] {shlex.join(command)}")

        try:
            self._active_subprocess = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            if self._cancel_requested:
                await self._terminate_active_subprocess()
            assert self._active_subprocess.stdout is not None
            while line := await self._active_subprocess.stdout.readline():
                log.write(line.decode(errors="replace").rstrip())
            returncode = await self._active_subprocess.wait()

            if self._cancel_requested:
                log.write("[yellow]Operation cancelled.[/yellow]")
            elif returncode == 0:
                log.write("[green]Operation completed successfully.[/green]")
            else:
                log.write(f"[red]Operation failed with exit code {returncode}.[/red]")
        except asyncio.CancelledError:
            await self._terminate_active_subprocess()
            raise
        except OSError as error:
            log.write(f"[red]Unable to start PDM: {error}[/red]")
        finally:
            self._active_subprocess = None
            self._busy = False
            self._operation_worker = None
            self._set_project_selection_enabled(True)
            self._set_mutation_enabled(self.project_path is not None)
            self.query_one("#venv-cancel", Button).disabled = True
            await self.load_installed_packages()

    async def cancel_active_operation(self) -> None:
        if not self._busy:
            return
        self._cancel_requested = True
        self.query_one("#venv-cancel", Button).disabled = True
        await self._terminate_active_subprocess()

    async def _terminate_active_subprocess(self) -> None:
        process = self._active_subprocess
        if process is None or process.returncode is not None:
            return

        try:
            process.terminate()
        except ProcessLookupError:
            return

        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                return
            await process.wait()

    async def _capture_command(
        self,
        command: list[str],
    ) -> tuple[int, str, str]:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            return 127, "", str(error)
        stdout, stderr = await process.communicate()
        return (
            process.returncode or 0,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
        )

    def _invalidate_project(self, message: str) -> None:
        self.project_path = None
        self._set_mutation_enabled(False)
        self.query_one("#venv-package-table", DataTable).clear()
        self._set_status(f"[red]{message}[/red]")

    def _set_status(self, message: str) -> None:
        self.query_one("#venv-info", Label).update(message)

    def _set_project_selection_enabled(self, enabled: bool) -> None:
        self.query_one("#venv-project-path", Input).disabled = not enabled
        self.query_one("#venv-open-project", Button).disabled = not enabled

    def _set_mutation_enabled(self, enabled: bool) -> None:
        self.query_one("#venv-package-input", Input).disabled = not enabled
        self.query_one("#venv-add", Button).disabled = not enabled
        self.query_one("#venv-remove", Button).disabled = not enabled
        self.query_one("#venv-update-all", Button).disabled = not enabled

    def _write_log(self, message: str, style: str = "") -> None:
        if not message:
            return
        log = self.query_one("#venv-action-log", RichLog)
        log.write(f"[{style}]{message}[/{style}]" if style else message)
