# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import yaml


SETTINGS_DIR = Path.home() / ".config" / "etui"
SETTINGS_PATH = SETTINGS_DIR / "settings.yaml"

DEFAULT_SETTINGS = {
    "workspace": {
        "root": "",
        "auto_restore": True,
    },
    "probe": {
        "backend": "pyocd",
        "target": "",
        "adapter_speed_khz": 4000,
        "gdb_port": 3333,
        "telnet_port": 4444,
        "tcl_port": 6666,
        "transport": "swd",
    },
    "lldb": {
        "theme": "vibrant",
        "layout": ["registers", "assembly", "stack", "backtrace"],
        "collapsed": [],
        "executable": "",
    },
    "tools": {
        "custom_paths": [],
    },
    "ui": {
        "theme": "dark",
        "word_wrap": False,
    },
}


class SettingsManager:
    """Load and atomically persist ETUI's unified user settings."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or SETTINGS_PATH
        self.settings_dir = self.path.parent
        self.settings = self.load_settings()

    @staticmethod
    def defaults() -> dict[str, Any]:
        return deepcopy(DEFAULT_SETTINGS)

    def load_settings(self) -> dict[str, Any]:
        settings = self.defaults()
        if self.path.is_file():
            try:
                loaded = yaml.safe_load(self.path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                loaded = None
            if isinstance(loaded, dict):
                self._merge_known_settings(settings, loaded)
                return settings

        self.migrate_legacy_configs(settings)
        return settings

    @staticmethod
    def _merge_known_settings(
        destination: dict[str, Any], source: dict[str, Any]
    ) -> None:
        for category, values in source.items():
            if category not in destination or not isinstance(values, dict):
                continue
            for key, value in values.items():
                if key in destination[category]:
                    destination[category][key] = value

    def migrate_legacy_configs(self, settings: dict[str, Any]) -> None:
        legacy_workspace = self.settings_dir / "workspace.json"
        if legacy_workspace.is_file():
            try:
                root = json.loads(legacy_workspace.read_text()).get("workspace_root")
                if root:
                    settings["workspace"]["root"] = root
            except (OSError, json.JSONDecodeError, AttributeError):
                pass

        legacy_debugger = self.settings_dir / "debugger.json"
        if legacy_debugger.is_file():
            try:
                data = json.loads(legacy_debugger.read_text())
                if isinstance(data, dict):
                    for key in settings["probe"]:
                        if key in data:
                            settings["probe"][key] = data[key]
            except (OSError, json.JSONDecodeError):
                pass

        legacy_dashboard = self.settings_dir / "dashboard.json"
        if legacy_dashboard.is_file():
            try:
                data = json.loads(legacy_dashboard.read_text())
                if isinstance(data, dict):
                    for key in ("layout", "collapsed", "theme"):
                        if key in data:
                            settings["lldb"][key] = data[key]
            except (OSError, json.JSONDecodeError):
                pass

        legacy_tools = self.settings_dir / "tools.json"
        if legacy_tools.is_file():
            try:
                data = json.loads(legacy_tools.read_text())
                if isinstance(data, list):
                    settings["tools"]["custom_paths"] = data
            except (OSError, json.JSONDecodeError):
                pass

    def save_settings(self, settings: dict[str, Any] | None = None) -> None:
        data = self.settings if settings is None else settings
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def get(self, category: str, key: str, default: Any = None) -> Any:
        return self.settings.get(category, {}).get(key, default)

    def set(self, category: str, key: str, value: Any) -> None:
        if category not in self.settings:
            self.settings[category] = {}
        self.settings[category][key] = value
        self.save_settings()

    def replace(self, settings: dict[str, Any]) -> None:
        merged = self.defaults()
        self._merge_known_settings(merged, settings)
        self.save_settings(merged)
        self.settings = merged
