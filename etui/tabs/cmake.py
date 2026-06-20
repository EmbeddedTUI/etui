# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import os
import shutil
import signal
import json
import asyncio
from pathlib import Path
from rich.markup import escape
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label, Button, Input, DataTable, RichLog
from textual.worker import Worker, WorkerCancelled

if __package__:
    from ..contracts import on_workspace_changed
else:  # pragma: no cover - script-mode import
    from contracts import on_workspace_changed


class CMakeTab(Vertical):
    """ Project CMake build configuration and dashboard """

    DEFAULT_CSS = """
    CMakeTab {
        height: 1fr;
    }

    CMakeTab #cmake-header-bar {
        height: 6;
        background: $surface;
        border-bottom: solid $accent;
        padding: 1;
    }

    CMakeTab #cmake-main-split {
        height: 1fr;
    }

    CMakeTab #cmake-targets-view {
        width: 30%;
        height: 1fr;
        border-right: solid $accent;
    }

    CMakeTab #cmake-output-panel {
        width: 70%;
        height: 1fr;
    }

    CMakeTab #cmake-log-viewer {
        height: 1fr;
        background: $boost;
    }

    CMakeTab #cmake-control-bar {
        height: 3;
        padding: 0 1;
        align: left middle;
        border-top: solid $accent;
    }

    CMakeTab #cmake-control-bar Button {
        margin-right: 1;
    }
    """

    BUILD_TYPES = {"Debug", "Release", "RelWithDebInfo", "MinSizeRel"}

    def __init__(self) -> None:
        super().__init__()
        self.repo_path: Path | None = None
        self.build_path: Path | None = None
        self._configured_build_path: Path | None = None
        self._configured_build_type: str | None = None
        self.selected_build_type: str = "Debug"
        self.selected_target: str = "all"
        self.is_multi_config: bool = False
        self.known_targets: set[str] = {"all"}
        self.busy: bool = False
        self._active_subprocess: asyncio.subprocess.Process | None = None
        self._operation_worker: Worker[None] | None = None
        self._workspace_disposer = None

    def compose(self) -> ComposeResult:
        if __package__:
            from .tools import ToolWarningBanner
        else:
            from tools import ToolWarningBanner
        yield ToolWarningBanner("cmake", "CMake", id="cmake-tool-warning")

        with Vertical(id="cmake-header-bar"):
            with Horizontal():
                yield Label("Source Dir: ", classes="control-label")
                yield Input(placeholder="Path to CMakeLists.txt root", id="txt-cmake-source", disabled=True)
            with Horizontal():
                yield Label("Build Dir:  ", classes="control-label")
                yield Input(placeholder="Relative path (e.g. build)", id="txt-cmake-build")
                yield Label("Build Type: ", classes="control-label")
                yield Input(placeholder="Debug", id="txt-cmake-type")

        with Horizontal(id="cmake-main-split"):
            # Left pane: Available targets
            yield DataTable(id="cmake-targets-view")

            # Right pane: Build log and command controls
            with Vertical(id="cmake-output-panel"):
                yield RichLog(id="cmake-log-viewer", highlight=True, markup=True)
                with Horizontal(id="cmake-control-bar"):
                    yield Button("Configure", id="btn-cmake-configure")
                    yield Button("Build", id="btn-cmake-build", variant="primary")
                    yield Button("Clean", id="btn-cmake-clean")
                    yield Button("Cancel", id="btn-cmake-cancel", variant="warning", disabled=True)

    def on_mount(self) -> None:
        bus = getattr(self.app, "bus", None)
        if bus is not None:
            self._workspace_disposer = on_workspace_changed(
                bus,
                self._on_workspace_changed,
            )
        table = self.query_one(DataTable)
        table.add_columns("Target Name", "Type")
        self._set_controls_enabled(False)

    async def on_unmount(self) -> None:
        if self._workspace_disposer is not None:
            self._workspace_disposer()
            self._workspace_disposer = None
        await self.cancel_active_operation()

    def _on_workspace_changed(self, event) -> None:
        repo_path = Path(event.root).resolve()
        self.repo_path = repo_path
        source_input = self.query_one("#txt-cmake-source", Input)
        build_input = self.query_one("#txt-cmake-build", Input)
        if (repo_path / "CMakeLists.txt").is_file():
            source_input.value = str(repo_path)
            build_input.value = "build"
            self.build_path = (repo_path / "build").resolve()
        else:
            source_input.value = ""
            build_input.value = ""
            self.build_path = None

    async def change_repository(self, repo_path: Path) -> None:
        await self.cancel_active_operation()
        self.repo_path = repo_path.resolve()
        
        source_input = self.query_one("#txt-cmake-source", Input)
        build_input = self.query_one("#txt-cmake-build", Input)
        log = self.query_one(RichLog)
        
        # Check CMake executable presence
        cmake_exists = False
        if hasattr(self.app, "tool_registry"):
            cmake_exists = self.app.tool_registry.is_installed("cmake")
        if not cmake_exists:
            cmake_exists = shutil.which("cmake") is not None

        if not cmake_exists:
            log.clear()
            log.write("[red]Error: 'cmake' executable not found on system PATH.[/red]")
            self._set_controls_enabled(False)
            return

        if (self.repo_path / "CMakeLists.txt").is_file():
            source_input.value = str(self.repo_path)
            build_input.value = "build"
            self.build_path = (self.repo_path / "build").resolve()
            log.clear()
            log.write("[green]CMake project detected.[/green]")
            self._set_controls_enabled(True)
            self._start_operation(self._setup_file_api_and_load_targets(), "cmake-setup")
        else:
            source_input.value = ""
            build_input.value = ""
            self.build_path = None
            log.clear()
            log.write("[yellow]No CMakeLists.txt found at repository root. CMake Tab is disabled.[/yellow]")
            self._set_controls_enabled(False)
            self.query_one(DataTable).clear()

    def _start_operation(self, coroutine, name: str) -> None:
        if self.busy:
            coroutine.close()
            return
        # Set busy synchronously before spawning worker to avoid scheduling races
        self.busy = True
        self._operation_worker = self.run_worker(
            coroutine,
            name=name,
            group="cmake-ops",
            exclusive=True,
            exit_on_error=False
        )

    async def _setup_file_api_and_load_targets(self) -> None:
        if not self.repo_path or not self.build_path:
            self.busy = False
            return

        self._set_controls_enabled(False)
        log = self.query_one(RichLog)
        
        try:
            # Write codemodel-v2 API query before configuration
            query_dir = self.build_path / ".cmake" / "api" / "v1" / "query" / "client-etui"
            query_dir.mkdir(parents=True, exist_ok=True)
            query_file = query_dir / "query.json"
            query_data = {"requests": [{"kind": "codemodel", "version": 2}]}
            query_file.write_text(json.dumps(query_data))
            
            # Check if configure is needed to prevent stale targets
            reply_dir = self.build_path / ".cmake" / "api" / "v1" / "reply"
            index_files = list(reply_dir.glob("index-*.json"))
            needs_configure = True
            if index_files:
                latest_index = max(index_files, key=os.path.getmtime)
                cmakelists = self.repo_path / "CMakeLists.txt"
                if cmakelists.is_file() and latest_index.stat().st_mtime >= cmakelists.stat().st_mtime:
                    needs_configure = False

            if needs_configure:
                log.write("[cyan]Generating/Refreshing CMake API Cache...[/cyan]")
                cmd = ["cmake", "-S", str(self.repo_path), "-B", str(self.build_path)]
                if not self.is_multi_config:
                    cmd.append(f"-DCMAKE_BUILD_TYPE={self.selected_build_type}")
                ret, _, err = await self._capture_command(cmd, timeout=30)
                if ret != 0:
                    log.write(f"[red]Initial configuration failed: {escape(err)}[/red]")
                    return

            await self._load_targets_from_reply()
        except Exception as e:
            log.write(f"[red]Error loading CMake File API: {escape(str(e))}[/red]")
        finally:
            self.busy = False
            self._set_controls_enabled(True)

    async def _load_targets_from_reply(self) -> None:
        reply_dir = self.build_path / ".cmake" / "api" / "v1" / "reply"
        targets = await self._parse_file_api_reply(reply_dir)
        
        table = self.query_one(DataTable)
        table.clear()
        table.add_row("all", "Build All Targets")
        self.known_targets = {"all"}
        
        for t_name, t_type in targets:
            table.add_row(t_name, t_type)
            self.known_targets.add(t_name)
            
        self._configured_build_path = self.build_path
        self._configured_build_type = self.selected_build_type

    async def _parse_file_api_reply(self, reply_dir: Path) -> list[tuple[str, str]]:
        if not reply_dir.is_dir():
            raise FileNotFoundError(f"Reply directory '{reply_dir}' does not exist.")

        # Parse index-*.json file to identify correct codemodel-v2 file
        index_files = list(reply_dir.glob("index-*.json"))
        if not index_files:
            raise FileNotFoundError("CMake File API index file not found. Project must be configured first.")
        latest_index = max(index_files, key=os.path.getmtime)
        
        with open(latest_index, "r") as f:
            try:
                index_data = json.load(f)
            except json.JSONDecodeError as e:
                raise ValueError(f"Malformed index JSON: {e}")
            
        # Extract generator multi-config capability
        cmake_info = index_data.get("cmake", {})
        generator_info = cmake_info.get("generator", {})
        self.is_multi_config = generator_info.get("multiConfig", False)

        # Find reply for codemodel kind
        reply_file_name = None
        replies = index_data.get("reply", {})
        client_replies = replies.get("client-etui", {}).get("query.json", {}).get("responses", [])
        for resp in client_replies:
            if resp.get("kind") == "codemodel":
                reply_file_name = resp.get("jsonFile")
        
        if not reply_file_name:
            raise ValueError("CMake File API replies do not contain codemodel metadata. Make sure query was written and configure completed.")
            
        codemodel_path = reply_dir / reply_file_name
        if not codemodel_path.is_file():
            raise FileNotFoundError(f"Codemodel reply file '{reply_file_name}' not found.")

        with open(codemodel_path, "r") as f:
            try:
                codemodel_data = json.load(f)
            except json.JSONDecodeError as e:
                raise ValueError(f"Malformed codemodel JSON: {e}")
            
        targets = []
        configurations = codemodel_data.get("configurations", [])
        if not configurations:
            raise ValueError("CMake codemodel response contains no configurations.")
            
        # Select appropriate configuration list for multi-config vs single-config
        active_config = configurations[0]
        if self.is_multi_config:
            found = False
            for cfg in configurations:
                if cfg.get("name") == self.selected_build_type:
                    active_config = cfg
                    found = True
                    break
            if not found:
                raise ValueError(f"Configuration '{self.selected_build_type}' not found in codemodel. Available: {', '.join(c.get('name', '') for c in configurations)}")

        for target_ref in active_config.get("targets", []):
            t_name = target_ref.get("name")
            target_json_name = target_ref.get("jsonFile")
            t_type = "Target"
            
            # Read detailed target JSON file to extract type
            if target_json_name:
                try:
                    with open(reply_dir / target_json_name, "r") as tf:
                        target_detail = json.load(tf)
                        t_type = target_detail.get("type", "Target")
                except Exception:
                    pass
            
            targets.append((t_name, t_type))
        return targets

    async def _capture_command(
        self,
        command: list[str],
        *,
        timeout: float,
        log_widget: RichLog | None = None
    ) -> tuple[int, str, str]:
        """ Unified runner with process group cancellation support """
        cmd_args = list(command)
        if cmd_args:
            exe = cmd_args[0]
            if exe in ("cmake", "ctest") and hasattr(self.app, "tool_registry"):
                res = self.app.tool_registry.get_result("cmake")
                if res and res.state.value == "Installed":
                    for e in res.executables:
                        if e.name == exe and e.path:
                            cmd_args[0] = e.path
                            break

        process = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=(os.name == "posix")
        )
        self._active_subprocess = process
        
        stdout_chunks = []
        stderr_chunks = []

        async def read_stream(stream, chunks):
            try:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded = line.decode(errors="replace")
                    chunks.append(decoded)
                    # Stream both stdout and stderr outputs to the log in real-time
                    if log_widget:
                        log_widget.write(escape(decoded.rstrip()))
            except asyncio.CancelledError:
                pass

        try:
            # Read stdout and stderr concurrently with a timeout limit
            await asyncio.wait_for(
                asyncio.gather(
                    read_stream(process.stdout, stdout_chunks),
                    read_stream(process.stderr, stderr_chunks)
                ),
                timeout=timeout
            )
            await process.wait()
            return (
                process.returncode or 0,
                "".join(stdout_chunks),
                "".join(stderr_chunks)
            )
        except (TimeoutError, asyncio.TimeoutError, asyncio.CancelledError) as e:
            await self._terminate_active_subprocess()
            if isinstance(e, (TimeoutError, asyncio.TimeoutError)):
                return (-1, "".join(stdout_chunks), "Command execution timed out.")
            raise
        finally:
            if self._active_subprocess is process:
                self._active_subprocess = None

    async def _run_cmake_operation(self, args: list[str], timeout: float) -> None:
        self.busy = True
        self._set_controls_enabled(False)
        log = self.query_one(RichLog)
        log.clear()
        
        log.write(f"[bold cyan]Running: cmake {' '.join(args)}[/bold cyan]\n")
        
        try:
            ret, _, err = await self._capture_command(["cmake"] + args, timeout=timeout, log_widget=log)
            if ret == 0:
                log.write("\n[bold green]CMake operation succeeded.[/bold green]")
                if "-S" in args:
                    await self._load_targets_from_reply()
            else:
                log.write(f"\n[bold red]CMake failed: {escape(err)}[/bold red]")
        except asyncio.CancelledError:
            log.write("\n[bold yellow]Operation cancelled by user.[/bold yellow]")
        finally:
            self._active_subprocess = None
            self.busy = False
            self._set_controls_enabled(True)

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
        except TimeoutError:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                return
            await process.wait()

    def _set_controls_enabled(self, enabled: bool) -> None:
        if not self.is_mounted:
            return
        from textual.css.query import NoMatches
        try:
            self.query_one("#btn-cmake-configure", Button).disabled = not enabled or self.busy
            self.query_one("#btn-cmake-build", Button).disabled = not enabled or self.busy
            self.query_one("#btn-cmake-clean", Button).disabled = not enabled or self.busy
            self.query_one("#btn-cmake-cancel", Button).disabled = not self.busy
            self.query_one("#txt-cmake-build", Input).disabled = not enabled or self.busy
            self.query_one("#txt-cmake-type", Input).disabled = not enabled or self.busy
        except NoMatches:
            pass

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "btn-cmake-cancel":
            await self.cancel_active_operation()
            return
            
        if self.busy or not self.repo_path or not self.build_path:
            return
            
        # 1. Validate Build Type
        build_type = self.query_one("#txt-cmake-type", Input).value.strip() or "Debug"
        if build_type not in self.BUILD_TYPES:
            self.query_one(RichLog).write(f"[red]Error: Invalid Build Type '{escape(build_type)}'. Must be one of: {', '.join(self.BUILD_TYPES)}[/red]")
            return
        self.selected_build_type = build_type

        # 2. Validate and Constrain Build Path Containment (Strict sub-containment check)
        custom_build_dir = self.query_one("#txt-cmake-build", Input).value.strip() or "build"
        candidate_build_path = (self.repo_path / custom_build_dir).resolve()
        if not candidate_build_path.is_relative_to(self.repo_path) or candidate_build_path == self.repo_path:
            self.query_one(RichLog).write("[red]Error: Build directory must reside strictly inside a subdirectory of the repository root.[/red]")
            return

        # 3. Require Configure before operating on a changed directory or build type
        if button_id in {"btn-cmake-build", "btn-cmake-clean"}:
            if candidate_build_path != self._configured_build_path or build_type != self._configured_build_type:
                self.query_one(RichLog).write("[red]Error: Build directory or type has changed. You must 'Configure' the project first.[/red]")
                return

        self.build_path = candidate_build_path

        # 4. Validate target name
        if self.selected_target.startswith("-"):
            self.query_one(RichLog).write("[red]Error: Invalid target name starting with '-'.[/red]")
            return
        if self.selected_target not in self.known_targets:
            self.query_one(RichLog).write(f"[red]Error: Target '{escape(self.selected_target)}' is unknown.[/red]")
            return

        if button_id == "btn-cmake-configure":
            # Set up File API query directory first
            query_dir = self.build_path / ".cmake" / "api" / "v1" / "query" / "client-etui"
            query_dir.mkdir(parents=True, exist_ok=True)
            query_file = query_dir / "query.json"
            query_data = {"requests": [{"kind": "codemodel", "version": 2}]}
            query_file.write_text(json.dumps(query_data))

            args = ["-S", str(self.repo_path), "-B", str(self.build_path)]
            if not self.is_multi_config:
                args.append(f"-DCMAKE_BUILD_TYPE={self.selected_build_type}")
            self._start_operation(self._run_cmake_operation(args, timeout=60), "cmake-configure")

        elif button_id == "btn-cmake-build":
            args = ["--build", str(self.build_path), "--target", self.selected_target]
            if self.is_multi_config:
                args.extend(["--config", self.selected_build_type])
            self._start_operation(self._run_cmake_operation(args, timeout=300), "cmake-build")

        elif button_id == "btn-cmake-clean":
            args = ["--build", str(self.build_path), "--target", "clean"]
            if self.is_multi_config:
                args.extend(["--config", self.selected_build_type])
            self._start_operation(self._run_cmake_operation(args, timeout=60), "cmake-clean")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if self.busy:
            return
        row_data = self.query_one(DataTable).get_row(event.row_key)
        self.selected_target = str(row_data[0])
        self.query_one(RichLog).write(f"[cyan]Selected target: {escape(self.selected_target)}[/cyan]")
