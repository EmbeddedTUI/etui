# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
import unittest
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from typing import Any

from textual.widget import Widget

from etui.plugin import API_VERSION, EtuiTabPlugin, TabSpec, CancelOnLeaveMixin, BusMixin
from etui.plugins import LoadedPlugin, PluginManager, ScopedBus
from etui.bus import MessageBus
from etui.bus_contract import (
    SVC_CONSOLE_RUN,
    SVC_HELP_ADD_ENTRY,
    SVC_NAV_ACTIVATE,
    SVC_SETTINGS_GET,
    SVC_SETTINGS_SET,
    SVC_WORKSPACE_GET_ROOT,
    SVC_WORKSPACE_SET_ROOT,
    TOPIC_TAB_ACTIVATED,
    TOPIC_TAB_DEACTIVATED,
    TOPIC_PLUGINS_INSTALL_PROGRESS,
    TabEvent,
    PluginInstallProgress,
)


def _run_textual_test(coro) -> None:
    loop = asyncio.new_event_loop()
    heartbeat = None

    def wake_loop() -> None:
        nonlocal heartbeat
        heartbeat = loop.call_later(0.05, wake_loop)

    try:
        asyncio.set_event_loop(loop)
        heartbeat = loop.call_later(0.05, wake_loop)
        loop.run_until_complete(coro)
    finally:
        if heartbeat is not None:
            heartbeat.cancel()
        executor = getattr(loop, "_default_executor", None)
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        loop.close()
        asyncio.set_event_loop(None)


class GoodPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        return TabSpec(id="plugin-good", title="Good Plugin", order=100)

    def create_widget(self) -> Widget:
        return Widget()


class DuplicatePlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        return TabSpec(id="plugin-good", title="Duplicate Plugin", order=101)

    def create_widget(self) -> Widget:
        return Widget()


class OldPlugin(EtuiTabPlugin):
    api_version = 999

    def spec(self) -> TabSpec:
        return TabSpec(id="plugin-old", title="Old Plugin")

    def create_widget(self) -> Widget:
        return Widget()


class BadIdPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        return TabSpec(id="bad-id", title="Bad ID Plugin")

    def create_widget(self) -> Widget:
        return Widget()


class UnauthorizedProvidesPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        return TabSpec(
            id="plugin-bad-provides",
            title="Bad Provides Plugin",
            provides=("core.unauthorized",),
        )

    def create_widget(self) -> Widget:
        return Widget()


class AuthorizedProvidesPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        return TabSpec(
            id="plugin-good-provides",
            title="Good Provides Plugin",
            provides=("debug.restart_probe",),
        )

    def create_widget(self) -> Widget:
        return Widget()


class MockEntryPoint:
    def __init__(self, name: str, plugin_class: type, dist: Any = None) -> None:
        self.name = name
        self.plugin_class = plugin_class
        self.dist = dist

    def load(self) -> type:
        return self.plugin_class


class MockDist:
    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version


class PluginDiscoveryTests(unittest.TestCase):
    @patch("etui.plugins._entry_points")
    def test_discover_loads_and_sorts_valid_plugins(self, mock_eps: MagicMock) -> None:
        dist = MockDist("etui-plugin-good", "0.1.0")
        mock_eps.return_value = [
            MockEntryPoint("good", GoodPlugin, dist),
        ]

        pm = PluginManager()
        pm.discover()

        self.assertEqual(len(pm.errors), 0)
        self.assertEqual(len(pm.loaded), 1)
        lp = pm.loaded[0]
        self.assertEqual(lp.name, "good")
        self.assertEqual(lp.dist, "etui-plugin-good 0.1.0")
        self.assertEqual(lp.spec.id, "plugin-good")
        self.assertEqual(lp.spec.title, "Good Plugin")

    @patch("etui.plugins._entry_points")
    def test_discover_skips_invalid_plugins_and_records_errors(self, mock_eps: MagicMock) -> None:
        mock_eps.return_value = [
            MockEntryPoint("old", OldPlugin),
            MockEntryPoint("bad_id", BadIdPlugin),
            MockEntryPoint("good1", GoodPlugin),
            MockEntryPoint("good2", DuplicatePlugin),
        ]

        pm = PluginManager()
        pm.discover()

        # Should load the first good plugin, but skip duplicate, old, and bad ID plugins
        self.assertEqual(len(pm.loaded), 1)
        self.assertEqual(pm.loaded[0].name, "good1")

        self.assertEqual(len(pm.errors), 3)
        errors_dict = dict(pm.errors)
        self.assertIn("old", errors_dict)
        self.assertIn("needs etui plugin API", errors_dict["old"])
        self.assertIn("bad_id", errors_dict)
        self.assertIn("must start with 'plugin-'", errors_dict["bad_id"])
        self.assertIn("good2", errors_dict)
        self.assertIn("duplicate tab id", errors_dict["good2"])

    @patch("etui.plugins._entry_points")
    def test_discover_skips_core_plugin_entry_points(self, mock_eps: MagicMock) -> None:
        class CoreVenvPlugin(GoodPlugin):
            def spec(self) -> TabSpec:
                return TabSpec(id="plugin-venv", title="Venv", order=200)

        class CoreManagerPlugin(AuthorizedProvidesPlugin):
            def spec(self) -> TabSpec:
                return TabSpec(id="plugin-manager", title="Plugins", order=950)

        mock_eps.return_value = [
            MockEntryPoint("venv", CoreVenvPlugin, MockDist("etui-venv", "0.1.0")),
            MockEntryPoint("manager", CoreManagerPlugin, MockDist("etui-plugin-manager", "0.1.0")),
        ]

        pm = PluginManager()
        pm.discover()

        self.assertEqual(len(pm.loaded), 0)
        self.assertEqual(len(pm.errors), 0)

    @patch("etui.plugins._entry_points")
    def test_discover_skips_unauthorized_provides_plugin(self, mock_eps: MagicMock) -> None:
        mock_eps.return_value = [
            MockEntryPoint("bad_provides", UnauthorizedProvidesPlugin),
            MockEntryPoint("good_provides", AuthorizedProvidesPlugin),
        ]
        pm = PluginManager()
        pm.discover()

        self.assertEqual(len(pm.loaded), 1)
        self.assertEqual(pm.loaded[0].name, "good_provides")
        self.assertEqual(len(pm.errors), 1)
        self.assertEqual(pm.errors[0][0], "bad_provides")
        self.assertIn("unauthorized service name", pm.errors[0][1])


