# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

"""Shared UI widgets and helpers for etui plugins."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Label, Button


class ToolWarningBanner(Horizontal):
    DEFAULT_CSS = """
    ToolWarningBanner {
        display: none;
        height: 3;
        background: $error-darken-1;
        color: $text;
        padding: 0 1;
        align: left middle;
        border-bottom: solid $error;
    }
    ToolWarningBanner Label {
        margin-top: 1;
        margin-right: 2;
        text-style: bold;
    }
    ToolWarningBanner Button {
        height: 1;
        min-width: 15;
    }
    """

    def __init__(self, tool_id: str, tool_name: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.tool_id = tool_id
        self.tool_name = tool_name

    def compose(self) -> ComposeResult:
        yield Label(f"Required tool '{self.tool_name}' is missing or incomplete!")
        yield Button(f"Configure {self.tool_name}", id="btn-fix-tool", variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-fix-tool":
            from textual.widgets import TabbedContent
            self.app.query_one(TabbedContent).active = "tools"
            try:
                tools_tab = self.app.query_one("#tools")
                if hasattr(tools_tab, "select_tool"):
                    tools_tab.select_tool(self.tool_id)
            except Exception:
                pass

    def check_status(self) -> None:
        if hasattr(self.app, "tool_registry"):
            if self.app.tool_registry.is_missing_or_incomplete(self.tool_id):
                self.display = True
            else:
                self.display = False
