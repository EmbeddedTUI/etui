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
TOPIC_TAB_ACTIVATED = "tab.activated"      # payload: TabEvent
TOPIC_TAB_DEACTIVATED = "tab.deactivated"  # payload: TabEvent

# ---- Services (imperative verbs) -----------------------------------------
# console.run(command: str, timeout: float | None = None) -> int
SVC_CONSOLE_RUN = "console.run"
# console.force_complete(exit_code: int = 0) -> None
# Manually resolve the command the console is currently waiting on (Sync override).
SVC_CONSOLE_FORCE_COMPLETE = "console.force_complete"
# nav.activate_tab(tab_id: str) -> None
SVC_NAV_ACTIVATE = "nav.activate_tab"
# settings.get(section: str, key: str, default: Any = None) -> Any
SVC_SETTINGS_GET = "settings.get"
# settings.set(section: str, key: str, value: Any) -> None
SVC_SETTINGS_SET = "settings.set"


@dataclass(frozen=True)
class RepoChanged:
    path: str


@dataclass(frozen=True)
class TabEvent:
    pane_id: str | None

