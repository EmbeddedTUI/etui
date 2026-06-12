# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from textual.app import App, ComposeResult
from textual.widgets import RichLog

from etui.tabs.lldb import (
    CONNECT_FAILURE,
    LldbTab,
    MEMORY_MAP_ASSERTION,
    ProbeRestartRequested,
)
from etui.tabs.probe import ProbeTab, TARGETS
from etui.tabs.tools import ToolWarningBanner


class LldbTestApp(App):
    def compose(self) -> ComposeResult:
        yield LldbTab()


class ProbeTestApp(App):
    def compose(self) -> ComposeResult:
        yield ProbeTab()


class FakeStdout:
    def __init__(self, lines: list[str]) -> None:
        self.lines = iter([*(f"{line}\n".encode() for line in lines), b""])

    async def readline(self) -> bytes:
        return next(self.lines)


class CrashedLldbProcess:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = FakeStdout(lines)
        self.returncode = None
        self.killed = False

    async def wait(self) -> int:
        if self.returncode is None:
            self.returncode = -6
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


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

            posted_messages: list[object] = []
            with patch.object(
                tab,
                "post_message",
                side_effect=posted_messages.append,
            ):
                await tab._read_output()

            self.assertTrue(tab._memory_map_assertion)
            self.assertTrue(tab._suppress_crash_trace)
            self.assertTrue(tab._remote_memory_safe_mode)
            self.assertFalse(tab._in_dash)
            self.assertIn("aborted", tab._last_data["assembly"][0])
            self.assertTrue(process.killed)
            self.assertTrue(tab._recovery_attempted)
            self.assertIsNone(tab._proc)
            self.assertEqual(len(posted_messages), 1)
            self.assertIsInstance(posted_messages[0], ProbeRestartRequested)

            log_text = "\n".join(
                line.text for line in tab.query_one(RichLog).lines
            )
            self.assertIn("LLDB aborted while querying remote memory", log_text)
            self.assertNotIn("PrintStackTrace", log_text)
            self.assertNotIn("liblldb-20.so", log_text)

            recovery_commands = tab._dash_commands()
            self.assertNotIn(
                "memory read --size 2 --format x --count 8 $pc",
                recovery_commands,
            )
            self.assertNotIn(
                "memory read --size 4 --format x --count 16 $sp",
                recovery_commands,
            )
            self.assertIn(
                "script print('remote memory view disabled after LLDB crash')",
                recovery_commands,
            )

    async def test_recovery_requests_fresh_probe_server(self) -> None:
        app = LldbTestApp()
        async with app.run_test():
            tab = app.query_one(LldbTab)
            process = CrashedLldbProcess([])
            process.returncode = -9
            tab._proc = process
            tab._port = 4242
            tab._remote_memory_safe_mode = True

            with patch.object(tab, "post_message") as post_message:
                tab._request_probe_restart(process)

            post_message.assert_called_once()
            self.assertIsInstance(
                post_message.call_args.args[0], ProbeRestartRequested
            )
            self.assertIsNone(tab._proc)
            self.assertTrue(tab._remote_memory_safe_mode)

    async def test_connect_failure_is_detected_before_dashboard_setup(self) -> None:
        app = LldbTestApp()
        async with app.run_test():
            tab = app.query_one(LldbTab)

            async def fail_connection(command: str) -> None:
                self.assertEqual(command, "gdb-remote localhost:4242")
                tab._route(CONNECT_FAILURE)

            tab._port = 4242
            with patch.object(
                tab, "send_command", new=AsyncMock(side_effect=fail_connection)
            ):
                connected = await tab._connect_remote(timeout=0.1)

            self.assertFalse(connected)

    async def test_failed_connect_does_not_install_dashboard_commands(self) -> None:
        app = LldbTestApp()
        async with app.run_test():
            tab = app.query_one(LldbTab)
            process = MagicMock()
            process.returncode = None

            def close_reader(coroutine, **kwargs):
                coroutine.close()
                return MagicMock()

            with (
                patch("etui.tabs.lldb.shutil.which", return_value="/usr/bin/lldb"),
                patch(
                    "etui.tabs.lldb.asyncio.create_subprocess_exec",
                    new=AsyncMock(return_value=process),
                ),
                patch.object(tab, "run_worker", side_effect=close_reader),
                patch.object(
                    tab, "_connect_remote", new=AsyncMock(return_value=False)
                ),
                patch.object(tab, "_discard_process", new=AsyncMock()) as discard,
                patch.object(
                    tab, "_install_stop_hook", new=AsyncMock()
                ) as install_hook,
                patch.object(
                    tab, "refresh_dashboard", new=AsyncMock()
                ) as refresh,
            ):
                connected = await tab.start()

            self.assertFalse(connected)
            discard.assert_awaited_once_with(process)
            install_hook.assert_not_awaited()
            refresh.assert_not_awaited()

    async def test_probe_server_is_restarted_after_lldb_abort(self) -> None:
        app = ProbeTestApp()
        async with app.run_test():
            tab = app.query_one(ProbeTab)
            process = MagicMock()
            process.returncode = None
            process.terminate = MagicMock()
            process.wait = AsyncMock(return_value=0)
            tab._proc = process

            with (
                patch("etui.tabs.probe.asyncio.sleep", new=AsyncMock()),
                patch.object(tab, "start", new=AsyncMock()) as start,
            ):
                await tab.restart_for_lldb()

            process.terminate.assert_called_once_with()
            process.wait.assert_awaited_once_with()
            start.assert_awaited_once_with()
            self.assertIsNone(tab._proc)
