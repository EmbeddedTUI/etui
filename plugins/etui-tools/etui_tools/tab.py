# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import os
import shutil
import signal
import asyncio
from pathlib import Path
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

from rich.markup import escape
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.worker import Worker, WorkerCancelled
from textual.widgets import Label, Button, Input, DataTable, RichLog

from etui.plugin import SettingsField, SettingsSchema, ToolWarningBanner, BusMixin, CancelOnLeaveMixin
from etui.bus_contract import SVC_TOOLS_STATUS

# ==============================================================================
# Manifest & Data Model
# ==============================================================================

class ToolState(StrEnum):
    INSTALLED = "Installed"
    INCOMPLETE = "Incomplete"
    MISSING = "Missing"
    INVALID = "Invalid"
    UNKNOWN = "Unknown"

@dataclass(frozen=True)
class ExecutableProbe:
    name: str
    version_args: tuple[str, ...]
    required: bool = True

@dataclass(frozen=True)
class PackagePlan:
    manager: str
    packages: tuple[str, ...]
    documentation_url: str

@dataclass(frozen=True)
class ToolDefinition:
    tool_id: str
    display_name: str
    probes: tuple[ExecutableProbe, ...]
    documentation_url: str
    package_plans: dict[str, PackagePlan]
    validator_name: str | None = None

@dataclass(frozen=True)
class ExecutableResult:
    name: str
    path: str | None
    version: str | None
    error: str | None

@dataclass(frozen=True)
class ToolResult:
    definition: ToolDefinition
    state: ToolState
    executables: tuple[ExecutableResult, ...]
    validation_error: str | None = None

# ==============================================================================
# Catalog Entries
# ==============================================================================

