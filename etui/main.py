# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import sys
from pathlib import Path


from textual.app import App, ComposeResult
from textual.widgets import Footer, Header
from textual.widgets import Input
from textual.widgets import TabbedContent, TabPane
from textual.message import Message

if __package__:
    from .tabs.about import AboutTab
    from .tabs.console import ConsoleTab
    from .tabs.files import FilesTab
    from .tabs.debugger import DebuggerTab, LldbStart
    from .tabs.lldb import LldbTab
    from .tabs.theme import ThemeTab, ThemeChanged
    from .tabs.serial import SerialTab
    from .tabs.venv import VenvTab
    from .tabs.git import GitTab, RepositoryChanged
    from .tabs.github import GitHubTab
    from .tabs.cmake import CMakeTab
    from .tabs.tools import ToolsTab
else:
    from tabs.about import AboutTab
    from tabs.console import ConsoleTab
    from tabs.files import FilesTab
    from tabs.debugger import DebuggerTab, LldbStart
    from tabs.lldb import LldbTab
    from tabs.theme import ThemeTab, ThemeChanged
    from tabs.serial import SerialTab
    from tabs.venv import VenvTab
    from tabs.git import GitTab, RepositoryChanged
    from tabs.github import GitHubTab
    from tabs.cmake import CMakeTab
    from tabs.tools import ToolsTab

class CommandMessage(Message):
    def __init__(self ,command: str) -> None:
        super().__init__()
        self.command = command

class EtuiApp(App):
    """ Embedded TUI App"""

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

        /* Push the About tab (last one) to the far right of the tab bar. */
        #--content-tab-about {
            dock: right;
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

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="files"):
            with TabPane("Files", id="files"):
                yield FilesTab()
            with TabPane("Console", id="console"):
                yield ConsoleTab()
            with TabPane("Serial", id="serial"):
                yield SerialTab()
            with TabPane("Debugger", id="debugger"):
                yield DebuggerTab()
            with TabPane("LLDB", id="lldb"):
                yield LldbTab()
            with TabPane("Theme", id="theme"):
                yield ThemeTab()
            with TabPane("Git", id="git"):
                yield GitTab()
            with TabPane("GitHub", id="github"):
                yield GitHubTab()
            with TabPane("CMake", id="cmake"):
                yield CMakeTab()
            with TabPane("Tools", id="tools"):
                yield ToolsTab()
            with TabPane("Venv", id="venv"):
                yield VenvTab()
            with TabPane("About", id="about"):
                yield AboutTab()
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

    async def on_theme_changed(self, message: ThemeChanged) -> None:
        await self.query_one(LldbTab).set_theme(message.theme)

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        # Focus the appropriate input/widget when tabs are switched
        pane_id = event.pane.id
        
        # Show main-input only for serial tab, hide for all others
        try:
            self.query_one("#main-input").display = (pane_id == "serial")
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
        elif pane_id == "debugger":
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

        if pane_id != "venv":
            venv_tab = self.query_one(VenvTab)
            if venv_tab.is_busy:
                self.run_worker(
                    venv_tab.cancel_active_operation(),
                    name="cancel-venv-operation",
                    exit_on_error=False,
                )

        if pane_id != "git":
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

        if pane_id != "github":
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

        if pane_id != "cmake":
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

        if pane_id != "tools":
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
        # Update FilesTab path
        try:
            files_tab = self.query_one(FilesTab)
            files_tab.query_one("LeftWidget").path = Path(message.path)
        except Exception:
            pass

        # Update VenvTab path and select it if it has a pyproject.toml
        try:
            venv_tab = self.query_one(VenvTab)
            venv_tab.query_one("#venv-project-path", Input).value = message.path
            if (Path(message.path) / "pyproject.toml").is_file():
                self.run_worker(venv_tab._select_project())
        except Exception:
            pass

        # Update GitHubTab repo
        try:
            github_tab = self.query_one(GitHubTab)
            self.run_worker(github_tab.change_repository(Path(message.path)))
        except Exception:
            pass

        # Update CMakeTab repo
        try:
            cmake_tab = self.query_one(CMakeTab)
            self.run_worker(cmake_tab.change_repository(Path(message.path)))
        except Exception:
            pass

    

def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--etui-xonsh-command":
        from xonsh.main import main as xonsh_main

        xonsh_main(["--no-rc", "-c", sys.argv[2]])
        return

    print("Hello from etui!")
    app = EtuiApp()
    app.run()

if __name__ == "__main__":
    main()
