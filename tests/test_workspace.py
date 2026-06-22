# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
import unittest
import tempfile
import shutil
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch
from textual.widgets import Input

from etui.bus_contract import SVC_WORKSPACE_GET_ROOT, SVC_WORKSPACE_SET_ROOT
from etui.main import EtuiApp, _parse_main_args
from etui.tabs.files import FilesTab
from etui.tabs.console import ConsoleTab


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


class WorkspaceRootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.workspace_root = self.tmp_dir / "my_project"
        self.workspace_root.mkdir()
        # Create a git repo there to satisfy git/cmake validation
        (self.workspace_root / ".git").mkdir()
        # Create a pyproject.toml
        (self.workspace_root / "pyproject.toml").write_text("[project]\nname = \"test\"\n")
        self.settings_path = self.tmp_dir / "settings.yaml"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir)

    def _make_app(self) -> "EtuiApp":
        from etui.settings import SettingsManager
        with patch("etui.plugins._entry_points", return_value=[]):
            app = EtuiApp()
            app.settings_manager = SettingsManager(path=self.settings_path)
            app.workspace_root = app.load_workspace_root()
            return app

    def _make_app_with_startup_root(self, startup_workspace_root: str) -> "EtuiApp":
        from etui.settings import SettingsManager
        with patch("etui.plugins._entry_points", return_value=[]):
            app = EtuiApp(startup_workspace_root=startup_workspace_root)
            app.settings_manager = SettingsManager(path=self.settings_path)
            app.workspace_root = app.load_workspace_root()
            return app

    def _suppress_workspace_workers(self) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(patch("etui.main.Path.cwd", return_value=self.workspace_root))
        return stack

    def test_set_workspace_root_propagates_to_tabs(self) -> None:
        _run_textual_test(self._test_set_workspace_root_propagates_to_tabs())

    async def _test_set_workspace_root_propagates_to_tabs(self) -> None:
        app = self._make_app()
        with self._suppress_workspace_workers():
            async with app.run_test():
                # Set workspace root
                await app.set_workspace_root(str(self.workspace_root))

                # Check files tab tree path & input value
                files_tab = app.query_one(FilesTab)
                self.assertEqual(str(files_tab.query_one("LeftWidget").path), str(self.workspace_root))
                self.assertEqual(files_tab.query_one("#txt-workspace-root", Input).value, str(self.workspace_root))

                # Check console tab cwd
                console_tab = app.query_one(ConsoleTab)
                self.assertEqual(str(console_tab.cwd), str(self.workspace_root))

    def test_workspace_services_round_trip(self) -> None:
        _run_textual_test(self._test_workspace_services_round_trip())

    async def _test_workspace_services_round_trip(self) -> None:
        app = self._make_app()
        with self._suppress_workspace_workers():
            async with app.run_test():
                await app.bus.call(
                    SVC_WORKSPACE_SET_ROOT,
                    path=str(self.workspace_root),
                    persist=False,
                )
                self.assertEqual(
                    await app.bus.call(SVC_WORKSPACE_GET_ROOT),
                    str(self.workspace_root),
                )

                files_tab = app.query_one(FilesTab)
                self.assertEqual(
                    files_tab.query_one("#txt-workspace-root", Input).value,
                    str(self.workspace_root),
                )

    def test_workspace_set_root_persists_when_requested(self) -> None:
        _run_textual_test(self._test_workspace_set_root_persists_when_requested())

    async def _test_workspace_set_root_persists_when_requested(self) -> None:
        app = self._make_app()
        with self._suppress_workspace_workers():
            async with app.run_test():
                # Set workspace root
                await app.set_workspace_root(str(self.workspace_root))
                self.assertEqual(
                    app.settings_manager.get("workspace", "root"),
                    str(self.workspace_root),
                )

    def test_saved_workspace_notification_uses_supported_kwargs(self) -> None:
        _run_textual_test(self._test_saved_workspace_notification_uses_supported_kwargs())

    async def _test_saved_workspace_notification_uses_supported_kwargs(self) -> None:
        saved_workspace = self.tmp_dir / "saved_project"
        saved_workspace.mkdir()
        app = self._make_app()
        app.settings_manager.set("workspace", "root", str(saved_workspace))
        app.workspace_root = app.load_workspace_root()

        with self._suppress_workspace_workers():
            with patch.object(app, "notify") as mock_notify:
                async with app.run_test():
                    pass

        restore_notice = next(
            call for call in mock_notify.call_args_list
            if call.kwargs.get("title") == "Restore workspace?"
        )
        self.assertNotIn("action", restore_notice.kwargs)

    def test_cli_workspace_arg_resolves_relative_path(self) -> None:
        with patch("etui.main.Path.cwd", return_value=self.tmp_dir):
            _, workspace_root = _parse_main_args(["my_project"])

        self.assertEqual(workspace_root, str(self.workspace_root.resolve()))

    def test_startup_workspace_arg_wins_over_saved_workspace(self) -> None:
        _run_textual_test(self._test_startup_workspace_arg_wins_over_saved_workspace())

    async def _test_startup_workspace_arg_wins_over_saved_workspace(self) -> None:
        saved_workspace = self.tmp_dir / "saved_project"
        saved_workspace.mkdir()
        cli_workspace = self.tmp_dir / "cli_project"
        cli_workspace.mkdir()

        app = self._make_app_with_startup_root(str(cli_workspace))
        app.settings_manager.set("workspace", "root", str(saved_workspace))
        app.workspace_root = app.load_workspace_root()

        with patch.object(app, "notify") as mock_notify:
            async with app.run_test():
                self.assertEqual(app.workspace_root, str(cli_workspace))
                self.assertEqual(
                    await app.bus.call(SVC_WORKSPACE_GET_ROOT),
                    str(cli_workspace),
                )
                files_tab = app.query_one(FilesTab)
                self.assertEqual(
                    files_tab.query_one("#txt-workspace-root", Input).value,
                    str(cli_workspace),
                )

        restore_notices = [
            call for call in mock_notify.call_args_list
            if call.kwargs.get("title") == "Restore workspace?"
        ]
        self.assertEqual(restore_notices, [])

    def test_empty_input_falls_back_to_tree_path(self) -> None:
        _run_textual_test(self._test_empty_input_falls_back_to_tree_path())

    async def _test_empty_input_falls_back_to_tree_path(self) -> None:
        app = self._make_app()
        with self._suppress_workspace_workers():
            async with app.run_test() as pilot:
                files_tab = app.query_one(FilesTab)
                files_tab.query_one("LeftWidget").path = self.workspace_root
                # Empty out the input field
                files_tab.query_one("#txt-workspace-root", Input).value = ""

                # Click "Set Root" button
                await pilot.click("#btn-set-workspace-root")

                # Since input was empty, it should fall back to the LeftWidget path.
                expected_path = str(self.workspace_root)
                self.assertEqual(files_tab.query_one("#txt-workspace-root", Input).value, expected_path)
                self.assertEqual(str(app.workspace_root), expected_path)

if __name__ == "__main__":
    unittest.main()
