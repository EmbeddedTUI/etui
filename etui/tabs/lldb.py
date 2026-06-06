# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
import shutil
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.widgets import Input
from textual.widgets import RichLog


class LldbLog(RichLog):
    def __init__(self):
        super().__init__(highlight=True, markup=True)
        self.write("LLDB session")


class LldbTab(Horizontal):
    """ LLDB tab - drives an lldb session attached to a gdb remote server.

    Opened automatically once the hardware debugger (OpenOCD) has started
    its gdb server. Connects lldb to localhost:<port> and then forwards
    typed commands to the lldb prompt.
    """

    def __init__(self, port: int, arch: str | None = None):
        super().__init__()
        self._port = port
        self._arch = arch
        self._proc: asyncio.subprocess.Process | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield LldbLog()
            yield Input(placeholder="lldb command", id="lldb-input")

    async def on_mount(self) -> None:
        await self.start()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        event.input.value = ""
        if command:
            await self.send_command(command)

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
        log.write(f"[green]lldb started[/green]")
        self.run_worker(self._read_output(), exclusive=False)
        # Set the architecture before connecting so lldb does not probe
        # bogus memory while auto-detecting the target.
        if self._arch:
            await self.send_command(
                f"settings set target.default-arch {self._arch}"
            )
        # Connect to the OpenOCD gdb server.
        await self.send_command(f"gdb-remote localhost:{self._port}")

    async def send_command(self, command: str) -> None:
        log = self.query_one(LldbLog)
        if self._proc is None or self._proc.returncode is not None:
            log.write("[red]lldb not running[/red]")
            return
        log.write(f"[cyan](lldb) {command}[/cyan]")
        assert self._proc.stdin is not None
        self._proc.stdin.write((command + "\n").encode())
        await self._proc.stdin.drain()

    def on_unmount(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            self._proc.kill()

    async def _read_output(self) -> None:
        log = self.query_one(LldbLog)
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            log.write(line.decode(errors="replace").rstrip())
