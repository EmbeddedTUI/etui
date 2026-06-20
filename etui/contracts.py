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
    from .bus import Disposer, Event

from .bus_contract import (
    SVC_DEBUG_GET_GDBSERVER_STATUS,
    SVC_DEBUG_RESTART_PROBE,
    SVC_THEME_GET,
    SVC_THEME_SET,
    SVC_WORKSPACE_GET_ROOT,
    SVC_WORKSPACE_SET_ROOT,
    TOPIC_DEBUG_GDBSERVER_DOWN,
    TOPIC_DEBUG_GDBSERVER_READY,
    TOPIC_THEME_CHANGED,
    TOPIC_WORKSPACE_CHANGED,
    GdbserverDown,
    GdbserverReady,
    ThemeChanged,
    WorkspaceChanged,
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


__all__ = [
    "debug_get_gdbserver_status",
    "debug_restart_probe",
    "on_debug_gdbserver_down",
    "on_debug_gdbserver_ready",
    "on_theme_changed",
    "on_workspace_changed",
    "theme_get",
    "theme_set",
    "workspace_get_root",
    "workspace_set_root",
]
