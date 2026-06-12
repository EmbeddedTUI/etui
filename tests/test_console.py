import os
import sys
import unittest
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Input

from etui.tabs.console import ConsoleTab, LogWidget


class ConsoleTestApp(App):
    def __init__(self) -> None:
        super().__init__()
        self.bubbled_submissions = 0

    def compose(self) -> ComposeResult:
        yield ConsoleTab()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.bubbled_submissions += 1


class ConsoleCommandTests(unittest.TestCase):
    def test_source_command_runner_uses_etui_module(self) -> None:
        command = ConsoleTab.command_runner("ls")

        self.assertEqual(
            command,
            [
                sys.executable,
                "-m",
                "etui",
                "--etui-xonsh-command",
                "ls",
            ],
        )

    def test_command_environment_defaults_to_dummy_history(self) -> None:
        old_value = os.environ.pop("XONSH_HISTORY_BACKEND", None)
        try:
            environment = ConsoleTab.command_environment()
        finally:
            if old_value is not None:
                os.environ["XONSH_HISTORY_BACKEND"] = old_value

        self.assertEqual(environment["XONSH_HISTORY_BACKEND"], "dummy")

    def test_console_starts_in_process_working_directory(self) -> None:
        self.assertEqual(ConsoleTab().cwd, Path.cwd())


class ConsoleWidgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_is_single_line_and_does_not_bubble(self) -> None:
        app = ConsoleTestApp()
        async with app.run_test() as pilot:
            console_input = app.query_one("#console-input", Input)
            log = app.query_one(LogWidget)
            console_input.focus()

            await pilot.press("e", "c", "h", "o", "space", "o", "k", "enter")
            for _ in range(100):
                if not app.query_one(ConsoleTab)._command_lock.locked():
                    break
                await pilot.pause()

            text = "\n".join(line.text for line in log.lines)
            self.assertEqual(app.bubbled_submissions, 0)
            self.assertEqual(console_input.size.height, 1)
            self.assertFalse(log.show_horizontal_scrollbar)
            self.assertNotIn("Traceback", text)
            self.assertEqual(text.count("xonsh> echo ok"), 1)

    async def test_console_history_navigation(self) -> None:
        app = ConsoleTestApp()
        async with app.run_test() as pilot:
            console_input = app.query_one("#console-input")
            console_input.focus()

            # Submit first command
            await pilot.press("e", "c", "h", "o", "space", "1", "enter")
            for _ in range(100):
                if not app.query_one(ConsoleTab)._command_lock.locked():
                    break
                await pilot.pause()

            # Submit second command
            await pilot.press("e", "c", "h", "o", "space", "2", "enter")
            for _ in range(100):
                if not app.query_one(ConsoleTab)._command_lock.locked():
                    break
                await pilot.pause()

            # Type something but do not submit
            await pilot.press("t", "e", "m", "p")
            self.assertEqual(console_input.value, "temp")

            # Press Up arrow: should show the last submitted command ("echo 2")
            await pilot.press("up")
            self.assertEqual(console_input.value, "echo 2")

            # Press Up arrow again: should show the first submitted command ("echo 1")
            await pilot.press("up")
            self.assertEqual(console_input.value, "echo 1")

            # Press Up arrow again: should stay at "echo 1" (first command)
            await pilot.press("up")
            self.assertEqual(console_input.value, "echo 1")

            # Press Down arrow: should go back to "echo 2"
            await pilot.press("down")
            self.assertEqual(console_input.value, "echo 2")

            # Press Down arrow again: should restore the typed text ("temp")
            await pilot.press("down")
            self.assertEqual(console_input.value, "temp")


if __name__ == "__main__":
    unittest.main()
