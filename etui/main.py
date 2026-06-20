# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("etui.main")

from .version import COPYRIGHT  # noqa: F401 — re-exported for callers

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, RichLog
from textual.widgets import Input
from textual.widgets import TabbedContent, TabPane
from textual.message import Message

if __package__:
    from .tabs.help import HelpTab, OpenDocFile
    from .tabs.about import AboutTab
    from .tabs.console import ConsoleTab
    from .tabs.files import FilesTab
    from .tabs.probe import ProbeTab, LldbStart
    from .tabs.lldb import LldbTab, ProbeRestartRequested
    from .tabs.theme import ThemeTab
    from .tabs.serial import SerialTab
    from .tabs.venv import VenvTab
    from .tabs.git import GitTab, RepositoryChanged
    from .tabs.github import GitHubTab
    from .tabs.cmake import CMakeTab
    from .tabs.tools import ToolsTab
    from .tabs.settings import SettingsTab
    from .tabs.workflow import WorkflowTab
    from .settings import SettingsManager
    from .bus import MessageBus
    from .bus_contract import (
        SVC_CONSOLE_RUN,
        SVC_HELP_ADD_ENTRY,
        SVC_NAV_ACTIVATE,
        SVC_SETTINGS_GET,
        SVC_SETTINGS_SET,
        SVC_THEME_GET,
        SVC_THEME_SET,
        SVC_WORKSPACE_GET_ROOT,
        SVC_WORKSPACE_SET_ROOT,
        TOPIC_TAB_ACTIVATED,
        TOPIC_TAB_DEACTIVATED,
        TOPIC_THEME_CHANGED,
        TOPIC_WORKSPACE_CHANGED,
        TabEvent,
        ThemeChanged,
        WorkspaceChanged,
    )
else:
    from tabs.help import HelpTab, OpenDocFile
    from tabs.about import AboutTab
    from tabs.console import ConsoleTab
    from tabs.files import FilesTab
    from tabs.probe import ProbeTab, LldbStart
    from tabs.lldb import LldbTab, ProbeRestartRequested
    from tabs.theme import ThemeTab
    from tabs.serial import SerialTab
    from tabs.venv import VenvTab
    from tabs.git import GitTab, RepositoryChanged
    from tabs.github import GitHubTab
    from tabs.cmake import CMakeTab
    from tabs.tools import ToolsTab
    from tabs.settings import SettingsTab
    from tabs.workflow import WorkflowTab
    from settings import SettingsManager
    from bus import MessageBus
    from bus_contract import (
        SVC_CONSOLE_RUN,
        SVC_HELP_ADD_ENTRY,
        SVC_NAV_ACTIVATE,
        SVC_SETTINGS_GET,
        SVC_SETTINGS_SET,
        SVC_THEME_GET,
        SVC_THEME_SET,
        SVC_WORKSPACE_GET_ROOT,
        SVC_WORKSPACE_SET_ROOT,
        TOPIC_TAB_ACTIVATED,
        TOPIC_TAB_DEACTIVATED,
        TOPIC_THEME_CHANGED,
        TOPIC_WORKSPACE_CHANGED,
        TabEvent,
        ThemeChanged,
        WorkspaceChanged,
    )

class CommandMessage(Message):
    def __init__(self ,command: str) -> None:
        super().__init__()
        self.command = command

