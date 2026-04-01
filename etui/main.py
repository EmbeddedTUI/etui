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
    from .tabs.files import FilesTab
else:
    from tabs.about import AboutTab
    from tabs.files import FilesTab

class EtuiApp(App):
    """ Embedded TUI App"""

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="about"):
            with TabPane("Files", id="files"):
                yield FilesTab()
            with TabPane("About", id="about"):
                yield AboutTab()
        yield Input()
        yield Footer()

def main():
    print("Hello from etui!")
    app = EtuiApp()
    app.run()

if __name__ == "__main__":
    main()
