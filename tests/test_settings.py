# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import json
from pathlib import Path
import tempfile
import unittest

import yaml
from textual.app import App, ComposeResult
from textual.widgets import Input, Select

from etui.settings import SettingsManager
from etui_probe.tab import ProbeTab
from etui.tabs.settings import SettingsTab


class SettingsTestApp(App):
    def __init__(self, manager: SettingsManager) -> None:
        super().__init__()
        self.settings_manager = manager
        self.workspace_root: str | None = None
        from etui.bus import MessageBus
        from etui.bus_contract import SVC_THEME_SET
        self.bus = MessageBus()
        self.bus.provide(SVC_THEME_SET, self._svc_theme_set)

    async def _svc_theme_set(self, name: str) -> None:
        pass

    def compose(self) -> ComposeResult:
        yield ProbeTab()
        yield SettingsTab()

    async def set_workspace_root(
        self, path: str, update_files: bool = True, persist: bool = True
    ) -> None:
        self.workspace_root = path


def test_settings_manager_persists_and_ignores_unknown_keys(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        yaml.safe_dump(
            {
                "workspace": {"root": "/tmp/project", "unknown": True},
                "unknown_category": {"value": 1},
            }
        )
    )

    manager = SettingsManager(settings_path)
    assert manager.get("workspace", "root") == "/tmp/project"
    assert "unknown" not in manager.settings["workspace"]
    assert "unknown_category" not in manager.settings

    manager.set("ui", "word_wrap", True)
    reloaded = SettingsManager(settings_path)
    assert reloaded.get("ui", "word_wrap") is True
    assert reloaded.get("lldb", "theme") == "vibrant"


def test_settings_manager_migrates_local_legacy_files(tmp_path: Path) -> None:
    (tmp_path / "workspace.json").write_text(
        json.dumps({"workspace_root": "/tmp/legacy"})
    )
    (tmp_path / "debugger.json").write_text(json.dumps({"gdb_port": 1234}))
    (tmp_path / "dashboard.json").write_text(json.dumps({"theme": "mono"}))
    (tmp_path / "tools.json").write_text(json.dumps(["/opt/toolchain/bin"]))

    manager = SettingsManager(tmp_path / "settings.yaml")
    assert manager.get("workspace", "root") == "/tmp/legacy"
    assert manager.get("probe", "gdb_port") == 1234
    assert manager.get("lldb", "theme") == "mono"
    assert manager.get("tools", "custom_paths") == ["/opt/toolchain/bin"]


class SettingsTabTests(unittest.IsolatedAsyncioTestCase):
    async def test_validates_then_applies_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            settings_path = tmp_path / "settings.yaml"
            manager = SettingsManager(settings_path)
            workspace = tmp_path / "workspace"
            tool_path = tmp_path / "toolchain" / "bin"
            workspace.mkdir()
            tool_path.mkdir(parents=True)

            app = SettingsTestApp(manager)
            async with app.run_test():
                tab = app.query_one(SettingsTab)
                tab.query_one("#set-workspace-root", Input).value = str(workspace)
                tab.query_one("#set-probe-backend", Select).value = "openocd"
                tab.query_one("#set-probe-speed", Input).value = "8000"
                tab.query_one("#set-probe-gdb", Input).value = "3334"
                tab.query_one("#set-probe-telnet", Input).value = "4445"
                tab.query_one("#set-probe-tcl", Input).value = "6667"
                tab.query_one("#set-tools-paths", Input).value = str(tool_path)

                await tab.save_settings_from_ui()

                self.assertEqual(app.workspace_root, str(workspace.resolve()))
                self.assertEqual(manager.get("probe", "backend"), "openocd")
                self.assertEqual(manager.get("probe", "adapter_speed_khz"), 8000)
                self.assertEqual(
                    manager.get("tools", "custom_paths"),
                    [str(tool_path.resolve())],
                )
                self.assertEqual(app.query_one(ProbeTab)._backend, "openocd")
                self.assertTrue(settings_path.is_file())

                saved = manager.settings.copy()
                tab.query_one("#set-probe-gdb", Input).value = "not-a-port"
                await tab.save_settings_from_ui()
                self.assertEqual(manager.settings, saved)
