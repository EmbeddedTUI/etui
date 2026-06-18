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
