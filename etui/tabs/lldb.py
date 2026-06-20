# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
import json
import re
import shutil
from pathlib import Path
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Button
from textual.widgets import Input
from textual.widgets import RichLog
from textual.widgets import Static


if __package__:
    from ..contracts import on_theme_changed, theme_get, ThemeChanged
else:
    from contracts import on_theme_changed, theme_get, ThemeChanged


# Markers used to separate dashboard output (emitted by the lldb stop-hook)
# from normal interactive console output on the shared stdout stream.
DASH_BEGIN = "<<<ETUI-DASH-BEGIN>>>"
DASH_END = "<<<ETUI-DASH-END>>>"
SECTION = "### "

# Available dashboard sections, modeled on gdb-dashboard's modules.
# name -> (title, [lldb commands]).
SECTIONS = {
    "registers": ("Registers", ["register read"]),
    # LLDB 20 can abort in IRMemoryMap::FindSpace when `disassemble --pc`
    # queries inconsistent memory-region data from embedded gdb-remotes.
    # Reading bounded Thumb halfwords avoids that host-process crash.
    "assembly": (
        "Code Memory",
        ["memory read --size 2 --format x --count 8 $pc"],
    ),
    "stack": ("Stack", ["memory read --size 4 --format x --count 16 $sp"]),
    "backtrace": ("Backtrace", ["thread backtrace"]),
    "source": ("Source", ["source list --count 10"]),
    "locals": ("Locals", ["frame variable"]),
}
DEFAULT_LAYOUT = ["registers", "assembly", "stack", "backtrace"]
TITLE_TO_NAME = {title: name for name, (title, _) in SECTIONS.items()}

# Selectable dashboard color schemes. Each maps style keys to Rich style
# strings ("none" => no style). "header" is the section-title color.
THEMES = {
    "vibrant": {
        "header": "yellow",
        "dim": "grey50",
        "reg_name": "bright_cyan",
        "value": "bright_green",
        "changed": "bold bright_yellow",
        "address": "bright_green",
        "current": "bold black on yellow",
        "mem_word": "magenta",
        "frame": "bright_yellow",
        "thread": "bright_magenta",
    },
    "ocean": {
        "header": "cyan",
        "dim": "grey46",
        "reg_name": "cyan",
        "value": "bright_white",
        "changed": "bold bright_cyan",
        "address": "bright_blue",
        "current": "bold black on cyan",
        "mem_word": "blue",
        "frame": "bright_cyan",
        "thread": "bright_blue",
    },
    "solarized": {
        "header": "#b58900",
        "dim": "#586e75",
        "reg_name": "#268bd2",
        "value": "#93a1a1",
        "changed": "bold #859900",
        "address": "#2aa198",
        "current": "bold #073642 on #b58900",
        "mem_word": "#6c71c4",
        "frame": "#cb4b16",
        "thread": "#d33682",
    },
    "subtle": {
        "header": "yellow",
        "dim": "grey58",
        "reg_name": "grey58",
        "value": "none",
        "changed": "bold green",
        "address": "grey58",
        "current": "bold",
        "mem_word": "none",
        "frame": "yellow",
        "thread": "grey58",
    },
    "mono": {
        "header": "white",
        "dim": "grey42",
        "reg_name": "grey70",
        "value": "none",
        "changed": "bold white",
        "address": "grey50",
        "current": "reverse",
        "mem_word": "none",
        "frame": "bold",
        "thread": "grey50",
    },
}
DEFAULT_THEME = "vibrant"
MEMORY_MAP_ASSERTION = 'GetMemoryRegionInfo() succeeded, then failed'
CONNECT_FAILURE = "error: Failed to connect port"

# Debug control buttons shown at the bottom of the dashboard panel.
# (label, button id, lldb command). Frame nav refreshes the dashboard
# directly since it does not trigger a stop event.
CONTROLS = [
    ("Cont", "ctl-continue", "continue"),
    ("Next", "ctl-next", "next"),
    ("Step", "ctl-step", "step"),
    ("Finish", "ctl-finish", "finish"),
    ("Halt", "ctl-halt", "process interrupt"),
    ("Up", "ctl-up", "up"),
    ("Down", "ctl-down", "down"),
    ("Restart", "ctl-restart", None),
]
CONTROL_CMDS = {bid: cmd for _, bid, cmd in CONTROLS if cmd}
CONTROL_REFRESH = {"ctl-up", "ctl-down"}

