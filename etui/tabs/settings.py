# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import (
    Button,
    Checkbox,
    ContentSwitcher,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Select,
)

from ..settings import DEFAULT_SETTINGS
from .lldb import THEMES
from .probe import ProbeTab
from .theme import ThemeChanged
from .tools import ToolService, ToolsTab


class SettingsTab(Horizontal):
    """Centralized configuration for ETUI and its external integrations."""

    DEFAULT_CSS = """
    SettingsTab {
        layout: horizontal;
        height: 1fr;
    }
    #settings-sidebar {
        width: 28;
        border-right: solid $accent;
        background: $surface;
        height: 1fr;
    }
    #settings-sidebar ListView {
        background: transparent;
    }
    #settings-forms-container {
        width: 1fr;
        height: 1fr;
        layout: vertical;
    }
    #settings-forms {
        height: 1fr;
        padding: 1 2;
    }
    .settings-form, .setting-group {
        height: auto;
    }
    .setting-group {
        margin-bottom: 1;
        layout: vertical;
    }
    .setting-label {
        text-style: bold;
        margin-bottom: 1;
    }
    .setting-field {
        margin-bottom: 1;
    }
    #settings-buttons {
        height: 4;
        align: right middle;
        background: $surface;
        padding: 0 2;
        border-top: solid $accent;
    }
    #settings-buttons Button {
        margin-left: 1;
        min-width: 15;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-sidebar"):
            with ListView(id="settings-categories", initial_index=0):
                yield ListItem(Label("Workspace"), id="item-workspace")
                yield ListItem(Label("Probe / Debugger"), id="item-probe")
                yield ListItem(Label("LLDB Dashboard"), id="item-lldb")
                yield ListItem(Label("Tool Paths"), id="item-tools")
                yield ListItem(Label("UI"), id="item-ui")

        with Vertical(id="settings-forms-container"):
            with ContentSwitcher(id="settings-forms", initial="form-workspace"):
                with ScrollableContainer(
                    id="form-workspace", classes="settings-form"
                ):
                    yield Label("Workspace Settings", classes="setting-label")
                    with Vertical(classes="setting-group"):
                        yield Label("Workspace root folder:")
                        yield Input(
                            placeholder="Path to folder...",
                            id="set-workspace-root",
                            classes="setting-field",
                        )
                    yield Checkbox(
                        "Auto-restore workspace session on startup",
                        value=True,
                        id="set-workspace-restore",
                    )

                with ScrollableContainer(id="form-probe", classes="settings-form"):
                    yield Label("Probe / Debugger Settings", classes="setting-label")
                    with Vertical(classes="setting-group"):
                        yield Label("Debugger backend:")
                        yield Select(
                            [(name, name) for name in ("pyocd", "openocd", "gdb")],
                            value="pyocd",
                            allow_blank=False,
                            id="set-probe-backend",
                        )
                    with Vertical(classes="setting-group"):
                        yield Label("Target family:")
                        yield Input(
                            placeholder="e.g. MSPM0L",
                            id="set-probe-target",
                            classes="setting-field",
                        )
                    for label, widget_id, placeholder in (
                        ("Adapter speed (kHz):", "set-probe-speed", "4000"),
                        ("GDB server port:", "set-probe-gdb", "3333"),
                        ("Telnet port:", "set-probe-telnet", "4444"),
                        ("TCL port:", "set-probe-tcl", "6666"),
                    ):
                        with Vertical(classes="setting-group"):
                            yield Label(label)
                            yield Input(
                                placeholder=placeholder,
                                id=widget_id,
                                classes="setting-field",
                            )

                with ScrollableContainer(id="form-lldb", classes="settings-form"):
                    yield Label("LLDB Dashboard Settings", classes="setting-label")
                    with Vertical(classes="setting-group"):
                        yield Label("Dashboard visual theme:")
                        yield Select(
                            [(name.title(), name) for name in THEMES],
                            value="vibrant",
                            allow_blank=False,
                            id="set-lldb-theme",
                        )

                with ScrollableContainer(id="form-tools", classes="settings-form"):
                    yield Label("Tool Search Settings", classes="setting-label")
                    with Vertical(classes="setting-group"):
                        yield Label("Custom search paths (comma or newline separated):")
                        yield Input(
                            placeholder="/usr/local/bin, /opt/toolchain/bin",
                            id="set-tools-paths",
                        )

                with ScrollableContainer(id="form-ui", classes="settings-form"):
                    yield Label("UI Settings", classes="setting-label")
                    yield Checkbox(
                        "Enable word wrapping in log views",
                        id="set-ui-word-wrap",
                    )

            with Horizontal(id="settings-buttons"):
                yield Button(
                    "Reset Defaults", id="btn-settings-reset", variant="warning"
                )
                yield Button(
                    "Save Changes", id="btn-settings-save", variant="primary"
                )

    def on_mount(self) -> None:
        self.load_settings_into_ui()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        form_by_item = {
            "item-workspace": "form-workspace",
            "item-probe": "form-probe",
            "item-lldb": "form-lldb",
            "item-tools": "form-tools",
            "item-ui": "form-ui",
        }
        form_id = form_by_item.get(event.item.id or "")
        if form_id:
            self.query_one("#settings-forms", ContentSwitcher).current = form_id

    def load_settings_into_ui(self) -> None:
        manager = getattr(self.app, "settings_manager", None)
        if manager is not None:
            self._populate(manager.settings)

    def _populate(self, settings: dict) -> None:
        workspace = settings["workspace"]
        probe = settings["probe"]
        lldb = settings["lldb"]
        tools = settings["tools"]
        ui = settings["ui"]

        self.query_one("#set-workspace-root", Input).value = str(workspace["root"])
        self.query_one("#set-workspace-restore", Checkbox).value = bool(
            workspace["auto_restore"]
        )
        self.query_one("#set-probe-backend", Select).value = str(probe["backend"])
        self.query_one("#set-probe-target", Input).value = str(probe["target"])
        self.query_one("#set-probe-speed", Input).value = str(
            probe["adapter_speed_khz"]
        )
        self.query_one("#set-probe-gdb", Input).value = str(probe["gdb_port"])
        self.query_one("#set-probe-telnet", Input).value = str(probe["telnet_port"])
        self.query_one("#set-probe-tcl", Input).value = str(probe["tcl_port"])
        theme = str(lldb["theme"])
        self.query_one("#set-lldb-theme", Select).value = (
            theme if theme in THEMES else "vibrant"
        )
        self.query_one("#set-tools-paths", Input).value = ", ".join(
            str(path) for path in tools["custom_paths"]
        )
        self.query_one("#set-ui-word-wrap", Checkbox).value = bool(ui["word_wrap"])

    def _parse_positive_int(
        self, selector: str, label: str, maximum: int
    ) -> int | None:
        raw = self.query_one(selector, Input).value.strip()
        try:
            value = int(raw)
        except ValueError:
            self.notify(f"{label} must be an integer.", severity="error")
            return None
        if not 1 <= value <= maximum:
            self.notify(
                f"{label} must be between 1 and {maximum}.", severity="error"
            )
            return None
        return value

    def _parse_tool_paths(self) -> list[str] | None:
        raw = self.query_one("#set-tools-paths", Input).value.replace("\n", ",")
        paths: list[str] = []
        for value in raw.split(","):
            value = value.strip()
            if not value:
                continue
            path = Path(value).expanduser().resolve()
            if not path.is_dir():
                self.notify(
                    f"Tool search path is not a directory: {value}",
                    severity="error",
                )
                return None
            normalized = str(path)
            if normalized not in paths:
                paths.append(normalized)
        return paths

    async def save_settings_from_ui(self) -> None:
        manager = getattr(self.app, "settings_manager", None)
        if manager is None:
            self.notify("Settings manager is unavailable.", severity="error")
            return

        root = self.query_one("#set-workspace-root", Input).value.strip()
        if root:
            workspace_path = Path(root).expanduser().resolve()
            if not workspace_path.is_dir():
                self.notify(
                    f"Invalid workspace root folder: {root}", severity="error"
                )
                return
            root = str(workspace_path)

        speed = self._parse_positive_int(
            "#set-probe-speed", "Adapter speed", 10_000_000
        )
        gdb_port = self._parse_positive_int("#set-probe-gdb", "GDB port", 65_535)
        telnet_port = self._parse_positive_int(
            "#set-probe-telnet", "Telnet port", 65_535
        )
        tcl_port = self._parse_positive_int("#set-probe-tcl", "TCL port", 65_535)
        paths = self._parse_tool_paths()
        if None in (speed, gdb_port, telnet_port, tcl_port) or paths is None:
            return

        backend = str(self.query_one("#set-probe-backend", Select).value)
        theme = str(self.query_one("#set-lldb-theme", Select).value)
        if backend not in {"pyocd", "openocd", "gdb"} or theme not in THEMES:
            self.notify("A selected setting is invalid.", severity="error")
            return

        updated = deepcopy(manager.settings)
        updated["workspace"].update(
            {
                "root": root,
                "auto_restore": self.query_one(
                    "#set-workspace-restore", Checkbox
                ).value,
            }
        )
        updated["probe"].update(
            {
                "backend": backend,
                "target": self.query_one("#set-probe-target", Input).value.strip(),
                "adapter_speed_khz": speed,
                "gdb_port": gdb_port,
                "telnet_port": telnet_port,
                "tcl_port": tcl_port,
            }
        )
        updated["lldb"].update(
            {
                "theme": theme,
                "layout": manager.get("lldb", "layout", updated["lldb"]["layout"]),
                "collapsed": manager.get(
                    "lldb", "collapsed", updated["lldb"]["collapsed"]
                ),
            }
        )
        updated["tools"]["custom_paths"] = paths
        updated["ui"]["word_wrap"] = self.query_one(
            "#set-ui-word-wrap", Checkbox
        ).value

        try:
            manager.replace(updated)
        except OSError as error:
            self.notify(f"Could not save settings: {error}", severity="error")
            return

        if root:
            await self.app.set_workspace_root(root, persist=False)
        await self._apply_runtime_settings(updated)
        self.notify("Settings saved.", severity="information")

    async def _apply_runtime_settings(self, settings: dict) -> None:
        probe = self.app.query_one(ProbeTab)
        probe.apply_settings(settings["probe"])

        try:
            tools_tab = self.app.query_one(ToolsTab)
            tools_tab.custom_paths = [
                Path(path) for path in settings["tools"]["custom_paths"]
            ]
            tools_tab.service = ToolService(tuple(tools_tab.custom_paths))
            if not tools_tab.busy:
                tools_tab.start_scan_all()
        except Exception:
            pass

        theme = settings["lldb"]["theme"]
        self.post_message(ThemeChanged(theme))

        wrap = bool(settings["ui"]["word_wrap"])
        for log in self.app.query(RichLog):
            log.wrap = wrap

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-settings-save":
            await self.save_settings_from_ui()
        elif event.button.id == "btn-settings-reset":
            self._populate(DEFAULT_SETTINGS)
            self.notify(
                "Defaults loaded. Select Save Changes to apply them.",
                severity="information",
            )
