# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

from __future__ import annotations

import importlib
from copy import deepcopy
from pathlib import Path
from typing import Any

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

from etui.plugin import SettingsField, SettingsSchema
if __package__ and "." in __package__:
    from ..settings import DEFAULT_SETTINGS
    from ..bus import BusMixin
    from ..contracts import theme_set
    from ..bus_contract import SVC_SETTINGS_SET
else:
    from settings import DEFAULT_SETTINGS
    from bus import BusMixin
    from contracts import theme_set
    from bus_contract import SVC_SETTINGS_SET


# Core schemas defined locally
WORKSPACE_SCHEMA = SettingsSchema(
    section="workspace",
    fields=(
        SettingsField(
            key="root",
            type="path",
            label="Workspace root folder:",
            default="",
        ),
        SettingsField(
            key="auto_restore",
            type="bool",
            label="Auto-restore workspace session on startup",
            default=True,
        ),
    )
)

UI_SCHEMA = SettingsSchema(
    section="ui",
    fields=(
        SettingsField(
            key="word_wrap",
            type="bool",
            label="Enable word wrapping in log views",
            default=False,
        ),
    )
)

PRETTY_TITLES = {
    "workspace": "Workspace Settings",
    "probe": "Probe / Debugger Settings",
    "lldb": "LLDB Dashboard Settings",
    "tools": "Tool Search Settings",
    "ui": "UI Settings",
}


def _field_id(section: str, key: str) -> str:
    # Map section + key to legacy widget IDs to pass tests and keep CSS selectors working
    legacy = {
        ("probe", "adapter_speed_khz"): "set-probe-speed",
        ("probe", "gdb_port"): "set-probe-gdb",
        ("probe", "telnet_port"): "set-probe-telnet",
        ("probe", "tcl_port"): "set-probe-tcl",
        ("tools", "custom_paths"): "set-tools-paths",
        ("workspace", "auto_restore"): "set-workspace-restore",
        ("ui", "word_wrap"): "set-ui-word-wrap",
        ("lldb", "theme"): "set-lldb-theme",
    }
    return legacy.get((section, key), f"set-{section}-{key}")


