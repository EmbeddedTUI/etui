# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Label, ListItem, ListView, Static

if __package__:
    from ..bus import BusMixin
    from ..bus_contract import SVC_HELP_ADD_ENTRY
else:
    from bus import BusMixin
    from bus_contract import SVC_HELP_ADD_ENTRY


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


class HelpTab(BusMixin, Vertical):
    """Help tab — documentation browser linked to the Files tab viewer."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._disposers = []
        self._plugin_entries: list[tuple[str, Path]] = []

    def on_mount(self) -> None:
        self._disposers = [
            self.bus.provide(SVC_HELP_ADD_ENTRY, self.add_entry),
        ]

    def on_unmount(self) -> None:
        for dispose in self._disposers:
            dispose()
        self._disposers = []

    async def add_entry(self, title: str, path: Path) -> None:
        """Register a dynamic help document path under the Plugins category."""
        self._plugin_entries.append((title, path))

        try:
            help_list = self.query_one("#help-list", ListView)
        except Exception:
            return

        if len(self._plugin_entries) == 1:
            header_item = ListItem(Label("Plugins"), disabled=True)
            help_list.append(header_item)

        item = ListItem(Label(f"  {title}"))
        item.add_class("sub-item")
        help_list.append(item)

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
        if index < len(_MENU):
            _, doc_rel, _ = _MENU[index]
            doc_path = _DOC_DIR / doc_rel
        else:
            plugin_idx = index - (len(_MENU) + 1)
            if plugin_idx < 0 or plugin_idx >= len(self._plugin_entries):
                return
            _, doc_path = self._plugin_entries[plugin_idx]

        if not doc_path.is_file():
            self.notify(f"Doc file not found: {doc_path}", severity="warning")
            return
        self.post_message(OpenDocFile(doc_path))
