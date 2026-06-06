# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
import shutil
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.widgets import Button
from textual.widgets import Input
from textual.widgets import RichLog
from textual.widgets import Select


# Available debugger backends: label -> command line (argv) launched as a
# line-oriented interactive console driven over stdin/stdout.
BACKENDS = {
    "pyocd": ["pyocd", "commander"],
    "gdb": ["gdb", "--quiet", "--interpreter=mi2"],
}


class DebuggerLog(RichLog):
    def __init__(self):
        super().__init__(highlight=True, markup=True)
        self.write("Debugger ready")


class DebuggerTab(Horizontal):
    """ Debugger tab - drives pyocd or gdb """

    def __init__(self):
        super().__init__()
        self._proc: asyncio.subprocess.Process | None = None
        self._backend = "pyocd"

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="debugger-controls"):
                yield Select(
                    [(name, name) for name in BACKENDS],
                    value="pyocd",
                    allow_blank=False,
                    id="dbg-backend",
                )
                yield Button("Start", id="dbg-start", variant="success")
                yield Button("Stop", id="dbg-stop", variant="error")
            yield DebuggerLog()
            yield Input(placeholder="debugger command", id="dbg-input")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "dbg-backend":
            self._backend = str(event.value)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "dbg-start":
            await self.start()
        elif event.button.id == "dbg-stop":
            await self.stop()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        event.input.value = ""
        if command:
            await self.send_command(command)

    async def start(self) -> None:
        log = self.query_one(DebuggerLog)
        if self._proc is not None and self._proc.returncode is None:
            log.write("[yellow]debugger already running[/yellow]")
            return
        argv = BACKENDS[self._backend]
        if shutil.which(argv[0]) is None:
            log.write(f"[red]{argv[0]} not found on PATH[/red]")
            return
        self._proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        log.write(f"[green]{self._backend} started[/green]")
        self.run_worker(self._read_output(), exclusive=False)

    async def stop(self) -> None:
        log = self.query_one(DebuggerLog)
        if self._proc is None or self._proc.returncode is not None:
            log.write("[yellow]debugger not running[/yellow]")
            return
        self._proc.terminate()
        await self._proc.wait()
        log.write(f"[green]{self._backend} stopped[/green]")
        self._proc = None

    async def send_command(self, command: str) -> None:
        log = self.query_one(DebuggerLog)
        if self._proc is None or self._proc.returncode is not None:
            log.write("[red]debugger not running - press Start[/red]")
            return
        log.write(f"[cyan]> {command}[/cyan]")
        assert self._proc.stdin is not None
        self._proc.stdin.write((command + "\n").encode())
        await self._proc.stdin.drain()

    async def _read_output(self) -> None:
        log = self.query_one(DebuggerLog)
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            log.write(line.decode(errors="replace").rstrip())
