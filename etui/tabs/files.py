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
from textual.widgets import DirectoryTree, Button, Input, Label, Checkbox
from textual.widgets import Static
from rich.syntax import Syntax
from textual.widgets import Markdown, MarkdownViewer
from textual.screen import ModalScreen

try:
    from ..bus import BusMixin
    from ..bus_contract import SVC_FILES_SELECT, SVC_FILES_DELETE, SVC_FILES_CREATE, SVC_FILES_RENAME, SVC_FILES_COPY, SVC_FILES_MOVE, SVC_FILES_PERMISSIONS
except ImportError:
    from etui.bus import BusMixin
    from etui.bus_contract import SVC_FILES_SELECT, SVC_FILES_DELETE, SVC_FILES_CREATE, SVC_FILES_RENAME, SVC_FILES_COPY, SVC_FILES_MOVE, SVC_FILES_PERMISSIONS

_MD_SUFFIXES = {".md", ".markdown"}


class CreateModal(ModalScreen):
    """Modal dialog that collects a name and kind (file / directory) for creation."""

    DEFAULT_CSS = """
    CreateModal { align: center middle; }
    #create-modal-box {
        background: $surface;
        padding: 1 2;
        border: thick $accent;
        width: 60;
        height: auto;
    }
    #create-modal-box Label { margin-bottom: 1; }
    #create-modal-box Input { margin-bottom: 1; }
    #create-modal-kind { height: 3; margin-bottom: 1; }
    #create-modal-btns { height: 3; align: right middle; }
    #create-modal-btns Button { margin-left: 1; }
    """

    def __init__(self, parent_dir: Path) -> None:
        super().__init__()
        self._parent_dir = parent_dir

    def compose(self) -> ComposeResult:
        with Vertical(id="create-modal-box"):
            yield Label(f"Create in: {self._parent_dir}")
            yield Input(placeholder="name (e.g. file.txt or subdir)", id="create-name")
            with Horizontal(id="create-modal-kind"):
                yield Button("File", id="kind-file", variant="primary")
                yield Button("Directory", id="kind-dir")
            with Horizontal(id="create-modal-btns"):
                yield Button("Cancel", id="create-cancel")
                yield Button("Create", id="create-ok", variant="success")

    def on_mount(self) -> None:
        self.query_one("#create-name", Input).focus()
        self._is_dir = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "kind-file":
            self._is_dir = False
            self.query_one("#kind-file", Button).variant = "primary"
            self.query_one("#kind-dir", Button).variant = "default"
        elif event.button.id == "kind-dir":
            self._is_dir = True
            self.query_one("#kind-file", Button).variant = "default"
            self.query_one("#kind-dir", Button).variant = "primary"
        elif event.button.id == "create-cancel":
            self.dismiss(None)
        elif event.button.id == "create-ok":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._submit()

    def _submit(self) -> None:
        name = self.query_one("#create-name", Input).value.strip()
        if name:
            self.dismiss((name, self._is_dir))


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


