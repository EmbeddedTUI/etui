# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from textual.app import App, ComposeResult
from textual.widgets import RichLog

from etui.tabs.lldb import LldbTab, MEMORY_MAP_ASSERTION
from etui.tabs.probe import TARGETS
from etui.tabs.tools import ToolWarningBanner


class LldbTestApp(App):
    def compose(self) -> ComposeResult:
        yield LldbTab()


class FakeStdout:
    def __init__(self, lines: list[str]) -> None:
        self.lines = iter([*(f"{line}\n".encode() for line in lines), b""])

    async def readline(self) -> bytes:
        return next(self.lines)


class CrashedLldbProcess:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = FakeStdout(lines)
        self.returncode = -6

    async def wait(self) -> int:
        return self.returncode


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

    def test_dashboard_avoids_live_memory_disassembly(self) -> None:
        tab = LldbTab()
        commands = tab._dash_commands()

        self.assertNotIn("disassemble --pc --count 8", commands)
        self.assertIn(
            "memory read --size 2 --format x --count 8 $pc",
            commands,
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

    async def test_memory_map_assertion_from_lldb_process_is_regressed(self) -> None:
        app = LldbTestApp()
        async with app.run_test():
            tab = app.query_one(LldbTab)
            process = CrashedLldbProcess(
                [
                    "error: Failed to disassemble memory at 0x0800024a.",
                    (
                        'error: Assertion failed: (0 && "'
                        f'{MEMORY_MAP_ASSERTION}"), function FindSpace, '
                        "file IRMemoryMap.cpp, line 146"
                    ),
                    "#0 llvm::sys::PrintStackTrace(llvm::raw_ostream&, int)",
                    "#1 /lib/aarch64-linux-gnu/liblldb-20.so.1",
                ]
            )
            tab._proc = process
            tab._port = 4242
            tab._in_dash = True

            scheduled_recoveries: list[object] = []

            def capture_worker(coroutine, **kwargs):
                scheduled_recoveries.append((coroutine, kwargs))
                coroutine.close()
                return MagicMock()

            with patch.object(tab, "run_worker", side_effect=capture_worker):
                await tab._read_output()

            self.assertTrue(tab._memory_map_assertion)
            self.assertTrue(tab._suppress_crash_trace)
            self.assertFalse(tab._in_dash)
            self.assertIn("aborted", tab._last_data["assembly"][0])
            self.assertTrue(tab._recovery_attempted)
            self.assertEqual(len(scheduled_recoveries), 1)
            self.assertEqual(
                scheduled_recoveries[0][1]["name"],
                "lldb-memory-map-recovery",
            )

            log_text = "\n".join(
                line.text for line in tab.query_one(RichLog).lines
            )
            self.assertIn("LLDB aborted while querying remote memory", log_text)
            self.assertNotIn("PrintStackTrace", log_text)
            self.assertNotIn("liblldb-20.so", log_text)
