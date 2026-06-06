# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

class AboutTab(Vertical):
    """ About tab"""

    def compose(self) -> ComposeResult:
        yield Static("etui - (c) 32bitmico LLC 2026")