TOOL_CATALOG = (
    ToolDefinition(
        tool_id="stlink",
        display_name="stlink / st-util",
        probes=(
            ExecutableProbe("st-util",  ("--version",)),
            ExecutableProbe("st-flash", ("--version",)),
            ExecutableProbe("st-info",  ("--version",)),
        ),
        documentation_url="https://github.com/stlink-org/stlink",
        package_plans={
            "apt":    PackagePlan("apt-get", ("stlink-tools",), "https://github.com/stlink-org/stlink"),
            "dnf":    PackagePlan("dnf",     ("stlink",),       "https://github.com/stlink-org/stlink"),
            "pacman": PackagePlan("pacman",  ("stlink",),       "https://github.com/stlink-org/stlink"),
            "brew":   PackagePlan("brew",    ("stlink",),       "https://github.com/stlink-org/stlink"),
        },
    ),
    ToolDefinition(
        tool_id="openocd",
        display_name="OpenOCD",
        probes=(ExecutableProbe("openocd", ("--version",)),),
        documentation_url="https://openocd.org/",
        package_plans={
            "apt": PackagePlan("apt-get", ("openocd",), "https://openocd.org/"),
            "dnf": PackagePlan("dnf", ("openocd",), "https://openocd.org/"),
            "pacman": PackagePlan("pacman", ("openocd",), "https://openocd.org/"),
            "brew": PackagePlan("brew", ("openocd",), "https://openocd.org/"),
            "winget": PackagePlan("winget", ("OpenOCD.OpenOCD",), "https://openocd.org/"),
        },
    ),
    ToolDefinition(
        tool_id="gnu-arm",
        display_name="GNU Arm Embedded Toolchain",
        probes=(
            ExecutableProbe("arm-none-eabi-gcc", ("--version",)),
            ExecutableProbe("arm-none-eabi-g++", ("--version",)),
            ExecutableProbe("arm-none-eabi-gdb", ("--version",)),
            ExecutableProbe("arm-none-eabi-objcopy", ("--version",)),
            ExecutableProbe("arm-none-eabi-size", ("--version",)),
        ),
        documentation_url="https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads",
        package_plans={
            "apt": PackagePlan("apt-get", ("gcc-arm-none-eabi", "gdb-multiarch"), "https://developer.arm.com/"),
            "dnf": PackagePlan("dnf", ("arm-none-eabi-gcc-cs", "arm-none-eabi-newlib"), "https://developer.arm.com/"),
            "pacman": PackagePlan("pacman", ("arm-none-eabi-gcc", "arm-none-eabi-newlib", "arm-none-eabi-gdb"), "https://developer.arm.com/"),
            "brew": PackagePlan("brew", ("arm-none-eabi-gcc",), "https://developer.arm.com/"),
            "winget": PackagePlan("winget", ("Arm.GnuArmEmbedded",), "https://developer.arm.com/"),
        },
        validator_name="validate_gnu_arm",
    ),
    ToolDefinition(
        tool_id="llvm-embedded",
        display_name="LLVM Embedded Toolchain",
        probes=(
            ExecutableProbe("clang", ("--version",)),
            ExecutableProbe("clang++", ("--version",)),
            ExecutableProbe("lld", ("--version",)),
            ExecutableProbe("llvm-objcopy", ("--version",)),
            ExecutableProbe("llvm-size", ("--version",)),
        ),
        documentation_url="https://github.com/ARM-software/LLVM-embedded-toolchain-for-Arm",
        package_plans={
            "apt": PackagePlan("apt-get", ("clang", "lld", "lldb"), "https://github.com/ARM-software/LLVM-embedded-toolchain-for-Arm"),
            "dnf": PackagePlan("dnf", ("clang", "lld", "lldb"), "https://github.com/ARM-software/LLVM-embedded-toolchain-for-Arm"),
            "pacman": PackagePlan("pacman", ("clang", "lld", "lldb"), "https://github.com/ARM-software/LLVM-embedded-toolchain-for-Arm"),
            "brew": PackagePlan("brew", ("llvm",), "https://github.com/ARM-software/LLVM-embedded-toolchain-for-Arm"),
            "winget": PackagePlan("winget", ("LLVM.LLVM",), "https://github.com/ARM-software/LLVM-embedded-toolchain-for-Arm"),
        },
        validator_name="validate_llvm_arm",
    ),
    ToolDefinition(
        tool_id="lldb",
        display_name="LLDB Debugger",
        probes=(ExecutableProbe("lldb", ("--version",)),),
        documentation_url="https://lldb.llvm.org/",
        package_plans={
            "apt": PackagePlan("apt-get", ("lldb",), "https://lldb.llvm.org/"),
            "dnf": PackagePlan("dnf", ("lldb",), "https://lldb.llvm.org/"),
            "pacman": PackagePlan("pacman", ("lldb",), "https://lldb.llvm.org/"),
            "brew": PackagePlan("brew", ("llvm",), "https://lldb.llvm.org/"),
            "winget": PackagePlan("winget", ("LLVM.LLVM",), "https://lldb.llvm.org/"),
        },
    ),
    ToolDefinition(
        tool_id="git",
        display_name="Git",
        probes=(ExecutableProbe("git", ("--version",)),),
        documentation_url="https://git-scm.com/",
        package_plans={
            "apt": PackagePlan("apt-get", ("git",), "https://git-scm.com/"),
            "dnf": PackagePlan("dnf", ("git",), "https://git-scm.com/"),
            "pacman": PackagePlan("pacman", ("git",), "https://git-scm.com/"),
            "brew": PackagePlan("brew", ("git",), "https://git-scm.com/"),
            "winget": PackagePlan("winget", ("Git.Git",), "https://git-scm.com/"),
        },
    ),
    ToolDefinition(
        tool_id="gh",
        display_name="GitHub CLI",
        probes=(ExecutableProbe("gh", ("--version",)),),
        documentation_url="https://cli.github.com/",
        package_plans={
            "apt": PackagePlan("apt-get", ("gh",), "https://cli.github.com/"),
            "dnf": PackagePlan("dnf", ("gh",), "https://cli.github.com/"),
            "pacman": PackagePlan("pacman", ("github-cli",), "https://cli.github.com/"),
            "brew": PackagePlan("brew", ("gh",), "https://cli.github.com/"),
            "winget": PackagePlan("winget", ("GitHub.cli",), "https://cli.github.com/"),
        },
    ),
    ToolDefinition(
        tool_id="cmake",
        display_name="CMake",
        probes=(
            ExecutableProbe("cmake", ("--version",)),
            ExecutableProbe("ctest", ("--version",)),
        ),
        documentation_url="https://cmake.org/download/",
        package_plans={
            "apt": PackagePlan("apt-get", ("cmake",), "https://cmake.org/"),
            "dnf": PackagePlan("dnf", ("cmake",), "https://cmake.org/"),
            "pacman": PackagePlan("pacman", ("cmake",), "https://cmake.org/"),
            "brew": PackagePlan("brew", ("cmake",), "https://cmake.org/"),
            "winget": PackagePlan("winget", ("Kitware.CMake",), "https://cmake.org/"),
        },
        validator_name="validate_cmake_installation",
    ),
)

