# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

"""Typed helpers for public etui bus contracts.

Contract names live in :mod:`etui.bus_contract`; this module adds thin typed
wrappers as contracts are introduced. Keeping the helpers separate avoids
turning plugin code into raw string-based ``bus.call(...)`` sites.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    if __package__:
        from .bus import Disposer, Event
    else:
        from bus import Disposer, Event

if __package__:
    from .bus_contract import (
        SVC_DEBUG_GET_GDBSERVER_STATUS,
        SVC_DEBUG_RESTART_PROBE,
        SVC_SERIAL_SEND,
        SVC_THEME_GET,
        SVC_THEME_SET,
        SVC_WORKSPACE_GET_ROOT,
        SVC_WORKSPACE_SET_ROOT,
        TOPIC_DEBUG_GDBSERVER_DOWN,
        TOPIC_DEBUG_GDBSERVER_READY,
        TOPIC_SETTINGS_CHANGED,
        TOPIC_THEME_CHANGED,
        TOPIC_WORKSPACE_CHANGED,
        GdbserverDown,
        GdbserverReady,
        SettingsChanged,
        ThemeChanged,
        WorkspaceChanged,
        SVC_PLUGINS_LIST,
        SVC_PLUGINS_INSTALL,
        SVC_PLUGINS_UNINSTALL,
        SVC_PLUGINS_SET_ENABLED,
        SVC_PLUGINS_SET_ORDER,
        SVC_PLUGINS_RELOAD,
        SVC_SETTINGS_FOCUS_SECTION,
        TOPIC_PLUGINS_CHANGED,
        TOPIC_PLUGINS_INSTALL_PROGRESS,
        PluginsChanged,
        PluginInstallProgress,
    )
else:
    from bus_contract import (
        SVC_DEBUG_GET_GDBSERVER_STATUS,
        SVC_DEBUG_RESTART_PROBE,
        SVC_SERIAL_SEND,
        SVC_THEME_GET,
        SVC_THEME_SET,
        SVC_WORKSPACE_GET_ROOT,
        SVC_WORKSPACE_SET_ROOT,
        TOPIC_DEBUG_GDBSERVER_DOWN,
        TOPIC_DEBUG_GDBSERVER_READY,
        TOPIC_SETTINGS_CHANGED,
        TOPIC_THEME_CHANGED,
        TOPIC_WORKSPACE_CHANGED,
        GdbserverDown,
        GdbserverReady,
        SettingsChanged,
        ThemeChanged,
        WorkspaceChanged,
        SVC_PLUGINS_LIST,
        SVC_PLUGINS_INSTALL,
        SVC_PLUGINS_UNINSTALL,
        SVC_PLUGINS_SET_ENABLED,
        SVC_PLUGINS_SET_ORDER,
        SVC_PLUGINS_RELOAD,
        SVC_SETTINGS_FOCUS_SECTION,
        TOPIC_PLUGINS_CHANGED,
        TOPIC_PLUGINS_INSTALL_PROGRESS,
        PluginsChanged,
        PluginInstallProgress,
    )


class ContractBus(Protocol):
    async def call(self, service: str, *, timeout: float | None = 30.0, **kwargs) -> object:
        ...

    def subscribe(
        self,
        topic: str,
        handler: Callable[["Event"], object],
    ) -> "Disposer":
        ...


async def workspace_get_root(bus: ContractBus) -> str:
    """Return the current host-owned workspace root."""
    return str(await bus.call(SVC_WORKSPACE_GET_ROOT))


async def workspace_set_root(
    bus: ContractBus,
    path: str,
    *,
    persist: bool = True,
) -> None:
    """Ask the host to change the workspace root."""
    await bus.call(SVC_WORKSPACE_SET_ROOT, path=path, persist=persist)


def on_workspace_changed(
    bus: ContractBus,
    handler: Callable[[WorkspaceChanged], None],
) -> "Disposer":
    """Subscribe to workspace root changes with a typed payload handler."""

    def _handle(event: "Event") -> None:
        payload = event.payload
        if isinstance(payload, WorkspaceChanged):
            handler(payload)

    return bus.subscribe(TOPIC_WORKSPACE_CHANGED, _handle)


async def theme_get(bus: ContractBus) -> str:
    """Return the current host-owned theme."""
    return str(await bus.call(SVC_THEME_GET))


async def theme_set(
    bus: ContractBus,
    name: str,
) -> None:
    """Ask the host to change the LLDB dashboard theme."""
    await bus.call(SVC_THEME_SET, name=name)


def on_theme_changed(
    bus: ContractBus,
    handler: Callable[[ThemeChanged], None],
) -> "Disposer":
    """Subscribe to theme changes with a typed payload handler."""

    def _handle(event: "Event") -> None:
        payload = event.payload
        if isinstance(payload, ThemeChanged):
            handler(payload)

    return bus.subscribe(TOPIC_THEME_CHANGED, _handle)


async def debug_restart_probe(bus: ContractBus) -> None:
    """Ask the probe provider to restart the probe gdbserver."""
    await bus.call(SVC_DEBUG_RESTART_PROBE)


async def debug_get_gdbserver_status(bus: ContractBus) -> dict | None:
    """Return the current gdbserver status dict (or None if down)."""
    return await bus.call(SVC_DEBUG_GET_GDBSERVER_STATUS)  # type: ignore[return-value]


def on_debug_gdbserver_ready(
    bus: ContractBus,
    handler: Callable[[GdbserverReady], None],
) -> "Disposer":
    """Subscribe to gdbserver ready events with a typed payload handler."""

    def _handle(event: "Event") -> None:
        payload = event.payload
        if isinstance(payload, GdbserverReady):
            handler(payload)

    return bus.subscribe(TOPIC_DEBUG_GDBSERVER_READY, _handle)


def on_debug_gdbserver_down(
    bus: ContractBus,
    handler: Callable[[GdbserverDown], None],
) -> "Disposer":
    """Subscribe to gdbserver down events with a typed payload handler."""

    def _handle(event: "Event") -> None:
        payload = event.payload
        if isinstance(payload, GdbserverDown):
            handler(payload)

    return bus.subscribe(TOPIC_DEBUG_GDBSERVER_DOWN, _handle)


async def serial_send(bus: ContractBus, data: str) -> None:
    """Send data over the active serial connection (provided by etui-serial)."""
    await bus.call(SVC_SERIAL_SEND, data=data)


def on_settings_changed(
    bus: ContractBus,
    handler: Callable[[SettingsChanged], None],
) -> "Disposer":
    """Subscribe to settings changed events with a typed payload handler."""

    def _handle(event: "Event") -> None:
        payload = event.payload
        if isinstance(payload, SettingsChanged):
            handler(payload)

    return bus.subscribe(TOPIC_SETTINGS_CHANGED, _handle)


async def plugins_list(bus: ContractBus) -> list[dict]:
    return await bus.call(SVC_PLUGINS_LIST)  # type: ignore[return-value]


async def plugins_install(bus: ContractBus, spec: str, *, upgrade: bool = False) -> dict:
    return await bus.call(SVC_PLUGINS_INSTALL, timeout=None, spec=spec, upgrade=upgrade)  # type: ignore[return-value]


async def plugins_uninstall(bus: ContractBus, dist: str) -> None:
    await bus.call(SVC_PLUGINS_UNINSTALL, timeout=None, dist=dist)


async def plugins_set_enabled(bus: ContractBus, plugin_id: str, enabled: bool) -> None:
    await bus.call(SVC_PLUGINS_SET_ENABLED, plugin_id=plugin_id, enabled=enabled)


async def plugins_set_order(bus: ContractBus, order: list[str]) -> None:
    await bus.call(SVC_PLUGINS_SET_ORDER, order=order)


async def plugins_reload(bus: ContractBus) -> dict:
    return await bus.call(SVC_PLUGINS_RELOAD)  # type: ignore[return-value]


async def settings_focus_section(bus: ContractBus, section: str) -> None:
    await bus.call(SVC_SETTINGS_FOCUS_SECTION, section=section)


def on_plugins_changed(
    bus: ContractBus,
    handler: Callable[[PluginsChanged], None],
) -> "Disposer":
    def _handle(event: "Event") -> None:
        payload = event.payload
        if isinstance(payload, PluginsChanged):
            handler(payload)

    return bus.subscribe(TOPIC_PLUGINS_CHANGED, _handle)


def on_plugin_install_progress(
    bus: ContractBus,
    handler: Callable[[PluginInstallProgress], None],
) -> "Disposer":
    def _handle(event: "Event") -> None:
        payload = event.payload
        if isinstance(payload, PluginInstallProgress):
            handler(payload)

    return bus.subscribe(TOPIC_PLUGINS_INSTALL_PROGRESS, _handle)


__all__ = [
    "debug_get_gdbserver_status",
    "debug_restart_probe",
    "on_debug_gdbserver_down",
    "on_debug_gdbserver_ready",
    "on_settings_changed",
    "on_theme_changed",
    "on_workspace_changed",
    "serial_send",
    "theme_get",
    "theme_set",
    "workspace_get_root",
    "workspace_set_root",
    "plugins_list",
    "plugins_install",
    "plugins_uninstall",
    "plugins_set_enabled",
    "plugins_set_order",
    "plugins_reload",
    "settings_focus_section",
    "on_plugins_changed",
    "on_plugin_install_progress",
]
