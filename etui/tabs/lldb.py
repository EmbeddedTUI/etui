# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
import json
import re
import shutil
from pathlib import Path
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Button
from textual.widgets import Input
from textual.widgets import RichLog
from textual.widgets import Static


# Markers used to separate dashboard output (emitted by the lldb stop-hook)
# from normal interactive console output on the shared stdout stream.
DASH_BEGIN = "<<<ETUI-DASH-BEGIN>>>"
DASH_END = "<<<ETUI-DASH-END>>>"
SECTION = "### "

# Available dashboard sections, modeled on gdb-dashboard's modules.
# name -> (title, [lldb commands]).
SECTIONS = {
    "registers": ("Registers", ["register read"]),
    "assembly": ("Assembly", ["disassemble --pc --count 8"]),
    "stack": ("Stack", ["memory read --size 4 --format x --count 16 $sp"]),
    "backtrace": ("Backtrace", ["thread backtrace"]),
    "source": ("Source", ["source list --count 10"]),
    "locals": ("Locals", ["frame variable"]),
}
DEFAULT_LAYOUT = ["registers", "assembly", "stack", "backtrace"]
TITLE_TO_NAME = {title: name for name, (title, _) in SECTIONS.items()}

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
]
CONTROL_CMDS = {bid: cmd for _, bid, cmd in CONTROLS}
CONTROL_REFRESH = {"ctl-up", "ctl-down"}

DASHBOARD_PATH = Path.home() / ".config" / "etui" / "dashboard.json"


def load_config() -> tuple[list[str], list[str]]:
    """ Load persisted (layout, collapsed) section lists, validated. """
    layout, collapsed = list(DEFAULT_LAYOUT), []
    try:
        data = json.loads(DASHBOARD_PATH.read_text())
        saved = [s for s in data.get("layout", []) if s in SECTIONS]
        if saved:
            layout = saved
        collapsed = [s for s in data.get("collapsed", []) if s in SECTIONS]
    except Exception:
        pass
    return layout, collapsed


def save_config(layout: list[str], collapsed: list[str]) -> None:
    DASHBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_PATH.write_text(
        json.dumps({"layout": layout, "collapsed": collapsed}, indent=2)
    )


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


class DashboardSection(Vertical):
    """ One collapsible, reorderable dashboard section. """

    DEFAULT_CSS = """
        DashboardSection { height: auto; margin-bottom: 1; }
        DashboardSection .dash-header { height: 1; }
        DashboardSection .dash-btn {
            min-width: 3; width: auto; height: 1; border: none;
            padding: 0 1; margin: 0;
        }
        DashboardSection .dash-title {
            width: 1fr; height: 1; text-style: bold reverse;
        }
        DashboardSection .dash-content { height: auto; padding-left: 1; }
    """

    def __init__(self, name: str, title: str, collapsed: bool):
        super().__init__(id=f"sec-{name}")
        self._name = name
        self._title = title
        self._collapsed = collapsed

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

    def update_content(self, lines: list[str]) -> None:
        self.query_one("#dash-content", Static).update("\n".join(lines))


class LldbLog(RichLog):
    def __init__(self):
        super().__init__(highlight=True, markup=True)
        self.write("LLDB session")
        self.write("[dim]use [+]/[-] to collapse, up/down to reorder[/dim]")


class LldbTab(Horizontal):
    """ LLDB tab - lldb session attached to a gdb remote, with a dashboard.

    Opened automatically once the hardware debugger (OpenOCD) has started
    its gdb server. The left panel is the interactive lldb console; the
    right panel is a gdb-dashboard-style view of collapsible, reorderable
    sections that redraw on every stop via an lldb stop-hook. Section
    layout and collapsed state are persisted.
    """

    DEFAULT_CSS = """
        LldbTab #lldb-console { width: 1fr; }
        LldbTab #lldb-dashboard { width: 1fr; border-left: solid $accent; }
        LldbTab #lldb-sections { height: 1fr; }
        LldbTab #lldb-controls { height: 3; dock: bottom; }
        LldbTab #lldb-controls Button {
            min-width: 8; width: 1fr; margin: 0;
        }
    """

    def __init__(self, port: int, arch: str | None = None):
        super().__init__()
        self._port = port
        self._arch = arch
        self._proc: asyncio.subprocess.Process | None = None
        # Dashboard parsing state and configuration.
        self._in_dash = False
        self._dash_buf: list[str] = []
        self._last_data: dict[str, list[str]] = {}
        self._layout, self._collapsed = load_config()
        self._stop_hook_id: int | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="lldb-console"):
            yield LldbLog()
            yield Input(placeholder="lldb command", id="lldb-input")
        with Vertical(id="lldb-dashboard"):
            with VerticalScroll(id="lldb-sections"):
                for name in self._layout:
                    yield DashboardSection(
                        name, SECTIONS[name][0], name in self._collapsed
                    )
            with Horizontal(id="lldb-controls"):
                for label, bid, _cmd in CONTROLS:
                    yield Button(label, id=bid)

    async def on_mount(self) -> None:
        await self.start()

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
        save_config(self._layout, self._collapsed)

    async def on_section_move(self, message: SectionMove) -> None:
        i = self._layout.index(message.name)
        j = i + message.delta
        if not (0 <= j < len(self._layout)):
            return
        self._layout[i], self._layout[j] = self._layout[j], self._layout[i]
        save_config(self._layout, self._collapsed)
        await self._rebuild_sections()
        await self._install_stop_hook()
        await self.refresh_dashboard()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
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

    async def _rebuild_sections(self) -> None:
        container = self.query_one("#lldb-sections", VerticalScroll)
        await container.remove_children()
        for name in self._layout:
            await container.mount(
                DashboardSection(name, SECTIONS[name][0], name in self._collapsed)
            )
        self._apply_data()

    # ------------------------------------------------------------------ lldb

    async def start(self) -> None:
        log = self.query_one(LldbLog)
        if shutil.which("lldb") is None:
            log.write("[red]lldb not found on PATH[/red]")
            return
        self._proc = await asyncio.create_subprocess_exec(
            "lldb", "--no-use-colors",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        log.write("[green]lldb started[/green]")
        self.run_worker(self._read_output(), exclusive=False)
        # Set the architecture before connecting so lldb does not probe
        # bogus memory while auto-detecting the target.
        if self._arch:
            await self._send_raw(f"settings set target.default-arch {self._arch}")
        # Connect to the OpenOCD gdb server.
        await self.send_command(f"gdb-remote localhost:{self._port}")
        # Install a stop-hook that redraws the dashboard on every stop, then
        # draw it once for the initial (post-connect) halted state.
        await self._install_stop_hook()
        await self.refresh_dashboard()

    def _dash_commands(self) -> list[str]:
        """ Build the marker-wrapped command list for the current layout. """
        cmds = [f"script print('{DASH_BEGIN}')"]
        for name in self._layout:
            title, section_cmds = SECTIONS[name]
            cmds.append(f"script print('{SECTION}{title}')")
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
        if self._proc is not None and self._proc.returncode is None:
            self._proc.kill()

    # ---------------------------------------------------------------- output

    async def _read_output(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            self._route(line.decode(errors="replace").rstrip())

    def _route(self, text: str) -> None:
        """ Send dashboard-marked output to the dashboard, rest to console. """
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
            section.update_content(self._last_data.get(name, []))