TOOL_BY_ID = {t.tool_id: t for t in TOOL_CATALOG}

MANAGER_TO_KEY = {
    "apt-get": "apt",
    "dnf": "dnf",
    "pacman": "pacman",
    "brew": "brew",
    "winget": "winget"
}

INSTALL_BUILDERS = {
    "apt": lambda packages: ["apt-get", "install", "-y", "--", *packages],
    "dnf": lambda packages: ["dnf", "install", "-y", "--", *packages],
    "pacman": lambda packages: ["pacman", "-S", "--needed", "--noconfirm", "--", *packages],
    "brew": lambda packages: ["brew", "install", "--formula", *packages],
    "winget": lambda packages: [
        "winget", "install", "--exact", "--accept-package-agreements",
        "--accept-source-agreements", "--id", packages[0],
    ],
}

# ==============================================================================
# Service Layer
# ==============================================================================

class ToolService:
    def __init__(self, extra_search_paths: tuple[Path, ...]) -> None:
        self.extra_search_paths = extra_search_paths

    def find_executable(self, name: str) -> Path | None:
        search_path = os.pathsep.join(
            [*(str(path) for path in self.extra_search_paths),
             os.environ.get("PATH", "")]
        )
        result = shutil.which(name, path=search_path)
        return Path(result).resolve() if result else None

    async def scan_tool(self, definition: ToolDefinition) -> ToolResult:
        """Locate probes, capture versions, and run capability validation."""
        exec_results = []
        is_incomplete = False
        is_missing = False
        
        for probe in definition.probes:
            exe_path = self.find_executable(probe.name)
            if not exe_path:
                exec_results.append(ExecutableResult(probe.name, None, None, "Executable not found on path"))
                if probe.required:
                    is_missing = True
                continue
                
            # Run version command
            try:
                proc = await asyncio.create_subprocess_exec(
                    str(exe_path), *probe.version_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=2.0)
                if proc.returncode != 0:
                    exec_results.append(ExecutableResult(probe.name, str(exe_path), None, f"Version probe exited with code {proc.returncode}"))
                    if probe.required:
                        is_incomplete = True
                else:
                    # Parse version string (typically first line of output)
                    output = stdout.decode(errors="replace").strip() or stderr.decode(errors="replace").strip()
                    first_line = output.splitlines()[0] if output else "Unknown version"
                    exec_results.append(ExecutableResult(probe.name, str(exe_path), first_line, None))
            except Exception as e:
                exec_results.append(ExecutableResult(probe.name, str(exe_path), None, f"Failed to execute probe: {e}"))
                if probe.required:
                    is_incomplete = True

        # Run capability validation if primary executable is installed
        val_error = None
        state = ToolState.INSTALLED
        
        if is_missing:
            state = ToolState.MISSING
        elif is_incomplete:
            state = ToolState.INCOMPLETE
        elif definition.validator_name:
            primary_exe = exec_results[0]
            if primary_exe.path:
                validator = getattr(self, definition.validator_name, None)
                if validator:
                    val_error = await validator(Path(primary_exe.path))
                    if val_error:
                        state = ToolState.INCOMPLETE
            else:
                state = ToolState.MISSING
                
        return ToolResult(definition, state, tuple(exec_results), val_error)

    async def validate_gnu_arm(self, path: Path) -> str | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                str(path), "-dumpmachine",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            if proc.returncode != 0:
                return f"GCC check failed: {stderr.decode(errors='replace')}"
            machine = stdout.decode(errors="replace").strip()
            if not machine.startswith("arm-none-eabi"):
                return f"Invalid target machine: {machine} (expected arm-none-eabi)"
            return None
        except Exception as e:
            return f"Validation error: {e}"

    async def validate_llvm_arm(self, path: Path) -> str | None:
        try:
            # Run clang compile probe with empty input
            proc = await asyncio.create_subprocess_exec(
                str(path), "--target=arm-none-eabi", "-x", "c", "-fsyntax-only", "-",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(input=b""), timeout=3.0)
            if proc.returncode != 0:
                return f"Target compilation check failed: {stderr.decode(errors='replace')}"
            return None
        except Exception as e:
            return f"Validation error: {e}"

    async def validate_cmake_installation(self, path: Path) -> str | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                str(path), "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            if proc.returncode != 0:
                return f"CMake check failed: {stderr.decode(errors='replace')}"
            
            # Find ctest companion in the same directory as cmake
            ctest_path = path.parent / ("ctest.exe" if os.name == "nt" else "ctest")
            if not ctest_path.is_file():
                return f"ctest companion not found at {ctest_path}"
            return None
        except Exception as e:
            return f"Validation error: {e}"

    def detect_package_managers(self) -> tuple[str, ...]:
        """Return supported managers whose executables are available."""
        managers = []
        if os.name != "nt":
            # POSIX package managers
            for manager in ("apt-get", "dnf", "pacman", "brew"):
                if shutil.which(manager) is not None:
                    managers.append(manager)
        else:
            # Windows package manager
            if shutil.which("winget") is not None:
                managers.append("winget")
        return tuple(managers)

    def build_install_command(
        self,
        definition: ToolDefinition,
        manager: str,
    ) -> list[str]:
        """Build one fixed command from a verified manifest entry."""
        key = MANAGER_TO_KEY.get(manager)
        if not key or key not in definition.package_plans:
            raise ValueError(f"No installation plan for manager '{manager}'")
        
        plan = definition.package_plans[key]
        builder = INSTALL_BUILDERS.get(key)
        if not builder:
            raise ValueError(f"Unsupported package manager builder '{key}'")
            
        return builder(plan.packages)

