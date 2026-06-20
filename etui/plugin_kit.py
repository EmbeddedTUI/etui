# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

"""Shared UI widgets and helpers for etui plugins."""

from __future__ import annotations

from typing import Any
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Label, Button

if __package__:
    from .bus import BusMixin
else:
    from bus import BusMixin


class ToolWarningBanner(BusMixin, Horizontal):
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
            self.app.query_one(TabbedContent).active = "plugin-tools"
            try:
                for widget in self.app.query("*"):
                    if widget.__class__.__name__ == "ToolsTab":
                        if hasattr(widget, "select_tool"):
                            widget.select_tool(self.tool_id)
            except Exception:
                pass

    def on_mount(self) -> None:
        self._off_changed = self.bus.subscribe("tools.changed", self._on_tools_changed)
        self.run_worker(self._update_status())
        nxt = getattr(super(), "on_mount", None)
        if nxt is not None:
            nxt()

    def on_unmount(self) -> None:
        if hasattr(self, "_off_changed"):
            self._off_changed()
        nxt = getattr(super(), "on_unmount", None)
        if nxt is not None:
            nxt()

    async def _update_status(self) -> None:
        try:
            status = await self.bus.call("tools.status")
            present = status.get("tools", {}).get(self.tool_id, {}).get("present", False)
            self.display = not present
        except Exception:
            if hasattr(self.app, "tool_registry"):
                self.display = self.app.tool_registry.is_missing_or_incomplete(self.tool_id)

    def _on_tools_changed(self, event: Any) -> None:
        status = event.payload or {}
        present = status.get("tools", {}).get(self.tool_id, {}).get("present", False)
        self.display = not present

    def check_status(self) -> None:
        self.run_worker(self._update_status())
