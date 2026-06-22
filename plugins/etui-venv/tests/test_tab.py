import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from packaging.requirements import InvalidRequirement
from textual.app import App, ComposeResult

from etui.tabs.venv import VenvTab


class VenvTestApp(App):
    def compose(self) -> ComposeResult:
        yield VenvTab()


class VenvTabCommandTests(unittest.TestCase):
    def test_build_command_places_project_option_after_subcommand(self) -> None:
        command = VenvTab.build_pdm_command(
            "/usr/bin/pdm",
            "list",
            Path("/tmp/project"),
        )

        self.assertEqual(
            command,
            [
                "/usr/bin/pdm",
                "--non-interactive",
                "list",
                "--project",
                "/tmp/project",
            ],
        )

    def test_build_package_command_uses_option_separator(self) -> None:
        command = VenvTab.build_pdm_command(
            "pdm",
            "add",
            Path("/tmp/project"),
            "requests>=2",
        )

        self.assertEqual(command[-2:], ["--", "requests>=2"])

    def test_validate_install_requirement(self) -> None:
        self.assertEqual(
            VenvTab.validate_package_spec("requests>=2"),
            "requests>=2",
        )

    def test_validate_remove_requirement_returns_name(self) -> None:
        self.assertEqual(
            VenvTab.validate_package_spec("Requests[security]>=2", remove=True),
            "Requests",
        )

    def test_validate_requirement_rejects_options(self) -> None:
        with self.assertRaises(InvalidRequirement):
            VenvTab.validate_package_spec("--group dev")


class VenvTabWidgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_select_project_validates_and_loads_packages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_path = Path(directory).resolve()
            (project_path / "pyproject.toml").write_text("[project]\nname='sample'\n")
            project_info = {
                "python": {
                    "interpreter": str(project_path / "venv/bin/python"),
                    "version": "3.13",
                },
                "project": {"root": str(project_path)},
            }
            package_list = [{"name": "requests", "version": "2.32.0"}]

            app = VenvTestApp()
            async with app.run_test():
                tab = app.query_one(VenvTab)
                tab._pdm_path = "pdm"
                tab._capture_command = AsyncMock(
                    side_effect=[
                        (0, json.dumps(project_info), ""),
                        (0, json.dumps(package_list), ""),
                    ]
                )
                tab.query_one("#venv-project-path").value = str(project_path)

                await tab._select_project()

                self.assertEqual(tab.project_path, project_path)
                self.assertEqual(
                    tab.query_one("#venv-package-table").row_count,
                    1,
                )
                self.assertFalse(tab.query_one("#venv-add").disabled)

    async def test_invalid_project_clears_previous_selection(self) -> None:
        app = VenvTestApp()
        async with app.run_test():
            tab = app.query_one(VenvTab)
            tab._pdm_path = "pdm"
            tab.project_path = Path("/tmp/previous")
            tab._set_mutation_enabled(True)
            tab.query_one("#venv-project-path").value = "/does/not/exist"

            await tab._select_project()

            self.assertIsNone(tab.project_path)
            self.assertTrue(tab.query_one("#venv-add").disabled)


if __name__ == "__main__":
    unittest.main()