class RenameModal(ModalScreen):
    """Modal dialog that collects a new name for an existing file or directory."""

    DEFAULT_CSS = """
    RenameModal { align: center middle; }
    #rename-modal-box {
        background: $surface;
        padding: 1 2;
        border: thick $accent;
        width: 60;
        height: auto;
    }
    #rename-modal-box Label { margin-bottom: 1; }
    #rename-modal-box Input { margin-bottom: 1; }
    #rename-modal-btns { height: 3; align: right middle; }
    #rename-modal-btns Button { margin-left: 1; }
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path

    def compose(self) -> ComposeResult:
        with Vertical(id="rename-modal-box"):
            yield Label(f"Rename: {self._path.name}")
            yield Input(value=self._path.name, id="rename-input")
            with Horizontal(id="rename-modal-btns"):
                yield Button("Cancel", id="rename-cancel")
                yield Button("Rename", id="rename-ok", variant="success")

    def on_mount(self) -> None:
        inp = self.query_one("#rename-input", Input)
        inp.focus()
        inp.cursor_position = len(inp.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "rename-cancel":
            self.dismiss(None)
        elif event.button.id == "rename-ok":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._submit()

    def _submit(self) -> None:
        name = self.query_one("#rename-input", Input).value.strip()
        if name and name != self._path.name:
            self.dismiss(name)
        else:
            self.dismiss(None)


class CopyModal(ModalScreen):
    """Modal dialog that collects a destination path for a copy operation."""

    DEFAULT_CSS = """
    CopyModal { align: center middle; }
    #copy-modal-box {
        background: $surface;
        padding: 1 2;
        border: thick $accent;
        width: 70;
        height: auto;
    }
    #copy-modal-box Label { margin-bottom: 1; }
    #copy-modal-box Input { margin-bottom: 1; }
    #copy-modal-btns { height: 3; align: right middle; }
    #copy-modal-btns Button { margin-left: 1; }
    """

    def __init__(self, src: Path) -> None:
        super().__init__()
        self._src = src

    def compose(self) -> ComposeResult:
        with Vertical(id="copy-modal-box"):
            yield Label(f"Copy: {self._src.name}")
            yield Input(
                value=str(self._src.parent / (self._src.stem + "_copy" + self._src.suffix)),
                placeholder="destination path",
                id="copy-dest",
            )
            with Horizontal(id="copy-modal-btns"):
                yield Button("Cancel", id="copy-cancel")
                yield Button("Copy", id="copy-ok", variant="success")

    def on_mount(self) -> None:
        inp = self.query_one("#copy-dest", Input)
        inp.focus()
        inp.cursor_position = len(inp.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "copy-cancel":
            self.dismiss(None)
        elif event.button.id == "copy-ok":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._submit()

    def _submit(self) -> None:
        dest = self.query_one("#copy-dest", Input).value.strip()
        if dest:
            self.dismiss(dest)


class MoveModal(ModalScreen):
    """Modal dialog that collects a destination path for a move operation."""

    DEFAULT_CSS = """
    MoveModal { align: center middle; }
    #move-modal-box {
        background: $surface;
        padding: 1 2;
        border: thick $accent;
        width: 70;
        height: auto;
    }
    #move-modal-box Label { margin-bottom: 1; }
    #move-modal-box Input { margin-bottom: 1; }
    #move-modal-btns { height: 3; align: right middle; }
    #move-modal-btns Button { margin-left: 1; }
    """

    def __init__(self, src: Path) -> None:
        super().__init__()
        self._src = src

    def compose(self) -> ComposeResult:
        with Vertical(id="move-modal-box"):
            yield Label(f"Move: {self._src.name}")
            yield Input(
                value=str(self._src.parent),
                placeholder="destination directory or full path",
                id="move-dest",
            )
            with Horizontal(id="move-modal-btns"):
                yield Button("Cancel", id="move-cancel")
                yield Button("Move", id="move-ok", variant="success")

    def on_mount(self) -> None:
        inp = self.query_one("#move-dest", Input)
        inp.focus()
        inp.cursor_position = len(inp.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "move-cancel":
            self.dismiss(None)
        elif event.button.id == "move-ok":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._submit()

    def _submit(self) -> None:
        dest = self.query_one("#move-dest", Input).value.strip()
        if dest:
            self.dismiss(dest)



class LeftWidget(DirectoryTree):
    def __init__(self):
        super().__init__("./")


class FileViewer(Vertical):
    def compose(self) -> ComposeResult:
        with Horizontal(id="viewer-controls"):
            yield Button("Content", id="btn-content", variant="primary")
            yield Button("Details", id="btn-details")
            yield Button("Create", id="btn-create", variant="success")
            yield Button("Rename", id="btn-rename")
            yield Button("Copy", id="btn-copy")
            yield Button("Move", id="btn-move")
            yield Button("Delete", id="btn-delete", variant="error")
        with ScrollableContainer(id="file-scroll"):
            yield Static(id="file-display", expand=True)
        with Vertical(id="perm-grid"):
            with Horizontal(id="perm-header-row"):
                yield Label("", id="perm-corner")
                yield Label("Read", classes="perm-col-label")
                yield Label("Write", classes="perm-col-label")
                yield Label("Execute", classes="perm-col-label")
            with Horizontal(classes="perm-row"):
                yield Label("Owner", classes="perm-row-label")
                yield Checkbox("", id="perm-owner-r")
                yield Checkbox("", id="perm-owner-w")
                yield Checkbox("", id="perm-owner-x")
            with Horizontal(classes="perm-row"):
                yield Label("Group", classes="perm-row-label")
                yield Checkbox("", id="perm-group-r")
                yield Checkbox("", id="perm-group-w")
                yield Checkbox("", id="perm-group-x")
            with Horizontal(classes="perm-row"):
                yield Label("Others", classes="perm-row-label")
                yield Checkbox("", id="perm-other-r")
                yield Checkbox("", id="perm-other-w")
                yield Checkbox("", id="perm-other-x")
        yield SafeMarkdownViewer(show_table_of_contents=False, id="md-viewer")

    def on_mount(self) -> None:
        self.query_one("#md-viewer", SafeMarkdownViewer).display = False
        self.query_one("#perm-grid").display = False


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
    FilesTab #perm-grid {
        height: auto;
        border-top: solid $accent;
        padding: 0 1;
        background: $surface;
    }
    FilesTab #perm-header-row {
        height: 1;
    }
    FilesTab .perm-row {
        height: 3;
    }
    FilesTab #perm-corner {
        width: 8;
    }
    FilesTab .perm-row-label {
        width: 8;
        margin-top: 1;
    }
    FilesTab .perm-col-label {
        width: 12;
        text-align: center;
    }
    FilesTab #perm-grid Checkbox {
        width: 12;
    }
    """

    def __init__(self):
        super().__init__()
        self.current_path = None
        self.view_mode = "content"
        self._perm_loading = False

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
                self.bus.provide(SVC_FILES_CREATE, self._svc_create),
                self.bus.provide(SVC_FILES_RENAME, self._svc_rename),
                self.bus.provide(SVC_FILES_COPY, self._svc_copy),
                self.bus.provide(SVC_FILES_MOVE, self._svc_move),
                self.bus.provide(SVC_FILES_PERMISSIONS, self._svc_permissions),
            ]

    def on_unmount(self) -> None:
        for dispose in getattr(self, "_disposers", []):
            dispose()

    def _svc_select(self, path: str) -> None:
        self.select_path(Path(path))

    def _svc_delete(self, path: str) -> None:
        self.run_worker(self._confirm_and_delete(Path(path)))

    def _svc_create(self, path: str, *, is_dir: bool = False) -> None:
        self.create_path(Path(path), is_dir=is_dir)

    def _svc_rename(self, path: str, new_name: str) -> None:
        self.rename_path(Path(path), new_name)

    def _svc_copy(self, src: str, dest: str) -> None:
        self.copy_path(Path(src), Path(dest))

    def _svc_move(self, src: str, dest: str) -> None:
        self.move_path(Path(src), Path(dest))

    def _svc_permissions(self, path: str, mode: int) -> None:
        self.set_permissions(Path(path), mode)

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
        elif event.button.id == "btn-create":
            self.run_worker(self._show_create_dialog())
        elif event.button.id == "btn-rename":
            if self.current_path:
                self.run_worker(self._show_rename_dialog(self.current_path))
        elif event.button.id == "btn-copy":
            if self.current_path:
                self.run_worker(self._show_copy_dialog(self.current_path))
        elif event.button.id == "btn-move":
            if self.current_path:
                self.run_worker(self._show_move_dialog(self.current_path))
        elif event.button.id == "btn-delete":
            if self.current_path:
                self.run_worker(self._confirm_and_delete(self.current_path))
        elif event.button.id == "btn-set-workspace-root":
            await self._action_set_workspace_root()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if self._perm_loading or not self.current_path:
            return
        if not event.checkbox.id or not event.checkbox.id.startswith("perm-"):
            return
        event.stop()
        mode = self._read_perm_grid()
        self.set_permissions(self.current_path, mode)

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

    async def _show_create_dialog(self) -> None:
        parent_dir = (
            self.current_path.parent if self.current_path and self.current_path.is_file()
            else self.current_path
            if self.current_path and self.current_path.is_dir()
            else Path(self.query_one("#txt-workspace-root", Input).value.strip() or ".")
        )
        parent_dir = parent_dir.expanduser().resolve()
        result = await self.app.push_screen_wait(CreateModal(parent_dir))
        if result is not None:
            name, is_dir = result
            self.create_path(parent_dir / name, is_dir=is_dir)

    def create_path(self, path: Path, *, is_dir: bool = False) -> None:
        """Create a file or directory at *path* and refresh the tree."""
        path = path.expanduser().resolve()
        if path.exists():
            self.app.notify(f"Already exists: {path.name}", severity="warning")
            return
        try:
            if is_dir:
                path.mkdir(parents=True, exist_ok=False)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
        except OSError as exc:
            self.app.notify(f"Create failed: {exc}", severity="error")
            return
        self.query_one("LeftWidget", DirectoryTree).reload()
        self.app.notify(f"Created: {path.name}")
        if not is_dir:
            self.open_file(path)

    async def _show_rename_dialog(self, path: Path) -> None:
        new_name = await self.app.push_screen_wait(RenameModal(path))
        if new_name:
            self.rename_path(path, new_name)

    def rename_path(self, path: Path, new_name: str) -> None:
        """Rename *path* to *new_name* (sibling in the same directory) and refresh the tree."""
        path = path.expanduser().resolve()
        if not path.exists():
            self.app.notify(f"Path not found: {path.name}", severity="error")
            return
        dest = path.parent / new_name
        if dest.exists():
            self.app.notify(f"Already exists: {new_name}", severity="warning")
            return
        try:
            path.rename(dest)
        except OSError as exc:
            self.app.notify(f"Rename failed: {exc}", severity="error")
            return
        if self.current_path and self.current_path.resolve() == path:
            self.current_path = dest
        self.query_one("LeftWidget", DirectoryTree).reload()
        self.app.notify(f"Renamed to: {new_name}")
        if dest.is_file():
            self.open_file(dest)

    async def _show_copy_dialog(self, src: Path) -> None:
        dest_str = await self.app.push_screen_wait(CopyModal(src))
        if dest_str:
            self.copy_path(src, Path(dest_str))

    def copy_path(self, src: Path, dest: Path) -> None:
        """Copy *src* (file or directory tree) to *dest* and refresh the tree."""
        src = src.expanduser().resolve()
        dest = dest.expanduser().resolve()
        if not src.exists():
            self.app.notify(f"Source not found: {src.name}", severity="error")
            return
        if dest.exists():
            self.app.notify(f"Destination already exists: {dest.name}", severity="warning")
            return
        try:
            if src.is_dir():
                shutil.copytree(src, dest)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
        except OSError as exc:
            self.app.notify(f"Copy failed: {exc}", severity="error")
            return
        self.query_one("LeftWidget", DirectoryTree).reload()
        self.app.notify(f"Copied to: {dest.name}")
        if dest.is_file():
            self.open_file(dest)

    async def _show_move_dialog(self, src: Path) -> None:
        dest_str = await self.app.push_screen_wait(MoveModal(src))
        if dest_str:
            self.move_path(src, Path(dest_str))

    def move_path(self, src: Path, dest: Path) -> None:
        """Move *src* to *dest* and refresh the tree.

        If *dest* is an existing directory, *src* is moved inside it (matching
        shell ``mv`` semantics).  Otherwise *dest* is the full target path.
        """
        src = src.expanduser().resolve()
        dest = dest.expanduser().resolve()
        if not src.exists():
            self.app.notify(f"Source not found: {src.name}", severity="error")
            return
        if dest.is_dir():
            dest = dest / src.name
        if dest.exists():
            self.app.notify(f"Destination already exists: {dest.name}", severity="warning")
            return
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
        except OSError as exc:
            self.app.notify(f"Move failed: {exc}", severity="error")
            return
        if self.current_path and self.current_path.resolve() == src:
            self.current_path = dest
        self.query_one("LeftWidget", DirectoryTree).reload()
        self.app.notify(f"Moved to: {dest.name}")
        if dest.is_file():
            self.open_file(dest)

    def _load_perm_grid(self, path: Path) -> None:
        """Read current mode from *path* and sync all permission checkboxes."""
        try:
            mode = os.stat(path).st_mode & 0o777
        except OSError:
            return
        self._perm_loading = True
        try:
            bits = {
                "perm-owner-r": bool(mode & 0o400),
                "perm-owner-w": bool(mode & 0o200),
                "perm-owner-x": bool(mode & 0o100),
                "perm-group-r": bool(mode & 0o040),
                "perm-group-w": bool(mode & 0o020),
                "perm-group-x": bool(mode & 0o010),
                "perm-other-r": bool(mode & 0o004),
                "perm-other-w": bool(mode & 0o002),
                "perm-other-x": bool(mode & 0o001),
            }
            for cb_id, checked in bits.items():
                self.query_one(f"#{cb_id}", Checkbox).value = checked
        finally:
            self._perm_loading = False

    def _read_perm_grid(self) -> int:
        """Build an octal mode int from the current state of the permission checkboxes."""
        mapping = [
            ("perm-owner-r", 0o400), ("perm-owner-w", 0o200), ("perm-owner-x", 0o100),
            ("perm-group-r", 0o040), ("perm-group-w", 0o020), ("perm-group-x", 0o010),
            ("perm-other-r", 0o004), ("perm-other-w", 0o002), ("perm-other-x", 0o001),
        ]
        mode = 0
        for cb_id, bit in mapping:
            if self.query_one(f"#{cb_id}", Checkbox).value:
                mode |= bit
        return mode

    def set_permissions(self, path: Path, mode: int) -> None:
        """Apply *mode* (octal int) to *path* via chmod and refresh the details view."""
        path = path.expanduser().resolve()
        if not path.exists():
            self.app.notify(f"Path not found: {path.name}", severity="error")
            return
        try:
            path.chmod(mode)
        except OSError as exc:
            self.app.notify(f"chmod failed: {exc}", severity="error")
            return
        self.app.notify(f"Permissions set to {oct(mode)}: {path.name}")
        if self.current_path and self.current_path.resolve() == path and self.view_mode == "details":
            self.query_one("#file-display", Static).update(self.get_file_details(path))

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
            self.query_one("#perm-grid").display = True
            display.update(self.get_file_details(self.current_path))
            self._load_perm_grid(self.current_path)
            return

        self.query_one("#perm-grid").display = False

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
