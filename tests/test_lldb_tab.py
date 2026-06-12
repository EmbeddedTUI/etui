# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import tempfile
import unittest
from pathlib import Path

from textual.app import App, ComposeResult

from etui.tabs.lldb import LldbTab
from etui.tabs.probe import TARGETS
from etui.tabs.tools import ToolWarningBanner


class LldbTestApp(App):
    def compose(self) -> ComposeResult:
        yield LldbTab()


class LldbTabTests(unittest.IsolatedAsyncioTestCase):
    def test_probe_targets_use_thumb_triple(self) -> None:
        self.assertEqual(TARGETS["MSPM0L"][1], "thumbv6m-none-eabi")
        self.assertEqual(TARGETS["MSPM0G"][1], "thumbv6m-none-eabi")
        self.assertEqual(TARGETS["MSPM0C"][1], "thumbv6m-none-eabi")

    def test_target_setup_uses_firmware_elf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "firmware.elf"
            executable.write_bytes(b"\x7fELF")
            tab = LldbTab(
                arch="thumbv6m-none-eabi",
                settings={"executable": str(executable)},
            )

            self.assertEqual(
                tab._target_setup_command(),
                f'target create --arch thumbv6m-none-eabi "{executable}"',
            )

    def test_target_setup_without_elf_sets_default_arch(self) -> None:
        tab = LldbTab(arch="thumbv6m-none-eabi")
        self.assertEqual(
            tab._target_setup_command(),
            "settings set target.default-arch thumbv6m-none-eabi",
        )

    async def test_warning_is_above_main_debugger_layout(self) -> None:
        app = LldbTestApp()
        async with app.run_test():
            tab = app.query_one(LldbTab)
            banner = tab.query_one(ToolWarningBanner)
            main = tab.query_one("#lldb-main")

            self.assertEqual(banner.tool_id, "lldb")
            self.assertIs(banner.parent, tab)
            self.assertIs(main.parent, tab)
