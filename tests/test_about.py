import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from etui.tabs.about import capture_screenshots, enabled_tab_ids


def _run(coro) -> None:
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


class _Animator:
    async def wait_until_complete(self) -> None:
        pass


class _FakeTabs:
    def __init__(self) -> None:
        self.panes = [
            SimpleNamespace(id="files"),
            SimpleNamespace(id="plugin-manager"),
            SimpleNamespace(id="plugin-ocr"),
            SimpleNamespace(id="plugin-disabled", disabled=True),
            SimpleNamespace(id="plugin-hidden"),
        ]
        self.tabs = {
            "files": SimpleNamespace(disabled=False, display=True, visible=True),
            "plugin-manager": SimpleNamespace(disabled=False, display=True, visible=True),
            "plugin-ocr": SimpleNamespace(disabled=False, display=True, visible=True),
            "plugin-disabled": SimpleNamespace(disabled=True, display=True, visible=True),
            "plugin-hidden": SimpleNamespace(disabled=False, display=False, visible=True),
        }
        self.active = "about"

    def query(self, _selector):
        return self.panes

    def get_tab(self, tab_id: str):
        return self.tabs[tab_id]


class _FakeApp:
    def __init__(self, tabs: _FakeTabs) -> None:
        self.tabs = tabs
        self.animator = _Animator()

    def query_one(self, _selector):
        return self.tabs

    def export_screenshot(self, *, title: str) -> str:
        return f"<svg><title>{title}</title></svg>"


class AboutScreenshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir)

    def test_enabled_tab_ids_returns_mounted_enabled_panes(self) -> None:
        tabs = _FakeTabs()

        self.assertEqual(
            enabled_tab_ids(tabs),
            ["files", "plugin-manager", "plugin-ocr"],
        )

    def test_capture_screenshots_uses_enabled_tab_ids(self) -> None:
        _run(self._test_capture_screenshots_uses_enabled_tab_ids())

    async def _test_capture_screenshots_uses_enabled_tab_ids(self) -> None:
        tabs = _FakeTabs()
        app = _FakeApp(tabs)

        saved, failed = await capture_screenshots(app, self.tmp_dir)

        self.assertEqual(saved, ["files", "plugin-manager", "plugin-ocr"])
        self.assertEqual(failed, [])
        self.assertTrue((self.tmp_dir / "files.svg").is_file())
        self.assertTrue((self.tmp_dir / "plugin-manager.svg").is_file())
        self.assertTrue((self.tmp_dir / "plugin-ocr.svg").is_file())
        self.assertFalse((self.tmp_dir / "plugin-disabled.svg").exists())

    def test_enabled_tab_ids_reads_real_textual_panes(self) -> None:
        _run(self._test_enabled_tab_ids_reads_real_textual_panes())

    async def _test_enabled_tab_ids_reads_real_textual_panes(self) -> None:
        from textual.widgets import TabbedContent

        from etui.main import EtuiApp

        with patch("etui.plugins._entry_points", return_value=[]):
            app = EtuiApp(startup_workspace_root=str(self.tmp_dir))
            async with app.run_test():
                tab_ids = enabled_tab_ids(app.query_one(TabbedContent))

        self.assertIn("files", tab_ids)
        self.assertIn("plugin-manager", tab_ids)
        self.assertIn("about", tab_ids)
        self.assertGreater(len(tab_ids), 0)


if __name__ == "__main__":
    unittest.main()
