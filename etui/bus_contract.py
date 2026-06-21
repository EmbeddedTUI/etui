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
TOPIC_WORKSPACE_CHANGED = "workspace.changed"  # payload: WorkspaceChanged
TOPIC_THEME_CHANGED = "theme.changed"          # payload: ThemeChanged
TOPIC_DEBUG_GDBSERVER_READY = "debug.gdbserver_ready"  # payload: GdbserverReady
TOPIC_DEBUG_GDBSERVER_DOWN = "debug.gdbserver_down"    # payload: GdbserverDown
TOPIC_SETTINGS_CHANGED = "settings.changed"    # payload: SettingsChanged

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
# help.add_entry(title: str, path: Path) -> None
SVC_HELP_ADD_ENTRY = "help.add_entry"
# workspace.set_root(path: str, persist: bool = True) -> None
SVC_WORKSPACE_SET_ROOT = "workspace.set_root"
# workspace.get_root() -> str
SVC_WORKSPACE_GET_ROOT = "workspace.get_root"
# theme.set(name: str) -> None
SVC_THEME_SET = "theme.set"
# theme.get() -> str
SVC_THEME_GET = "theme.get"
# debug.restart_probe() -> None
SVC_DEBUG_RESTART_PROBE = "debug.restart_probe"
# debug.get_gdbserver_status() -> dict | None
SVC_DEBUG_GET_GDBSERVER_STATUS = "debug.get_gdbserver_status"
# serial.send(data: str) -> None  (provided by etui-serial; cross-tab command routing)
SVC_SERIAL_SEND = "serial.send"
# tools.status() -> dict  (provided by etui-tools; toolchain availability/versions)
SVC_TOOLS_STATUS = "tools.status"
# plugins.list() -> list[dict]
SVC_PLUGINS_LIST = "plugins.list"
# plugins.install(spec: str, *, upgrade: bool = False) -> dict
SVC_PLUGINS_INSTALL = "plugins.install"
# plugins.uninstall(dist: str) -> None
SVC_PLUGINS_UNINSTALL = "plugins.uninstall"
# plugins.set_enabled(plugin_id: str, enabled: bool) -> None
SVC_PLUGINS_SET_ENABLED = "plugins.set_enabled"
# plugins.set_order(order: list[str]) -> None
SVC_PLUGINS_SET_ORDER = "plugins.set_order"
# plugins.reload() -> dict
SVC_PLUGINS_RELOAD = "plugins.reload"
# settings.focus_section(section: str) -> None
SVC_SETTINGS_FOCUS_SECTION = "settings.focus_section"

# Event: plugins.changed (TOPIC_PLUGINS_CHANGED)
TOPIC_PLUGINS_CHANGED = "plugins.changed"


@dataclass(frozen=True)
class RepoChanged:
    path: str


@dataclass(frozen=True)
class TabEvent:
    pane_id: str | None


@dataclass(frozen=True)
class WorkspaceChanged:
    root: str


@dataclass(frozen=True)
class ThemeChanged:
    name: str


@dataclass(frozen=True)
class GdbserverReady:
    port: int
    arch: str | None
    iface: str | None = None


@dataclass(frozen=True)
class GdbserverDown:
    iface: str | None = None


@dataclass(frozen=True)
class SettingsChanged:
    section: str
    key: str
    source: str


@dataclass(frozen=True)
class PluginsChanged:
    added: list[str]
    removed: list[str]
    enabled: list[str]
    disabled: list[str]
    order: list[str]
