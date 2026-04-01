# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.widgets import DirectoryTree
from textual.widgets import RichLog

class LeftWidget(DirectoryTree):
    def __init__(self):
        super().__init__("./")

class RightWidget(RichLog):
    def __init__(self):
        super().__init__(highlight=True, markup=True)
        self.write("Log enabled")

class FilesTab(Horizontal):
    """ Files tab"""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield LeftWidget()
        with Vertical():
            yield RightWidget()
