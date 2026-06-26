# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import os
import datetime
import mimetypes
import shutil
from pathlib import Path
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical, ScrollableContainer
from textual.widgets import DirectoryTree, Button, Input, Label
from textual.widgets import Static
from rich.syntax import Syntax
from textual.widgets import Markdown, MarkdownViewer

try:
    from ..bus import BusMixin
    from ..bus_contract import SVC_FILES_SELECT, SVC_FILES_DELETE
except ImportError:
    from etui.bus import BusMixin
    from etui.bus_contract import SVC_FILES_SELECT, SVC_FILES_DELETE

_MD_SUFFIXES = {".md", ".markdown"}


class SafeMarkdownViewer(MarkdownViewer):
    """MarkdownViewer that only follows links to other Markdown files.

    Overrides go() so every navigation — whether triggered by a link click or
    by open_file() — resolves the target to an absolute path before the
    navigator sees it.  This prevents the navigator's stale base-dir from
    producing double-segment paths, and silently drops links to non-Markdown
    targets (SVG images, external URLs, etc.).
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._current_document: Path | None = None

    async def go(self, location: str | Path) -> None:
        path, anchor = Markdown.sanitize_location(str(location))
        if path == Path(".") and anchor:
            await super().go(f"#{anchor}")
            return

        if not path.is_absolute():
            base = (
                self._current_document.parent
                if self._current_document is not None
                else Path.cwd()
            )
            path = (base / path).resolve()
        else:
            path = path.resolve()

        if path.suffix.lower() not in _MD_SUFFIXES or not path.is_file():
            return

        self._current_document = path
        target = f"{path}#{anchor}" if anchor else path
        await super().go(target)


class LeftWidget(DirectoryTree):
    def __init__(self):
        super().__init__("./")


class FileViewer(Vertical):
    def compose(self) -> ComposeResult:
        with Horizontal(id="viewer-controls"):
            yield Button("Content", id="btn-content", variant="primary")
            yield Button("Details", id="btn-details")
            yield Button("Delete", id="btn-delete", variant="error")
        with ScrollableContainer(id="file-scroll"):
            yield Static(id="file-display", expand=True)
        yield SafeMarkdownViewer(show_table_of_contents=False, id="md-viewer")

    def on_mount(self) -> None:
        self.query_one("#md-viewer", SafeMarkdownViewer).display = False


class FilesTab(BusMixin, Vertical):
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
    FilesTab #file-scroll {
        height: 1fr;
    }
    FilesTab #md-viewer {
        height: 1fr;
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
            self._apply_workspace_root(self.app.workspace_root)
        if self.bus is not None:
            self._disposers = [
                self.bus.provide(SVC_FILES_SELECT, self._svc_select),
                self.bus.provide(SVC_FILES_DELETE, self._svc_delete),
            ]

    def on_unmount(self) -> None:
        for dispose in getattr(self, "_disposers", []):
            dispose()

    def _svc_select(self, path: str) -> None:
        self.select_path(Path(path))

    def _svc_delete(self, path: str) -> None:
        self.run_worker(self._confirm_and_delete(Path(path)))

    def _apply_workspace_root(self, root: str) -> None:
        self.query_one("LeftWidget").path = Path(root)
        self.query_one("#txt-workspace-root", Input).value = root

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        event.stop()
        self.query_one("#txt-workspace-root", Input).value = str(event.path)

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
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
        elif event.button.id == "btn-delete":
            if self.current_path:
                self.run_worker(self._confirm_and_delete(self.current_path))
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
        self._apply_workspace_root(str(path))
        self.notify(f"Workspace root set to {path}")

    def open_file(self, path: Path) -> None:
        """Display *path* in the viewer without changing the directory tree root."""
        self.current_path = path
        self.view_mode = "content"
        self.render_file()

    def select_path(self, path: Path) -> None:
        """Navigate the directory tree to *path* and open it in the viewer.

        If *path* is a file, the tree root is set to its parent directory and the
        file is displayed.  If *path* is a directory, the tree root is set to it.
        """
        path = path.expanduser().resolve()
        if path.is_file():
            self._apply_workspace_root(str(path.parent))
            self.open_file(path)
        elif path.is_dir():
            self._apply_workspace_root(str(path))
        else:
            self.app.notify(f"Path not found: {path}", severity="error")

    async def _confirm_and_delete(self, path: Path) -> None:
        path = path.expanduser().resolve()
        if not path.exists():
            self.app.notify(f"Path not found: {path}", severity="error")
            return
        kind = "directory" if path.is_dir() else "file"
        confirmed = await self.app.confirm_action(f"Delete {kind} '{path.name}'?")
        if confirmed:
            self.delete_path(path)

    def delete_path(self, path: Path) -> None:
        """Delete *path* from disk (file or directory tree) and refresh the tree."""
        path = path.expanduser().resolve()
        if not path.exists():
            self.app.notify(f"Path not found: {path}", severity="error")
            return
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as exc:
            self.app.notify(f"Delete failed: {exc}", severity="error")
            return
        if self.current_path and self.current_path.resolve() == path:
            self.current_path = None
            self.query_one("#file-display", Static).update("")
            self.query_one("#md-viewer", SafeMarkdownViewer).display = False
            self.query_one("#file-scroll").display = True
        tree = self.query_one("LeftWidget", DirectoryTree)
        tree.reload()
        self.app.notify(f"Deleted: {path.name}")

    def _is_markdown(self, path: Path) -> bool:
        return path.suffix.lower() in _MD_SUFFIXES

    def render_file(self) -> None:
        if not self.current_path:
            return

        scroll = self.query_one("#file-scroll")
        display = self.query_one("#file-display", Static)
        md_viewer = self.query_one("#md-viewer", SafeMarkdownViewer)
        btn_content = self.query_one("#btn-content", Button)
        btn_details = self.query_one("#btn-details", Button)

        btn_content.variant = "primary" if self.view_mode == "content" else "default"
        btn_details.variant = "primary" if self.view_mode == "details" else "default"

        if self.view_mode == "details":
            scroll.display = True
            md_viewer.display = False
            display.update(self.get_file_details(self.current_path))
            return

        # Content mode — use Viewer for Markdown, Syntax for everything else.
        if self._is_markdown(self.current_path):
            scroll.display = False
            md_viewer.display = True
            self.call_after_refresh(md_viewer.go, self.current_path)
            return

        scroll.display = True
        md_viewer.display = False

        try:
            file_size = os.path.getsize(self.current_path)
        except Exception:
            file_size = 0

        MAX_HIGHLIGHT_SIZE = 250 * 1024
        try:
            if file_size > MAX_HIGHLIGHT_SIZE:
                lines = []
                with open(self.current_path, "r", encoding="utf-8", errors="replace") as f:
                    for _ in range(500):
                        line = f.readline()
                        if not line:
                            break
                        lines.append(line)
                content = "".join(lines) + "\n\n... [TRUNCATED] ...\n"
                try:
                    from pygments.lexers import get_lexer_for_filename
                    lexer = get_lexer_for_filename(str(self.current_path))
                    lexer_name = lexer.aliases[0] if lexer.aliases else lexer.name
                except Exception:
                    lexer_name = "text"
                syntax = Syntax(content, lexer_name, line_numbers=True,
                                word_wrap=False, indent_guides=True, theme="monokai")
                display.update(syntax)
                self.notify("Large file: showing first 500 lines only", severity="warning")
            else:
                syntax = Syntax.from_path(str(self.current_path), line_numbers=True,
                                          word_wrap=False, indent_guides=True, theme="monokai")
                display.update(syntax)
        except Exception:
            try:
                display.update(self.get_file_details(self.current_path))
                self.notify("Non-text file: showing details instead", severity="warning")
            except Exception as e:
                display.update(f"[red]Error: {e}[/red]")

    def get_file_details(self, path) -> str:
        try:
            stats = os.stat(path)
            size = stats.st_size
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
