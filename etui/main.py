# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC


from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.widgets import Placeholder
from textual.widgets import Footer, Header
from textual.widgets import DirectoryTree
from textual.widgets import Input
from textual.widgets import RichLog

class LeftWidget1(Placeholder):
    def __init__(self):
        super().__init__()

class LeftWidget(DirectoryTree):
    def __init__(self):
        super().__init__("./")

class RightWidget1(Placeholder):
    def __init__(self):
        super().__init__()

class RightWidget(RichLog):
    def __init__(self):
        super().__init__(highlight=True, markup=True)
        self.write("Log enabled")

class EtuiApp(App):
    """ Embedded TUI App"""

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical():
                yield LeftWidget()
            with Vertical():
                yield RightWidget()
        yield Input()
        yield Footer()

def main():
    print("Hello from etui!")
    app = EtuiApp()
    app.run()

if __name__ == "__main__":
    main()