class ScopedBusTests(unittest.IsolatedAsyncioTestCase):
    def test_scoped_bus_provides_enforced_namespace(self) -> None:
        bus = MessageBus()
        sb = ScopedBus(bus, "plugin-good")

        # Allowed provide
        sb.provide("plugin.good.service", lambda: 42)
        self.assertTrue(bus.has("plugin.good.service"))

        # Blocked provide
        with self.assertRaises(PermissionError):
            sb.provide("plugin.other.service", lambda: 0)

        with self.assertRaises(PermissionError):
            sb.provide("console.run", lambda: 0)

    def test_scoped_bus_emit_stamps_source(self) -> None:
        bus = MessageBus()
        sb = ScopedBus(bus, "plugin-good")

        seen = []
        bus.subscribe("some.topic", lambda e: seen.append(e))

        # Emit without source
        sb.emit("some.topic", "data")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].source, "plugin-good")
        self.assertEqual(seen[0].payload, "data")

        # Emit with spoofed source
        sb.emit("some.topic", "data2", source="core")
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[1].source, "plugin-good")
        self.assertEqual(seen[1].payload, "data2")

    async def test_scoped_bus_settings_section_rewriting(self) -> None:
        bus = MessageBus()
        sb = ScopedBus(bus, "plugin-good")

        received_kwargs = {}

        async def fake_settings_get(section, key, default=None):
            received_kwargs["section"] = section
            received_kwargs["key"] = key
            return "val"

        bus.provide("settings.get", fake_settings_get)

        res = await sb.call("settings.get", section="my_sec", key="my_key")
        self.assertEqual(res, "val")
        self.assertEqual(received_kwargs["section"], "plugin.good.my_sec")
        self.assertEqual(received_kwargs["key"], "my_key")

    async def test_scoped_bus_plugins_call_stamps_caller(self) -> None:
        bus = MessageBus()
        sb = ScopedBus(bus, "plugin-good")
        received_kwargs = {}

        async def fake_plugins_install(spec, caller="host", upgrade=False):
            received_kwargs["spec"] = spec
            received_kwargs["caller"] = caller
            received_kwargs["upgrade"] = upgrade
            return {"success": True}

        bus.provide("plugins.install", fake_plugins_install)

        await sb.call("plugins.install", spec="etui-demo", upgrade=True)
        self.assertEqual(received_kwargs["spec"], "etui-demo")
        self.assertEqual(received_kwargs["caller"], "plugin-good")
        self.assertEqual(received_kwargs["upgrade"], True)

    def test_scoped_bus_provides_allowlist(self) -> None:
        bus = MessageBus()
        sb = ScopedBus(bus, "plugin-good", provides=("debug.restart_probe",))

        # Allowlisted service should be allowed
        sb.provide("debug.restart_probe", lambda: 42)
        self.assertTrue(bus.has("debug.restart_probe"))

        # Non-allowlisted service should be blocked
        with self.assertRaises(PermissionError):
            sb.provide("debug.get_gdbserver_status", lambda: 0)

    def test_scoped_bus_dispose_all(self) -> None:
        bus = MessageBus()
        sb = ScopedBus(bus, "plugin-good")

        sb.provide("plugin.good.service", lambda: 42)
        sb.subscribe("some.topic", lambda e: None)

        self.assertTrue(bus.has("plugin.good.service"))
        self.assertEqual(len(bus._services), 1)
        self.assertEqual(len(bus._subs), 1)

        sb.dispose_all()

        self.assertFalse(bus.has("plugin.good.service"))
        self.assertEqual(len(bus._services), 0)
        self.assertEqual(len(bus._subs), 0)


