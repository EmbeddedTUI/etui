# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

"""Single source of truth for bus topic/service names and payload types.

Producers and consumers import these constants so names stay in sync and remain
greppable. See ``doc/message-bus-rpc.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---- Events (past-tense facts) -------------------------------------------
TOPIC_REPO_CHANGED = "repo.changed"        # payload: RepoChanged

# ---- Services (imperative verbs) -----------------------------------------
# console.run(command: str, timeout: float | None = None) -> int
SVC_CONSOLE_RUN = "console.run"
# nav.activate_tab(tab_id: str) -> None
SVC_NAV_ACTIVATE = "nav.activate_tab"


@dataclass(frozen=True)
class RepoChanged:
    path: str
