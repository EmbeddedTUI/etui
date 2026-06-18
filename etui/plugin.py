# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

"""Public API contract and utilities for etui tab plugins."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from textual.widget import Widget

if __package__:
    from .bus import BusMixin
else:
    from bus import BusMixin

API_VERSION = 1  # MAJOR contract version; bump on breaking change


@dataclass(frozen=True)
class TabSpec:
    """Specification metadata for a tab plugin."""

    id: str  # MUST be "plugin.<slug>" (validated by host)
    title: str
    order: int = 1000  # sort hint; built-ins reserve order < 1000
    after: str | None = None  # optional pane id to place this after
    help_doc: Path | None = None  # absolute path to the plugin's markdown guide


class EtuiTabPlugin:
    """Base class for an entry-point target."""

    api_version: int = API_VERSION

    def spec(self) -> TabSpec:
        """Return the TabSpec metadata for this plugin."""
        raise NotImplementedError

    def create_widget(self) -> Widget:
        """Create and return the Textual widget for the tab's content."""
        raise NotImplementedError


class CancelOnLeaveMixin:
    """Cancel this tab's active operation when the user switches away.

    The widget must expose ``busy: bool`` and an async ``cancel_active_operation()``;
    override ``survives_leave()`` to keep detached work alive.
    """

    def on_mount(self) -> None:
        # Subscribe to the tab.deactivated event emitted by the app
        self._off_leave = self.bus.subscribe("tab.deactivated", self._on_tab_left)

    def on_unmount(self) -> None:
        if hasattr(self, "_off_leave"):
            self._off_leave()

    def survives_leave(self) -> bool:
        """Override this to return True if the active operation should survive switching tabs."""
        return False

    async def _on_tab_left(self, event: Any) -> None:
        # event.payload has a pane_id attribute representing the deactivated tab ID
        payload = getattr(event, "payload", None)
        pane_id = getattr(payload, "pane_id", None) if payload else None

        widget_id = getattr(self, "id", None)
        is_busy = getattr(self, "busy", False)

        if pane_id == widget_id and is_busy and not self.survives_leave():
            if hasattr(self, "cancel_active_operation"):
                await self.cancel_active_operation()