class DummyTab(CancelOnLeaveMixin):
    def __init__(self, bus: MessageBus, widget_id: str) -> None:
        self._bus = bus
        self.id = widget_id
        self.busy = False
        self.cancelled = False
        self.survive = False

        # Simulate parent chain
        self.parent = None

    @property
    def bus(self) -> MessageBus:
        return self._bus

    def survives_leave(self) -> bool:
        return self.survive

    async def cancel_active_operation(self) -> None:
        self.cancelled = True
        self.busy = False


class PluginContractsTests(unittest.IsolatedAsyncioTestCase):
    async def test_install_and_uninstall_disable_rpc_timeout(self) -> None:
        from etui.contracts import plugins_install, plugins_uninstall

        bus = MagicMock()
        bus.call = AsyncMock(side_effect=[{"success": True}, None])

        self.assertEqual(
            await plugins_install(bus, "etui-demo", upgrade=True),
            {"success": True},
        )
        await plugins_uninstall(bus, "etui_demo")

        bus.call.assert_any_call(
            "plugins.install",
            timeout=None,
            spec="etui-demo",
            upgrade=True,
        )
        bus.call.assert_any_call(
            "plugins.uninstall",
            timeout=None,
            dist="etui_demo",
        )


class CancelOnLeaveMixinTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_on_leave_triggers_on_matching_pane_id(self) -> None:
        bus = MessageBus()
        tab = DummyTab(bus, "plugin-my-tab")
        tab.on_mount()

        # If tab is busy, transitioning away from it cancels it
        tab.busy = True
        bus.emit(TOPIC_TAB_DEACTIVATED, TabEvent(pane_id="plugin-my-tab"), source="app")
        await asyncio.sleep(0.01)  # allow event task to run

        self.assertTrue(tab.cancelled)
        self.assertFalse(tab.busy)

    async def test_cancel_on_leave_ignored_if_not_busy(self) -> None:
        bus = MessageBus()
        tab = DummyTab(bus, "plugin-my-tab")
        tab.on_mount()

        tab.busy = False
        bus.emit(TOPIC_TAB_DEACTIVATED, TabEvent(pane_id="plugin-my-tab"), source="app")
        await asyncio.sleep(0.01)

        self.assertFalse(tab.cancelled)

    async def test_cancel_on_leave_ignored_if_survives_leave(self) -> None:
        bus = MessageBus()
        tab = DummyTab(bus, "plugin-my-tab")
        tab.on_mount()

        tab.busy = True
        tab.survive = True
        bus.emit(TOPIC_TAB_DEACTIVATED, TabEvent(pane_id="plugin-my-tab"), source="app")
        await asyncio.sleep(0.01)

        self.assertFalse(tab.cancelled)
        self.assertTrue(tab.busy)

    async def test_cancel_on_leave_ignored_if_different_pane_id(self) -> None:
        bus = MessageBus()
        tab = DummyTab(bus, "plugin-my-tab")
        tab.on_mount()

        tab.busy = True
        bus.emit(TOPIC_TAB_DEACTIVATED, TabEvent(pane_id="other-tab"), source="app")
        await asyncio.sleep(0.01)

        self.assertFalse(tab.cancelled)
        self.assertTrue(tab.busy)

    async def test_cancel_on_leave_matches_via_parent_hierarchy(self) -> None:
        bus = MessageBus()
        tab = DummyTab(bus, "nested-child")  # id doesn't match the tab pane
        tab.on_mount()

        # Simulate widget hierarchy: tab -> parent_pane(id="plugin-parent-tab")
        parent_pane = MagicMock()
        parent_pane.id = "plugin-parent-tab"
        parent_pane.parent = None
        tab.parent = parent_pane

        tab.busy = True
        bus.emit(TOPIC_TAB_DEACTIVATED, TabEvent(pane_id="plugin-parent-tab"), source="app")
        await asyncio.sleep(0.01)

        self.assertTrue(tab.cancelled)
        self.assertFalse(tab.busy)


class MockPluginWidget(Widget, BusMixin):
    pass


class MockAppPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        return TabSpec(id="plugin-mocktab", title="Mock Tab", order=1500)

    def create_widget(self) -> Widget:
        return MockPluginWidget()


class HostServiceCheckingWidget(BusMixin, Widget):
    missing_services: list[str] = []
    mounted = False

    def on_mount(self) -> None:
        self.__class__.mounted = True
        self.__class__.missing_services = [
            service
            for service in (
                SVC_NAV_ACTIVATE,
                SVC_SETTINGS_GET,
                SVC_SETTINGS_SET,
                SVC_HELP_ADD_ENTRY,
                SVC_CONSOLE_RUN,
                SVC_WORKSPACE_GET_ROOT,
                SVC_WORKSPACE_SET_ROOT,
            )
            if not self.bus.has(service)
        ]


class HostServiceCheckingPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        return TabSpec(id="plugin-host-check", title="Host Check", order=1500)

    def create_widget(self) -> Widget:
        return HostServiceCheckingWidget()


class PluginMountIntegrationTests(unittest.TestCase):
    @patch("etui.plugins._entry_points")
    def test_host_services_available_before_plugin_on_mount(self, mock_eps: MagicMock) -> None:
        _run_textual_test(
            self._test_host_services_available_before_plugin_on_mount(mock_eps)
        )

    async def _test_host_services_available_before_plugin_on_mount(self, mock_eps: MagicMock) -> None:
        from etui.main import EtuiApp
        from etui.settings import SettingsManager
        from textual.widgets import TabbedContent
        import tempfile

        HostServiceCheckingWidget.missing_services = []
        HostServiceCheckingWidget.mounted = False
        mock_eps.return_value = [
            MockEntryPoint("host_check", HostServiceCheckingPlugin),
        ]

        with tempfile.TemporaryDirectory() as d:
            settings_path = Path(d) / "settings.yaml"
            app = EtuiApp()
            app.settings_manager = SettingsManager(path=settings_path)
            app.workspace_root = app.load_workspace_root()

            async with app.run_test():
                self.assertTrue(HostServiceCheckingWidget.mounted)
                self.assertEqual(HostServiceCheckingWidget.missing_services, [])

    @patch("etui.plugins._entry_points")
    def test_plugin_mount_integration(self, mock_eps: MagicMock) -> None:
        _run_textual_test(self._test_plugin_mount_integration(mock_eps))

    async def _test_plugin_mount_integration(self, mock_eps: MagicMock) -> None:
        from etui.main import EtuiApp
        from etui.settings import SettingsManager
        from textual.widgets import TabbedContent
        import tempfile

        mock_eps.return_value = [
            MockEntryPoint("mock_plugin", MockAppPlugin),
        ]

        with tempfile.TemporaryDirectory() as d:
            settings_path = Path(d) / "settings.yaml"
            app = EtuiApp()
            app.settings_manager = SettingsManager(path=settings_path)
            app.workspace_root = app.load_workspace_root()

            async with app.run_test() as pilot:
                tabs = app.query_one(TabbedContent)

                # Verify tab exists and can be retrieved
                self.assertIsNotNone(tabs.get_pane("plugin-mocktab"))

                # Check widget instance is mounted
                pane = tabs.get_pane("plugin-mocktab")
                mock_widget = pane.query_one(MockPluginWidget)
                self.assertIsNotNone(mock_widget)

                # Check ScopedBus is correctly set and injected
                self.assertIsNotNone(mock_widget.bus)
                self.assertIsInstance(mock_widget.bus, ScopedBus)
                self.assertEqual(mock_widget.bus._id, "plugin-mocktab")

    @patch("etui.plugins._entry_points")
    def test_plugin_settings_rewriting_end_to_end(self, mock_eps: MagicMock) -> None:
        _run_textual_test(self._test_plugin_settings_rewriting_end_to_end(mock_eps))

    async def _test_plugin_settings_rewriting_end_to_end(self, mock_eps: MagicMock) -> None:
        from etui.main import EtuiApp
        from etui.settings import SettingsManager
        import tempfile

        mock_eps.return_value = []

        with tempfile.TemporaryDirectory() as d:
            settings_path = Path(d) / "settings.yaml"
            app = EtuiApp()
            app.settings_manager = SettingsManager(path=settings_path)
            app.workspace_root = app.load_workspace_root()

            sb = ScopedBus(app.bus, "plugin-hello")

            # Set a setting through ScopedBus
            await sb.call("settings.set", section="my_sec", key="my_key", value="hello_value")

            # Verify it got saved in actual settings manager under plugin.hello.my_sec
            val = app.settings_manager.get("plugin.hello.my_sec", "my_key")
            self.assertEqual(val, "hello_value")

            # Retrieve it back through ScopedBus
            retrieved = await sb.call("settings.get", section="my_sec", key="my_key")
            self.assertEqual(retrieved, "hello_value")

    @patch("etui.plugins._entry_points")
    def test_plugin_cleanup_on_app_unmount(self, mock_eps: MagicMock) -> None:
        _run_textual_test(self._test_plugin_cleanup_on_app_unmount(mock_eps))

    async def _test_plugin_cleanup_on_app_unmount(self, mock_eps: MagicMock) -> None:
        from etui.main import EtuiApp
        from etui.settings import SettingsManager
        import tempfile

        mock_eps.return_value = [
            MockEntryPoint("mock_plugin", MockAppPlugin),
        ]

        with tempfile.TemporaryDirectory() as d:
            settings_path = Path(d) / "settings.yaml"
            app = EtuiApp()
            app.settings_manager = SettingsManager(path=settings_path)
            app.workspace_root = app.load_workspace_root()

            async with app.run_test() as pilot:
                lp = app.plugins.loaded[0]
                self.assertIsNotNone(lp.scoped_bus)

                mock_widget = app.query_one(MockPluginWidget)
                mock_widget.bus.subscribe("plugin-dummy-topic", lambda e: None)

                self.assertEqual(len(lp.scoped_bus._disposers), 1)

            # After app teardown, check disposers are cleaned up
            self.assertEqual(len(lp.scoped_bus._disposers), 0)

    @patch("etui.plugins._entry_points")
    def test_plugin_help_registration(self, mock_eps: MagicMock) -> None:
        _run_textual_test(self._test_plugin_help_registration(mock_eps))

    async def _test_plugin_help_registration(self, mock_eps: MagicMock) -> None:
        from etui.main import EtuiApp
        from etui.settings import SettingsManager
        from etui.tabs.help import HelpTab, OpenDocFile, _MENU
        from textual.widgets import ListView
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            settings_path = Path(d) / "settings.yaml"
            help_doc_path = Path(d) / "help.md"
            help_doc_path.write_text("Hello dynamic help doc content!")

            class MockHelpAppPlugin(EtuiTabPlugin):
                def spec(self) -> TabSpec:
                    return TabSpec(
                        id="plugin-mockhelp",
                        title="Mock Help",
                        order=1600,
                        help_doc=help_doc_path
                    )

                def create_widget(self) -> Widget:
                    return MockPluginWidget()

            mock_eps.return_value = [
                MockEntryPoint("mock_help_plugin", MockHelpAppPlugin),
            ]

            app = EtuiApp()
            app.settings_manager = SettingsManager(path=settings_path)
            app.workspace_root = app.load_workspace_root()

            async with app.run_test() as pilot:
                help_tab = app.query_one(HelpTab)
                
                # Check that the help tab registered the plugin entry
                self.assertEqual(len(help_tab._plugin_entries), 1)
                self.assertEqual(help_tab._plugin_entries[0][0], "Mock Help")
                self.assertEqual(help_tab._plugin_entries[0][1], help_doc_path)

                help_list = help_tab.query_one("#help-list", ListView)
                
                header_idx = len(_MENU)
                plugin_idx = header_idx + 1

                self.assertEqual(len(help_list.children), len(_MENU) + 2)
                
                # Verify that OpenDocFile message was posted with help_doc_path on selection
                original_post_message = help_tab.post_message
                help_tab.post_message = MagicMock()
                try:
                    mock_event = MagicMock()
                    mock_event.list_view.index = plugin_idx
                    help_tab.on_list_view_selected(mock_event)
                    
                    help_tab.post_message.assert_called_once()
                    msg = help_tab.post_message.call_args[0][0]
                    self.assertIsInstance(msg, OpenDocFile)
                    self.assertEqual(msg.path, help_doc_path)
                finally:
                    help_tab.post_message = original_post_message

                # Selecting the header (Plugins) should not post OpenDocFile
                help_tab.post_message = MagicMock()
                try:
                    mock_event = MagicMock()
                    mock_event.list_view.index = header_idx
                    help_tab.on_list_view_selected(mock_event)
                    help_tab.post_message.assert_not_called()
                finally:
                    help_tab.post_message = original_post_message

                # If the help document does not exist, it should notify with warning and not post
                help_tab.post_message = MagicMock()
                try:
                    help_doc_path.unlink()
                    mock_event = MagicMock()
                    mock_event.list_view.index = plugin_idx
                    
                    with patch.object(help_tab, "notify") as mock_notify:
                        help_tab.on_list_view_selected(mock_event)
                        mock_notify.assert_called_once_with(f"Doc file not found: {help_doc_path}", severity="warning")
                    
                    help_tab.post_message.assert_not_called()
                finally:
                    help_tab.post_message = original_post_message


    @patch("etui.plugins._entry_points")
    def test_plugin_manager_list_and_toggle_and_reorder(self, mock_eps: MagicMock) -> None:
        _run_textual_test(self._test_plugin_manager_list_and_toggle_and_reorder(mock_eps))

    async def _test_plugin_manager_list_and_toggle_and_reorder(self, mock_eps: MagicMock) -> None:
        from etui.main import EtuiApp
        from etui.settings import SettingsManager
        from textual.widgets import TabbedContent
        import tempfile

        mock_eps.return_value = [
            MockEntryPoint("mock_plugin", MockAppPlugin),
        ]

        with tempfile.TemporaryDirectory() as d:
            settings_path = Path(d) / "settings.yaml"
            app = EtuiApp()
            app.settings_manager = SettingsManager(path=settings_path)
            app.workspace_root = app.load_workspace_root()

            async with app.run_test() as pilot:
                # 1. Test plugins_list
                lst = await app.bus.call("plugins.list")
                # Should contain core tabs and our mock plugin
                ids = {item["id"] for item in lst}
                self.assertIn("files", ids)
                self.assertIn("plugin-mocktab", ids)
                
                # Verify metadata fields are populated on mock plugin item
                mock_item = next(item for item in lst if item["id"] == "plugin-mocktab")
                self.assertEqual(mock_item["source"], "third-party")
                self.assertEqual(mock_item["enabled"], True)
                self.assertEqual(mock_item["status"], "loaded")
                self.assertEqual(mock_item["summary"], "Mock Tab")

                # 2. Test plugins_set_enabled
                await app.bus.call("plugins.set_enabled", plugin_id="plugin-mocktab", enabled=False)
                disabled = app.settings_manager.get("plugins", "disabled")
                self.assertIn("plugin-mocktab", disabled)

                with self.assertRaises(Exception):
                    app.query_one(TabbedContent).get_pane("plugin-mocktab")

                # Set enabled again
                await app.bus.call("plugins.set_enabled", plugin_id="plugin-mocktab", enabled=True)
                disabled = app.settings_manager.get("plugins", "disabled")
                self.assertNotIn("plugin-mocktab", disabled)
                await app.bus.call("plugins.reload")
                self.assertIsNotNone(app.query_one(TabbedContent).get_pane("plugin-mocktab"))

                # 3. Test plugins_set_order
                await app.bus.call("plugins.set_order", order=["plugin-mocktab", "other-plugin"])
                order = app.settings_manager.get("plugins", "order")
                self.assertEqual(order, ["plugin-mocktab"])

    @patch("etui.plugins._entry_points")
    def test_plugin_hot_mount_crash_isolation(self, mock_eps: MagicMock) -> None:
        _run_textual_test(self._test_plugin_hot_mount_crash_isolation(mock_eps))

    async def _test_plugin_hot_mount_crash_isolation(self, mock_eps: MagicMock) -> None:
        from etui.main import EtuiApp
        from etui.settings import SettingsManager
        import tempfile

        # A plugin that crashes during widget creation
        class CrashingPlugin(EtuiTabPlugin):
            def spec(self) -> TabSpec:
                return TabSpec(id="plugin-crash", title="Crash Plugin")
            def create_widget(self) -> Widget:
                raise RuntimeError("Boom!")

        mock_eps.return_value = [
            MockEntryPoint("crash_plugin", CrashingPlugin),
        ]

        with tempfile.TemporaryDirectory() as d:
            settings_path = Path(d) / "settings.yaml"
            app = EtuiApp()
            app.settings_manager = SettingsManager(path=settings_path)
            app.workspace_root = app.load_workspace_root()

            async with app.run_test() as pilot:
                # Run reload
                res = await app.bus.call("plugins.reload")
                
                # The app should keep running despite the crash
                # The plugin error should be recorded
                errors = dict(app.plugins.errors)
                self.assertIn("crash_plugin", errors)
                self.assertIn("hot-mount failed", errors["crash_plugin"])

                # The plugin status should be "error" in plugins.list and not auto-disabled
                lst = await app.bus.call("plugins.list")
                crash_item = next(item for item in lst if item["id"] == "plugin-crash")
                self.assertEqual(crash_item["status"], "error")
                self.assertEqual(crash_item["enabled"], True)

    @patch("etui.plugins._entry_points")
    def test_settings_focus_section(self, mock_eps: MagicMock) -> None:
        _run_textual_test(self._test_settings_focus_section(mock_eps))

    async def _test_settings_focus_section(self, mock_eps: MagicMock) -> None:
        from etui.main import EtuiApp
        from etui.settings import SettingsManager
        from textual.widgets import TabbedContent
        import tempfile

        mock_eps.return_value = []

        with tempfile.TemporaryDirectory() as d:
            settings_path = Path(d) / "settings.yaml"
            app = EtuiApp()
            app.settings_manager = SettingsManager(path=settings_path)
            app.workspace_root = app.load_workspace_root()

            async with app.run_test() as pilot:
                # 1. Test focus valid core section
                await app.bus.call("settings.focus_section", section="workspace")
                tabs = app.query_one(TabbedContent)
                self.assertEqual(tabs.active, "settings")

                # 2. Test focus invalid/unknown section
                with patch.object(app, "notify") as mock_notify:
                    await app.bus.call("settings.focus_section", section="invalid_section")
                    mock_notify.assert_called_once()
                    self.assertIn("Unknown or disabled settings section", mock_notify.call_args[0][0])

    @patch("etui.plugins._entry_points")
    def test_confirm_action_uses_push_screen_wait(self, mock_eps: MagicMock) -> None:
        _run_textual_test(self._test_confirm_action_uses_push_screen_wait(mock_eps))

    async def _test_confirm_action_uses_push_screen_wait(self, mock_eps: MagicMock) -> None:
        from etui.main import EtuiApp
        from etui.settings import SettingsManager
        import tempfile

        mock_eps.return_value = []

        with tempfile.TemporaryDirectory() as d:
            settings_path = Path(d) / "settings.yaml"
            app = EtuiApp()
            app.settings_manager = SettingsManager(path=settings_path)
            app.workspace_root = app.load_workspace_root()

            async with app.run_test():
                with patch.object(app, "push_screen_wait", AsyncMock(return_value=True)) as mock_push:
                    self.assertTrue(await app.confirm_action("Confirm?"))
                    mock_push.assert_called_once()

    @patch("etui.plugins._entry_points")
    @patch("asyncio.create_subprocess_exec")
    @patch("shutil.which")
    def test_plugin_install_uninstall_and_degrade(self, mock_which: MagicMock, mock_exec: MagicMock, mock_eps: MagicMock) -> None:
        _run_textual_test(self._test_plugin_install_uninstall_and_degrade(mock_which, mock_exec, mock_eps))

    async def _test_plugin_install_uninstall_and_degrade(self, mock_which: MagicMock, mock_exec: MagicMock, mock_eps: MagicMock) -> None:
        from etui.main import EtuiApp
        from etui.settings import SettingsManager
        import os
        import sys
        import tempfile
        import zipfile

        mock_eps.return_value = []
        mock_which.return_value = "/mock/bin/pdm"

        # Mock PDM process success
        from unittest.mock import AsyncMock
        class MockStream:
            def __init__(self, lines: list[bytes]) -> None:
                self._lines = list(lines)

            async def readline(self) -> bytes:
                if self._lines:
                    return self._lines.pop(0)
                return b""

        def make_proc(stdout_lines: list[bytes], stderr_lines: list[bytes]) -> MagicMock:
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = MockStream(stdout_lines)
            proc.stderr = MockStream(stderr_lines)
            proc.wait = AsyncMock(return_value=0)
            return proc

        with tempfile.TemporaryDirectory() as d:
            settings_path = Path(d) / "settings.yaml"
            app = EtuiApp()
            app.testing = True  # bypass confirmation dialog
            app.settings_manager = SettingsManager(path=settings_path)
            app.settings_manager.set("plugins", "user_plugin_dir", d)
            progress_events: list[PluginInstallProgress] = []
            app.bus.subscribe(
                TOPIC_PLUGINS_INSTALL_PROGRESS,
                lambda event: progress_events.append(event.payload),
            )

            async with app.run_test() as pilot:
                app.workspace_root = d

                # 1. Test degrade when no installer found
                mock_which.return_value = None
                with self.assertRaises(RuntimeError):
                    await app.bus.call("plugins.install", spec="etui-somepkg")

                # 2. Test install argv structure with pdm available
                mock_which.return_value = "/mock/bin/pdm"

                helper_site_packages = (
                    Path(d)
                    / ".tmp_install"
                    / "venv"
                    / "lib"
                    / f"python{sys.version_info.major}.{sys.version_info.minor}"
                    / "site-packages"
                )

                def write_distribution(root: Path, name: str, version: str, *, deps: list[str] | None = None) -> None:
                    pkg_name = name.replace("-", "_")
                    pkg_dir = root / pkg_name
                    pkg_dir.mkdir(parents=True, exist_ok=True)
                    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
                    dist_info = root / f"{pkg_name}-{version}.dist-info"
                    dist_info.mkdir(parents=True, exist_ok=True)
                    metadata_lines = [
                        "Metadata-Version: 2.4",
                        f"Name: {name}",
                        f"Version: {version}",
                    ]
                    for dep in deps or []:
                        metadata_lines.append(f"Requires-Dist: {dep}")
                    (dist_info / "METADATA").write_text("\n".join(metadata_lines) + "\n", encoding="utf-8")
                    (dist_info / "RECORD").write_text(
                        "\n".join(
                            [
                                f"{pkg_name}/__init__.py,,",
                                f"{dist_info.name}/METADATA,,",
                                f"{dist_info.name}/RECORD,,",
                            ]
                        )
                        + "\n",
                        encoding="utf-8",
                    )

                def side_effect(*args, **kwargs):
                    if args[1] == "run":
                        return make_proc([f"{helper_site_packages}\n".encode()], [])
                    helper_site_packages.mkdir(parents=True, exist_ok=True)
                    write_distribution(helper_site_packages, "etui-somepkg", "0.1.0")
                    return make_proc([b"pdm output\n"], [])
                mock_exec.side_effect = side_effect

                res = await app.bus.call("plugins.install", spec="etui-somepkg")
                self.assertTrue(res["success"])
                self.assertEqual(res["dist"], "etui_somepkg")
                self.assertTrue(
                    any("Using installer: /mock/bin/pdm" in event.message for event in progress_events)
                )
                self.assertTrue(any(event.message == "pdm output" for event in progress_events))
                self.assertTrue(
                    any("Install complete" in event.message for event in progress_events)
                )

                # Assert correct pdm call
                mock_exec.assert_any_call(
                    "/mock/bin/pdm", "add", "etui-somepkg",
                    env=ANY,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(Path(d) / ".tmp_install"),
                )
                mock_exec.assert_any_call(
                    "/mock/bin/pdm", "run", "python", "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])",
                    env=ANY,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(Path(d) / ".tmp_install"),
                )
                self.assertEqual(mock_exec.call_args_list[0].kwargs["env"]["PDM_IGNORE_ACTIVE_VENV"], "1")

                # Verify target folder moved
                self.assertTrue((Path(d) / "etui_somepkg").is_dir())
                self.assertTrue((Path(d) / "etui_somepkg" / "etui_somepkg" / "__init__.py").is_file())

                # 3. Test PDM build artifact resolution from a project directory
                project_dir = Path(d) / "project"
                dist_dir = project_dir / "dist"
                dist_dir.mkdir(parents=True)
                sdist = dist_dir / "etui_artifact-0.1.0.tar.gz"
                wheel = dist_dir / "etui_artifact-0.1.0-py3-none-any.whl"
                sdist.write_text("sdist")
                with zipfile.ZipFile(wheel, "w") as zf:
                    zf.writestr(
                        "etui_artifact-0.1.0.dist-info/METADATA",
                        "\n".join(
                            [
                                "Metadata-Version: 2.4",
                                "Name: etui-artifact",
                                "Version: 0.1.0",
                                "Requires-Dist: etui>=0.3.0",
                                "Requires-Dist: httpx>=0.27",
                                "",
                            ]
                        ),
                    )
                os.utime(sdist, (1, 1))
                os.utime(wheel, (2, 2))

                mock_exec.reset_mock()
                def artifact_side_effect(*args, **kwargs):
                    if args[1] == "run":
                        return make_proc([f"{helper_site_packages}\n".encode()], [])
                    helper_site_packages.mkdir(parents=True, exist_ok=True)
                    write_distribution(helper_site_packages, "httpx", "0.27.0")
                    write_distribution(
                        helper_site_packages,
                        "etui-artifact",
                        "0.1.0",
                        deps=["etui>=0.3.0", "httpx>=0.27"],
                    )
                    write_distribution(helper_site_packages, "etui", "0.4.0")
                    return make_proc([b"artifact output\n"], [])
                mock_exec.side_effect = artifact_side_effect

                res = await app.bus.call("plugins.install", spec="project")
                self.assertTrue(res["success"])
                self.assertEqual(res["dist"], "etui_artifact")
                self.assertEqual(res["spec"], str(wheel.resolve()))
                mock_exec.assert_any_call(
                    "/mock/bin/pdm", "add", str(wheel.resolve()),
                    env=ANY,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(Path(d) / ".tmp_install"),
                )
                mock_exec.assert_any_call(
                    "/mock/bin/pdm", "run", "python", "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])",
                    env=ANY,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(Path(d) / ".tmp_install"),
                )
                self.assertTrue((Path(d) / "etui_artifact" / "etui_artifact" / "__init__.py").is_file())
                self.assertTrue((Path(d) / "etui_artifact" / "httpx" / "__init__.py").is_file())
                self.assertFalse((Path(d) / "etui" / "__init__.py").exists())

                # 4. Test plugins_uninstall
                await app.bus.call("plugins.uninstall", dist="etui_somepkg")
                await app.bus.call("plugins.reload")
                self.assertFalse((Path(d) / "etui_somepkg").exists())
                plugin_ids = [item["id"] for item in await app.bus.call("plugins.list")]
                self.assertNotIn("plugin-somepkg", plugin_ids)


