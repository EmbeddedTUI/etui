# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC


from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.widgets import Placeholder
from textual.widgets import Footer, Header
from textual.widgets import Input
from textual.widgets import TabbedContent, TabPane

if __package__:
    from .tabs.about import AboutTab
    from .tabs.console import ConsoleTab, CommandMessage
    from .tabs.files import FilesTab
else:
    from tabs.about import AboutTab
    from tabs.console import ConsoleTab, CommandMessage
    from tabs.files import FilesTab

class EtuiApp(App):
    """ Embedded TUI App"""

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="about"):
            with TabPane("Console", id="console"):
                yield ConsoleTab()
            with TabPane("Files", id="files"):
                yield FilesTab()
            with TabPane("About", id="about"):
                yield AboutTab()
        yield Input()
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

    def on_command_message(self, message: CommandMessage) -> None:
        #self.notify(f"Got command message {message.command}")
        console = self.query_one(ConsoleTab)
        self.run_worker(console.run_commmand(message))

    

def main():
    print("Hello from etui!")
    app = EtuiApp()
    app.run()

if __name__ == "__main__":
    main()
