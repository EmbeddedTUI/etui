# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC


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
else:
    from tabs.about import AboutTab
    from tabs.console import ConsoleTab
    from tabs.files import FilesTab
    from tabs.debugger import DebuggerTab, LldbStart
    from tabs.lldb import LldbTab
    from tabs.theme import ThemeTab, ThemeChanged
    from tabs.serial import SerialTab

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
            height: 3
        }

        /* Push the About tab (last one) to the far right of the tab bar. */
        Tabs Tab:last-of-type {
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
        if pane_id == "files":
            try:
                self.query_one("LeftWidget").focus()
            except Exception:
                pass
        elif pane_id in ("console", "serial"):
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

    

def main():
    print("Hello from etui!")
    app = EtuiApp()
    app.run()

if __name__ == "__main__":
    main()
