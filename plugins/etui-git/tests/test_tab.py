# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import RichLog, Tree
from textual.worker import WorkerCancelled

from etui.bus import MessageBus
from etui.bus_contract import TOPIC_REPO_CHANGED, RepoChanged
from etui_git.tab import GitChange, GitTab


class GitTestApp(App):
    def __init__(self) -> None:
        super().__init__()
        self.bus = MessageBus()
        self.repository_events: list[str] = []
        self.bus.subscribe(TOPIC_REPO_CHANGED, self._on_repo_changed)
        # Provide dummy workspace get_root to satisfy mount query
        self.bus.provide("workspace.get_root", lambda: "")

    def compose(self) -> ComposeResult:
        yield GitTab()

    def _on_repo_changed(self, event) -> None:
        payload = event.payload
        if isinstance(payload, RepoChanged):
            self.repository_events.append(payload.path)


def run_git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        text=True,
        capture_output=True,
    )


def create_repository(root: Path) -> None:
    run_git(root.parent, "init", "-q", str(root))
    run_git(root, "config", "user.email", "test@example.com")
    run_git(root, "config", "user.name", "Test User")
    (root / "tracked file.txt").write_text("base\n", encoding="utf-8")
    run_git(root, "add", "--", "tracked file.txt")
    run_git(root, "commit", "-qm", "initial")


class GitTabParserTests(unittest.TestCase):
    def test_parse_porcelain_v2_untracked_path_with_spaces(self) -> None:
        staged, unstaged = GitTab._parse_porcelain_v2(
            b"? directory/file with spaces.txt\x00"
        )
        self.assertEqual(staged, [])
        self.assertEqual(
            unstaged,
            [GitChange("directory/file with spaces.txt", "?", False)],
        )

    def test_parse_porcelain_v2_modified(self) -> None:
        raw = (
            b"1 M. N... 100644 100644 100644 "
            b"1234567890abcdef1234567890abcdef12345678 "
            b"1234567890abcdef1234567890abcdef12345678 "
            b"file staged.txt\x00"
        )
        staged, unstaged = GitTab._parse_porcelain_v2(raw)
        self.assertEqual(staged, [GitChange("file staged.txt", "M", True)])
        self.assertEqual(unstaged, [])

    def test_parse_porcelain_v2_rename(self) -> None:
        raw = (
            b"2 R. N... 100644 100644 100644 "
            b"1234567890abcdef1234567890abcdef12345678 "
            b"1234567890abcdef1234567890abcdef12345678 "
            b"R100 new path.txt\x00old path.txt\x00"
        )
        staged, unstaged = GitTab._parse_porcelain_v2(raw)
        self.assertEqual(staged, [GitChange("new path.txt", "R", True)])
        self.assertEqual(unstaged, [])

    def test_parse_porcelain_v2_unmerged(self) -> None:
        raw = (
            b"u UU N... 100644 100644 100644 100644 "
            b"1234567890abcdef1234567890abcdef12345678 "
            b"1234567890abcdef1234567890abcdef12345678 "
            b"1234567890abcdef1234567890abcdef12345678 "
            b"conflicted file.txt\x00"
        )
        staged, unstaged = GitTab._parse_porcelain_v2(raw)
        self.assertEqual(staged, [GitChange("conflicted file.txt", "U", True)])
        self.assertEqual(
            unstaged,
            [GitChange("conflicted file.txt", "U", False)],
        )

    def test_parse_porcelain_v2_rejects_malformed_record(self) -> None:
        with self.assertRaises(ValueError):
            GitTab._parse_porcelain_v2(b"1 M. incomplete\x00")


class GitTabWidgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_repository_load_completes_and_posts_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repo"
            create_repository(repository)
            (repository / "tracked file.txt").write_text(
                "changed\n",
                encoding="utf-8",
            )

            app = GitTestApp()
            async with app.run_test() as pilot:
                tab = app.query_one(GitTab)
                worker = tab.validate_and_load_repo(str(repository))
                self.assertIsNotNone(worker)
                await worker.wait()
                await pilot.pause()

                self.assertFalse(tab.busy)
                self.assertEqual(tab.repo_path, repository.resolve())
                self.assertEqual(
                    app.repository_events,
                    [str(repository.resolve())],
                )
                tree = app.query_one("#git-changes-tree", Tree)
                self.assertEqual(len(tree.root.children[1].children), 1)

    async def test_stage_and_unstage_path_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repo"
            create_repository(repository)
            (repository / "tracked file.txt").write_text(
                "changed\n",
                encoding="utf-8",
            )

            app = GitTestApp()
            async with app.run_test():
                tab = app.query_one(GitTab)
                worker = tab.validate_and_load_repo(str(repository))
                assert worker is not None
                await worker.wait()

                worker = tab.toggle_stage_file("tracked file.txt", False)
                assert worker is not None
                await worker.wait()
                self.assertIn(
                    "tracked file.txt",
                    run_git(repository, "diff", "--cached", "--name-only").stdout,
                )

                worker = tab.toggle_stage_file("tracked file.txt", True)
                assert worker is not None
                await worker.wait()
                self.assertEqual(
                    run_git(repository, "diff", "--cached", "--name-only").stdout,
                    "",
                )

    async def test_large_diff_is_truncated_and_external_markup_is_literal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repo"
            create_repository(repository)
            (repository / "tracked file.txt").write_text(
                "[bold red]external[/bold red]\n" * 9000,
                encoding="utf-8",
            )

            app = GitTestApp()
            async with app.run_test():
                tab = app.query_one(GitTab)
                worker = tab.validate_and_load_repo(str(repository))
                assert worker is not None
                await worker.wait()

                worker = tab.show_file_diff("tracked file.txt", False)
                assert worker is not None
                await worker.wait()
                log = app.query_one("#git-diff-viewer", RichLog)

                self.assertFalse(log.markup)
                rendered = "\n".join(line.text for line in log.lines)
                self.assertIn("too large", rendered)

    async def test_cancel_waits_for_worker_and_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repo"
            create_repository(repository)
            run_git(repository, "config", "alias.pause", "!sleep 30")

            app = GitTestApp()
            async with app.run_test() as pilot:
                tab = app.query_one(GitTab)
                worker = tab.validate_and_load_repo(str(repository))
                assert worker is not None
                await worker.wait()

                worker = tab.run_git_command(["pause"])
                assert worker is not None
                await pilot.pause(0.1)
                await tab.cancel_active_operation()

                with self.assertRaises(WorkerCancelled):
                    await worker.wait()
                self.assertFalse(tab.busy)
                self.assertIsNone(tab._active_subprocess)
                self.assertIsNone(tab._operation_worker)


if __name__ == "__main__":
    unittest.main()
