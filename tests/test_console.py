import os
import unittest
from pathlib import Path

from textual.app import App, ComposeResult

from etui.tabs.console import ConsoleTab, TerminalWidget


class ConsoleTestApp(App):
    def compose(self) -> ComposeResult:
        yield ConsoleTab()


class ConsoleBasicTests(unittest.TestCase):
    def test_console_starts_in_process_working_directory(self) -> None:
        self.assertEqual(ConsoleTab().cwd, Path.cwd())

    def test_marker_detected_through_interleaved_escapes(self) -> None:
        """A completion marker must resolve even when escape sequences from the
        shell/sudo/apt interleave between the marker and its exit code."""
        import asyncio

        term = TerminalWidget()
        event = asyncio.Event()
        cmd = {"marker": b"__ETUI_CMD_DONE_1__", "event": event, "exit_code": -1}
        term._pending_commands.append(cmd)
        # Color reset + OSC title sequences land between the marker and "0".
        term._read_buffer.extend(
            b"0 upgraded.\r\n__ETUI_CMD_DONE_1__\x1b[0m \x1b]0;title\x07 0\r\n$ "
        )
        term._check_command_markers()
        self.assertTrue(event.is_set())
        self.assertEqual(cmd["exit_code"], 0)
        self.assertEqual(len(term._pending_commands), 0)

    def test_echoed_input_marker_does_not_false_match(self) -> None:
        """The echoed `__ETUI_CMD_DONE_""1__` input must not resolve the command."""
        import asyncio

        term = TerminalWidget()
        event = asyncio.Event()
        cmd = {"marker": b"__ETUI_CMD_DONE_1__", "event": event, "exit_code": -1}
        term._pending_commands.append(cmd)
        term._read_buffer.extend(b'sleep 1; echo __ETUI_CMD_DONE_""1__ $?\r\n')
        term._check_command_markers()
        self.assertFalse(event.is_set())
        self.assertEqual(len(term._pending_commands), 1)


@unittest.skipUnless(os.name == "posix", "terminal requires a POSIX PTY")
class ConsoleTerminalTests(unittest.IsolatedAsyncioTestCase):
    async def _wait_for(self, pilot, term: TerminalWidget, needle: str, tries: int = 100) -> bool:
        for _ in range(tries):
            await pilot.pause(0.05)
            if any(needle in row for row in term.pyte_screen.display):
                return True
        return False

    async def test_run_command_outputs_to_terminal(self) -> None:
        app = ConsoleTestApp()
        async with app.run_test() as pilot:
            term = app.query_one(TerminalWidget)
            await pilot.pause(0.2)  # let the shell start
            await app.query_one(ConsoleTab).run_command("echo hello_console_42")
            found = await self._wait_for(pilot, term, "hello_console_42")
            self.assertTrue(found, term.pyte_screen.display)

    async def test_keys_are_forwarded_to_shell(self) -> None:
        app = ConsoleTestApp()
        async with app.run_test() as pilot:
            term = app.query_one(TerminalWidget)
            term.focus()
            await pilot.pause(0.2)
            for ch in "echo KEYS_WORK":
                await pilot.press("space" if ch == " " else ch)
            await pilot.press("enter")
            found = await self._wait_for(pilot, term, "KEYS_WORK")
            self.assertTrue(found, term.pyte_screen.display)

    async def test_terminal_cleans_up_on_unmount(self) -> None:
        app = ConsoleTestApp()
        async with app.run_test() as pilot:
            term = app.query_one(TerminalWidget)
            await pilot.pause(0.2)
            self.assertIsNotNone(term._fd)
        self.assertIsNone(term._fd)
        self.assertIsNone(term._pid)


if __name__ == "__main__":
    unittest.main()