# ==============================================================================
# Modal Confirmation Screen
# ==============================================================================

class InstallConfirmation(ModalScreen[bool]):
    DEFAULT_CSS = """
    InstallConfirmation {
        align: center middle;
        background: rgba(0, 0, 0, 0.5);
    }

    #confirm-dialog {
        width: 60;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: thick $accent;
    }

    #confirm-dialog Label {
        margin-bottom: 1;
    }

    #confirm-dialog Button {
        margin-right: 2;
    }
    """

    def __init__(self, display_name: str, command: list[str]) -> None:
        super().__init__()
        self.display_name = display_name
        self.command = command

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(f"Are you sure you want to install {self.display_name}?")
            yield Label(f"Command to run:\n{' '.join(self.command)}")
            with Horizontal():
                yield Button("Yes, Install", id="btn-confirm-yes", variant="primary")
                yield Button("Cancel", id="btn-confirm-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm-yes":
            self.dismiss(True)
        else:
            self.dismiss(False)

# ==============================================================================
# Main Tools Tab Component
# ==============================================================================

class ToolsTab(CancelOnLeaveMixin, BusMixin, Vertical):
    """ TUI interface for managing external development tools """

    settings_schema = SettingsSchema(
        section="tools",
        fields=(
            SettingsField(
                key="custom_paths",
                type="str",
                label="Custom tool paths:",
                default="",
            ),
        ),
    )

    DEFAULT_CSS = """
    ToolsTab {
        height: 1fr;
    }

    ToolsTab #tools-toolbar {
        height: 3;
        padding: 0 1;
        align: left middle;
        background: $surface;
        border-bottom: solid $accent;
    }

    ToolsTab #txt-tools-custom-dir {
        width: 40;
        margin-right: 1;
    }

    ToolsTab #tools-toolbar Button {
        margin-right: 1;
    }

    ToolsTab #tools-main {
        height: 1fr;
    }

    ToolsTab #tools-table {
        width: 55%;
        height: 1fr;
        border-right: solid $accent;
    }

    ToolsTab #tools-details {
        width: 45%;
        padding: 1;
    }

    ToolsTab #tools-log {
        height: 1fr;
        margin-top: 1;
        background: $boost;
    }
    """

    def __init__(self, custom_paths: list[Path] | None = None) -> None:
        super().__init__()
        self.results: dict[str, ToolResult] = {}
        self.selected_tool_id: str | None = None
        self.custom_paths = list(custom_paths or [])
        self.busy = False
        self._active_subprocess: asyncio.subprocess.Process | None = None
        self._operation_worker: Worker[None] | None = None
        self.service = ToolService(tuple(self.custom_paths))

    def compose(self) -> ComposeResult:
        with Horizontal(id="tools-toolbar"):
            yield Label("Add Search Path: ", classes="control-label")
            yield Input(placeholder="Path to folder...", id="txt-tools-custom-dir")
            yield Button("Add Path", id="btn-tools-add-dir")
            yield Button("Scan All", id="btn-tools-scan")
            yield Button("Cancel", id="btn-tools-cancel", variant="warning", disabled=True)

        with Horizontal(id="tools-main"):
            yield DataTable(id="tools-table")
            with Vertical(id="tools-details"):
                yield Label("Select a tool to view details.", id="lbl-tool-details")
                yield DataTable(id="tbl-tool-executables")
                with Horizontal(id="tools-actions"):
                    yield Button("Install", id="btn-tools-install", disabled=True)
                    yield Button("Rescan Tool", id="btn-tools-rescan", disabled=True)
                yield RichLog(id="tools-log", highlight=True, markup=True)

    def get_status_payload(self) -> dict:
        tools_info = {}
        for tool_id, res in self.results.items():
            present = res.state == ToolState.INSTALLED
            tools_info[tool_id] = {
                "present": present,
                "version": res.version,
                "path": str(res.active_path) if res.active_path else None,
            }
        for tool_id, defn in TOOL_BY_ID.items():
            if tool_id not in tools_info:
                present = True
                for probe in defn.probes:
                    if probe.required:
                        if shutil.which(probe.name) is None:
                            present = False
                            break
                tools_info[tool_id] = {
                    "present": present,
                    "version": None,
                    "path": None,
                }
        return {"tools": tools_info}

    async def _svc_tools_status(self) -> dict:
        return self.get_status_payload()

    def on_mount(self) -> None:
        super().on_mount()
        self._status_provider = self.bus.provide(SVC_TOOLS_STATUS, self._svc_tools_status)

        table = self.query_one("#tools-table", DataTable)
        table.add_columns("Tool", "Status", "Version", "Active Path", "Source")
        
        sub_table = self.query_one("#tbl-tool-executables", DataTable)
        sub_table.add_columns("Executable", "Path", "Version", "Status")
        
        # Load settings
        manager = getattr(self.app, "settings_manager", None)
        if manager is not None:
            self.custom_paths = [
                Path(path) for path in manager.get("tools", "custom_paths", [])
            ]
            self.service = ToolService(tuple(self.custom_paths))

        self._set_controls_enabled(True)
        self.start_scan_all()

    async def on_unmount(self) -> None:
        super().on_unmount()
        if hasattr(self, "_status_provider"):
            self._status_provider()
        await self.cancel_active_operation()

    def apply_settings(self, settings: dict) -> None:
        """Apply new custom paths settings and rescan if needed."""
        self.custom_paths = [
            Path(path) for path in settings.get("custom_paths", [])
        ]
        self.service = ToolService(tuple(self.custom_paths))
        if not self.busy:
            self.start_scan_all()

    def _save_custom_paths(self) -> None:
        try:
            manager = getattr(self.app, "settings_manager", None)
            if manager is not None:
                manager.set(
                    "tools", "custom_paths", [str(path) for path in self.custom_paths]
                )
        except Exception:
            pass

    def start_scan_all(self) -> None:
        self._start_operation(self._scan_all(), "tools-scan-all")

    def _start_operation(self, coroutine, name: str) -> None:
        if self.busy:
            coroutine.close()
            return
        self.busy = True
        self._operation_worker = self.run_worker(
            coroutine,
            name=name,
            group="tools-ops",
            exclusive=True,
            exit_on_error=False,
        )

    async def _scan_all(self) -> None:
        self._set_controls_enabled(False)
        log = self.query_one("#tools-log", RichLog)
        log.clear()
        log.write("[cyan]Scanning host system for catalog tools...[/cyan]\n")
        
        try:
            for definition in TOOL_CATALOG:
                res = await self.service.scan_tool(definition)
                self.results[definition.tool_id] = res
            
            self._render_table()
            # Restore selection details if possible
            if self.selected_tool_id:
                self._render_tool_details(self.selected_tool_id)
            
            self.bus.emit("tools.changed", self.get_status_payload(), source="plugin-tools")
            for banner in self.app.query(ToolWarningBanner):
                banner.check_status()
            log.write("[green]System scan completed successfully.[/green]")
        except asyncio.CancelledError:
            log.write("[yellow]Scan cancelled.[/yellow]")
        finally:
            self._active_subprocess = None
            self._operation_worker = None
            self.busy = False
            self._set_controls_enabled(True)

    async def _rescan_single_tool(self, tool_id: str) -> None:
        self._set_controls_enabled(False)
        log = self.query_one("#tools-log", RichLog)
        log.clear()
        
        definition = TOOL_BY_ID[tool_id]
        log.write(f"[cyan]Scanning {definition.display_name}...[/cyan]\n")
        
        try:
            res = await self.service.scan_tool(definition)
            self.results[tool_id] = res
            
            self.bus.emit("tools.changed", self.get_status_payload(), source="plugin-tools")
            for banner in self.app.query(ToolWarningBanner):
                banner.check_status()
            self._render_table()
            self._render_tool_details(tool_id)
            log.write(f"[green]Scan of {definition.display_name} completed.[/green]")
        except asyncio.CancelledError:
            log.write("[yellow]Scan cancelled.[/yellow]")
        finally:
            self._active_subprocess = None
            self._operation_worker = None
            self.busy = False
            self._set_controls_enabled(True)

    def _render_table(self) -> None:
        table = self.query_one("#tools-table", DataTable)
        table.clear()
        
        for definition in TOOL_CATALOG:
            res = self.results.get(definition.tool_id)
            if not res:
                table.add_row(definition.display_name, "Unknown", "-", "-", "-")
                continue
                
            active_path = "-"
            source = "-"
            version = "-"
            
            primary_exe = res.executables[0] if res.executables else None
            if primary_exe and primary_exe.path:
                active_path = str(primary_exe.path)
                version = primary_exe.version or "Unknown version"
                
                # Determine source
                resolved_path = Path(primary_exe.path)
                found_custom = False
                for custom_p in self.custom_paths:
                    if resolved_path.is_relative_to(custom_p):
                        source = f"Custom: {custom_p.name}"
                        found_custom = True
                        break
                if not found_custom:
                    source = "System PATH"
            
            table.add_row(
                definition.display_name,
                res.state.value,
                version,
                active_path,
                source
            )

    def _render_tool_details(self, tool_id: str) -> None:
        res = self.results.get(tool_id)
        if not res:
            return
            
        lbl = self.query_one("#lbl-tool-details", Label)
        desc = [
            f"[bold]{escape(res.definition.display_name)}[/bold]",
            f"Documentation: {res.definition.documentation_url}",
            f"Overall Status: [bold]{res.state.value}[/bold]"
        ]
        if res.validation_error:
            desc.append(f"[red]Validation Error: {escape(res.validation_error)}[/red]")
        lbl.update("\n".join(desc))
        
        sub_table = self.query_one("#tbl-tool-executables", DataTable)
        sub_table.clear()
        
        for exe_res in res.executables:
            path_str = exe_res.path or "-"
            version_str = exe_res.version or "-"
            status_str = "Installed" if exe_res.path else "Missing"
            if exe_res.error:
                status_str = f"Error: {exe_res.error}"
                
            sub_table.add_row(
                exe_res.name,
                path_str,
                version_str,
                status_str
            )
            
        # Set up install & rescan button actions
        install_btn = self.query_one("#btn-tools-install", Button)
        rescan_btn = self.query_one("#btn-tools-rescan", Button)
        rescan_btn.disabled = self.busy
        
        # Check package manager plans
        available_managers = self.service.detect_package_managers()
        manager_key = next((m for m in available_managers if MANAGER_TO_KEY.get(m) in res.definition.package_plans), None)
        
        if res.state == ToolState.INSTALLED:
            install_btn.disabled = True
            install_btn.label = "Installed"
        elif manager_key:
            install_btn.disabled = self.busy
            install_btn.label = f"Install via {manager_key}"
        else:
            install_btn.disabled = True
            install_btn.label = "Manual Install Required"

    async def _stream_command(self, command: list[str], timeout: float) -> int:
        log = self.query_one("#tools-log", RichLog)
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=(os.name == "posix")
        )
        self._active_subprocess = process

        async def read_stream(stream):
            try:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    # Escape outputs to prevent RichLog markup injection
                    log.write(escape(line.decode(errors="replace").rstrip()))
            except asyncio.CancelledError:
                pass

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    read_stream(process.stdout),
                    read_stream(process.stderr)
                ),
                timeout=timeout
            )
            await process.wait()
            return process.returncode or 0
        except (TimeoutError, asyncio.TimeoutError):
            await self._terminate_active_subprocess()
            log.write("[red]Error: Command execution timed out.[/red]")
            return -1
        except asyncio.CancelledError:
            await self._terminate_active_subprocess()
            log.write("[yellow]Warning: Operation cancelled by user.[/yellow]")
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
            self.query_one("#btn-tools-scan", Button).disabled = not enabled or self.busy
            self.query_one("#btn-tools-cancel", Button).disabled = not self.busy
            self.query_one("#btn-tools-add-dir", Button).disabled = not enabled or self.busy
            self.query_one("#txt-tools-custom-dir", Input).disabled = not enabled or self.busy
            
            if self.selected_tool_id:
                res = self.results.get(self.selected_tool_id)
                if res:
                    self.query_one("#btn-tools-rescan", Button).disabled = not enabled or self.busy
                    available_managers = self.service.detect_package_managers()
                    manager_key = next((m for m in available_managers if MANAGER_TO_KEY.get(m) in res.definition.package_plans), None)
                    if res.state != ToolState.INSTALLED and manager_key:
                        self.query_one("#btn-tools-install", Button).disabled = not enabled or self.busy
        except NoMatches:
            pass

    async def _install_and_rescan(self, definition: ToolDefinition, command: list[str]) -> None:
        self.busy = True
        self._set_controls_enabled(False)
        log = self.query_one("#tools-log", RichLog)
        log.clear()
        
        try:
            confirmed = await self.app.push_screen_wait(
                InstallConfirmation(definition.display_name, command)
            )
            if not confirmed:
                log.write("[yellow]Installation cancelled by user.[/yellow]")
                return
                
            log.write(f"[cyan]Starting installation of {definition.display_name}...[/cyan]\n")
            returncode = await self._stream_command(command, timeout=15 * 60)
            
            if returncode != 0:
                log.write(
                    f"\n[red]Installation failed with exit status {returncode}.[/red]\n"
                    f"Please run the command manually in a terminal if elevation is needed:\n"
                    f"  {' '.join(command)}"
                )
                return
                
            log.write("\n[green]Installation process completed. Verifying...[/green]")
            res = await self.service.scan_tool(definition)
            self.results[definition.tool_id] = res
            if hasattr(self.app, "tool_registry"):
                self.app.tool_registry.update_result(definition.tool_id, res)
                for banner in self.app.query(ToolWarningBanner):
                    banner.check_status()
            self._render_table()
            self._render_tool_details(definition.tool_id)
        except TimeoutError:
            log.write("\n[red]Installation timed out.[/red]")
        except asyncio.CancelledError:
            log.write("\n[yellow]Installation cancelled by user.[/yellow]")
        finally:
            self._active_subprocess = None
            self._operation_worker = None
            self.busy = False
            self._set_controls_enabled(True)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "btn-tools-scan":
            self.start_scan_all()
        elif button_id == "btn-tools-cancel":
            await self.cancel_active_operation()
        elif button_id == "btn-tools-add-dir":
            path_val = self.query_one("#txt-tools-custom-dir", Input).value.strip()
            if not path_val:
                return
            cand = Path(path_val).expanduser().resolve()
            if not cand.is_dir():
                self.query_one("#tools-log", RichLog).write(f"[red]Error: Path '{path_val}' is not a valid directory.[/red]")
                return
            if cand not in self.custom_paths:
                self.custom_paths.append(cand)
                self._save_custom_paths()
                self.service = ToolService(tuple(self.custom_paths))
                self.query_one("#txt-tools-custom-dir", Input).value = ""
                self.start_scan_all()
        elif button_id == "btn-tools-rescan":
            if self.selected_tool_id:
                self._start_operation(self._rescan_single_tool(self.selected_tool_id), f"tools-rescan-{self.selected_tool_id}")
        elif button_id == "btn-tools-install":
            if self.selected_tool_id:
                definition = TOOL_BY_ID[self.selected_tool_id]
                available_managers = self.service.detect_package_managers()
                manager_key = next((m for m in available_managers if MANAGER_TO_KEY.get(m) in definition.package_plans), None)
                if manager_key:
                    command = self.service.build_install_command(definition, manager_key)
                    self._start_operation(
                        self._install_and_rescan(definition, command),
                        f"tools-install-{self.selected_tool_id}"
                    )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.control.id != "tools-table":
            return
        row_data = self.query_one("#tools-table", DataTable).get_row(event.row_key)
        tool_name = str(row_data[0])
        # Find tool definition
        for definition in TOOL_CATALOG:
            if definition.display_name == tool_name:
                self.selected_tool_id = definition.tool_id
                self._render_tool_details(definition.tool_id)
                self._set_controls_enabled(True)
                break

    def select_tool(self, tool_id: str) -> None:
        """Programmatically select a tool in the table and display its details."""
        table = self.query_one("#tools-table", DataTable)
        for index, row_key in enumerate(table.rows):
            row_data = table.get_row(row_key)
            defn = TOOL_BY_ID.get(tool_id)
            if defn and row_data[0] == defn.display_name:
                table.move_cursor(row=index)
                self.selected_tool_id = tool_id
                self._render_tool_details(tool_id)
                self._set_controls_enabled(True)
                break


# ==============================================================================
# Tool Registry & Warning Banner
# ==============================================================================

class ToolRegistry:
    def __init__(self, app) -> None:
        self.app = app
        self._results: dict[str, ToolResult] = {}

    def update_result(self, tool_id: str, result: ToolResult) -> None:
        self._results[tool_id] = result

    def get_result(self, tool_id: str) -> ToolResult | None:
        return self._results.get(tool_id)

    def is_installed(self, tool_id: str) -> bool:
        res = self._results.get(tool_id)
        return res is not None and res.state == ToolState.INSTALLED

    def is_missing_or_incomplete(self, tool_id: str) -> bool:
        res = self._results.get(tool_id)
        if res is not None:
            return res.state in (ToolState.MISSING, ToolState.INCOMPLETE, ToolState.INVALID)
        
        # Fallback before scan finishes
        defn = TOOL_BY_ID.get(tool_id)
        if not defn:
            return False
        for probe in defn.probes:
            if probe.required:
                if shutil.which(probe.name) is None:
                    return True
        return False
