# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import os
import shlex
import asyncio
from dataclasses import dataclass
from pathlib import Path
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.worker import Worker
from textual.widgets import Label, Button, Input, Tree, RichLog

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
        self.busy: bool = False
        self._active_subprocess: asyncio.subprocess.Process | None = None
        self._mutation_worker: Worker[None] | None = None
        self._selected_change: GitChange | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="git-repo-select"):
            yield Label("Git Repository: ")
            yield Input(placeholder="Path to directory containing .git", id="txt-repo-path")
            yield Button("Open", id="btn-open-repo")

        with Horizontal(id="git-info-bar"):
            yield Label("Select an external git repository to begin.", id="lbl-git-info")

        with Horizontal(id="git-main-split"):
            # Left side: Staged and unstaged tree
            yield Tree("Changes", id="git-changes-tree")
            
            # Right side: Diff viewer and commit buttons
            with Vertical(id="git-view-panel"):
                yield RichLog(id="git-diff-viewer", highlight=True, markup=True)
                with Vertical(id="git-action-bar"):
                    with Horizontal():
                        yield Button("Stage All", id="btn-git-add-all", disabled=True)
                        yield Button("Stage Selected", id="btn-git-toggle-stage", disabled=True)
                        yield Button("Pull", id="btn-git-pull", disabled=True)
                        yield Button("Push", id="btn-git-push", disabled=True)
                        yield Button("Cancel", id="btn-git-cancel", variant="warning", disabled=True)
                    with Horizontal():
                        yield Input(placeholder="Commit message...", id="txt-commit-msg", disabled=True)
                        yield Button("Commit", id="btn-git-commit", variant="primary", disabled=True)

    def on_mount(self) -> None:
        self._rebuild_tree([], [])

    async def on_unmount(self) -> None:
        await self.cancel_active_operation()

    async def deactivate_tab(self) -> None:
        """Invoked when switching away from this tab."""
        await self.cancel_active_operation()

    async def cancel_active_operation(self) -> None:
        process = self._active_subprocess
        worker = self._mutation_worker

        if process is not None and process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()

        if worker is not None and not worker.is_finished:
            worker.cancel()

    def set_controls_disabled(self, disabled: bool) -> None:
        self.query_one("#btn-git-add-all", Button).disabled = disabled
        self.query_one("#btn-git-toggle-stage", Button).disabled = (
            disabled or self._selected_change is None
        )
        self.query_one("#btn-git-pull", Button).disabled = disabled
        self.query_one("#btn-git-push", Button).disabled = disabled
        self.query_one("#txt-commit-msg", Input).disabled = disabled
        self.query_one("#btn-git-commit", Button).disabled = disabled
        self.query_one("#btn-git-cancel", Button).disabled = not disabled

    # 4.2 Repository Validation
    @work(exclusive=True, group="git-queries")
    async def validate_and_load_repo(self, path: str) -> None:
        if self.busy:
            return

        self.busy = True
        info_bar = self.query_one("#lbl-git-info", Label)
        
        try:
            candidate = Path(path).expanduser().resolve()
            if not candidate.is_dir():
                info_bar.update("[red]Invalid path: directory does not exist[/red]")
                self.repo_path = None
                self.set_controls_disabled(True)
                return

            # Check inside work tree and resolve top-level root path
            proc = await asyncio.create_subprocess_exec(
                "git", "rev-parse", "--show-toplevel",
                cwd=str(candidate),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                err_msg = stderr.decode().strip() or "Not a git repository."
                info_bar.update(f"[red]Validation Failed: {err_msg}[/red]")
                self.repo_path = None
                self.set_controls_disabled(True)
                return

            self.repo_path = Path(stdout.decode().strip())
            self.set_controls_disabled(False)
            self.post_message(RepositoryChanged(str(self.repo_path)))
            self.load_repo_status()
        finally:
            self.busy = False

    # 4.3 Query Repo Status and Branch Info
    @work(exclusive=True, group="git-queries")
    async def load_repo_status(self) -> None:
        if not self.repo_path or self.busy:
            return

        self.busy = True
        try:
            # 1. Get active branch name
            branch_proc = await asyncio.create_subprocess_exec(
                "git", "branch", "--show-current",
                cwd=str(self.repo_path),
                stdout=asyncio.subprocess.PIPE
            )
            branch_out, _ = await branch_proc.communicate()
            branch = branch_out.decode().strip() or "DETACHED"

            # 2. Get short commit hash
            hash_proc = await asyncio.create_subprocess_exec(
                "git", "rev-parse", "--short", "HEAD",
                cwd=str(self.repo_path),
                stdout=asyncio.subprocess.PIPE
            )
            hash_out, _ = await hash_proc.communicate()
            commit_hash = hash_out.decode().strip() or "N/A"

            # 3. Get status using porcelain v2 with NUL separator
            status_proc = await asyncio.create_subprocess_exec(
                "git", "status", "--porcelain=v2", "-z",
                cwd=str(self.repo_path),
                stdout=asyncio.subprocess.PIPE
            )
            status_out, _ = await status_proc.communicate()
            
            # Rebuild Staged & Unstaged lists using parsed entries
            staged, unstaged = self._parse_porcelain_v2(status_out)

            # Update Info Bar
            info_bar = self.query_one("#lbl-git-info", Label)
            info_bar.update(
                f"Branch: [bold cyan]{branch}[/bold cyan]  |  "
                f"Commit: [bold green]{commit_hash}[/bold green]  |  "
                f"Changes: [bold yellow]{len(staged) + len(unstaged)}[/bold yellow]"
            )

            # Rebuild Tree nodes
            self._rebuild_tree(staged, unstaged)
        finally:
            self.busy = False

    def _parse_porcelain_v2(
        self, raw_status: bytes
    ) -> tuple[list[GitChange], list[GitChange]]:
        """Parse NUL-separated porcelain v2 status entries."""
        staged: list[GitChange] = []
        unstaged: list[GitChange] = []
        if not raw_status:
            return staged, unstaged

        entries = raw_status.split(b"\x00")
        i = 0
        while i < len(entries):
            entry = entries[i]
            if not entry:
                i += 1
                continue

            prefix = entry[:1]
            if prefix == b"1":
                fields = entry.split(b" ", 8)
                if len(fields) != 9:
                    raise ValueError("malformed porcelain v2 type-1 record")
                xy, path_bytes = fields[1], fields[8]
            elif prefix == b"2":
                fields = entry.split(b" ", 9)
                if len(fields) != 10 or i + 1 >= len(entries):
                    raise ValueError("malformed porcelain v2 type-2 record")
                xy, path_bytes = fields[1], fields[9]
                i += 1  # Consume orig_path; retain it if rename UI needs it later.
            elif prefix == b"u":
                fields = entry.split(b" ", 10)
                if len(fields) != 11:
                    raise ValueError("malformed porcelain v2 unmerged record")
                xy, path_bytes = fields[1], fields[10]
            elif prefix == b"?":
                fields = entry.split(b" ", 1)
                if len(fields) != 2:
                    raise ValueError("malformed porcelain v2 untracked record")
                unstaged.append(GitChange(os.fsdecode(fields[1]), "?", False))
                i += 1
                continue
            else:
                i += 1  # Ignore ignored-file and optional header records.
                continue

            path = os.fsdecode(path_bytes)
            if xy[0:1] != b".":
                staged.append(GitChange(path, os.fsdecode(xy[0:1]), True))
            if xy[1:2] != b".":
                unstaged.append(GitChange(path, os.fsdecode(xy[1:2]), False))
            i += 1
        return staged, unstaged

    def _rebuild_tree(
        self, staged: list[GitChange], unstaged: list[GitChange]
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
        toggle.label = "Unstage Selected" if change.staged else "Stage Selected"
        toggle.disabled = self.busy
        self.show_file_diff(change.path, change.staged)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        change = event.node.data
        if isinstance(change, GitChange) and not self.busy:
            self._mutation_worker = self.toggle_stage_file(change.path, change.staged)

    # 4.4 Stage/Unstage Individual Node Action
    @work(exclusive=True, group="git-mutations")
    async def toggle_stage_file(self, path: str, is_staged: bool) -> None:
        if not self.repo_path or self.busy:
            return
        
        self.busy = True
        self.set_controls_disabled(True)
        log = self.query_one("#git-diff-viewer", RichLog)
        try:
            if is_staged:
                # Unstage file
                args = ["restore", "--staged", "--", path]
            else:
                # Stage file
                args = ["add", "--", path]

            self._active_subprocess = await asyncio.create_subprocess_exec(
                "git", *args,
                cwd=str(self.repo_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await self._active_subprocess.communicate()
            if self._active_subprocess.returncode != 0:
                log.write(
                    f"[red]Git operation failed: "
                    f"{stderr.decode(errors='replace')}[/red]"
                )
        except asyncio.CancelledError:
            log.write("[yellow]Git operation cancelled by user.[/yellow]")
        finally:
            self._active_subprocess = None
            self.busy = False
            self.set_controls_disabled(False)
            self.load_repo_status()

    # 4.5 Query File Diff (Staged vs Unstaged)
    @work(exclusive=True, group="git-queries")
    async def show_file_diff(self, path: str, is_staged: bool) -> None:
        if not self.repo_path:
            return
        
        log = self.query_one("#git-diff-viewer", RichLog)
        log.clear()

        # Ask Git whether this exact staged/unstaged delta is binary. This also
        # works for deleted files and staged blobs that differ from the worktree.
        numstat_args = ["diff"]
        if is_staged:
            numstat_args.append("--cached")
        numstat_args.extend(["--numstat", "--", path])
        binary_proc = await asyncio.create_subprocess_exec(
            "git", *numstat_args,
            cwd=str(self.repo_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        numstat, numstat_error = await binary_proc.communicate()
        if binary_proc.returncode != 0:
            log.write(
                f"[red]Failed to inspect diff: "
                f"{numstat_error.decode(errors='replace')}[/red]"
            )
            return
        if numstat.startswith(b"-\t-\t"):
            log.write("[yellow]Binary diff cannot be displayed inline.[/yellow]")
            return

        # Bound the diff output itself instead of checking the worktree file.
        # This covers staged content, deletions, and small files with huge diffs.
        args = ["diff"]
        if is_staged:
            args.append("--cached")
        args.extend(["--color=never", "--", path])

        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=str(self.repo_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        assert proc.stdout is not None
        stdout = await proc.stdout.read(100 * 1024 + 1)
        if len(stdout) > 100 * 1024:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            await proc.wait()
            log.write(
                "[yellow]Diff is too large to display inline "
                "(exceeds 100KB).[/yellow]"
            )
            return
        _, stderr = await proc.communicate()
        
        if proc.returncode == 0:
            diff_text = stdout.decode(errors="replace")
            if not diff_text.strip():
                log.write("[gray]No modifications found.[/gray]")
            else:
                # Render lines with basic color formatting
                for line in diff_text.splitlines():
                    if line.startswith("+"):
                        log.write(f"[green]{line}[/green]")
                    elif line.startswith("-"):
                        log.write(f"[red]{line}[/red]")
                    else:
                        log.write(line)
        else:
            log.write(f"[red]Failed to load diff: {stderr.decode().strip()}[/red]")

    # 4.6 Safe Mutation Subprocess Execution (Committing, Pushing, Pulling)
    @work(exclusive=True, group="git-mutations")
    async def run_git_command(self, args: list[str]) -> None:
        if not self.repo_path:
            return

        self.busy = True
        self.set_controls_disabled(True)
        log = self.query_one("#git-diff-viewer", RichLog)
        log.clear()
        
        log.write(f"[bold cyan]Running: git {shlex.join(args)}[/bold cyan]\n")

        # Disable interactive terminal prompts to prevent blocking forever
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"

        try:
            self._active_subprocess = await asyncio.create_subprocess_exec(
                "git", *args,
                cwd=str(self.repo_path),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )

            while True:
                line = await self._active_subprocess.stdout.readline()
                if not line:
                    break
                log.write(line.decode(errors="replace").rstrip())

            await self._active_subprocess.wait()

            if self._active_subprocess.returncode == 0:
                log.write("\n[bold green]Git operation succeeded.[/bold green]")
            else:
                log.write(f"\n[bold red]Git operation failed with exit code {self._active_subprocess.returncode}.[/bold red]")
        except asyncio.CancelledError:
            log.write("\n[bold yellow]Git operation cancelled by user.[/bold yellow]")
        finally:
            self._active_subprocess = None
            self.busy = False
            self.set_controls_disabled(False)
            self.load_repo_status()

    # 4.7 Event Dispatching
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-open-repo":
            path = self.query_one("#txt-repo-path", Input).value.strip()
            if path:
                self.validate_and_load_repo(path)
        elif event.button.id == "btn-git-cancel":
            await self.cancel_active_operation()
        elif event.button.id == "btn-git-toggle-stage":
            change = self._selected_change
            if change is not None and not self.busy:
                self._mutation_worker = self.toggle_stage_file(
                    change.path, change.staged
                )
        elif event.button.id == "btn-git-add-all":
            if not self.busy:
                self._mutation_worker = self.run_git_command(["add", "."])
        elif event.button.id == "btn-git-pull":
            if not self.busy:
                # pull safely using fast-forward-only
                self._mutation_worker = self.run_git_command(["pull", "--ff-only"])
        elif event.button.id == "btn-git-push":
            if not self.busy:
                self._mutation_worker = self.run_git_command(["push"])
        elif event.button.id == "btn-git-commit":
            if self.busy:
                return
            msg_input = self.query_one("#txt-commit-msg", Input)
            msg = msg_input.value.strip()
            if msg:
                msg_input.value = ""
                self._mutation_worker = self.run_git_command(["commit", "-m", msg])

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "txt-commit-msg":
            if self.busy:
                return
            msg = event.value.strip()
            if msg:
                event.input.value = ""
                self._mutation_worker = self.run_git_command(["commit", "-m", msg])
        elif event.input.id == "txt-repo-path":
            path = event.value.strip()
            if path:
                self.validate_and_load_repo(path)
