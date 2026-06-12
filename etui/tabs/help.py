# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Label, ListItem, ListView, Static


_DOC_DIR = Path(__file__).parents[1] / "doc"

# (label, doc file relative to _DOC_DIR, is_sub_item)
_MENU: list[tuple[str, str, bool]] = [
    ("User Guide", "index.md", False),
    ("  Files", "tabs/files.md", True),
    ("  Console", "tabs/console.md", True),
    ("  Tools", "tabs/tools.md", True),
    ("  Git", "tabs/git.md", True),
    ("  GitHub", "tabs/github.md", True),
    ("  CMake", "tabs/cmake.md", True),
    ("  Serial", "tabs/serial.md", True),
    ("  Probe", "tabs/probe.md", True),
    ("  LLDB", "tabs/lldb.md", True),
    ("  Venv", "tabs/venv.md", True),
    ("  Settings", "tabs/settings.md", True),
    ("  Theme", "tabs/theme.md", True),
    ("  About", "tabs/about.md", True),
    ("  Help", "tabs/help.md", True),
]


class OpenDocFile(Message):
    """Posted when the user selects a help topic. The app opens it in Files."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path


class HelpTab(Vertical):
    """Help tab — documentation browser linked to the Files tab viewer."""

    DEFAULT_CSS = """
    HelpTab {
        height: 1fr;
        layout: vertical;
    }
    HelpTab #help-header {
        height: 3;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $accent;
        content-align: left middle;
    }
    HelpTab #help-list {
        height: 1fr;
        background: $panel;
    }
    HelpTab ListItem {
        padding: 0 1;
    }
    HelpTab ListItem.sub-item {
        color: $text-muted;
    }
    HelpTab #help-hint {
        height: 2;
        padding: 0 1;
        background: $surface;
        border-top: solid $accent;
        color: $text-muted;
        content-align: left middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Documentation", id="help-header")
        with ListView(id="help-list"):
            for label, _doc_path, is_sub in _MENU:
                item = ListItem(Label(label))
                if is_sub:
                    item.add_class("sub-item")
                yield item
        yield Static("Enter / click to open in Files tab", id="help-hint")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        if index is None:
            return
        _, doc_rel, _ = _MENU[index]
        doc_path = _DOC_DIR / doc_rel
        if not doc_path.is_file():
            self.notify(f"Doc file not found: {doc_path}", severity="warning")
            return
        self.post_message(OpenDocFile(doc_path))
