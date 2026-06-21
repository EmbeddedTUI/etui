# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
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
    TabEvent,
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


class GlobalGateTests(unittest.TestCase):
    def test_global_gate_no_domain_tab_imports_or_queries_in_main(self) -> None:
        import ast
        main_path = Path(__file__).parents[1] / "etui" / "main.py"
        self.assertTrue(main_path.is_file())
        
        with open(main_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(main_path))
            
        # The forbidden domain tab names
        forbidden_tab_classes = {"ProbeTab", "LldbTab", "GitTab", "GitHubTab", "CMakeTab", "WorkflowTab", "SerialTab", "VenvTab", "ToolsTab"}
        
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