DASHBOARD_PATH = Path.home() / ".config" / "etui" / "dashboard.json"


def load_config() -> tuple[list[str], list[str], str]:
    """ Load persisted (layout, collapsed, theme), validated. """
    layout, collapsed, theme = list(DEFAULT_LAYOUT), [], DEFAULT_THEME
    try:
        data = json.loads(DASHBOARD_PATH.read_text())
        saved = [s for s in data.get("layout", []) if s in SECTIONS]
        if saved:
            layout = saved
        collapsed = [s for s in data.get("collapsed", []) if s in SECTIONS]
        if data.get("theme") in THEMES:
            theme = data["theme"]
    except Exception:
        pass
    return layout, collapsed, theme


def save_config(layout: list[str], collapsed: list[str], theme: str) -> None:
    DASHBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_PATH.write_text(
        json.dumps(
            {"layout": layout, "collapsed": collapsed, "theme": theme}, indent=2
        )
    )


def save_theme(theme: str) -> None:
    """ Persist only the theme, preserving the saved layout/collapsed. """
    layout, collapsed, _ = load_config()
    save_config(layout, collapsed, theme)


class SectionMove(Message):
    def __init__(self, name: str, delta: int) -> None:
        super().__init__()
        self.name = name
        self.delta = delta


class SectionToggle(Message):
    def __init__(self, name: str, collapsed: bool) -> None:
        super().__init__()
        self.name = name
        self.collapsed = collapsed


class ProbeRestartRequested(Message):
    """Request a fresh gdb-server process after LLDB aborts."""


class DashboardSection(Vertical):
    """ One collapsible, reorderable dashboard section. """

    DEFAULT_CSS = """
        DashboardSection { height: auto; margin-bottom: 1; }
        DashboardSection .dash-header { height: 1; }
        DashboardSection .dash-btn {
            min-width: 3; width: auto; height: 1; border: none;
            padding: 0 1; margin: 0;
        }
        DashboardSection .dash-header { border-bottom: solid #3a3a3a; }
        DashboardSection .dash-title {
            width: 1fr; height: 1; text-style: bold; color: yellow;
        }
        DashboardSection .dash-content { height: auto; padding-left: 1; }
    """

    def __init__(self, name: str, title: str, collapsed: bool,
                 header_color: str = "yellow"):
        super().__init__(id=f"sec-{name}")
        self._name = name
        self._title = title
        self._collapsed = collapsed
        self._header_color = header_color

    def compose(self) -> ComposeResult:
        with Horizontal(classes="dash-header"):
            yield Button(
                "[+]" if self._collapsed else "[-]",
                id="dash-toggle", classes="dash-btn",
            )
            yield Static(f" {self._title} ", classes="dash-title")
            yield Button("▲", id="dash-up", classes="dash-btn")
            yield Button("▼", id="dash-down", classes="dash-btn")
        content = Static("", classes="dash-content", id="dash-content", markup=False)
        content.display = not self._collapsed
        yield content

    def on_mount(self) -> None:
        # Header color uses Textual's parser; ignore values it can't handle.
        try:
            self.query_one(".dash-title", Static).styles.color = self._header_color
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "dash-toggle":
            self._collapsed = not self._collapsed
            self.query_one("#dash-content", Static).display = not self._collapsed
            event.button.label = "[+]" if self._collapsed else "[-]"
            self.post_message(SectionToggle(self._name, self._collapsed))
        elif event.button.id == "dash-up":
            self.post_message(SectionMove(self._name, -1))
        elif event.button.id == "dash-down":
            self.post_message(SectionMove(self._name, +1))

    def update_content(self, renderable) -> None:
        self.query_one("#dash-content", Static).update(renderable)


class LldbLog(RichLog):
    def __init__(self):
        super().__init__(highlight=True, markup=True)
        self.write("LLDB session")
        self.write("[dim]use [+]/[-] to collapse, up/down to reorder[/dim]")


