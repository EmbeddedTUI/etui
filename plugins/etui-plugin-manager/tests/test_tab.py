# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
import unittest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Label, Button, Input
from etui_plugin_manager.tab import PluginManagerTab
from etui.bus import MessageBus
from etui.bus_contract import PluginsChanged, TOPIC_PLUGINS_CHANGED


class PluginManagerTestApp(App):
    def __init__(self, bus: MessageBus) -> None:
        super().__init__()
        self.bus = bus

    def compose(self) -> ComposeResult:
        tab = PluginManagerTab()
        tab._bus = self.bus
        yield tab


class PluginManagerTabTests(unittest.IsolatedAsyncioTestCase):
    async def test_tab_lifecycle_and_actions(self) -> None:
        bus = MessageBus()
        
        # Mock central services
        mock_plugins_list = [
            {"id": "files", "dist": "etui", "version": "0.4.0", "source": "core", "enabled": True, "status": "loaded", "summary": "Workspace files", "errors": None},
            {"id": "plugin-mocktab", "dist": "etui-mock", "version": "0.1.0", "source": "third-party", "enabled": True, "status": "loaded", "summary": "Mock Tab", "errors": None, "settings_section": "mocktab"},
            {"id": "plugin-default", "dist": "etui-default", "version": "0.1.0", "source": "default", "enabled": True, "status": "loaded", "summary": "Default Tab", "errors": None, "settings_section": None},
            {"id": "plugin-other", "dist": "etui-other", "version": "0.1.0", "source": "third-party", "enabled": True, "status": "loaded", "summary": "Other Tab", "errors": None, "settings_section": None},
        ]
        
        bus.provide("plugins.list", AsyncMock(return_value=mock_plugins_list))
        
        mock_set_enabled = AsyncMock()
        bus.provide("plugins.set_enabled", mock_set_enabled)
        
        mock_reload = AsyncMock(return_value={"added": []})
        bus.provide("plugins.reload", mock_reload)
        
        mock_focus_section = AsyncMock()
        bus.provide("settings.focus_section", mock_focus_section)
        
        mock_uninstall = AsyncMock()
        bus.provide("plugins.uninstall", mock_uninstall)
        
        mock_set_order = AsyncMock()
        bus.provide("plugins.set_order", mock_set_order)

        mock_install = AsyncMock(return_value={"dist": "etui-new", "success": True})
        bus.provide("plugins.install", mock_install)

        app = PluginManagerTestApp(bus)
        
        async with app.run_test() as pilot:
            tab = app.query_one(PluginManagerTab)
            
            # 1. Assert initial load populated DataTable and Summary Label
            table = tab.query_one("#plugins-table", DataTable)
            self.assertEqual(table.row_count, 4)
            self.assertEqual(table.get_row_at(0)[1], "files")
            self.assertEqual(table.get_row_at(1)[1], "plugin-default")
            self.assertEqual(table.get_row_at(2)[1], "plugin-mocktab")

            summary = tab.query_one("#install-summary", Label)
            self.assertIn("4 plugins", str(summary.content))
            self.assertEqual(tab.selected_plugin_id, "files")
            self.assertEqual(
                str(tab.query_one("#lbl-detail-id", Label).content),
                "ID: files",
            )

            # 2. Select a default plugin and verify the enable/disable button works.
            table.move_cursor(row=1)
            await pilot.pause()
            self.assertEqual(tab.selected_plugin_id, "plugin-default")
            self.assertEqual(
                str(tab.query_one("#lbl-detail-id", Label).content),
                "ID: plugin-default",
            )

            btn_toggle = tab.query_one("#btn-toggle-enable", Button)
            self.assertFalse(btn_toggle.disabled)
            self.assertEqual(btn_toggle.label, "Disable")

            await tab.toggle_plugin_enable()
            mock_set_enabled.assert_called_once_with(plugin_id="plugin-default", enabled=False)
            mock_reload.assert_called_once()
            mock_set_enabled.reset_mock()
            mock_reload.reset_mock()

            # 3. Select plugin-mocktab and verify details view
            table.move_cursor(row=2)
            tab.selected_plugin_id = "plugin-mocktab"
            tab.update_detail_view()
            await pilot.pause()
            
            # Verify details view is updated
            detail_id = tab.query_one("#lbl-detail-id", Label)
            self.assertEqual(str(detail_id.content), "ID: plugin-mocktab")
            
            self.assertEqual(btn_toggle.label, "Disable")

            # 4. Test Enable/Disable Action Button click for third-party plugin.
            await tab.toggle_plugin_enable()
            mock_set_enabled.assert_called_once_with(plugin_id="plugin-mocktab", enabled=False)
            mock_reload.assert_called_once()

            # 5. Test Configure Action Button click
            await tab.configure_plugin()
            mock_focus_section.assert_called_once_with(section="mocktab")

            # 6. Test Move Down Action Button click
            await tab.move_plugin(1)
            mock_set_order.assert_called_once_with(
                order=["plugin-default", "plugin-other", "plugin-mocktab"]
            )

            # 7. Test Uninstall Action Button click
            await tab.uninstall_plugin()
            await pilot.pause()
            mock_uninstall.assert_called_once_with(dist="etui-mock")

            # 8. Test bus event TOPIC_PLUGINS_CHANGED refreshes table
            # Modify list response to simulate an update
            mock_plugins_list.append(
                {"id": "plugin-new", "dist": "etui-new", "version": "0.2.0", "source": "third-party", "enabled": True, "status": "loaded", "summary": "New Tab", "errors": None}
            )
            
            bus.emit(
                TOPIC_PLUGINS_CHANGED,
                PluginsChanged(added=["etui-new"], removed=[], enabled=[], disabled=[], order=[])
            )
            await pilot.pause()
            
            self.assertEqual(table.row_count, 5)
            self.assertIn("5 plugins", str(summary.content))

            install_input = tab.query_one("#txt-install-spec", Input)
            install_input.value = "etui-new"
            await tab.install_plugin()
            await pilot.pause()
            mock_install.assert_called_once_with(spec="etui-new", upgrade=False)
            self.assertFalse(tab.query_one("#btn-install", Button).disabled)
