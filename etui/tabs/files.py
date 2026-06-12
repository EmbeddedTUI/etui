# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import os
import datetime
import mimetypes
from pathlib import Path
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical, ScrollableContainer
from textual.widgets import DirectoryTree, Button, Input, Label
from textual.widgets import Static
from rich.syntax import Syntax

class LeftWidget(DirectoryTree):
    def __init__(self):
        super().__init__("./")

class FileViewer(Vertical):
    def compose(self) -> ComposeResult:
        with Horizontal(id="viewer-controls"):
            yield Button("Content", id="btn-content", variant="primary")
            yield Button("Details", id="btn-details")
        with ScrollableContainer():
            yield Static(id="file-display", expand=True)

class FilesTab(Vertical):
    """ Files tab"""

    DEFAULT_CSS = """
    FilesTab #files-workspace-bar {
        height: 3;
        align: left middle;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $accent;
    }
    FilesTab #files-workspace-bar Label {
        margin-top: 1;
        margin-right: 1;
    }
    FilesTab #files-workspace-bar Input {
        width: 60;
    }
    FilesTab #files-workspace-bar Button {
        margin-left: 1;
        min-width: 12;
    }
    FilesTab #files-body {
        height: 1fr;
    }
    FilesTab LeftWidget {
        width: 30%;
        border-right: solid $accent;
    }
    FilesTab FileViewer {
        width: 70%;
    }
    FilesTab #viewer-controls {
        height: 3;
        align: left middle;
        padding: 0 1;
        background: $surface;
    }
    FilesTab #viewer-controls Button {
        margin-right: 1;
        min-width: 12;
    }
    FilesTab #file-display {
        width: auto;
    }
    """

    def __init__(self):
        super().__init__()
        self.current_path = None
        self.view_mode = "content"

    def compose(self) -> ComposeResult:
        with Horizontal(id="files-workspace-bar"):
            yield Label("Workspace Root:")
            yield Input(placeholder="Path to workspace root...", id="txt-workspace-root")
            yield Button("Set Root", id="btn-set-workspace-root")
        with Horizontal(id="files-body"):
            yield LeftWidget()
            yield FileViewer()

    def on_mount(self) -> None:
        if hasattr(self.app, "workspace_root") and self.app.workspace_root:
            self.query_one("LeftWidget").path = Path(self.app.workspace_root)
            self.query_one("#txt-workspace-root", Input).value = self.app.workspace_root

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        event.stop()
        self.query_one("#txt-workspace-root", Input).value = str(event.path)

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Called when the user selects a file in the directory tree."""
        event.stop()
        self.current_path = event.path
        self.render_file()
        self.query_one("#txt-workspace-root", Input).value = str(event.path.parent)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-content":
            self.view_mode = "content"
            self.render_file()
        elif event.button.id == "btn-details":
            self.view_mode = "details"
            self.render_file()
        elif event.button.id == "btn-set-workspace-root":
            await self._action_set_workspace_root()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "txt-workspace-root":
            await self._action_set_workspace_root()

    async def _action_set_workspace_root(self) -> None:
        path_input = self.query_one("#txt-workspace-root", Input)
        path_str = path_input.value.strip()
        if not path_str:
            try:
                tree = self.query_one("LeftWidget")
                path_str = str(tree.path)
                path_input.value = path_str
            except Exception:
                return
        
        path = Path(path_str).expanduser().resolve()
        if not path.is_dir():
            self.notify(f"Path '{path_str}' is not a valid directory.", severity="error")
            return
        
        if hasattr(self.app, "set_workspace_root"):
            await self.app.set_workspace_root(str(path))
            self.notify(f"Workspace root set to {path}")

    def open_file(self, path: Path) -> None:
        """Display *path* in the viewer without changing the directory tree root."""
        self.current_path = path
        self.view_mode = "content"
        self.render_file()

    def render_file(self) -> None:
        if not self.current_path:
            return

        display = self.query_one("#file-display", Static)
        btn_content = self.query_one("#btn-content", Button)
        btn_details = self.query_one("#btn-details", Button)

        # Update button visual state
        btn_content.variant = "primary" if self.view_mode == "content" else "default"
        btn_details.variant = "primary" if self.view_mode == "details" else "default"

        if self.view_mode == "details":
            display.update(self.get_file_details(self.current_path))
        else:
            try:
                # Check file size to prevent freezing on large files
                try:
                    file_size = os.path.getsize(self.current_path)
                except Exception:
                    file_size = 0

                MAX_HIGHLIGHT_SIZE = 250 * 1024  # 250 KB
                if file_size > MAX_HIGHLIGHT_SIZE:
                    # Load only the first 500 lines to prevent UI freezing
                    lines = []
                    with open(self.current_path, "r", encoding="utf-8", errors="replace") as f:
                        for _ in range(500):
                            line = f.readline()
                            if not line:
                                break
                            lines.append(line)
                    content = "".join(lines)
                    content += "\n\n... [TRUNCATED - File is larger than 250KB] ...\n"
                    
                    try:
                        from pygments.lexers import get_lexer_for_filename
                        lexer = get_lexer_for_filename(str(self.current_path))
                        lexer_name = lexer.aliases[0] if lexer.aliases else lexer.name
                    except Exception:
                        lexer_name = "text"
                        
                    syntax = Syntax(
                        content,
                        lexer_name,
                        line_numbers=True,
                        word_wrap=False,
                        indent_guides=True,
                        theme="monokai"
                    )
                    display.update(syntax)
                    self.notify("Large file detected: showing first 500 lines only", severity="warning")
                else:
                    # Use Syntax.from_path to read and highlight the file
                    syntax = Syntax.from_path(
                        str(self.current_path),
                        line_numbers=True,
                        word_wrap=False,
                        indent_guides=True,
                        theme="monokai"
                    )
                    display.update(syntax)
            except Exception:
                # Fallback to details for non-text/binary files
                try:
                    details = self.get_file_details(self.current_path)
                    display.update(details)
                    self.notify("Non-text file detected, showing details instead", severity="warning")
                except Exception as e:
                    display.update(f"[red]Error showing file details: {e}[/red]")

    def get_file_details(self, path) -> str:
        try:
            stats = os.stat(path)
            size = stats.st_size
            # Format size
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if size < 1024.0:
                    break
                size /= 1024.0
            size_str = f"{size:.2f} {unit}"
            
            mtype, _ = mimetypes.guess_type(str(path))
            
            details = [
                f"[bold]Path:[/bold] {path}",
                f"[bold]Size:[/bold] {size_str} ({stats.st_size} bytes)",
                f"[bold]Type:[/bold] {mtype or 'Unknown'}",
                f"[bold]Permissions:[/bold] {oct(stats.st_mode & 0o777)}",
                f"[bold]Created:[/bold] {datetime.datetime.fromtimestamp(stats.st_ctime).strftime('%Y-%m-%d %H:%M:%S')}",
                f"[bold]Modified:[/bold] {datetime.datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}",
                f"[bold]Accessed:[/bold] {datetime.datetime.fromtimestamp(stats.st_atime).strftime('%Y-%m-%d %H:%M:%S')}",
            ]
            return "\n".join(details)
        except Exception as e:
            return f"[red]Error retrieving file details: {e}[/red]"
