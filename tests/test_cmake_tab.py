# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import json
import tempfile
import asyncio
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from etui.tabs.cmake import CMakeTab
from textual.app import App, ComposeResult
from textual.widgets import Input, RichLog

class CMakeTestApp(App):
    def compose(self) -> ComposeResult:
        yield CMakeTab()

class CMakeTabUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_type_validation(self) -> None:
        tab = CMakeTab()
        self.assertIn("Debug", tab.BUILD_TYPES)
        self.assertNotIn("InvalidType", tab.BUILD_TYPES)

    async def test_parse_file_api_reply_empty(self) -> None:
        tab = CMakeTab()
        with tempfile.TemporaryDirectory() as tmpdir:
            reply_dir = Path(tmpdir)
            targets = await tab._parse_file_api_reply(reply_dir)
            self.assertEqual(len(targets), 0)

    async def test_parse_file_api_reply_single_config(self) -> None:
        tab = CMakeTab()
        with tempfile.TemporaryDirectory() as tmpdir:
            reply_dir = Path(tmpdir)
            
            # Write a mock index file
            index_data = {
                "cmake": {"generator": {"multiConfig": False}},
                "reply": {
                    "client-etui": {
                        "query.json": {
                            "responses": [
                                {"kind": "codemodel", "jsonFile": "codemodel.json"}
                            ]
                        }
                    }
                }
            }
            (reply_dir / "index-1.json").write_text(json.dumps(index_data))

            # Write a mock codemodel file
            codemodel_data = {
                "configurations": [
                    {
                        "name": "Debug",
                        "targets": [
                            {"name": "my_exe", "jsonFile": "target-my_exe.json"}
                        ]
                    }
                ]
            }
            (reply_dir / "codemodel.json").write_text(json.dumps(codemodel_data))

            # Write detailed target file
            target_detail = {"name": "my_exe", "type": "EXECUTABLE"}
            (reply_dir / "target-my_exe.json").write_text(json.dumps(target_detail))

            targets = await tab._parse_file_api_reply(reply_dir)
            self.assertEqual(targets, [("my_exe", "EXECUTABLE")])
            self.assertFalse(tab.is_multi_config)

    async def test_parse_file_api_reply_multi_config(self) -> None:
        tab = CMakeTab()
        tab.selected_build_type = "Release"
        with tempfile.TemporaryDirectory() as tmpdir:
            reply_dir = Path(tmpdir)
            
            # Write a mock index file
            index_data = {
                "cmake": {"generator": {"multiConfig": True}},
                "reply": {
                    "client-etui": {
                        "query.json": {
                            "responses": [
                                {"kind": "codemodel", "jsonFile": "codemodel.json"}
                            ]
                        }
                    }
                }
            }
            (reply_dir / "index-1.json").write_text(json.dumps(index_data))

            # Write a mock codemodel file with multiple configurations
            codemodel_data = {
                "configurations": [
                    {
                        "name": "Debug",
                        "targets": [
                            {"name": "debug_exe", "jsonFile": "target-debug_exe.json"}
                        ]
                    },
                    {
                        "name": "Release",
                        "targets": [
                            {"name": "release_exe", "jsonFile": "target-release_exe.json"}
                        ]
                    }
                ]
            }
            (reply_dir / "codemodel.json").write_text(json.dumps(codemodel_data))

            # Write detailed target files
            (reply_dir / "target-debug_exe.json").write_text(json.dumps({"type": "EXECUTABLE"}))
            (reply_dir / "target-release_exe.json").write_text(json.dumps({"type": "STATIC_LIBRARY"}))

            targets = await tab._parse_file_api_reply(reply_dir)
            self.assertEqual(targets, [("release_exe", "STATIC_LIBRARY")])
            self.assertTrue(tab.is_multi_config)

    async def test_path_containment_validation(self) -> None:
        app = CMakeTestApp()
        async with app.run_test() as pilot:
            tab = app.query_one(CMakeTab)
            tab.repo_path = Path("/workspace/myrepo")
            tab.build_path = Path("/workspace/myrepo/build")
            tab.known_targets = {"all"}
            tab.busy = False
            
            # Attempt to use path traversal to escape repository
            tab.query_one("#txt-cmake-build", Input).value = "../escaped_build"
            tab.query_one("#txt-cmake-type", Input).value = "Debug"
            
            # Enable controls so the button is clickable
            tab._set_controls_enabled(True)
            
            # Trigger build
            btn = tab.query_one("#btn-cmake-build")
            await pilot.click("#btn-cmake-build")
            
            # Verify build path was not changed to the invalid one and build is not busy
            self.assertNotEqual(tab.build_path, Path("/workspace/escaped_build").resolve())
            log_content = "\n".join(line.text for line in tab.query_one(RichLog).lines)
            self.assertIn("Error: Build directory must reside strictly inside the repository root", log_content)

if __name__ == "__main__":
    unittest.main()
