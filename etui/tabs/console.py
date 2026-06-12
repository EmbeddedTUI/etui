# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Label, RichLog


CWD_MARKER = "__ETUI_XONSH_CWD__"


class LogWidget(RichLog):
    def __init__(self) -> None:
        super().__init__(highlight=True, markup=True, wrap=True)
        self.write("xonsh console ready")


class ConsoleTab(Horizontal):
    """Console tab powered by isolated xonsh command processes."""

    DEFAULT_CSS = """
    ConsoleTab {
        height: 1fr;
    }

    ConsoleTab Vertical {
        height: 1fr;
    }

    ConsoleTab LogWidget {
        height: 1fr;
        overflow-x: hidden;
        scrollbar-size-horizontal: 0;
    }

    ConsoleTab #console-input-line {
        height: 1;
        min-height: 1;
        background: $background;
        padding: 0;
        margin: 0;
    }

    ConsoleTab #console-prompt {
        width: 7;
        height: 1;
        padding: 0;
        margin: 0;
        background: $background;
    }

    ConsoleTab #console-input {
        width: 1fr;
        height: 1;
        min-height: 1;
        border: none;
        background: $background;
        padding: 0;
        margin: 0;
    }

    ConsoleTab #console-input:focus {
        border: none;
        background: $background;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.cwd = Path.cwd()
        self._command_lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield LogWidget()
            with Horizontal(id="console-input-line"):
                yield Label("[bold cyan]xonsh>[/bold cyan]", id="console-prompt")
                yield Input(id="console-input", select_on_focus=False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "console-input":
            return

        event.stop()
        command = event.value.strip()
        event.input.value = ""
        if command:
            self.run_worker(
                self.run_command(command),
                name="console-command",
                group="console",
                exit_on_error=False,
            )

    async def run_command(self, command: str) -> None:
        log = self.query_one(LogWidget)
        if self._command_lock.locked():
            log.write("[yellow]A command is already running.[/yellow]")
            return

        async with self._command_lock:
            if not self.cwd.is_dir():
                self.cwd = Path.cwd()
            log.write(f"[bold cyan]xonsh>[/bold cyan] {command}")
            cwd_marker = f"{CWD_MARKER}{uuid4().hex}:"
            wrapped_command = (
                f"{command}\n"
                "import os\n"
                f'print("{cwd_marker}" + os.getcwd())'
            )
            try:
                self._process = await asyncio.create_subprocess_exec(
                    *self.command_runner(wrapped_command),
                    cwd=self.cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=self.command_environment(),
                )
                assert self._process.stdout is not None

                while line := await self._process.stdout.readline():
                    text = line.decode(errors="replace").rstrip("\r\n")
                    if text.startswith(cwd_marker):
                        new_cwd = text.removeprefix(cwd_marker)
                        if new_cwd:
                            self.cwd = Path(new_cwd)
                        continue
                    log.write(text)

                returncode = await self._process.wait()
                if returncode != 0:
                    log.write(f"[red]Command exited with status {returncode}.[/red]")
            except asyncio.CancelledError:
                await self._terminate_process()
                raise
            except OSError as error:
                log.write(f"[red]Unable to start xonsh: {error}[/red]")
            finally:
                self._process = None

    async def on_unmount(self) -> None:
        await self._terminate_process()

    async def _terminate_process(self) -> None:
        process = self._process
        if process is None or process.returncode is not None:
            return
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                return
            await process.wait()

    @staticmethod
    def command_runner(command: str) -> list[str]:
        """Run xonsh through ETUI so bundled builds use bundled modules."""
        if getattr(sys, "frozen", False):
            return [sys.executable, "--etui-xonsh-command", command]
        return [
            sys.executable,
            "-m",
            "etui",
            "--etui-xonsh-command",
            command,
        ]

    @staticmethod
    def command_environment() -> dict[str, str]:
        environment = os.environ.copy()
        environment.setdefault("XONSH_HISTORY_BACKEND", "dummy")
        return environment
