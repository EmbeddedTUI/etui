# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.widgets import RichLog
from textual.message import Message


class CommandMessage(Message):
    def __init__(self ,command: str) -> None:
        super().__init__()
        self.command = command

class RightWidget(RichLog):
    def __init__(self):
        super().__init__(highlight=True, markup=True)
        self.write("Log enabled")

class ConsoleTab(Horizontal):
    """ Console tab"""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield RightWidget()

    async def run_commmand(self, command: str) -> None:
        log = self.query_one(RightWidget)
        log.write(f"command: {command.command}")
        try:
            proc = await asyncio.create_subprocess_shell(
                command.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode().strip()
            log.write(output)
            if proc.returncode != 0:
                raise Exception(f"command failed with {proc.returncode}")
        except Exception as e:
            log.write(f"[red]{e}[/red]")

