# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import unittest
import tempfile
import shutil
from pathlib import Path
from textual.widgets import Input

from etui.main import EtuiApp
from etui.tabs.files import FilesTab
from etui.tabs.console import ConsoleTab
from etui.tabs.venv import VenvTab
from etui.tabs.git import GitTab
from etui.tabs.cmake import CMakeTab
from etui.tabs.github import GitHubTab

class WorkspaceRootTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.workspace_root = self.tmp_dir / "my_project"
        self.workspace_root.mkdir()
        # Create a git repo there to satisfy git/cmake validation
        (self.workspace_root / ".git").mkdir()
        # Create a pyproject.toml
        (self.workspace_root / "pyproject.toml").write_text("[project]\nname = \"test\"\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir)

    async def test_set_workspace_root_propagates_to_tabs(self) -> None:
        app = EtuiApp()
        async with app.run_test() as pilot:
            # Set workspace root
            await app.set_workspace_root(str(self.workspace_root))

            # Check files tab tree path & input value
            files_tab = app.query_one(FilesTab)
            self.assertEqual(str(files_tab.query_one("LeftWidget").path), str(self.workspace_root))
            self.assertEqual(files_tab.query_one("#txt-workspace-root", Input).value, str(self.workspace_root))

            # Check console tab cwd
            console_tab = app.query_one(ConsoleTab)
            self.assertEqual(str(console_tab.cwd), str(self.workspace_root))

            # Check venv tab path
            venv_tab = app.query_one(VenvTab)
            self.assertEqual(venv_tab.query_one("#venv-project-path", Input).value, str(self.workspace_root))

            # Check git tab path
            git_tab = app.query_one(GitTab)
            self.assertEqual(git_tab.query_one("#txt-repo-path", Input).value, str(self.workspace_root))

    async def test_empty_input_falls_back_to_tree_path(self) -> None:
        app = EtuiApp()
        async with app.run_test() as pilot:
            files_tab = app.query_one(FilesTab)
            # Empty out the input field
            files_tab.query_one("#txt-workspace-root", Input).value = ""
            
            # Click "Set Root" button
            await pilot.click("#btn-set-workspace-root")
            
            # Since input was empty, it should have fallen back to the LeftWidget (DirectoryTree)'s path (which defaults to "./" resolved)
            expected_path = str(Path("./").resolve())
            self.assertEqual(files_tab.query_one("#txt-workspace-root", Input).value, expected_path)
            self.assertEqual(str(app.workspace_root), expected_path)

if __name__ == "__main__":
    unittest.main()
