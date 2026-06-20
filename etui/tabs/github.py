# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
import json
import os
import re
import signal
from pathlib import Path
from urllib.parse import urlparse

from rich.markup import escape
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.worker import Worker, WorkerCancelled
from textual.widgets import Button, DataTable, Input, Label, RichLog

if __package__:
    from ..bus_contract import WorkspaceChanged
    from ..contracts import on_workspace_changed, workspace_get_root
else:  # pragma: no cover - script-mode import
    from bus_contract import WorkspaceChanged
    from contracts import on_workspace_changed, workspace_get_root


class GitHubTab(Vertical):
    """GitHub companion tab powered by the gh CLI."""

    PAGE_SIZE = 50
    VALID_HOSTS = {"github.com", "ssh.github.com"}

    DEFAULT_CSS = """
    GitHubTab {
        height: 1fr;
    }

    GitHubTab #github-navigation-bar {
        height: 3;
        background: $surface;
        border-bottom: solid $accent;
        align: left middle;
        padding: 0 1;
    }

    GitHubTab #github-main-split {
        height: 1fr;
    }

    GitHubTab #github-list-view {
        width: 40%;
        height: 1fr;
        border-right: solid $accent;
    }

    GitHubTab #github-detail-panel {
        width: 60%;
        height: 1fr;
    }

    GitHubTab #github-detail-log {
        height: 1fr;
        background: $boost;
    }

    GitHubTab #github-action-bar {
        height: 8;
        padding: 1;
        border-top: solid $accent;
    }

    GitHubTab #github-title, GitHubTab #github-body {
        width: 1fr;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.repo_path: Path | None = None
        self.repo_slug: str | None = None
        self.active_mode = "issues"
        self.busy = False
        self._limit = self.PAGE_SIZE
        self._cancel_requested = False
        self._active_subprocess: asyncio.subprocess.Process | None = None
        self._operation_worker: Worker[None] | None = None
        self._workspace_disposer = None

    def compose(self) -> ComposeResult:
        if __package__:
            from ..plugin import ToolWarningBanner
        else:
            from plugin import ToolWarningBanner
        yield ToolWarningBanner("gh", "GitHub CLI", id="gh-tool-warning")

        with Horizontal(id="github-navigation-bar"):
            yield Button("Issues", id="btn-mode-issues", variant="primary")
            yield Button("Pull Requests", id="btn-mode-prs")
            yield Button("Workflow Runs", id="btn-mode-runs")
            yield Label("", id="lbl-github-repo-slug")
        with Horizontal(id="github-main-split"):
            yield DataTable(id="github-list-view")
            with Vertical(id="github-detail-panel"):
                yield RichLog(id="github-detail-log", markup=True)
                with Vertical(id="github-action-bar"):
                    with Horizontal():
                        yield Input(placeholder="Title", id="github-title")
                        yield Input(placeholder="Body", id="github-body")
                    with Horizontal():
                        yield Button("Refresh", id="btn-github-refresh")
                        yield Button("Create Issue", id="btn-github-create")
                        yield Button(
                            "Cancel",
                            id="btn-github-cancel",
                            variant="warning",
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
        self.query_one(DataTable).add_columns("ID", "Title", "Status")
        self._set_controls_enabled(False)

    async def on_unmount(self) -> None:
        if self._workspace_disposer is not None:
            self._workspace_disposer()
            self._workspace_disposer = None
        await self.cancel_active_operation()

    def _on_workspace_changed(self, event) -> None:
        self.repo_path = Path(event.root).resolve()
        self.repo_slug = None
        try:
            self.query_one("#lbl-github-repo-slug", Label).update("")
        except Exception:
            pass

    async def change_repository(self, repo_path: Path) -> None:
        await self.cancel_active_operation()
        self.repo_path = repo_path.resolve()
        self.repo_slug = None
        self._limit = self.PAGE_SIZE
        self._start_operation(self._initialize(), "github-initialize")

    def _start_operation(self, coroutine, name: str) -> None:
        if self.busy:
            coroutine.close()
            return
        self._operation_worker = self.run_worker(
            coroutine,
            name=name,
            group="github-ops",
            exclusive=True,
            exit_on_error=False,
        )

    async def _initialize(self) -> None:
        if self.repo_path is None:
            return
        self.busy = True
        self._cancel_requested = False
        self._set_controls_enabled(False)
        log = self.query_one(RichLog)
        label = self.query_one("#lbl-github-repo-slug", Label)
        try:
            result, stdout, stderr = await self._capture_command(
                ["git", "remote", "-v"], timeout=5, cwd=self.repo_path
            )
            if result != 0:
                self._write_external_error("Unable to read remotes", stderr)
                return

            self.repo_slug = self.parse_github_remote(stdout.splitlines())
            if self.repo_slug is None:
                log.write(
                    "[yellow]No GitHub remote detected. This tab is disabled."
                    "[/yellow]"
                )
                label.update("")
                return
            label.update(Text(f"Repository: {self.repo_slug}"))

            result, _, stderr = await self._capture_command(
                ["gh", "auth", "status"], timeout=5
            )
            if result != 0:
                self._write_external_error(
                    "GitHub CLI authentication failed", stderr
                )
                return
            await self._query_list_data()
        except TimeoutError:
            log.write("[red]GitHub setup timed out.[/red]")
        except OSError as error:
            self._write_external_error("Unable to start Git or gh", str(error))
        except (UnicodeError, ValueError, json.JSONDecodeError) as error:
            self._write_external_error("Invalid command output", str(error))
        finally:
            self._active_subprocess = None
            self._operation_worker = None
            self.busy = False
            self._set_controls_enabled(self.repo_slug is not None)

    @classmethod
    def parse_github_remote(cls, lines: list[str]) -> str | None:
        candidates: dict[str, str] = {}
        scp_url = re.compile(
            r"^(?:[^@/]+@)?(?P<host>[^:/]+):(?P<path>[^?#]+)$"
        )
        for line in lines:
            fields = line.split()
            if len(fields) < 2 or (
                len(fields) >= 3 and fields[2] != "(fetch)"
            ):
                continue
            name, remote_url = fields[0], fields[1]
            match = scp_url.fullmatch(remote_url)
            if match and "://" not in remote_url:
                host = match.group("host").lower()
                path = match.group("path")
            else:
                parsed = urlparse(remote_url)
                host = (parsed.hostname or "").lower()
                path = parsed.path.lstrip("/")

            segments = path.removesuffix(".git").split("/")
            if host in cls.VALID_HOSTS and len(segments) == 2 and all(segments):
                candidates.setdefault(name, "/".join(segments))

        for preferred in ("upstream", "origin"):
            if preferred in candidates:
                return candidates[preferred]
        return next(iter(candidates.values()), None)

    async def _query_list_data(self) -> None:
        assert self.repo_slug is not None
        requested = self._limit + 1
        if self.active_mode == "issues":
            args = [
                "gh", "issue", "list", "--repo", self.repo_slug,
                "--limit", str(requested),
                "--json", "number,title,state",
            ]
        elif self.active_mode == "prs":
            args = [
                "gh", "pr", "list", "--repo", self.repo_slug,
                "--limit", str(requested),
                "--json", "number,title,state",
            ]
        else:
            args = [
                "gh", "run", "list", "--repo", self.repo_slug,
                "--limit", str(requested),
                "--json", "databaseId,name,status,conclusion",
            ]

        result, stdout, stderr = await self._capture_command(args, timeout=10)
        table = self.query_one(DataTable)
        table.clear()
        if result != 0:
            self._show_query_error(stderr)
            return

        items = json.loads(stdout)
        has_more = len(items) > self._limit
        items = items[:self._limit]
        if not items:
            table.add_row("-", Text(f"No {self.active_mode} found."), "-")
            return

        for item in items:
            if self.active_mode == "workflows":
                item_id = str(item["databaseId"])
                title = str(item.get("name") or "")
                state = str(item.get("conclusion") or item.get("status") or "")
            else:
                item_id = f"#{item['number']}"
                title = str(item.get("title") or "")
                state = str(item.get("state") or "")
            table.add_row(Text(item_id), Text(title), Text(state))

        if has_more:
            table.add_row(
                "+",
                Text(f"Load {self.PAGE_SIZE} more..."),
                "",
                key="__load_more__",
            )

    async def _load_item_details(self, item_id: str) -> None:
        assert self.repo_slug is not None
        cleaned_id = item_id.removeprefix("#")
        if not cleaned_id.isdecimal():
            raise ValueError("invalid GitHub item identifier")
        if self.active_mode == "issues":
            args = [
                "gh", "issue", "view", cleaned_id,
                "--repo", self.repo_slug, "--comments",
            ]
        elif self.active_mode == "prs":
            args = [
                "gh", "pr", "view", cleaned_id,
                "--repo", self.repo_slug, "--comments",
            ]
        else:
            args = [
                "gh", "run", "view", cleaned_id, "--repo", self.repo_slug
            ]
        result, stdout, stderr = await self._capture_command(args, timeout=10)
        log = self.query_one(RichLog)
        log.clear()
        if result == 0:
            log.write(escape(stdout))
        else:
            self._show_query_error(stderr)

    @staticmethod
    def _validate_text(value: str, field: str) -> str:
        value = value.strip()
        if not value or value.startswith("-"):
            raise ValueError(f"{field} is empty or begins with '-'")
        return value

    async def _create_issue(self, title: str, body: str) -> None:
        title = self._validate_text(title, "title")
        body = self._validate_text(body, "body")
        await self._run_mutation(
            ["gh", "issue", "create", "--repo", self.repo_slug,
             "--title", title, "--body", body]
        )

    async def _create_pr(self, title: str, body: str) -> None:
        title = self._validate_text(title, "title")
        body = self._validate_text(body, "body")
        await self._run_mutation(
            ["gh", "pr", "create", "--repo", self.repo_slug,
             "--title", title, "--body", body]
        )

    async def _run_mutation(self, command: list[str]) -> None:
        result, stdout, stderr = await self._capture_command(
            command, timeout=60
        )
        if result == 0:
            self.query_one(RichLog).write(escape(stdout))
            await self._query_list_data()
        else:
            self._show_query_error(stderr)

    async def _run_guarded(self, action) -> None:
        self.busy = True
        self._cancel_requested = False
        self._set_controls_enabled(False)
        try:
            await action
        except asyncio.CancelledError:
            self.query_one(RichLog).write("[yellow]Operation cancelled.[/yellow]")
            raise
        except TimeoutError:
            self.query_one(RichLog).write("[red]GitHub operation timed out.[/red]")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self._write_external_error("GitHub operation failed", str(error))
        finally:
            self._active_subprocess = None
            self._operation_worker = None
            self.busy = False
            self._set_controls_enabled(self.repo_slug is not None)

    async def _capture_command(
        self,
        command: list[str],
        *,
        timeout: float,
        cwd: Path | None = None,
    ) -> tuple[int, str, str]:
        cmd_args = list(command)
        if cmd_args:
            exe = cmd_args[0]
            if hasattr(self.app, "tool_registry"):
                res = self.app.tool_registry.get_result(exe)
                if res and res.state.value == "Installed":
                    primary_exe = res.executables[0] if res.executables else None
                    if primary_exe and primary_exe.path:
                        cmd_args[0] = primary_exe.path

        process = await asyncio.create_subprocess_exec(
            *cmd_args,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=(os.name == "posix"),
        )
        self._active_subprocess = process
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout
            )
            return (
                process.returncode or 0,
                stdout.decode(errors="replace"),
                stderr.decode(errors="replace"),
            )
        except (TimeoutError, asyncio.CancelledError):
            await self._terminate_active_subprocess()
            raise
        finally:
            if self._active_subprocess is process:
                self._active_subprocess = None

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
            await asyncio.wait_for(process.wait(), timeout=3)
        except TimeoutError:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                return
            await process.wait()

    def _set_controls_enabled(self, enabled: bool) -> None:
        if not self.is_mounted:
            return
        from textual.css.query import NoMatches
        try:
            for selector in (
                "#btn-mode-issues", "#btn-mode-prs", "#btn-mode-runs",
                "#btn-github-refresh", "#github-title", "#github-body",
            ):
                self.query_one(selector).disabled = not enabled
            create = self.query_one("#btn-github-create", Button)
            create.disabled = not enabled or self.active_mode == "workflows"
            create.label = (
                "Create Pull Request" if self.active_mode == "prs"
                else "Create Issue"
            )
            self.query_one("#btn-github-cancel", Button).disabled = not self.busy
        except NoMatches:
            pass

    def _write_external_error(self, prefix: str, detail: str) -> None:
        self.query_one(RichLog).write(
            f"[red]{escape(prefix)}:[/red] {escape(detail.strip())}"
        )

    def _show_query_error(self, stderr: str) -> None:
        lowered = stderr.lower()
        if "rate limit" in lowered or "http 403" in lowered:
            self._write_external_error(
                "GitHub API rate limit reached", stderr
            )
        else:
            self._write_external_error("GitHub query failed", stderr)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "btn-github-cancel":
            await self.cancel_active_operation()
            return
        if self.busy or self.repo_slug is None:
            return
        if button_id in {"btn-mode-issues", "btn-mode-prs", "btn-mode-runs"}:
            self.active_mode = {
                "btn-mode-issues": "issues",
                "btn-mode-prs": "prs",
                "btn-mode-runs": "workflows",
            }[button_id]
            self._limit = self.PAGE_SIZE
            self._start_operation(
                self._run_guarded(self._query_list_data()),
                "github-change-mode",
            )
        elif button_id == "btn-github-refresh":
            self._start_operation(
                self._run_guarded(self._query_list_data()),
                "github-refresh",
            )
        elif button_id == "btn-github-create":
            title = self.query_one("#github-title", Input).value
            body = self.query_one("#github-body", Input).value
            mutation = (
                self._create_pr(title, body)
                if self.active_mode == "prs"
                else self._create_issue(title, body)
            )
            self._start_operation(
                self._run_guarded(mutation), "github-create"
            )

    def on_data_table_row_selected(
        self, event: DataTable.RowSelected
    ) -> None:
        if self.busy or self.repo_slug is None:
            return
        if str(event.row_key.value) == "__load_more__":
            self._limit += self.PAGE_SIZE
            action = self._query_list_data()
            name = "github-load-more"
        else:
            item_id = str(self.query_one(DataTable).get_row(event.row_key)[0])
            if item_id == "-":
                return
            action = self._load_item_details(item_id)
            name = "github-load-details"
        self._start_operation(self._run_guarded(action), name)
