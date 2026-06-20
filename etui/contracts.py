# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

"""Typed helpers for public etui bus contracts.

Contract names live in :mod:`etui.bus_contract`; this module adds thin typed
wrappers as contracts are introduced. Keeping the helpers separate avoids
turning plugin code into raw string-based ``bus.call(...)`` sites.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bus import Disposer, Event
    from .plugins import ScopedBus


__all__: list[str] = []
