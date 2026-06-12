# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import sys
from pathlib import Path


from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, RichLog
from textual.widgets import Input
from textual.widgets import TabbedContent, TabPane
from textual.message import Message

if __package__:
    from .tabs.help import HelpTab, OpenDocFile
    from .tabs.about import AboutTab
    from .tabs.console import ConsoleTab
    from .tabs.files import FilesTab
    from .tabs.probe import ProbeTab, LldbStart
    from .tabs.lldb import LldbTab
    from .tabs.theme import ThemeTab, ThemeChanged
    from .tabs.serial import SerialTab
    from .tabs.venv import VenvTab
    from .tabs.git import GitTab, RepositoryChanged
    from .tabs.github import GitHubTab
    from .tabs.cmake import CMakeTab
    from .tabs.tools import ToolsTab
    from .tabs.settings import SettingsTab
    from .settings import SettingsManager
else:
    from tabs.help import HelpTab, OpenDocFile
    from tabs.about import AboutTab
    from tabs.console import ConsoleTab
    from tabs.files import FilesTab
    from tabs.probe import ProbeTab, LldbStart
    from tabs.lldb import LldbTab
    from tabs.theme import ThemeTab, ThemeChanged
    from tabs.serial import SerialTab
    from tabs.venv import VenvTab
    from tabs.git import GitTab, RepositoryChanged
    from tabs.github import GitHubTab
    from tabs.cmake import CMakeTab
    from tabs.tools import ToolsTab
    from tabs.settings import SettingsTab
    from settings import SettingsManager

class CommandMessage(Message):
    def __init__(self ,command: str) -> None:
        super().__init__()
        self.command = command

