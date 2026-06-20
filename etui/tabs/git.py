# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
import os
import shlex
import signal
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.worker import Worker, WorkerCancelled
from textual.widgets import Button, Input, Label, RichLog, Tree
from textual.css.query import NoMatches

if __package__:
    from ..bus_contract import WorkspaceChanged
    from ..contracts import on_workspace_changed, workspace_get_root
else:  # pragma: no cover - script-mode import
    from bus_contract import WorkspaceChanged
    from contracts import on_workspace_changed, workspace_get_root


class RepositoryChanged(Message):
    """Event posted when repository context changes."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path


@dataclass(frozen=True)
class GitChange:
    path: str
    status: str
    staged: bool


class GitTab(Vertical):
    """Repository Git dashboard tab."""

    DIFF_LIMIT = 100 * 1024

    DEFAULT_CSS = """
    GitTab {
        height: 1fr;
    }

    GitTab #git-repo-select {
        height: 3;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $accent;
        align: left middle;
    }

    GitTab #git-info-bar {
        height: 3;
        background: $surface;
        border-bottom: solid $accent;
        padding: 0 1;
        align: left middle;
    }

    GitTab #git-main-split {
        height: 1fr;
    }

    GitTab #git-changes-tree {
        width: 35%;
        height: 1fr;
        border-right: solid $accent;
    }

    GitTab #git-view-panel {
        width: 65%;
        height: 1fr;
    }

    GitTab #git-diff-viewer {
        height: 1fr;
        background: $boost;
        border-bottom: solid $accent;
    }

    GitTab #git-action-bar {
        height: 8;
        padding: 1;
    }

    GitTab #txt-commit-msg {
        width: 1fr;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.repo_path: Path | None = None
        self.busy = False
        self._active_subprocess: asyncio.subprocess.Process | None = None
        self._operation_worker: Worker[None] | None = None
        self._selected_change: GitChange | None = None
        self._cancel_requested = False
        self._workspace_disposer = None

    def compose(self) -> ComposeResult:
        if __package__:
            from ..plugin import ToolWarningBanner
        else:
            from plugin import ToolWarningBanner
        yield ToolWarningBanner("git", "Git", id="git-tool-warning")

        with Horizontal(id="git-repo-select"):
            yield Label("Git Repository: ")
            yield Input(
                placeholder="Path to directory containing .git",
                id="txt-repo-path",
            )
            yield Button("Open", id="btn-open-repo")

        with Horizontal(id="git-info-bar"):
            yield Label(
                "Select an external git repository to begin.",
                id="lbl-git-info",
            )

        with Horizontal(id="git-main-split"):
            yield Tree("Changes", id="git-changes-tree")
            with Vertical(id="git-view-panel"):
                yield RichLog(
                    id="git-diff-viewer",
                    highlight=False,
                    markup=False,
                )
                with Vertical(id="git-action-bar"):
                    with Horizontal():
                        yield Button(
                            "Stage All",
                            id="btn-git-add-all",
                            disabled=True,
                        )
                        yield Button(
                            "Stage Selected",
                            id="btn-git-toggle-stage",
                            disabled=True,
                        )
                        yield Button("Pull", id="btn-git-pull", disabled=True)
                        yield Button("Push", id="btn-git-push", disabled=True)
                        yield Button(
                            "Cancel",
                            id="btn-git-cancel",
                            variant="warning",
                            disabled=True,
                        )
                    with Horizontal():
                        yield Input(
                            placeholder="Commit message...",
                            id="txt-commit-msg",
                            disabled=True,
                        )
                        yield Button(
                            "Commit",
                            id="btn-git-commit",
                            variant="primary",
                            disabled=True,
                        )

    async def on_mount(self) -> None:
        bus = getattr(self.app, "bus", None)
        if bus is not None:
            try:
                root = await workspace_get_root(bus)
                self._on_workspace_changed(WorkspaceChanged(root=root))
            except Exception:
                pass
            self._workspace_disposer = on_workspace_changed(
                bus,
                self._on_workspace_changed,
            )
        self._rebuild_tree([], [])
        self._set_controls_enabled(False)

    async def on_unmount(self) -> None:
        if self._workspace_disposer is not None:
            self._workspace_disposer()
            self._workspace_disposer = None
        await self.cancel_active_operation()

    async def deactivate_tab(self) -> None:
        await self.cancel_active_operation()

    def validate_and_load_repo(self, path: str) -> Worker[None] | None:
        return self._start_operation(
            self._validate_and_load_repo(path),
            "git-validate-repository",
        )

    def _on_workspace_changed(self, event) -> None:
        path = Path(event.root)
        if self.repo_path is None or str(self.repo_path) != str(path.resolve()):
            self.query_one("#txt-repo-path", Input).value = event.root

    def load_repo_status(self) -> Worker[None] | None:
        return self._start_operation(
            self._load_repo_status(),
            "git-load-status",
        )

    def show_file_diff(
        self,
        path: str,
        is_staged: bool,
    ) -> Worker[None] | None:
        return self._start_operation(
            self._show_file_diff(path, is_staged),
            "git-show-diff",
        )

    def toggle_stage_file(
        self,
        path: str,
        is_staged: bool,
    ) -> Worker[None] | None:
        return self._start_operation(
            self._toggle_stage_file(path, is_staged),
            "git-toggle-stage",
        )

    def run_git_command(self, args: list[str]) -> Worker[None] | None:
        return self._start_operation(
            self._run_git_command(args),
            "git-mutation",
        )

    def _start_operation(
        self,
        operation: Awaitable[None],
        name: str,
    ) -> Worker[None] | None:
        if self.busy:
            if asyncio.iscoroutine(operation):
                operation.close()
            return None

        self.busy = True
        self._cancel_requested = False
        self._set_controls_enabled(False)
        worker = self.run_worker(
            self._run_operation(operation),
            name=name,
            group="git-ops",
            exclusive=False,
            exit_on_error=False,
        )
        self._operation_worker = worker
        return worker

    async def _run_operation(self, operation: Awaitable[None]) -> None:
        try:
            await operation
        except asyncio.CancelledError:
            self._write_log("Git operation cancelled.", style="yellow")
            raise
        except (OSError, UnicodeError, ValueError) as error:
            self._write_log(f"Git operation failed: {error}", style="red")
        finally:
            self._active_subprocess = None
            self._operation_worker = None
            self.busy = False
            self._set_controls_enabled(self.repo_path is not None)

    async def cancel_active_operation(self) -> None:
        self._cancel_requested = True
        worker = self._operation_worker
        if worker is not None and not worker.is_finished:
            worker.cancel()
        await self._terminate_active_subprocess()
        if worker is not None:
            try:
                await worker.wait()
            except WorkerCancelled:
                pass

    async def _terminate_active_subprocess(self) -> None:
        process = self._active_subprocess
        if process is None or process.returncode is not None:
            return

        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            return

        try:
            await asyncio.wait_for(process.wait(), timeout=3.0)
        except TimeoutError:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                return
            await process.wait()

    async def _capture_git(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 15.0,
        stdin: bytes | None = None,
    ) -> tuple[int, bytes, bytes]:
        git_path = "git"
        if hasattr(self.app, "tool_registry"):
            res = self.app.tool_registry.get_result("git")
            if res and res.state.value == "Installed":
                primary_exe = res.executables[0] if res.executables else None
                if primary_exe and primary_exe.path:
                    git_path = primary_exe.path

        process = await asyncio.create_subprocess_exec(
            git_path,
            *args,
            cwd=str(cwd or self.repo_path) if (cwd or self.repo_path) else None,
            env=env,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=(os.name == "posix"),
        )
        self._active_subprocess = process
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(stdin),
                timeout=timeout,
            )
            return process.returncode or 0, stdout, stderr
        except (TimeoutError, asyncio.CancelledError):
            await self._terminate_active_subprocess()
            raise
        finally:
            if self._active_subprocess is process:
                self._active_subprocess = None

    async def _capture_git_limited(
        self,
        args: list[str],
        *,
        limit: int,
        timeout: float = 15.0,
    ) -> tuple[int, bytes, bytes, bool]:
        git_path = "git"
        if hasattr(self.app, "tool_registry"):
            res = self.app.tool_registry.get_result("git")
            if res and res.state.value == "Installed":
                primary_exe = res.executables[0] if res.executables else None
                if primary_exe and primary_exe.path:
                    git_path = primary_exe.path

        process = await asyncio.create_subprocess_exec(
            git_path,
            *args,
            cwd=str(self.repo_path) if self.repo_path else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=(os.name == "posix"),
        )
        self._active_subprocess = process
        assert process.stdout is not None
        assert process.stderr is not None

        async def read_output() -> tuple[bytes, bytes, bool]:
            chunks: list[bytes] = []
            size = 0
            stderr_task = asyncio.create_task(process.stderr.read())
            truncated = False
            try:
                while chunk := await process.stdout.read(16 * 1024):
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > limit:
                        truncated = True
                        await self._terminate_active_subprocess()
                        break
                stderr = await stderr_task
                if process.returncode is None:
                    await process.wait()
                return b"".join(chunks)[: limit + 1], stderr, truncated
            finally:
                if not stderr_task.done():
                    stderr_task.cancel()

        try:
            stdout, stderr, truncated = await asyncio.wait_for(
                read_output(),
                timeout=timeout,
            )
            return process.returncode or 0, stdout, stderr, truncated
        except (TimeoutError, asyncio.CancelledError):
            await self._terminate_active_subprocess()
            raise
        finally:
            if self._active_subprocess is process:
                self._active_subprocess = None

    async def _validate_and_load_repo(self, path: str) -> None:
        try:
            info_bar = self.query_one("#lbl-git-info", Label)
        except NoMatches:
            return
        candidate = Path(path).expanduser().resolve()
        if not candidate.is_dir():
            self.repo_path = None
            info_bar.update(Text("Invalid path: directory does not exist", style="red"))
            return

        returncode, stdout, stderr = await self._capture_git(
            ["rev-parse", "--show-toplevel"],
            cwd=candidate,
        )
        if returncode != 0:
            self.repo_path = None
            detail = stderr.decode(errors="replace").strip()
            info_bar.update(
                Text(f"Validation failed: {detail or 'Not a git repository.'}", style="red")
            )
            return

        self.repo_path = Path(os.fsdecode(stdout).strip()).resolve()
        self.post_message(RepositoryChanged(str(self.repo_path)))
        await self._load_repo_status()

    async def _load_repo_status(self) -> None:
        if self.repo_path is None:
            return

        try:
            branch_code, branch_out, branch_error = await self._capture_git(
                ["branch", "--show-current"]
            )
            if branch_code != 0:
                raise OSError(branch_error.decode(errors="replace").strip())
            branch = branch_out.decode(errors="replace").strip() or "DETACHED"

            hash_code, hash_out, hash_error = await self._capture_git(
                ["rev-parse", "--short", "HEAD"]
            )
            if hash_code == 0:
                commit_hash = hash_out.decode(errors="replace").strip() or "N/A"
            else:
                commit_hash = "N/A"
                if b"unknown revision" not in hash_error.lower():
                    self._write_log(
                        hash_error.decode(errors="replace").strip(),
                        style="yellow",
                    )

            status_code, status_out, status_error = await self._capture_git(
                ["status", "--porcelain=v2", "-z"]
            )
            if status_code != 0:
                raise OSError(status_error.decode(errors="replace").strip())

            staged, unstaged = self._parse_porcelain_v2(status_out)
            self.query_one("#lbl-git-info", Label).update(
                Text.assemble(
                    "Branch: ",
                    (branch, "bold cyan"),
                    "  |  Commit: ",
                    (commit_hash, "bold green"),
                    "  |  Changes: ",
                    (str(len(staged) + len(unstaged)), "bold yellow"),
                )
            )
            self._rebuild_tree(staged, unstaged)
        except NoMatches:
            pass

    @staticmethod
    def _parse_porcelain_v2(
        raw_status: bytes,
    ) -> tuple[list[GitChange], list[GitChange]]:
        """Parse NUL-separated porcelain v2 records without altering paths."""
        staged: list[GitChange] = []
        unstaged: list[GitChange] = []
        entries = raw_status.split(b"\x00")
        index = 0

        while index < len(entries):
            entry = entries[index]
            if not entry:
                index += 1
                continue

            prefix = entry[:1]
            if prefix == b"1":
                fields = entry.split(b" ", 8)
                if len(fields) != 9:
                    raise ValueError("malformed porcelain v2 type-1 record")
                xy, path_bytes = fields[1], fields[8]
            elif prefix == b"2":
                fields = entry.split(b" ", 9)
                if len(fields) != 10 or index + 1 >= len(entries):
                    raise ValueError("malformed porcelain v2 type-2 record")
                xy, path_bytes = fields[1], fields[9]
                index += 1
            elif prefix == b"u":
                fields = entry.split(b" ", 10)
                if len(fields) != 11:
                    raise ValueError("malformed porcelain v2 unmerged record")
                xy, path_bytes = fields[1], fields[10]
            elif prefix == b"?":
                fields = entry.split(b" ", 1)
                if len(fields) != 2:
                    raise ValueError("malformed porcelain v2 untracked record")
                unstaged.append(
                    GitChange(os.fsdecode(fields[1]), "?", False)
                )
                index += 1
                continue
            elif prefix in {b"!", b"#"}:
                index += 1
                continue
            else:
                raise ValueError(
                    f"unsupported porcelain v2 record: {os.fsdecode(prefix)}"
                )

            if len(xy) != 2:
                raise ValueError("malformed porcelain v2 XY status")
            path = os.fsdecode(path_bytes)
            if xy[0:1] != b".":
                staged.append(
                    GitChange(path, os.fsdecode(xy[0:1]), True)
                )
            if xy[1:2] != b".":
                unstaged.append(
                    GitChange(path, os.fsdecode(xy[1:2]), False)
                )
            index += 1

        return staged, unstaged

    def _rebuild_tree(
        self,
        staged: list[GitChange],
        unstaged: list[GitChange],
    ) -> None:
        tree = self.query_one("#git-changes-tree", Tree)
        tree.clear()
        staged_node = tree.root.add("Staged", expand=True)
        unstaged_node = tree.root.add("Unstaged", expand=True)

        for change in staged:
            staged_node.add_leaf(
                Text.assemble((f"[{change.status}] ", "bold"), change.path),
                data=change,
            )
        for change in unstaged:
            unstaged_node.add_leaf(
                Text.assemble((f"[{change.status}] ", "bold"), change.path),
                data=change,
            )

        self._selected_change = None
        self.query_one("#btn-git-toggle-stage", Button).disabled = True

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.control.id != "git-changes-tree":
            return
        change = event.node.data
        if not isinstance(change, GitChange):
            self._selected_change = None
            self.query_one("#btn-git-toggle-stage", Button).disabled = True
            return

        self._selected_change = change
        toggle = self.query_one("#btn-git-toggle-stage", Button)
        toggle.label = (
            "Unstage Selected" if change.staged else "Stage Selected"
        )
        toggle.disabled = self.busy
        if not self.busy:
            self.show_file_diff(change.path, change.staged)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        change = event.node.data
        if isinstance(change, GitChange) and not self.busy:
            self.toggle_stage_file(change.path, change.staged)

    async def _toggle_stage_file(self, path: str, is_staged: bool) -> None:
        if self.repo_path is None:
            return
        args = (
            ["restore", "--staged", "--", path]
            if is_staged
            else ["add", "--", path]
        )
        returncode, _, stderr = await self._capture_git(args)
        if returncode != 0:
            raise OSError(stderr.decode(errors="replace").strip())
        await self._load_repo_status()

    async def _show_file_diff(self, path: str, is_staged: bool) -> None:
        if self.repo_path is None:
            return
        try:
            log = self.query_one("#git-diff-viewer", RichLog)
        except NoMatches:
            return
        log.clear()

        base_args = ["diff"]
        if is_staged:
            base_args.append("--cached")

        returncode, numstat, stderr = await self._capture_git(
            [*base_args, "--numstat", "--", path]
        )
        if returncode != 0:
            raise OSError(stderr.decode(errors="replace").strip())
        if any(line.startswith(b"-\t-\t") for line in numstat.splitlines()):
            self._write_log("Binary diff cannot be displayed inline.", style="yellow")
            return

        returncode, stdout, stderr, truncated = await self._capture_git_limited(
            [*base_args, "--color=never", "--", path],
            limit=self.DIFF_LIMIT,
            timeout=15.0,
        )
        if truncated:
            self._write_log(
                "Diff is too large to display inline (exceeds 100KB).",
                style="yellow",
            )
            return
        if returncode != 0:
            raise OSError(stderr.decode(errors="replace").strip())

        diff_text = stdout.decode(errors="replace")
        if not diff_text.strip():
            self._write_log("No modifications found.", style="dim")
            return
        for line in diff_text.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                log.write(Text(line, style="green"))
            elif line.startswith("-") and not line.startswith("---"):
                log.write(Text(line, style="red"))
            else:
                log.write(Text(line))

    async def _run_git_command(self, args: list[str]) -> None:
        if self.repo_path is None:
            return
        try:
            log = self.query_one("#git-diff-viewer", RichLog)
        except NoMatches:
            return
        log.clear()
        log.write(Text(f"Running: git {shlex.join(args)}", style="bold cyan"))

        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GCM_INTERACTIVE"] = "Never"
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"
        returncode, stdout, stderr = await self._capture_git(
            args,
            env=env,
            timeout=15 * 60,
        )
        output = stdout.decode(errors="replace")
        error = stderr.decode(errors="replace")
        if output:
            log.write(Text(output.rstrip()))
        if error:
            log.write(Text(error.rstrip(), style="red"))
        if returncode != 0:
            raise OSError(f"git exited with status {returncode}")

        log.write(Text("Git operation succeeded.", style="bold green"))
        await self._load_repo_status()

    def _set_controls_enabled(self, enabled: bool) -> None:
        if not self.is_mounted:
            return
        from textual.css.query import NoMatches
        try:
            self.query_one("#btn-open-repo", Button).disabled = self.busy
            self.query_one("#txt-repo-path", Input).disabled = self.busy
            self.query_one("#git-changes-tree", Tree).disabled = self.busy
            self.query_one("#btn-git-add-all", Button).disabled = not enabled
            self.query_one("#btn-git-pull", Button).disabled = not enabled
            self.query_one("#btn-git-push", Button).disabled = not enabled
            self.query_one("#txt-commit-msg", Input).disabled = not enabled
            self.query_one("#btn-git-commit", Button).disabled = not enabled
            self.query_one("#btn-git-toggle-stage", Button).disabled = (
                not enabled or self._selected_change is None
            )
            self.query_one("#btn-git-cancel", Button).disabled = not self.busy
        except NoMatches:
            pass

    def _write_log(self, message: str, *, style: str | None = None) -> None:
        try:
            self.query_one("#git-diff-viewer", RichLog).write(
                Text(message, style=style)
            )
        except NoMatches:
            pass

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "btn-git-cancel":
            await self.cancel_active_operation()
            return
        if self.busy:
            return
        if button_id == "btn-open-repo":
            path = self.query_one("#txt-repo-path", Input).value.strip()
            if path:
                self.validate_and_load_repo(path)
        elif button_id == "btn-git-toggle-stage":
            change = self._selected_change
            if change is not None:
                self.toggle_stage_file(change.path, change.staged)
        elif button_id == "btn-git-add-all":
            self.run_git_command(["add", "-A"])
        elif button_id == "btn-git-pull":
            self.run_git_command(["pull", "--ff-only"])
        elif button_id == "btn-git-push":
            self.run_git_command(["push"])
        elif button_id == "btn-git-commit":
            self._commit_from_input()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self.busy:
            return
        if event.input.id == "txt-commit-msg":
            self._commit_from_input()
        elif event.input.id == "txt-repo-path":
            path = event.value.strip()
            if path:
                self.validate_and_load_repo(path)

    def _commit_from_input(self) -> None:
        message_input = self.query_one("#txt-commit-msg", Input)
        message = message_input.value.strip()
        if message:
            message_input.value = ""
            self.run_git_command(["commit", "-m", message])
