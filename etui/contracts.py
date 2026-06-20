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
    SVC_WORKSPACE_GET_ROOT,
    SVC_WORKSPACE_SET_ROOT,
    TOPIC_WORKSPACE_CHANGED,
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


__all__ = [
    "on_workspace_changed",
    "workspace_get_root",
    "workspace_set_root",
]
