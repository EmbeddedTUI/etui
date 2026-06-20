# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

"""Public API contract and utilities for etui tab plugins."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from textual.widget import Widget

if __package__:
    from .bus import BusMixin, MessageBus, NoProvider, RpcError, RpcTimeout
    from . import bus_contract
    from .plugin_kit import ToolWarningBanner
else:
    from bus import BusMixin, MessageBus, NoProvider, RpcError, RpcTimeout
    import bus_contract
    from plugin_kit import ToolWarningBanner

API_VERSION = 1  # MAJOR contract version; bump on breaking change

# Public extension API. Plugins import everything they need from etui.plugin.
__all__ = [
    "API_VERSION",
    "TabSpec",
    "EtuiTabPlugin",
    "CancelOnLeaveMixin",
    "ToolWarningBanner",
    "SettingsField",
    "SettingsSchema",
    # Re-exported bus primitives so plugins have one import root.
    "BusMixin",
    "MessageBus",
    "NoProvider",
    "RpcError",
    "RpcTimeout",
    "bus_contract",
]


@dataclass(frozen=True)
class SettingsField:
    key: str
    type: Literal["str", "int", "bool", "choice", "path", "secret"]
    label: str
    default: Any = None
    required: bool = False
    # validation
    min: int | None = None
    max: int | None = None
    pattern: str | None = None
    # choice fields: static or dynamic (e.g. LLDB THEMES)
    choices: tuple[str, ...] | None = None
    choices_provider: str | None = None   # a service name returning list[str]
    sensitive: bool = False               # secret: masked in UI, never logged
    apply: Literal["live", "restart"] = "live"


@dataclass(frozen=True)
class SettingsSchema:
    section: str                          # maps to the settings section
    fields: tuple[SettingsField, ...]


@dataclass(frozen=True)
class TabSpec:
    """Specification metadata for a tab plugin."""

    id: str  # MUST be "plugin-<slug>" (validated by host)
    title: str
    order: int = 1000  # sort hint; built-ins reserve order < 1000
    after: str | None = None  # optional pane id to place this after
    help_doc: Path | None = None  # absolute path to the plugin's markdown guide
    provides: tuple[str, ...] = ()
    settings_schema: SettingsSchema | None = None


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

    The mixin's ``on_mount``/``on_unmount`` call ``super()`` so they cooperate with
    the widget's own handlers under the MRO. List the mixin before the widget base
    (e.g. ``class MyTab(CancelOnLeaveMixin, BusMixin, Vertical)``); if the widget
    overrides ``on_mount``/``on_unmount``, it must call ``super()`` too.
    """

    def on_mount(self) -> None:
        # Subscribe to the tab.deactivated event emitted by the app
        self._off_leave = self.bus.subscribe("tab.deactivated", self._on_tab_left)
        # Cooperate with any other on_mount in the MRO. Textual handlers are
        # optional (Widget has none), so only chain if one actually exists.
        nxt = getattr(super(), "on_mount", None)
        if nxt is not None:
            nxt()

    def on_unmount(self) -> None:
        if hasattr(self, "_off_leave"):
            self._off_leave()
        nxt = getattr(super(), "on_unmount", None)
        if nxt is not None:
            nxt()

    def survives_leave(self) -> bool:
        """Override this to return True if the active operation should survive switching tabs."""
        return False

    async def _on_tab_left(self, event: Any) -> None:
        # event.payload has a pane_id attribute representing the deactivated tab ID
        payload = getattr(event, "payload", None)
        pane_id = getattr(payload, "pane_id", None) if payload else None
        if not pane_id:
            return

        # Check if this widget or any of its ancestors match the deactivated pane_id
        matched = False
        node = self
        while node is not None:
            if getattr(node, "id", None) == pane_id:
                matched = True
                break
            node = getattr(node, "parent", None)

        is_busy = getattr(self, "busy", False)

        if matched and is_busy and not self.survives_leave():
            if hasattr(self, "cancel_active_operation"):
                await self.cancel_active_operation()
