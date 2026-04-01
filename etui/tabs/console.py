# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

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