class LldbTab(Vertical):
    """ LLDB tab - lldb session attached to a gdb remote, with a dashboard.

    Opened automatically once the hardware debugger (OpenOCD) has started
    its gdb server. The left panel is the interactive lldb console; the
    right panel is a gdb-dashboard-style view of collapsible, reorderable
    sections that redraw on every stop via an lldb stop-hook. Section
    layout and collapsed state are persisted.
    """

    DEFAULT_CSS = """
        LldbTab { height: 1fr; }
        LldbTab #lldb-main { height: 1fr; }
        LldbTab #lldb-toolbar {
            height: 3;
            padding: 0 1;
            background: $surface;
        }
        LldbTab #lldb-executable-label {
            width: auto;
            height: 3;
            content-align: left middle;
            margin-right: 1;
        }
        LldbTab #lldb-executable { width: 1fr; }
        LldbTab #lldb-load-executable {
            width: 18;
            margin-left: 1;
        }
        LldbTab #lldb-console { width: 2fr; }
        LldbTab #lldb-dashboard { width: 3fr; border-left: solid $accent; }
        LldbTab #lldb-sections { height: 1fr; }
        LldbTab #lldb-controls { height: 3; dock: bottom; }
        LldbTab #lldb-controls Button {
            min-width: 8; width: 1fr; margin: 0;
        }
    """

    def __init__(
        self,
        port: int | None = None,
        arch: str | None = None,
        settings: dict | None = None,
    ):
        super().__init__()
        self._port = port
        self._arch = arch
        self._executable: Path | None = None
        self._proc: asyncio.subprocess.Process | None = None
        # Dashboard parsing state and configuration.
        self._in_dash = False
        self._dash_buf: list[str] = []
        self._last_data: dict[str, list[str]] = {}
        # Previous values per section, used to highlight what changed.
        self._prev: dict[str, dict] = {}
        if settings is None:
            self._layout, self._collapsed, self._theme_name = load_config()
        else:
            layout = [
                name for name in settings.get("layout", []) if name in SECTIONS
            ]
            self._layout = layout or list(DEFAULT_LAYOUT)
            self._collapsed = [
                name for name in settings.get("collapsed", []) if name in SECTIONS
            ]
            theme = str(settings.get("theme", DEFAULT_THEME))
            self._theme_name = theme if theme in THEMES else DEFAULT_THEME
            executable = str(settings.get("executable", "")).strip()
            if executable:
                self._executable = Path(executable).expanduser().resolve()
        self._theme = THEMES[self._theme_name]
        self._stop_hook_id: int | None = None
        self._memory_map_assertion = False
        self._suppress_crash_trace = False
        self._recovery_attempted = False
        self._remote_memory_safe_mode = False
        self._connect_event = asyncio.Event()
        self._connect_succeeded = False
        self._theme_disposer = None

    def compose(self) -> ComposeResult:
        if __package__:
            from ..plugin import ToolWarningBanner
        else:
            from plugin import ToolWarningBanner
        yield ToolWarningBanner("lldb", "LLDB", id="lldb-tool-warning")
        with Horizontal(id="lldb-toolbar"):
            yield Static("Firmware ELF:", id="lldb-executable-label")
            yield Input(
                value=str(self._executable or ""),
                placeholder="Path to firmware .elf for symbols and source",
                id="lldb-executable",
            )
            yield Button("Load / Reconnect", id="lldb-load-executable")
        with Horizontal(id="lldb-main"):
            with Vertical(id="lldb-console"):
                yield LldbLog()
                yield Input(placeholder="lldb command", id="lldb-input")
            with Vertical(id="lldb-dashboard"):
                with VerticalScroll(id="lldb-sections"):
                    for name in self._layout:
                        yield DashboardSection(
                            name, SECTIONS[name][0], name in self._collapsed,
                            self._sc("header"),
                        )
                with Horizontal(id="lldb-controls"):
                    for label, bid, _cmd in CONTROLS:
                        yield Button(label, id=bid)

    async def on_mount(self) -> None:
        self.query_one(LldbLog).write(
            "[dim]waiting for probe - start it in the Probe tab[/dim]"
        )
        bus = getattr(self.app, "bus", None)
        if bus is not None:
            try:
                theme = await theme_get(bus)
                await self.set_theme(theme)
            except Exception:
                pass
            self._theme_disposer = on_theme_changed(
                bus,
                self._on_theme_changed,
            )

    async def connect(self, port: int, arch: str | None) -> None:
        """ (Re)connect lldb to the gdb server on the given port. """
        if self._proc is not None and self._proc.returncode is None:
            self._proc.kill()
            self._proc = None
        self._port = port
        self._arch = arch
        self._stop_hook_id = None
        self._recovery_attempted = False
        await self.start()

    async def restart(self) -> None:
        log = self.query_one(LldbLog)
        if self._port is None:
            log.write("[yellow]no previous connection to restart[/yellow]")
            return
        log.write("[cyan]restarting lldb...[/cyan]")
        self._recovery_attempted = False
        await self.connect(self._port, self._arch)

    async def set_theme(self, name: str) -> None:
        if getattr(self, "_theme_name", None) == name:
            return
        self._theme_name = name
        self._theme = THEMES[name]
        await self._rebuild_sections()

    def _on_theme_changed(self, event: ThemeChanged) -> None:
        self.run_worker(self.set_theme(event.name))

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        event.input.value = ""
        if command:
            await self.send_command(command)

    # ------------------------------------------------------ section controls

    async def on_section_toggle(self, message: SectionToggle) -> None:
        if message.collapsed and message.name not in self._collapsed:
            self._collapsed.append(message.name)
        elif not message.collapsed and message.name in self._collapsed:
            self._collapsed.remove(message.name)
        self._persist_config()

    async def on_section_move(self, message: SectionMove) -> None:
        i = self._layout.index(message.name)
        j = i + message.delta
        if not (0 <= j < len(self._layout)):
            return
        self._layout[i], self._layout[j] = self._layout[j], self._layout[i]
        self._persist_config()
        await self._rebuild_sections()
        await self._install_stop_hook()
        await self.refresh_dashboard()

    def _persist_config(self) -> None:
        manager = getattr(self.app, "settings_manager", None)
        if manager is None:
            save_config(self._layout, self._collapsed, self._theme_name)
            return
        manager.settings["lldb"].update(
            {
                "layout": list(self._layout),
                "collapsed": list(self._collapsed),
                "theme": self._theme_name,
            }
        )
        try:
            manager.save_settings()
        except OSError:
            pass

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "lldb-load-executable":
            await self._load_executable_and_reconnect()
            return
        if event.button.id == "ctl-restart":
            await self.restart()
            return
        cmd = CONTROL_CMDS.get(event.button.id or "")
        if cmd is None:
            return
        # Issue the command through the left console input so it flows the
        # same way a typed command does (appears in the console, runs lldb).
        console_input = self.query_one("#lldb-input", Input)
        console_input.value = cmd
        await console_input.action_submit()
        # Frame navigation doesn't trigger a stop-hook; refresh manually.
        if event.button.id in CONTROL_REFRESH:
            await self.refresh_dashboard()

    async def _load_executable_and_reconnect(self) -> None:
        value = self.query_one("#lldb-executable", Input).value.strip()
        executable: Path | None = None
        if value:
            executable = Path(value).expanduser().resolve()
            if not executable.is_file():
                self.notify(
                    f"Firmware executable does not exist: {value}",
                    severity="error",
                )
                return
            try:
                with executable.open("rb") as firmware:
                    magic = firmware.read(4)
                if magic != b"\x7fELF":
                    self.notify(
                        f"Firmware executable is not an ELF file: {value}",
                        severity="error",
                    )
                    return
            except OSError as error:
                self.notify(f"Could not read firmware ELF: {error}", severity="error")
                return

        self._executable = executable
        manager = getattr(self.app, "settings_manager", None)
        if manager is not None:
            manager.settings["lldb"]["executable"] = str(executable or "")
            try:
                manager.save_settings()
            except OSError as error:
                self.notify(f"Could not save LLDB settings: {error}", severity="error")
                return

        if self._port is None:
            self.notify("Firmware ELF saved; start the probe to connect.")
            return
        await self.connect(self._port, self._arch)

    async def _rebuild_sections(self) -> None:
        container = self.query_one("#lldb-sections", VerticalScroll)
        await container.remove_children()
        for name in self._layout:
            await container.mount(
                DashboardSection(
                    name, SECTIONS[name][0], name in self._collapsed,
                    self._sc("header"),
                )
            )
        self._apply_data()

    # ------------------------------------------------------------------ lldb

    def _target_setup_command(self) -> str | None:
        if self._executable and self._executable.is_file():
            arch_arg = f" --arch {self._arch}" if self._arch else ""
            return f"target create{arch_arg} {json.dumps(str(self._executable))}"
        if self._arch:
            return f"settings set target.default-arch {self._arch}"
        return None

    async def start(self) -> bool:
        log = self.query_one(LldbLog)
        self._memory_map_assertion = False
        self._suppress_crash_trace = False
        
        lldb_path = "lldb"
        if hasattr(self.app, "tool_registry"):
            res = self.app.tool_registry.get_result("lldb")
            if res and res.state.value == "Installed":
                for exe in res.executables:
                    if exe.name == "lldb" and exe.path:
                        lldb_path = exe.path
                        break

        if shutil.which(lldb_path) is None:
            log.write(f"[red]{lldb_path} not found on PATH[/red]")
            return False
        self._proc = await asyncio.create_subprocess_exec(
            lldb_path, "--no-use-colors",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        log.write("[green]lldb started[/green]")
        self.run_worker(self._read_output(), exclusive=False)
        target_setup = self._target_setup_command()
        if target_setup:
            await self._send_raw(target_setup)
        if self._executable and self._executable.is_file():
            log.write(f"[green]loaded symbols:[/green] {self._executable}")
        elif self._arch:
            log.write(
                "[yellow]no firmware ELF loaded; symbols, source, and exact "
                "disassembly boundaries are unavailable[/yellow]"
            )
        # Connect to the OpenOCD gdb server.
        if not await self._connect_remote():
            await self._discard_process(self._proc)
            return False
        # Install a stop-hook that redraws the dashboard on every stop, then
        # draw it once for the initial (post-connect) halted state.
        await self._install_stop_hook()
        await self.refresh_dashboard()
        return True

    async def _connect_remote(self, timeout: float = 5.0) -> bool:
        self._connect_event = asyncio.Event()
        self._connect_succeeded = False
        await self.send_command(f"gdb-remote localhost:{self._port}")
        try:
            await asyncio.wait_for(self._connect_event.wait(), timeout=timeout)
        except TimeoutError:
            self.query_one(LldbLog).write(
                "[red]timed out waiting for the gdb server connection[/red]"
            )
            return False
        finally:
            self._connect_event = None
        return self._connect_succeeded

    async def _discard_process(
        self, process: asyncio.subprocess.Process | None
    ) -> None:
        if process is None:
            return
        if self._proc is process:
            self._proc = None
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                return
            await process.wait()

    def _dash_commands(self) -> list[str]:
        """ Build the marker-wrapped command list for the current layout. """
        cmds = [f"script print('{DASH_BEGIN}')"]
        for name in self._layout:
            title, section_cmds = SECTIONS[name]
            cmds.append(f"script print('{SECTION}{title}')")
            if self._remote_memory_safe_mode and name in {"assembly", "stack"}:
                cmds.append(
                    "script print('remote memory view disabled after LLDB crash')"
                )
            else:
                cmds.extend(section_cmds)
        cmds.append(f"script print('{DASH_END}')")
        return cmds

    async def _install_stop_hook(self) -> None:
        # Replace any previous hook so layout changes take effect.
        if self._stop_hook_id is not None:
            await self._send_raw(f"target stop-hook delete {self._stop_hook_id}")
            self._stop_hook_id = None
        # "target stop-hook add" reads commands until a line containing DONE.
        await self._send_raw("target stop-hook add")
        for cmd in self._dash_commands():
            await self._send_raw(cmd)
        await self._send_raw("DONE")

    async def refresh_dashboard(self) -> None:
        for cmd in self._dash_commands():
            await self._send_raw(cmd)

    async def send_command(self, command: str) -> None:
        log = self.query_one(LldbLog)
        if self._proc is None or self._proc.returncode is not None:
            log.write("[red]lldb not running[/red]")
            return
        log.write(f"[cyan](lldb) {command}[/cyan]")
        await self._send_raw(command)

    async def _send_raw(self, command: str) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        self._proc.stdin.write((command + "\n").encode())
        await self._proc.stdin.drain()

    def on_unmount(self) -> None:
        if self._theme_disposer is not None:
            self._theme_disposer()
            self._theme_disposer = None
        if self._proc is not None and self._proc.returncode is None:
            self._proc.kill()

    # ---------------------------------------------------------------- output

    async def _read_output(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            self._route(line.decode(errors="replace").rstrip())
        # stdout closed: the lldb process has exited (often a crash).
        await proc.wait()
        # Ignore if a newer session already replaced this process.
        if proc is self._proc:
            if self._in_dash:
                self._in_dash = False
                self._dash_buf = []
            self._handle_exit(proc.returncode)
            if self._memory_map_assertion and not self._recovery_attempted:
                self._recovery_attempted = True
                self._request_probe_restart(proc)

    def _request_probe_restart(
        self, failed_process: asyncio.subprocess.Process
    ) -> None:
        if self._port is None or self._proc is not failed_process:
            return
        self._stop_hook_id = None
        self._proc = None
        self.query_one(LldbLog).write(
            "[yellow]restarting the probe server before reconnecting LLDB[/yellow]"
        )
        self.post_message(ProbeRestartRequested())

    def _handle_exit(self, code: int | None) -> None:
        log = self.query_one(LldbLog)
        if self._memory_map_assertion:
            log.write(
                "[bold red]LLDB aborted while querying remote memory regions.[/bold red] "
                "Memory-backed dashboard views have been disabled."
            )
            return
        if code is not None and code < 0:
            log.write(
                f"[bold red]lldb crashed (signal {-code}).[/bold red] "
                "press Restart to reconnect."
            )
        elif code:
            log.write(
                f"[red]lldb exited (code {code}).[/red] press Restart to reconnect."
            )
        else:
            log.write("[yellow]lldb session ended.[/yellow]")

    def _route(self, text: str) -> None:
        """ Send dashboard-marked output to the dashboard, rest to console. """
        if text.startswith("Process ") and "stopped" in text:
            if self._connect_event is not None:
                self._connect_succeeded = True
                self._connect_event.set()
        elif CONNECT_FAILURE in text:
            if self._connect_event is not None:
                self._connect_succeeded = False
                self._connect_event.set()
        if MEMORY_MAP_ASSERTION in text:
            self._memory_map_assertion = True
            self._suppress_crash_trace = True
            self._remote_memory_safe_mode = True
            self._in_dash = False
            self._dash_buf = []
            self._last_data["assembly"] = [
                "LLDB aborted while reading remote memory.",
                "Restarting with memory-backed views disabled.",
            ]
            self._last_data["stack"] = [
                "remote memory view disabled after LLDB crash"
            ]
            self._apply_data()
            process = self._proc
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            return
        if self._suppress_crash_trace:
            return
        # lldb echoes "(lldb) <cmd>" for each piped command (the prompt is
        # printed even without a tty); drop those so neither panel is noisy.
        if text.startswith("(lldb) "):
            return
        # Capture the stop-hook id so we can replace it on layout changes.
        match = re.match(r"Stop hook #(\d+) added", text)
        if match:
            self._stop_hook_id = int(match.group(1))
            return
        if text == DASH_BEGIN:
            self._in_dash = True
            self._dash_buf = []
            return
        if text == DASH_END:
            self._in_dash = False
            self._parse_dashboard(self._dash_buf)
            return
        if self._in_dash:
            self._dash_buf.append(text)
            return
        self.query_one(LldbLog).write(text)

    def _parse_dashboard(self, lines: list[str]) -> None:
        data: dict[str, list[str]] = {}
        current: str | None = None
        for line in lines:
            if line.startswith(SECTION):
                current = TITLE_TO_NAME.get(line[len(SECTION):])
                if current:
                    data[current] = []
            elif current:
                data[current].append(line)
        self._last_data = data
        self._apply_data()

    def _apply_data(self) -> None:
        for name in self._layout:
            try:
                section = self.query_one(f"#sec-{name}", DashboardSection)
            except Exception:
                continue
            lines = self._last_data.get(name, [])
            renderable, new_prev = self._format_section(name, lines)
            section.update_content(renderable)
            self._prev[name] = new_prev

    def _sc(self, key: str) -> str | None:
        """ Resolve a theme style key to a Rich style ("none" => None). """
        value = self._theme.get(key, "none")
        return None if value == "none" else value

    def _format_section(self, name: str, lines: list[str]):
        if name == "registers":
            return self._fmt_registers(lines)
        if name == "stack":
            return self._fmt_memory(lines)
        if name == "assembly":
            return self._fmt_assembly(lines)
        if name == "backtrace":
            return self._fmt_backtrace(lines)
        return self._fmt_plain(lines)

    def _fmt_registers(self, lines: list[str]):
        prev = self._prev.get("registers", {})
        dim, name_s = self._sc("dim"), self._sc("reg_name")
        changed_s, value_s = self._sc("changed"), self._sc("value")
        text = Text()
        new: dict[str, str] = {}
        for line in lines:
            m = re.match(r"\s*([\w.]+) = (0x[0-9a-fA-F]+)(.*)", line)
            if not m:
                text.append(line + "\n", style=dim)
                continue
            reg, val, rest = m.groups()
            new[reg] = val
            changed = reg in prev and prev[reg] != val
            text.append(f"{reg:>5}", style=name_s)
            text.append(" = ", style=dim)
            text.append(val, style=changed_s if changed else value_s)
            text.append(rest + "\n", style=dim)
        return text, new

    def _fmt_memory(self, lines: list[str]):
        prev = self._prev.get("stack", {})
        dim, changed_s, word_s = (
            self._sc("dim"), self._sc("changed"), self._sc("mem_word")
        )
        text = Text()
        new: dict[str, list[str]] = {}
        for line in lines:
            m = re.match(r"(0x[0-9a-fA-F]+):\s*(.*)", line)
            if not m:
                text.append(line + "\n", style=dim)
                continue
            addr, rest = m.groups()
            words = rest.split()
            new[addr] = words
            old = prev.get(addr, [])
            text.append(addr + ": ", style=dim)
            for i, word in enumerate(words):
                changed = i < len(old) and old[i] != word
                text.append(word + " ", style=changed_s if changed else word_s)
            text.append("\n")
        return text, new

    def _fmt_assembly(self, lines: list[str]):
        dim, cur_s = self._sc("dim"), self._sc("current")
        text = Text()
        for line in lines:
            current = line.lstrip().startswith("->")
            m = re.match(r"(\s*(?:->)?\s*)(0x[0-9a-fA-F]+)(:?)(.*)", line)
            if not m:
                text.append(line + "\n", style=dim)
                continue
            pre, addr, colon, rest = m.groups()
            if current or not text:
                text.append(pre + addr + colon + rest + "\n", style=cur_s)
            else:
                text.append(pre)
                text.append(addr, style=dim)
                text.append(colon, style=dim)
                text.append(rest + "\n")
        return text, {}

    def _fmt_backtrace(self, lines: list[str]):
        text = Text()
        for line in lines:
            t = Text(line + "\n")
            t.highlight_regex(r"frame #\d+", self._sc("frame") or "")
            t.highlight_regex(r"thread #\d+", self._sc("thread") or "")
            t.highlight_regex(r"0x[0-9a-fA-F]+", self._sc("address") or "")
            text.append_text(t)
        return text, {}

    def _fmt_plain(self, lines: list[str]):
        text = Text()
        for line in lines:
            t = Text(line + "\n")
            t.highlight_regex(r"0x[0-9a-fA-F]+", self._sc("address") or "")
            text.append_text(t)
        return text, {}
