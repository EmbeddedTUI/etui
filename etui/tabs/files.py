# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical, ScrollableContainer
from textual.widgets import DirectoryTree
from textual.widgets import Static
from rich.syntax import Syntax

class LeftWidget(DirectoryTree):
    def __init__(self):
        super().__init__("./")

class FileViewer(ScrollableContainer):
    def compose(self) -> ComposeResult:
        yield Static(id="file-content", expand=True)

class FilesTab(Horizontal):
    """ Files tab"""

    DEFAULT_CSS = """
    FilesTab LeftWidget {
        width: 30%;
        border-right: solid $accent;
    }
    FilesTab FileViewer {
        width: 70%;
    }
    FilesTab #file-content {
        width: auto;
    }
    """

    def compose(self) -> ComposeResult:
        yield LeftWidget()
        yield FileViewer()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Called when the user selects a file in the directory tree."""
        event.stop()
        viewer = self.query_one("#file-content", Static)
        try:
            # Use Syntax.from_path to read and highlight the file
            syntax = Syntax.from_path(
                str(event.path),
                line_numbers=True,
                word_wrap=False,
                indent_guides=True,
                theme="monokai"
            )
            viewer.update(syntax)
        except Exception as e:
            viewer.update(f"[red]Error loading file: {e}[/red]")