class EtuiApp(App):
    """ Embedded TUI App"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if __package__:
            from .tabs.tools import ToolRegistry
        else:
            from tabs.tools import ToolRegistry
        self.settings_manager = SettingsManager()
        self.tool_registry = ToolRegistry(self)
        self._last_active_tab = "files"
        self.workspace_root = self.load_workspace_root()
        self.bus = MessageBus()
        # App-owned services that don't belong to any single tab.
        self.bus.provide(SVC_NAV_ACTIVATE, self._svc_activate_tab)
        self.bus.provide(SVC_SETTINGS_GET, self._svc_settings_get)
        self.bus.provide(SVC_SETTINGS_SET, self._svc_settings_set)
        self.bus.provide(SVC_WORKSPACE_GET_ROOT, self._svc_workspace_get_root)
        self.bus.provide(SVC_WORKSPACE_SET_ROOT, self._svc_workspace_set_root)
        self.bus.provide(SVC_THEME_GET, self._svc_theme_get)
        self.bus.provide(SVC_THEME_SET, self._svc_theme_set)

        # Discover plugins
        if __package__:
            from .plugins import PluginManager
        else:
            from plugins import PluginManager
        self.plugins = PluginManager()
        self.plugins.discover()

    async def _svc_activate_tab(self, tab_id: str) -> None:
        """Bus service: switch the active tab. Lets tabs request navigation
        without reaching into TabbedContent themselves."""
        self.query_one(TabbedContent).active = tab_id

    async def _svc_settings_get(self, section: str, key: str, default: Any = None) -> Any:
        """Bus service: get a settings value."""
        return self.settings_manager.get(section, key, default)

    async def _svc_settings_set(self, section: str, key: str, value: Any) -> None:
        """Bus service: set a settings value."""
        self.settings_manager.set(section, key, value)

    async def _svc_workspace_get_root(self) -> str:
        """Bus service: get the current workspace root."""
        return self.workspace_root or str(Path.cwd())

    async def _svc_workspace_set_root(self, path: str, persist: bool = True) -> None:
        """Bus service: set the host-owned workspace root."""
        await self.set_workspace_root(path, persist=persist)

    async def _svc_theme_get(self) -> str:
        """Bus service: get the current LLDB dashboard theme."""
        return self.settings_manager.get("lldb", "theme", "vibrant")

    async def _svc_theme_set(self, name: str) -> None:
        """Bus service: set the LLDB dashboard theme and notify tabs."""
        try:
            self.settings_manager.set("lldb", "theme", name)
        except OSError:
            pass
        await self.query_one(LldbTab).set_theme(name)
        self.bus.emit(TOPIC_THEME_CHANGED, ThemeChanged(name=name), source="app")


    CSS = """
        TabbedContent {
            height: 1fr;
        }

        Input {
            height: 3;
        }

        #main-input {
            display: none;
        }

        /* Push the Theme and About tabs to the far right of the tab bar. */
        #--content-tab-about {
            dock: right;
        }
        #--content-tab-theme {
            dock: right;
            margin-right: 7;
        }

        .control-bar {
            height: 3;
            align: left middle;
            padding: 0 1;
        }

        .control-label {
            margin-top: 1;
            margin-right: 1;
        }
        
        #serial-port {
            width: 40;
        }
        
        #serial-baud {
            width: 20;
        }

        #serial-connect {
            width: 15;
            margin-left: 1;
        }
    """

    def load_workspace_root(self) -> str | None:
        return self.settings_manager.get("workspace", "root") or None

    def save_workspace_root(self, path: str) -> None:
        try:
            self.settings_manager.set("workspace", "root", path)
        except OSError:
            pass

    async def set_workspace_root(
        self, path: str, update_files: bool = True, persist: bool = True
    ) -> None:
        self.workspace_root = path
        if persist:
            self.save_workspace_root(path)
        if update_files:
            try:
                files_tab = self.query_one(FilesTab)
                files_tab.query_one("LeftWidget").path = Path(path)
                files_tab.query_one("#txt-workspace-root", Input).value = path
            except Exception:
                pass
        if update_files:
            self.bus.emit(
                TOPIC_WORKSPACE_CHANGED,
                WorkspaceChanged(root=path),
                source="app",
            )

    async def on_mount(self) -> None:
        await self._mount_plugin_tabs()

        probe_tab = self.query_one(ProbeTab)
        probe_tab.apply_settings(self.settings_manager.settings["probe"])
        wrap = bool(self.settings_manager.get("ui", "word_wrap", False))
        for log in self.query(RichLog):
            log.wrap = wrap
        await self.query_one(LldbTab).set_theme(
            self.settings_manager.get("lldb", "theme", "vibrant")
        )
        # Always start from the process CWD; offer to restore the previously
        # saved workspace root if it still exists and differs from CWD.
        saved = self.workspace_root
        cwd = str(Path.cwd())
        await self.set_workspace_root(cwd, update_files=False, persist=False)
        if saved and Path(saved).is_dir() and saved != cwd:
            self.notify(
                f"Previous workspace: {saved}",
                title="Restore workspace?",
                timeout=12,
                action="restore_workspace",
            )

    async def _mount_plugin_tabs(self) -> None:
        missing_services = [
            service
            for service in (
                SVC_NAV_ACTIVATE,
                SVC_SETTINGS_GET,
                SVC_SETTINGS_SET,
                SVC_HELP_ADD_ENTRY,
                SVC_CONSOLE_RUN,
                SVC_WORKSPACE_GET_ROOT,
                SVC_WORKSPACE_SET_ROOT,
            )
            if not self.bus.has(service)
        ]
        if missing_services:
            self.plugins.errors.append(
                (
                    "host-services",
                    f"missing host service(s) before plugin mount: {', '.join(missing_services)}",
                )
            )
            logger.error(
                "missing host service(s) before plugin mount: %s",
                ", ".join(missing_services),
            )
            self.notify(
                "Plugin host services are not ready; plugin tabs were not mounted",
                severity="error",
            )
            return

        # Mount plugin tabs
        tabs = self.query_one(TabbedContent)
        for lp in self.plugins.loaded:
            try:
                widget = lp.plugin.create_widget()

                # Instantiate and assign ScopedBus
                if __package__:
                    from .plugins import ScopedBus
                else:
                    from plugins import ScopedBus
                lp.scoped_bus = ScopedBus(self.bus, lp.spec.id)
                widget._bus = lp.scoped_bus

                target = lp.spec.after
                has_target = False
                if target:
                    try:
                        tabs.get_pane(target)
                        has_target = True
                    except Exception:
                        pass

                kwargs = {"after": target} if has_target else {}
                await tabs.add_pane(TabPane(lp.spec.title, widget, id=lp.spec.id), **kwargs)

                # Register help document if specified and it exists
                if lp.spec.help_doc and lp.spec.help_doc.is_file():
                    if self.bus.has(SVC_HELP_ADD_ENTRY):
                        await self.bus.call(SVC_HELP_ADD_ENTRY, title=lp.spec.title, path=lp.spec.help_doc)

                logger.info("mounted plugin tab %s (%s)", lp.spec.id, lp.dist)
            except Exception as exc:
                self.plugins.errors.append((lp.name, f"mount failed: {exc!r}"))
                logger.exception("failed to mount plugin %s", lp.spec.id)

        if self.plugins.errors:
            self.notify(
                f"{len(self.plugins.errors)} plugin(s) failed to load; see logs",
                severity="error",
            )

    def on_unmount(self) -> None:
        """Clean up plugin bus registrations on app teardown."""
        for lp in self.plugins.loaded:
            if lp.scoped_bus:
                lp.scoped_bus.dispose_all()
        super_unmount = getattr(super(), "on_unmount", None)
        if super_unmount is not None:
            super_unmount()

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="files"):
            with TabPane("Files", id="files"):
                yield FilesTab()
            with TabPane("Console", id="console"):
                yield ConsoleTab()
            with TabPane("Tools", id="tools"):
                yield ToolsTab(
                    [
                        Path(path)
                        for path in self.settings_manager.get(
                            "tools", "custom_paths", []
                        )
                    ]
                )
            with TabPane("Git", id="git"):
                yield GitTab()
            with TabPane("GitHub", id="github"):
                yield GitHubTab()
            with TabPane("CMake", id="cmake"):
                yield CMakeTab()
            with TabPane("Workflow", id="workflow"):
                yield WorkflowTab()
            with TabPane("Serial", id="serial"):
                yield SerialTab()
            with TabPane("Probe", id="probe"):
                yield ProbeTab()
            with TabPane("LLDB", id="lldb"):
                yield LldbTab(settings=self.settings_manager.settings["lldb"])
            with TabPane("Venv", id="venv"):
                yield VenvTab()
            with TabPane("Settings", id="settings"):
                yield SettingsTab()
            with TabPane("Theme", id="theme"):
                yield ThemeTab(
                    self.settings_manager.get("lldb", "theme", "vibrant")
                )
            with TabPane("About", id="about"):
                yield AboutTab()
            with TabPane("Help", id="help"):
                yield HelpTab()
        yield Input(id="main-input")
        yield Footer()

    # dispatch commands based on the first character
    # if "/" it is a built-in command otherwise it is shell command  
    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Only the main command input drives command dispatch. Submissions from
        # any other Input (tab search boxes, the workflow password dialog, …)
        # must never be treated as shell commands — that would leak their value
        # (e.g. a sudo password) into the console in plaintext.
        if event.input.id != "main-input":
            return
        command = event.value.strip()
        if not command:
            return
        #self.notify(f"Posting command messafge {command}")
        self.post_message(CommandMessage(command))
        event.input.value=""

    async def on_lldb_start(self, message: LldbStart) -> None:
        # The LLDB tab is always present; (re)connect it to the gdb server.
        lldb = self.query_one(LldbTab)
        await lldb.connect(message.port, message.arch)
        self.query_one(TabbedContent).active = "lldb"

    async def on_probe_restart_requested(
        self, message: ProbeRestartRequested
    ) -> None:
        await self.query_one(ProbeTab).restart_for_lldb()

    def on_open_doc_file(self, message: OpenDocFile) -> None:
        self.query_one(TabbedContent).active = "files"
        self.query_one(FilesTab).open_file(message.path)


    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        # Focus the appropriate input/widget when tabs are switched
        pane_id = event.pane.id
        old_pane_id = getattr(self, "_last_active_tab", None)
        self._last_active_tab = pane_id
        
        # Emit tab change lifecycle events on the bus only if changed
        if old_pane_id != pane_id:
            if old_pane_id:
                self.bus.emit(TOPIC_TAB_DEACTIVATED, TabEvent(pane_id=old_pane_id), source="app")
            self.bus.emit(TOPIC_TAB_ACTIVATED, TabEvent(pane_id=pane_id), source="app")
        
        # Show main-input only for serial tab, hide for all others
        try:
            self.query_one("#main-input").display = (pane_id == "serial")
        except Exception:
            pass

        # Update any tool warning banners in the active pane
        try:
            if __package__:
                from .tabs.tools import ToolWarningBanner
            else:
                from tabs.tools import ToolWarningBanner
            for banner in event.pane.query(ToolWarningBanner):
                banner.check_status()
        except Exception:
            pass

        if pane_id == "files":
            try:
                self.query_one("LeftWidget").focus()
            except Exception:
                pass
        elif pane_id == "console":
            try:
                self.query_one("#console-terminal").focus()
            except Exception:
                pass
        elif pane_id == "serial":
            try:
                self.query_one("#main-input").focus()
            except Exception:
                pass
        elif pane_id == "probe":
            try:
                self.query_one("#dbg-input").focus()
            except Exception:
                pass
        elif pane_id == "lldb":
            try:
                self.query_one("#lldb-input").focus()
            except Exception:
                pass
        elif pane_id == "git":
            try:
                self.query_one("#txt-repo-path").focus()
            except Exception:
                pass
        elif pane_id == "github":
            try:
                self.query_one("#btn-mode-issues").focus()
            except Exception:
                pass
        elif pane_id == "cmake":
            try:
                self.query_one("#txt-cmake-build").focus()
            except Exception:
                pass
        elif pane_id == "workflow":
            try:
                self.query_one("#workflow-select").focus()
            except Exception:
                pass
        elif pane_id == "tools":
            try:
                self.query_one("#tools-table").focus()
            except Exception:
                pass
        elif pane_id == "venv":
            try:
                self.query_one("#venv-project-path").focus()
            except Exception:
                pass
        elif pane_id == "settings":
            try:
                self.query_one("#settings-categories").focus()
            except Exception:
                pass

        if old_pane_id == "venv" and pane_id != "venv":
            try:
                venv_tab = self.query_one(VenvTab)
                if venv_tab.is_busy:
                    self.run_worker(
                        venv_tab.cancel_active_operation(),
                        name="cancel-venv-operation",
                        exit_on_error=False,
                    )
            except Exception:
                pass

        if old_pane_id == "git" and pane_id != "git":
            try:
                git_tab = self.query_one(GitTab)
                if git_tab.busy:
                    self.run_worker(
                        git_tab.cancel_active_operation(),
                        name="cancel-git-operation",
                        exit_on_error=False,
                    )
            except Exception:
                pass

        if old_pane_id == "github" and pane_id != "github":
            try:
                github_tab = self.query_one(GitHubTab)
                if github_tab.busy:
                    self.run_worker(
                        github_tab.cancel_active_operation(),
                        name="cancel-github-operation",
                        exit_on_error=False,
                    )
            except Exception:
                pass

        if old_pane_id == "cmake" and pane_id != "cmake":
            try:
                cmake_tab = self.query_one(CMakeTab)
                if cmake_tab.busy:
                    self.run_worker(
                        cmake_tab.cancel_active_operation(),
                        name="cancel-cmake-operation",
                        exit_on_error=False,
                    )
            except Exception:
                pass


        if old_pane_id == "tools" and pane_id != "tools":
            try:
                tools_tab = self.query_one(ToolsTab)
                if tools_tab.busy:
                    self.run_worker(
                        tools_tab.cancel_active_operation(),
                        name="cancel-tools-operation",
                        exit_on_error=False,
                    )
            except Exception:
                pass

    def on_command_message(self, message: CommandMessage) -> None:
        tabs = self.query_one(TabbedContent)
        if tabs.active == "serial":
            serial = self.query_one(SerialTab)
            serial.send_data(message.command)
        else:
            tabs.active = "console"
            #self.notify(f"Got command message {message.command}")
            console = self.query_one(ConsoleTab)
            self.run_worker(console.run_command(message.command))

    async def on_repository_changed(self, message: RepositoryChanged) -> None:
        await self.set_workspace_root(message.path, update_files=True)

    async def action_restore_workspace(self) -> None:
        saved = self.settings_manager.get("workspace", "root")
        if saved and Path(saved).is_dir():
            await self.set_workspace_root(saved, update_files=True)

    

def _setup_debug_logging() -> Path:
    """Route ``etui`` loggers (incl. the message bus) to a debug file.

    The app is a full-screen TUI, so debug output must not go to stdout/stderr.
    Returns the log file path. Idempotent.
    """
    import logging

    log_path = Path(os.environ.get("ETUI_DEBUG_LOG", "etui-debug.log")).expanduser()
    logger = logging.getLogger("etui")
    logger.setLevel(logging.DEBUG)
    already = any(
        isinstance(h, logging.FileHandler)
        and getattr(h, "_etui_debug", False)
        for h in logger.handlers
    )
    if not already:
        handler = logging.FileHandler(log_path)
        handler._etui_debug = True  # type: ignore[attr-defined]
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        logger.addHandler(handler)
        logger.propagate = False
    logger.debug("debug logging enabled -> %s", log_path)
    return log_path


def main():
    if "--debug" in sys.argv:
        sys.argv = [a for a in sys.argv if a != "--debug"]
        path = _setup_debug_logging()
        print(f"[etui] debug logging -> {path}")

    if len(sys.argv) >= 3 and sys.argv[1] == "--etui-xonsh-command":
        from xonsh.main import main as xonsh_main

        xonsh_main(["--no-rc", "-c", sys.argv[2]])
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "--screenshots":
        _run_screenshots(Path(sys.argv[2]) if len(sys.argv) >= 3 else None)
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test":
        _run_self_test()
        return

    print("Hello from etui!")
    app = EtuiApp()
    app.run()


def _run_screenshots(output_dir: Path | None) -> None:
    """Run the app, capture one screenshot per tab, print results, then exit."""
    if __package__:
        from .tabs.about import capture_screenshots, DEFAULT_SCREENSHOT_DIR
    else:
        from tabs.about import capture_screenshots, DEFAULT_SCREENSHOT_DIR

    dest = output_dir or DEFAULT_SCREENSHOT_DIR
    results: dict[str, object] = {}

    app = EtuiApp()

    async def _after_mount() -> None:
        saved, failed = await capture_screenshots(app, dest)
        results["saved"] = saved
        results["failed"] = failed
        app.exit()

    app.call_after_refresh(_after_mount)
    app.run()

    saved = results.get("saved", [])
    failed = results.get("failed", [])
    for tab_id in saved:
        print(f"  saved  {dest / (tab_id + '.svg')}")
    for entry in failed:
        print(f"  FAILED {entry}", file=sys.stderr)
    print(f"{len(saved)} screenshots written to {dest}")

def _run_self_test() -> None:
    """Run built-in self-tests, print results, and exit 0/1."""
    if __package__:
        from .self_test import run_all
    else:
        from self_test import run_all

    results = run_all()
    passed = sum(r.passed for r in results)
    total = len(results)
    for r in results:
        tag = "PASS" if r.passed else "FAIL"
        print(f"  {tag}  {r.name}: {r.message}")
    print(f"\n{passed}/{total} passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