class SettingsTab(BusMixin, Horizontal):
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
            yield ListView(id="settings-categories")

        with Vertical(id="settings-forms-container"):
            yield ContentSwitcher(id="settings-forms")

            with Horizontal(id="settings-buttons"):
                yield Button(
                    "Reset Defaults", id="btn-settings-reset", variant="warning"
                )
                yield Button(
                    "Save Changes", id="btn-settings-save", variant="primary"
                )

    def _discover_schemas(self) -> list[SettingsSchema]:
        schemas = [WORKSPACE_SCHEMA]
        seen_sections = {"workspace"}

        # Discover built-in tab schemas from known modules
        builtin_modules = []
        for mod_name, class_name in builtin_modules:
            try:
                mod = importlib.import_module(mod_name)
                cls = getattr(mod, class_name)
                schema = getattr(cls, "settings_schema", None)
                if schema and schema.section not in seen_sections:
                    schemas.append(schema)
                    seen_sections.add(schema.section)
            except Exception:
                pass

        # Check mounted widgets in the app
        for widget in self.app.query("*"):
            schema = getattr(widget, "settings_schema", None)
            if schema and schema.section not in seen_sections:
                schemas.append(schema)
                seen_sections.add(schema.section)

        # Check plugin specs
        plugins = getattr(self.app, "plugins", None)
        if plugins and hasattr(plugins, "loaded"):
            for lp in plugins.loaded:
                if lp.spec.settings_schema and lp.spec.settings_schema.section not in seen_sections:
                    schemas.append(lp.spec.settings_schema)
                    seen_sections.add(lp.spec.settings_schema.section)

        # Fallback to discover all installed entry points (useful for test apps)
        try:
            from etui.plugins import _entry_points
            for ep in _entry_points():
                try:
                    cls = ep.load()
                    plugin = cls()
                    spec = plugin.spec()
                    if spec.settings_schema and spec.settings_schema.section not in seen_sections:
                        schemas.append(spec.settings_schema)
                        seen_sections.add(spec.settings_schema.section)
                except Exception:
                    pass
        except Exception:
            pass

        if UI_SCHEMA.section not in seen_sections:
            schemas.append(UI_SCHEMA)

        return schemas

    async def on_mount(self) -> None:
        self.schemas = self._discover_schemas()

        categories = self.query_one("#settings-categories", ListView)
        forms = self.query_one("#settings-forms", ContentSwitcher)

        first_form_id = None
        for schema in self.schemas:
            form_id = f"form-{schema.section}"
            if not first_form_id:
                first_form_id = form_id

            # Category item
            title = PRETTY_TITLES.get(schema.section, f"{schema.section.title()} Settings")
            cat_label = title.replace(" Settings", "")
            await categories.mount(ListItem(Label(cat_label), id=f"item-{schema.section}"))

            # Form container
            form = ScrollableContainer(id=form_id, classes="settings-form")
            await forms.mount(form)

            # Add fields to the form
            await form.mount(Label(title, classes="setting-label"))
            for field in schema.fields:
                widget_id = _field_id(schema.section, field.key)

                if field.type == "bool":
                    await form.mount(Checkbox(field.label, value=bool(field.default), id=widget_id))
                else:
                    group = Vertical(classes="setting-group")
                    await form.mount(group)
                    await group.mount(Label(field.label))

                    if field.type == "choice":
                        choices = field.choices or ()
                        if field.choices_provider:
                            try:
                                choices = await self.bus.call(field.choices_provider)
                            except Exception:
                                pass
                        await group.mount(Select(
                            [(str(c).title(), str(c)) for c in choices],
                            value=str(field.default) if choices else None,
                            allow_blank=False,
                            id=widget_id,
                        ))
                    elif field.type == "secret":
                        await group.mount(Input(
                            placeholder=f"e.g. {field.default or ''}",
                            password=True,
                            id=widget_id,
                        ))
                    else:  # str, path, int
                        placeholder = ""
                        if schema.section == "tools" and field.key == "custom_paths":
                            placeholder = "/usr/local/bin, /opt/toolchain/bin"
                        elif schema.section == "probe" and field.key == "adapter_speed_khz":
                            placeholder = "4000"
                        elif schema.section == "probe" and field.key == "gdb_port":
                            placeholder = "3333"
                        elif schema.section == "probe" and field.key == "telnet_port":
                            placeholder = "4444"
                        elif schema.section == "probe" and field.key == "tcl_port":
                            placeholder = "6666"

                        await group.mount(Input(
                            placeholder=placeholder,
                            id=widget_id,
                        ))

        if first_form_id:
            forms.current = first_form_id

        self.load_settings_into_ui()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item and event.item.id:
            section = event.item.id.replace("item-", "")
            self.query_one("#settings-forms", ContentSwitcher).current = f"form-{section}"

    def load_settings_into_ui(self) -> None:
        manager = getattr(self.app, "settings_manager", None)
        if manager is not None:
            self._populate(manager.settings)

    def _populate(self, settings: dict) -> None:
        for schema in self.schemas:
            section_settings = settings.get(schema.section, {})
            for field in schema.fields:
                widget_id = _field_id(schema.section, field.key)
                try:
                    widget = self.query_one(f"#{widget_id}")
                except Exception:
                    continue

                val = section_settings.get(field.key, field.default)
                if val is None:
                    val = field.default

                if field.type == "bool":
                    widget.value = bool(val)
                elif field.type == "choice":
                    choices = field.choices or ()
                    widget.value = str(val) if val in choices else (str(field.default) if field.default in choices else None)
                else:  # str, path, secret, int
                    if isinstance(val, list):
                        widget.value = ", ".join(str(p) for p in val)
                    else:
                        widget.value = str(val) if val is not None else ""

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

        to_save = {}
        root = ""

        for schema in self.schemas:
            for field in schema.fields:
                widget_id = _field_id(schema.section, field.key)
                try:
                    widget = self.query_one(f"#{widget_id}")
                except Exception:
                    continue

                if schema.section == "tools" and field.key == "custom_paths":
                    paths = self._parse_tool_paths()
                    if paths is None:
                        return
                    val = paths
                elif field.type == "bool":
                    val = widget.value
                elif field.type == "choice":
                    val = widget.value
                elif field.type == "int":
                    raw = widget.value.strip()
                    try:
                        val = int(raw)
                    except ValueError:
                        self.notify(f"{field.label} must be an integer.", severity="error")
                        return

                    maximum = 65535
                    if field.key == "adapter_speed_khz":
                        maximum = 10_000_000

                    min_val = field.min if field.min is not None else 1
                    max_val = field.max if field.max is not None else maximum

                    if not min_val <= val <= max_val:
                        self.notify(
                            f"{field.label} must be between {min_val} and {max_val}.",
                            severity="error"
                        )
                        return
                else:  # str, secret, path
                    val = widget.value.strip()
                    if field.key == "root" and schema.section == "workspace":
                        if val:
                            workspace_path = Path(val).expanduser().resolve()
                            if not workspace_path.is_dir():
                                self.notify(
                                    f"Invalid workspace root folder: {val}", severity="error"
                                )
                                return
                            val = str(workspace_path)
                            root = val
                    elif field.type == "path" and val:
                        path = Path(val).expanduser().resolve()
                        if not path.is_dir():
                            self.notify(f"{field.label} must be an existing folder.", severity="error")
                            return
                        val = str(path.resolve())

                to_save[(schema.section, field.key)] = val

        # Save values using bus service (SVC_SETTINGS_SET) which emits settings.changed
        has_set_svc = self.bus.has(SVC_SETTINGS_SET)
        for (section, key), val in to_save.items():
            if has_set_svc:
                await self.bus.call(SVC_SETTINGS_SET, section=section, key=key, value=val, source="host")
            else:
                manager.set(section, key, val)

        if root:
            await self.app.set_workspace_root(root, persist=False)

        settings_dict = {}
        for (section, key), val in to_save.items():
            if section not in settings_dict:
                settings_dict[section] = {}
            settings_dict[section][key] = val

        await self._apply_runtime_settings(settings_dict)
        self.notify("Settings saved.", severity="information")

    async def _apply_runtime_settings(self, settings: dict) -> None:
        for widget in self.app.query("*"):
            class_name = widget.__class__.__name__
            if class_name == "ProbeTab":
                if hasattr(widget, "apply_settings"):
                    widget.apply_settings(settings.get("probe", {}))
            elif class_name == "ToolsTab":
                if hasattr(widget, "apply_settings"):
                    widget.apply_settings(settings.get("tools", {}))

        theme = settings.get("lldb", {}).get("theme")
        if theme:
            await theme_set(self.bus, theme)

        wrap = bool(settings.get("ui", {}).get("word_wrap", False))
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
