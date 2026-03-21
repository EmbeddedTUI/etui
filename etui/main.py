# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC


from textual.app import App, ComposeResult
from textual.widgets import Footer, Header
from textual.widgets import DirectoryTree

class EtuiApp(App):
    """ Embedded TUI App"""

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield DirectoryTree("./")
        yield Footer()

def main():
    print("Hello from etui!")
    app = EtuiApp()
    app.run()

if __name__ == "__main__":
    main()