class GlobalGateTests(unittest.TestCase):
    def test_global_gate_no_domain_tab_imports_or_queries_in_main(self) -> None:
        import ast
        main_path = Path(__file__).parents[1] / "etui" / "main.py"
        self.assertTrue(main_path.is_file())
        
        with open(main_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(main_path))
            
        # The forbidden domain tab names
        forbidden_tab_classes = {"ProbeTab", "LldbTab", "GitTab", "GitHubTab", "CMakeTab", "WorkflowTab", "SerialTab", "ToolsTab"}
        
        # Walk AST to find imports or query_one with the forbidden names
        for node in ast.walk(tree):
            # Check imports
            if isinstance(node, ast.ImportFrom):
                for name in node.names:
                    if name.name in forbidden_tab_classes:
                        self.fail(f"Global Gate Violation: main.py imports {name.name} from {node.module}")
            if isinstance(node, ast.Import):
                for name in node.names:
                    if name.name in forbidden_tab_classes:
                        self.fail(f"Global Gate Violation: main.py imports {name.name}")
                        
            # Check query_one(<Class>) calls
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "query_one":
                    for arg in node.args:
                        if isinstance(arg, ast.Name) and arg.id in forbidden_tab_classes:
                            self.fail(f"Global Gate Violation: main.py calls query_one({arg.id})")
