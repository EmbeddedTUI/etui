# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.widgets import RichLog

class LogWidget(RichLog):
    def __init__(self):
        super().__init__(highlight=True, markup=True)
        self.write("Log enabled")

class ConsoleTab(Horizontal):
    """ Console tab"""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield LogWidget()

    async def run_command(self, command: str) -> None:
        log = self.query_one(LogWidget)
        log.write(f"command: {command}")
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode().strip()
            if stdout:                                                                                                                               
                log.write(stdout.decode(errors="replace").rstrip())                                                                                  
            if stderr:                                                                                                                               
                log.write(f"[red]{stderr.decode(errors='replace').rstrip()}[/red]")
            if proc.returncode != 0:                                                                                                                 
                log.write(f"[red]exit code: {proc.returncode}[/red]")
                raise Exception(f"command failed with {proc.returncode}")
        except Exception as e:
            log.write(f"[red]{e}[/red]")