class EtuiApp(App):
    """ Embedded TUI App"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if __package__:
            from .tabs.tools import ToolRegistry
        else:
            from tabs.tools import ToolRegistry
        self.settings_manager = SettingsManager()
        self.tool_registry = ToolRegistry(self)
        self._last_active_tab = "files"
        self.workspace_root = self.load_workspace_root()


    CSS = """
        TabbedContent {
            height: 1fr;
        }

        Input {
            height: 3;
        }

        #main-input {
            display: none;
        }

        /* Push the Theme and About tabs to the far right of the tab bar. */
        #--content-tab-about {
            dock: right;
        }
        #--content-tab-theme {
            dock: right;
            margin-right: 7;
        }

        .control-bar {
            height: 3;
            align: left middle;
            padding: 0 1;
        }

        .control-label {
            margin-top: 1;
            margin-right: 1;
        }
        
        #serial-port {
            width: 40;
        }
        
        #serial-baud {
            width: 20;
        }

        #serial-connect {
            width: 15;
            margin-left: 1;
        }
    """

    def load_workspace_root(self) -> str | None:
        return self.settings_manager.get("workspace", "root") or None

    def save_workspace_root(self, path: str) -> None:
        try:
            self.settings_manager.set("workspace", "root", path)
        except OSError:
            pass

    async def set_workspace_root(
        self, path: str, update_files: bool = True, persist: bool = True
    ) -> None:
        self.workspace_root = path
        if persist:
            self.save_workspace_root(path)
        
        # 1. Update Files tab
        if update_files:
            try:
                files_tab = self.query_one(FilesTab)
                files_tab.query_one("LeftWidget").path = Path(path)
                files_tab.query_one("#txt-workspace-root", Input).value = path
            except Exception:
                pass

        # 2. Update Console tab (cwd)
        try:
            console_tab = self.query_one(ConsoleTab)
            console_tab.cwd = Path(path)
        except Exception:
            pass

        # 3. Update Venv tab
        try:
            venv_tab = self.query_one(VenvTab)
            venv_tab.query_one("#venv-project-path", Input).value = path
            if (Path(path) / "pyproject.toml").is_file():
                venv_tab.start_project_selection()
        except Exception:
            pass

        # 4. Update Git tab
        try:
            git_tab = self.query_one(GitTab)
            if git_tab.repo_path is None or str(git_tab.repo_path) != str(Path(path).resolve()):
                git_tab.query_one("#txt-repo-path", Input).value = path
                git_tab.validate_and_load_repo(path)
        except Exception:
            pass

        # 5. Update GitHub tab
        try:
            github_tab = self.query_one(GitHubTab)
            self.run_worker(github_tab.change_repository(Path(path)))
        except Exception:
            pass

        # 6. Update CMake tab
        try:
            cmake_tab = self.query_one(CMakeTab)
            self.run_worker(cmake_tab.change_repository(Path(path)))
        except Exception:
            pass

    async def on_mount(self) -> None:
        probe_tab = self.query_one(ProbeTab)
        probe_tab.apply_settings(self.settings_manager.settings["probe"])
        wrap = bool(self.settings_manager.get("ui", "word_wrap", False))
        for log in self.query(RichLog):
            log.wrap = wrap
        await self.query_one(LldbTab).set_theme(
            self.settings_manager.get("lldb", "theme", "vibrant")
        )
        if (
            self.workspace_root
            and self.settings_manager.get("workspace", "auto_restore", True)
        ):
            await self.set_workspace_root(self.workspace_root, update_files=True)

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="files"):
            with TabPane("Files", id="files"):
                yield FilesTab()
            with TabPane("Console", id="console"):
                yield ConsoleTab()
            with TabPane("Tools", id="tools"):
                yield ToolsTab(
                    [
                        Path(path)
                        for path in self.settings_manager.get(
                            "tools", "custom_paths", []
                        )
                    ]
                )
            with TabPane("Git", id="git"):
                yield GitTab()
            with TabPane("GitHub", id="github"):
                yield GitHubTab()
            with TabPane("CMake", id="cmake"):
                yield CMakeTab()
            with TabPane("Serial", id="serial"):
                yield SerialTab()
            with TabPane("Probe", id="probe"):
                yield ProbeTab()
            with TabPane("LLDB", id="lldb"):
                yield LldbTab(settings=self.settings_manager.settings["lldb"])
            with TabPane("Venv", id="venv"):
                yield VenvTab()
            with TabPane("Settings", id="settings"):
                yield SettingsTab()
            with TabPane("Theme", id="theme"):
                yield ThemeTab(
                    self.settings_manager.get("lldb", "theme", "vibrant")
                )
            with TabPane("About", id="about"):
                yield AboutTab()
            with TabPane("Help", id="help"):
                yield HelpTab()
        yield Input(id="main-input")
        yield Footer()

    # dispatch commands based on the first character
    # if "/" it is a built-in command otherwise it is shell command  
    def on_input_submitted(self, event: Input.Submitted) -> None:
        #self.notify(f"on_input_submitted {event.value}")
        command = event.value.strip()
        if not command:
            return
        #self.notify(f"Posting command messafge {command}")
        self.post_message(CommandMessage(command))
        event.input.value=""

    async def on_lldb_start(self, message: LldbStart) -> None:
        # The LLDB tab is always present; (re)connect it to the gdb server.
        lldb = self.query_one(LldbTab)
        await lldb.connect(message.port, message.arch)
        self.query_one(TabbedContent).active = "lldb"

    def on_open_doc_file(self, message: OpenDocFile) -> None:
        self.query_one(TabbedContent).active = "files"
        self.query_one(FilesTab).open_file(message.path)

    async def on_theme_changed(self, message: ThemeChanged) -> None:
        try:
            self.settings_manager.set("lldb", "theme", message.theme)
        except OSError:
            pass
        await self.query_one(LldbTab).set_theme(message.theme)

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        # Focus the appropriate input/widget when tabs are switched
        pane_id = event.pane.id
        old_pane_id = getattr(self, "_last_active_tab", None)
        self._last_active_tab = pane_id
        
        # Show main-input only for serial tab, hide for all others
        try:
            self.query_one("#main-input").display = (pane_id == "serial")
        except Exception:
            pass

        # Update any tool warning banners in the active pane
        try:
            if __package__:
                from .tabs.tools import ToolWarningBanner
            else:
                from tabs.tools import ToolWarningBanner
            for banner in event.pane.query(ToolWarningBanner):
                banner.check_status()
        except Exception:
            pass

        if pane_id == "files":
            try:
                self.query_one("LeftWidget").focus()
            except Exception:
                pass
        elif pane_id == "console":
            try:
                self.query_one("#console-input").focus()
            except Exception:
                pass
        elif pane_id == "serial":
            try:
                self.query_one("#main-input").focus()
            except Exception:
                pass
        elif pane_id == "probe":
            try:
                self.query_one("#dbg-input").focus()
            except Exception:
                pass
        elif pane_id == "lldb":
            try:
                self.query_one("#lldb-input").focus()
            except Exception:
                pass
        elif pane_id == "git":
            try:
                self.query_one("#txt-repo-path").focus()
            except Exception:
                pass
        elif pane_id == "github":
            try:
                self.query_one("#btn-mode-issues").focus()
            except Exception:
                pass
        elif pane_id == "cmake":
            try:
                self.query_one("#txt-cmake-build").focus()
            except Exception:
                pass
        elif pane_id == "tools":
            try:
                self.query_one("#tools-table").focus()
            except Exception:
                pass
        elif pane_id == "venv":
            try:
                self.query_one("#venv-project-path").focus()
            except Exception:
                pass
        elif pane_id == "settings":
            try:
                self.query_one("#settings-categories").focus()
            except Exception:
                pass

        if old_pane_id == "venv" and pane_id != "venv":
            try:
                venv_tab = self.query_one(VenvTab)
                if venv_tab.is_busy:
                    self.run_worker(
                        venv_tab.cancel_active_operation(),
                        name="cancel-venv-operation",
                        exit_on_error=False,
                    )
            except Exception:
                pass

        if old_pane_id == "git" and pane_id != "git":
            try:
                git_tab = self.query_one(GitTab)
                if git_tab.busy:
                    self.run_worker(
                        git_tab.cancel_active_operation(),
                        name="cancel-git-operation",
                        exit_on_error=False,
                    )
            except Exception:
                pass

        if old_pane_id == "github" and pane_id != "github":
            try:
                github_tab = self.query_one(GitHubTab)
                if github_tab.busy:
                    self.run_worker(
                        github_tab.cancel_active_operation(),
                        name="cancel-github-operation",
                        exit_on_error=False,
                    )
            except Exception:
                pass

        if old_pane_id == "cmake" and pane_id != "cmake":
            try:
                cmake_tab = self.query_one(CMakeTab)
                if cmake_tab.busy:
                    self.run_worker(
                        cmake_tab.cancel_active_operation(),
                        name="cancel-cmake-operation",
                        exit_on_error=False,
                    )
            except Exception:
                pass

        if old_pane_id == "tools" and pane_id != "tools":
            try:
                tools_tab = self.query_one(ToolsTab)
                if tools_tab.busy:
                    self.run_worker(
                        tools_tab.cancel_active_operation(),
                        name="cancel-tools-operation",
                        exit_on_error=False,
                    )
            except Exception:
                pass

    def on_command_message(self, message: CommandMessage) -> None:
        tabs = self.query_one(TabbedContent)
        if tabs.active == "serial":
            serial = self.query_one(SerialTab)
            serial.send_data(message.command)
        else:
            tabs.active = "console"
            #self.notify(f"Got command message {message.command}")
            console = self.query_one(ConsoleTab)
            self.run_worker(console.run_command(message.command))

    async def on_repository_changed(self, message: RepositoryChanged) -> None:
        await self.set_workspace_root(message.path, update_files=True)

    

def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--etui-xonsh-command":
        from xonsh.main import main as xonsh_main

        xonsh_main(["--no-rc", "-c", sys.argv[2]])
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "--screenshots":
        _run_screenshots(Path(sys.argv[2]) if len(sys.argv) >= 3 else None)
        return

    print("Hello from etui!")
    app = EtuiApp()
    app.run()


def _run_screenshots(output_dir: Path | None) -> None:
    """Run the app, capture one screenshot per tab, print results, then exit."""
    if __package__:
        from .tabs.about import capture_screenshots, DEFAULT_SCREENSHOT_DIR
    else:
        from tabs.about import capture_screenshots, DEFAULT_SCREENSHOT_DIR

    dest = output_dir or DEFAULT_SCREENSHOT_DIR
    results: dict[str, object] = {}

    app = EtuiApp()

    async def _after_mount() -> None:
        saved, failed = await capture_screenshots(app, dest)
        results["saved"] = saved
        results["failed"] = failed
        app.exit()

    app.call_after_refresh(_after_mount)
    app.run()

    saved = results.get("saved", [])
    failed = results.get("failed", [])
    for tab_id in saved:
        print(f"  saved  {dest / (tab_id + '.svg')}")
    for entry in failed:
        print(f"  FAILED {entry}", file=sys.stderr)
    print(f"{len(saved)} screenshots written to {dest}")

if __name__ == "__main__":
    main()
