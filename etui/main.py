# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("etui.main")
CORE_TAB_IDS = {"files", "console", "settings", "theme", "about", "help", "plugin-venv", "plugin-manager"}

if __package__:
    from .version import COPYRIGHT  # noqa: F401 — re-exported for callers
else:
    from version import COPYRIGHT  # noqa: F401 — re-exported for callers

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, RichLog
from textual.widgets import Input
from textual.widgets import TabbedContent, TabPane
from textual.message import Message
from textual.screen import ModalScreen

if __package__:
    from .tabs.help import HelpTab, OpenDocFile
    from .tabs.about import AboutTab
    from .tabs.console import ConsoleTab
    from .tabs.files import FilesTab
    from .tabs.venv import VenvTab
    from .tabs.plugin_manager import PluginManagerTab
    from .tabs.theme import ThemeTab
    from .tabs.settings import SettingsTab
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
        TOPIC_REPO_CHANGED,
        TOPIC_SETTINGS_CHANGED,
        TOPIC_TAB_ACTIVATED,
        TOPIC_TAB_DEACTIVATED,
        TOPIC_THEME_CHANGED,
        TOPIC_WORKSPACE_CHANGED,
        RepoChanged,
        SettingsChanged,
        TabEvent,
        ThemeChanged,
        WorkspaceChanged,
        SVC_PLUGINS_LIST,
        SVC_PLUGINS_INSTALL,
        SVC_PLUGINS_UNINSTALL,
        SVC_PLUGINS_SET_ENABLED,
        SVC_PLUGINS_SET_ORDER,
        SVC_PLUGINS_RELOAD,
        SVC_SETTINGS_FOCUS_SECTION,
        TOPIC_PLUGINS_INSTALL_PROGRESS,
        PluginInstallProgress,
    )
else:
    from tabs.help import HelpTab, OpenDocFile
    from tabs.about import AboutTab
    from tabs.console import ConsoleTab
    from tabs.files import FilesTab
    from tabs.venv import VenvTab
    from tabs.plugin_manager import PluginManagerTab
    from tabs.theme import ThemeTab
    from tabs.settings import SettingsTab
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
        TOPIC_REPO_CHANGED,
        TOPIC_SETTINGS_CHANGED,
        TOPIC_TAB_ACTIVATED,
        TOPIC_TAB_DEACTIVATED,
        TOPIC_THEME_CHANGED,
        TOPIC_WORKSPACE_CHANGED,
        RepoChanged,
        SettingsChanged,
        TabEvent,
        ThemeChanged,
        WorkspaceChanged,
        SVC_PLUGINS_LIST,
        SVC_PLUGINS_INSTALL,
        SVC_PLUGINS_UNINSTALL,
        SVC_PLUGINS_SET_ENABLED,
        SVC_PLUGINS_SET_ORDER,
        SVC_PLUGINS_RELOAD,
        SVC_SETTINGS_FOCUS_SECTION,
        TOPIC_PLUGINS_INSTALL_PROGRESS,
        PluginInstallProgress,
    )

class CommandMessage(Message):
    def __init__(self ,command: str) -> None:
        super().__init__()
        self.command = command

class EtuiApp(App):
    """ Embedded TUI App"""

    def __init__(self, *args, startup_workspace_root: str | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.settings_manager = SettingsManager()
        self._last_active_tab = "files"
        self.startup_workspace_root = startup_workspace_root
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

        # Register new plugin manager services
        self.bus.provide(SVC_PLUGINS_LIST, self._svc_plugins_list)
        self.bus.provide(SVC_PLUGINS_INSTALL, self._svc_plugins_install)
        self.bus.provide(SVC_PLUGINS_UNINSTALL, self._svc_plugins_uninstall)
        self.bus.provide(SVC_PLUGINS_SET_ENABLED, self._svc_plugins_set_enabled)
        self.bus.provide(SVC_PLUGINS_SET_ORDER, self._svc_plugins_set_order)
        self.bus.provide(SVC_PLUGINS_RELOAD, self._svc_plugins_reload)
        self.bus.provide(SVC_SETTINGS_FOCUS_SECTION, self._svc_settings_focus_section)

        # Load user plugins target directories to sys.path
        self.load_user_plugins_sys_path()

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

    async def _svc_settings_set(self, section: str, key: str, value: Any, source: str = "host") -> None:
        """Bus service: set a settings value."""
        self.settings_manager.set(section, key, value)
        self.bus.emit(
            TOPIC_SETTINGS_CHANGED,
            SettingsChanged(section=section, key=key, source=source),
            source="app",
        )

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
        self.bus.subscribe(TOPIC_REPO_CHANGED, self._on_repo_changed)
        await self._mount_plugin_tabs()

        wrap = bool(self.settings_manager.get("ui", "word_wrap", False))
        for log in self.query(RichLog):
            log.wrap = wrap
        # Start from the explicit CLI workspace if provided, otherwise from
        # the process CWD. Only offer restore when startup was implicit.
        saved = self.workspace_root
        startup_root = self.startup_workspace_root or str(Path.cwd())
        await self.set_workspace_root(startup_root, update_files=True, persist=False)
        if (
            self.startup_workspace_root is None
            and saved
            and Path(saved).is_dir()
            and saved != startup_root
        ):
            self.notify(
                f"Previous workspace: {saved}",
                title="Restore workspace?",
                timeout=12,
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
        
        disabled_set = set(self.settings_manager.get("plugins", "disabled", []))
        self.plugins.loaded = self._ordered_loaded_plugins()

        for lp in self.plugins.loaded:
            if lp.spec.id in disabled_set:
                continue
            try:
                widget = lp.plugin.create_widget()

                # Instantiate and assign ScopedBus
                if __package__:
                    from .plugins import ScopedBus
                else:
                    from plugins import ScopedBus
                lp.scoped_bus = ScopedBus(self.bus, lp.spec.id, lp.spec.provides)
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
                if lp.scoped_bus:
                    lp.scoped_bus.dispose_all()
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
            with TabPane("Settings", id="settings"):
                yield SettingsTab()
            with TabPane("Venv", id="plugin-venv"):
                yield VenvTab()
            with TabPane("Plugins", id="plugin-manager"):
                yield PluginManagerTab()
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
            self.query_one("#main-input").display = (pane_id == "plugin-serial")
        except Exception:
            pass

        # Update any tool warning banners in the active pane
        try:
            if __package__:
                from .plugin import ToolWarningBanner
            else:
                from plugin import ToolWarningBanner
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
        elif pane_id == "plugin-serial":
            try:
                self.query_one("#main-input").focus()
            except Exception:
                pass
        elif pane_id == "plugin-probe":
            try:
                self.query_one("#dbg-input").focus()
            except Exception:
                pass
        elif pane_id == "plugin-lldb":
            try:
                self.query_one("#lldb-input").focus()
            except Exception:
                pass
        elif pane_id == "plugin-git":
            try:
                self.query_one("#txt-repo-path").focus()
            except Exception:
                pass
        elif pane_id == "plugin-github":
            try:
                self.query_one("#btn-mode-issues").focus()
            except Exception:
                pass
        elif pane_id == "plugin-tools":
            try:
                self.query_one("#tools-table").focus()
            except Exception:
                pass
        elif pane_id == "settings":
            try:
                self.query_one("#settings-categories").focus()
            except Exception:
                pass




    async def on_command_message(self, message: CommandMessage) -> None:
        tabs = self.query_one(TabbedContent)
        if tabs.active == "plugin-serial":
            try:
                await self.bus.call("serial.send", data=message.command)
            except Exception:
                pass
        else:
            tabs.active = "console"
            #self.notify(f"Got command message {message.command}")
            console = self.query_one(ConsoleTab)
            self.run_worker(console.run_command(message.command))

    def _on_repo_changed(self, event) -> None:
        payload = event.payload
        if isinstance(payload, RepoChanged):
            self.run_worker(self.set_workspace_root(payload.path, update_files=True))

    async def action_restore_workspace(self) -> None:
        saved = self.settings_manager.get("workspace", "root")
        if saved and Path(saved).is_dir():
            await self.set_workspace_root(saved, update_files=True)

    def get_user_plugin_dir(self) -> Path:
        path_str = self.settings_manager.get("plugins", "user_plugin_dir")
        if path_str:
            return Path(path_str).expanduser().resolve()
        import os
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            base = Path(xdg_data)
        else:
            base = Path.home() / ".local" / "share"
        return base / "etui" / "plugins"

    def load_user_plugins_sys_path(self) -> None:
        user_plugin_dir = self.get_user_plugin_dir()
        user_plugin_root = user_plugin_dir.resolve()
        import sys
        cleaned_sys_path: list[str] = []
        for path_str in sys.path:
            try:
                path = Path(path_str).expanduser().resolve()
            except Exception:
                cleaned_sys_path.append(path_str)
                continue
            if user_plugin_root in path.parents and not path.exists():
                continue
            cleaned_sys_path.append(path_str)
        sys.path[:] = cleaned_sys_path
        if user_plugin_dir.is_dir():
            for path in user_plugin_dir.iterdir():
                if path.is_dir() and not path.name.startswith("."):
                    path_str = str(path)
                    if path_str not in sys.path:
                        sys.path.insert(0, path_str)

    def _resolve_plugin_install_spec(self, spec: str) -> str:
        if "://" in spec or spec.startswith("git+"):
            return spec

        raw_path = Path(spec).expanduser()
        candidates: list[Path]
        if raw_path.is_absolute():
            candidates = [raw_path]
        else:
            candidates = []
            if self.workspace_root:
                candidates.append(Path(self.workspace_root) / raw_path)
            candidates.append(Path.cwd() / raw_path)

        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.is_file():
                return str(resolved)
            if resolved.is_dir():
                artifact = self._latest_pdm_build_artifact(resolved)
                if artifact is not None:
                    return str(artifact)
                return str(resolved)

        return spec

    @staticmethod
    def _latest_pdm_build_artifact(path: Path) -> Path | None:
        search_dirs = [path] if path.name == "dist" else [path / "dist", path]
        for search_dir in search_dirs:
            if not search_dir.is_dir():
                continue
            wheels = sorted(
                search_dir.glob("*.whl"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            if wheels:
                return wheels[0].resolve()
            sdists = sorted(
                search_dir.glob("*.tar.gz"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            if sdists:
                return sdists[0].resolve()
        return None

    @staticmethod
    def _write_pdm_helper_project(project_dir: Path) -> None:
        host_root = Path(__file__).resolve().parents[1]
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "pyproject.toml").write_text(
            "\n".join(
                [
                    "[build-system]",
                    'requires = ["pdm-backend"]',
                    'build-backend = "pdm.backend"',
                    "",
                    "[project]",
                    'name = "etui-plugin-install-helper"',
                    'version = "0.0.0"',
                    f'requires-python = ">={sys.version_info.major}.{sys.version_info.minor},<{sys.version_info.major}.{sys.version_info.minor + 2}"',
                    f'dependencies = ["etui @ {host_root.as_uri()}"]',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (project_dir / "pdm.toml").write_text(
            "[venv]\nin_project = true\n",
            encoding="utf-8",
        )

    @staticmethod
    def _distribution_name_from_spec(spec: str) -> str:
        if __package__:
            from .plugins import normalize_dist_name
        else:
            from plugins import normalize_dist_name
        path = Path(spec)
        if path.suffix == ".whl" or path.name.endswith(".tar.gz"):
            return normalize_dist_name(path.name.split("-", 1)[0])
        return normalize_dist_name(spec)

    @staticmethod
    def _installed_distribution(name: str):
        import importlib.metadata as md

        if __package__:
            from .plugins import normalize_dist_name
        else:
            from plugins import normalize_dist_name

        target = normalize_dist_name(name)
        for dist in md.distributions():
            if normalize_dist_name(dist.metadata.get("Name", "")) == target:
                return dist
        return None

    @staticmethod
    def _remove_distribution_from_environment(dist) -> bool:
        import shutil

        removed = False
        dist_path = getattr(dist, "_path", None)

        roots: set[Path] = set()
        for file in dist.files or []:
            rel = Path(str(file))
            if not rel.parts:
                continue
            top_level = rel.parts[0]
            if top_level.endswith(".dist-info"):
                continue
            roots.add(Path(top_level))

        for root in sorted(roots):
            path = Path(dist.locate_file(root))
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                removed = True
            elif path.exists():
                path.unlink()
                removed = True

        if dist_path is not None:
            dist_dir = Path(dist_path)
            if dist_dir.exists():
                shutil.rmtree(dist_dir, ignore_errors=True)
                removed = True

        return removed

    @staticmethod
    def _copy_distribution_files(src_root: Path, target_root: Path, dist_name: str) -> None:
        import shutil
        if __package__:
            from .plugins import normalize_dist_name
        else:
            from plugins import normalize_dist_name

        skip = {
            "etui",
            "pdm",
            "pip",
            "setuptools",
            "wheel",
            "virtualenv",
            "installer",
            "pdm-backend",
        }

        for entry in src_root.iterdir():
            name = normalize_dist_name(entry.name.split("-", 1)[0].split(".", 1)[0])
            if name in skip:
                continue
            dest = target_root / entry.name
            if entry.is_dir():
                shutil.copytree(entry, dest, dirs_exist_ok=True)
            elif entry.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(entry, dest)

    @staticmethod
    def _is_local_build_artifact(spec: str) -> bool:
        path = Path(spec)
        return path.is_file() and (path.suffix == ".whl" or path.name.endswith(".tar.gz"))

    @staticmethod
    def _requires_dist_from_artifact(path: Path) -> list[str]:
        import email
        import tarfile
        import zipfile

        metadata = ""
        if path.suffix == ".whl":
            with zipfile.ZipFile(path) as wheel:
                metadata_name = next(
                    (
                        name
                        for name in wheel.namelist()
                        if name.endswith(".dist-info/METADATA")
                    ),
                    None,
                )
                if metadata_name:
                    metadata = wheel.read(metadata_name).decode(errors="replace")
        elif path.name.endswith(".tar.gz"):
            with tarfile.open(path, "r:gz") as sdist:
                member = next(
                    (
                        item
                        for item in sdist.getmembers()
                        if item.name.endswith("/PKG-INFO")
                    ),
                    None,
                )
                if member:
                    extracted = sdist.extractfile(member)
                    if extracted is not None:
                        metadata = extracted.read().decode(errors="replace")

        if not metadata:
            return []
        message = email.message_from_string(metadata)
        return list(message.get_all("Requires-Dist", []))

    @staticmethod
    def _requirement_name(requirement: str) -> str:
        import re

        return re.split(r"\s|<|>|=|!|~|;|\[", requirement, maxsplit=1)[0].strip()

    @classmethod
    def _plugin_artifact_dependencies(cls, artifact: Path) -> list[str]:
        deps = []
        for requirement in cls._requires_dist_from_artifact(artifact):
            name = cls._requirement_name(requirement).lower().replace("_", "-")
            if name == "etui":
                continue
            if "extra ==" in requirement:
                continue
            deps.append(requirement)
        return deps

    async def confirm_action(self, message: str) -> bool:
        if getattr(self, "testing", False) or os.environ.get("ETUI_TEST") == "1":
            return True
        screen = ConfirmModal(message)
        return bool(await self.push_screen_wait(screen))

    def _emit_plugins_changed(
        self,
        *,
        added: list[str] | None = None,
        removed: list[str] | None = None,
        enabled: list[str] | None = None,
        disabled: list[str] | None = None,
        order: list[str] | None = None,
    ) -> None:
        if __package__:
            from .bus_contract import TOPIC_PLUGINS_CHANGED, PluginsChanged
        else:
            from bus_contract import TOPIC_PLUGINS_CHANGED, PluginsChanged

        self.bus.emit(
            TOPIC_PLUGINS_CHANGED,
            PluginsChanged(
                added=added or [],
                removed=removed or [],
                enabled=enabled or [],
                disabled=disabled or [],
                order=list(self.settings_manager.get("plugins", "order", []))
                if order is None
                else order,
            ),
            source="app",
        )

    def _emit_plugin_install_progress(
        self,
        spec: str,
        message: str,
        *,
        stream: str = "info",
    ) -> None:
        self.bus.emit(
            TOPIC_PLUGINS_INSTALL_PROGRESS,
            PluginInstallProgress(spec=spec, message=message, stream=stream),
            source="app",
        )

    def _plugin_by_id(self, plugin_id: str):
        return next((lp for lp in self.plugins.loaded if lp.spec.id == plugin_id), None)

    def _non_core_plugin_ids(self) -> set[str]:
        if __package__:
            from .plugins import PINNED_PLUGIN_IDS
        else:
            from plugins import PINNED_PLUGIN_IDS
        return {
            lp.spec.id
            for lp in self.plugins.loaded
            if lp.spec.id not in PINNED_PLUGIN_IDS
        }

    def _clean_plugin_order(self, order: list[str]) -> list[str]:
        known = self._non_core_plugin_ids()
        clean: list[str] = []
        for plugin_id in order:
            if plugin_id in CORE_TAB_IDS or plugin_id not in known or plugin_id in clean:
                continue
            clean.append(plugin_id)
        return clean

    def _ordered_loaded_plugins(self) -> list:
        order_list = self._clean_plugin_order(self.settings_manager.get("plugins", "order", []))
        order_index = {plugin_id: idx for idx, plugin_id in enumerate(order_list)}

        def sort_key(lp):
            return (
                order_index.get(lp.spec.id, len(order_index)),
                lp.spec.order or 1000,
                lp.spec.title,
            )

        return sorted(self.plugins.loaded, key=sort_key)

    async def _hot_unmount_plugin_tab(self, plugin_id: str, loaded_by_id: dict | None = None) -> bool:
        tabs = self.query_one(TabbedContent)
        try:
            tabs.get_pane(plugin_id)
        except Exception:
            return False

        lp = (loaded_by_id or {}).get(plugin_id) or self._plugin_by_id(plugin_id)
        if lp and lp.scoped_bus:
            lp.scoped_bus.dispose_all()
            lp.scoped_bus = None

        await tabs.remove_pane(plugin_id)
        logger.info("hot-unmounted plugin tab %s", plugin_id)
        return True

    async def _svc_plugins_list(self, *, caller: str = "host") -> list[dict]:
        try:
            import importlib.metadata as md
            ver = md.version("etui")
        except Exception:
            ver = "0.5.0"

        core_tabs = [
            {"id": "files", "dist": "etui", "version": ver, "source": "core", "enabled": True, "status": "loaded", "summary": "Workspace file explorer and editor", "errors": None},
            {"id": "console", "dist": "etui", "version": ver, "source": "core", "enabled": True, "status": "loaded", "summary": "Interactive command terminal", "errors": None},
            {"id": "settings", "dist": "etui", "version": ver, "source": "core", "enabled": True, "status": "loaded", "summary": "Application configuration", "errors": None},
            {"id": "plugin-venv", "dist": "etui", "version": ver, "source": "core", "enabled": True, "status": "loaded", "summary": "PDM project environment manager", "errors": None},
            {"id": "plugin-manager", "dist": "etui", "version": ver, "source": "core", "enabled": True, "status": "loaded", "summary": "Plugin installation and management", "errors": None},
            {"id": "theme", "dist": "etui", "version": ver, "source": "core", "enabled": True, "status": "loaded", "summary": "UI theme selector", "errors": None},
            {"id": "about", "dist": "etui", "version": ver, "source": "core", "enabled": True, "status": "loaded", "summary": "About EmbeddedTUI", "errors": None},
            {"id": "help", "dist": "etui", "version": ver, "source": "core", "enabled": True, "status": "loaded", "summary": "Help and documentation browser", "errors": None},
        ]

        disabled_set = set(self.settings_manager.get("plugins", "disabled", []))
        error_map = {name: msg for name, msg in self.plugins.errors}

        plugin_dicts = []
        for lp in self.plugins.loaded:
            is_enabled = lp.spec.id not in disabled_set
            
            if lp.spec.id in error_map:
                status = "error"
                err = error_map[lp.spec.id]
            elif lp.name in error_map:
                status = "error"
                err = error_map[lp.name]
            elif not is_enabled:
                status = "disabled"
                err = None
            else:
                status = "loaded"
                err = None

            plugin_dicts.append({
                "id": lp.spec.id,
                "dist": lp.dist_name or lp.name,
                "version": lp.version,
                "source": lp.source,
                "enabled": is_enabled,
                "status": status,
                "summary": lp.spec.title,
                "errors": err,
                "entry_point": lp.entry_point,
                "location": lp.location,
                "settings_section": (
                    lp.spec.settings_schema.section if lp.spec.settings_schema else None
                ),
            })

        loaded_names = {lp.name for lp in self.plugins.loaded}
        loaded_ids = {lp.spec.id for lp in self.plugins.loaded}
        for name, msg in self.plugins.errors:
            if name in loaded_names or name in loaded_ids or name == "host-services":
                continue
            is_enabled = f"plugin-{name}" not in disabled_set

            if __package__:
                from .plugins import FIRST_PARTY_PLUGINS
            else:
                from plugins import FIRST_PARTY_PLUGINS

            if f"etui-{name}" in FIRST_PARTY_PLUGINS or name in FIRST_PARTY_PLUGINS:
                source = "default"
            else:
                source = "third-party"
            
            plugin_dicts.append({
                "id": f"plugin-{name}",
                "dist": name,
                "version": None,
                "source": source,
                "enabled": is_enabled,
                "status": "error",
                "summary": f"Load failed: {name}",
                "errors": msg,
                "entry_point": "",
                "location": None,
                "settings_section": None,
            })

        return core_tabs + plugin_dicts

    async def _svc_plugins_install(
        self, spec: str, *, upgrade: bool = False, caller: str = "host"
    ) -> dict:
        self._emit_plugin_install_progress(spec, "Waiting for confirmation...")
        approved = await self.confirm_action(
            f"Install plugin '{spec}' requested by {caller}?"
        )
        if not approved:
            self._emit_plugin_install_progress(spec, "Installation cancelled.", stream="error")
            raise PermissionError("Installation cancelled by user.")

        user_plugin_dir = self.get_user_plugin_dir()
        user_plugin_dir.mkdir(parents=True, exist_ok=True)

        install_spec = self._resolve_plugin_install_spec(spec)
        if install_spec != spec:
            self._emit_plugin_install_progress(spec, f"Resolved artifact: {install_spec}")

        helper_root = user_plugin_dir / ".tmp_install"
        import shutil
        installer = shutil.which("pdm")

        if not installer:
            self._emit_plugin_install_progress(spec, "No package installer found.", stream="error")
            raise RuntimeError("No package installer (pdm) found on PATH.")
        self._emit_plugin_install_progress(spec, f"Using installer: {installer}")

        if helper_root.exists():
            self._emit_plugin_install_progress(spec, f"Removing stale helper project: {helper_root}")
            shutil.rmtree(helper_root)
        self._write_pdm_helper_project(helper_root)
        self._emit_plugin_install_progress(spec, f"Installing into helper project: {helper_root}")

        import asyncio
        env = os.environ.copy()
        env["PDM_IGNORE_ACTIVE_VENV"] = "1"

        async def run_install_command(
            cmd: list[str],
            *,
            cwd: Path,
            emit_stdout: bool = True,
        ) -> list[str]:
            self._emit_plugin_install_progress(spec, "Running: " + " ".join(cmd))
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            assert proc.stdout is not None
            assert proc.stderr is not None

            stdout_lines: list[str] = []
            stderr_lines: list[str] = []

            async def stream_reader(reader: asyncio.StreamReader, stream: str) -> None:
                while True:
                    line = await reader.readline()
                    if not line:
                        break
                    text = line.decode(errors="replace").rstrip()
                    if not text:
                        continue
                    if stream == "stdout":
                        stdout_lines.append(text)
                        if not emit_stdout:
                            continue
                    if stream == "stderr":
                        stderr_lines.append(text)
                    self._emit_plugin_install_progress(spec, text, stream=stream)

            await asyncio.gather(
                stream_reader(proc.stdout, "stdout"),
                stream_reader(proc.stderr, "stderr"),
                proc.wait(),
            )
            if proc.returncode != 0:
                err_msg = "\n".join(stderr_lines)
                self._emit_plugin_install_progress(
                    spec,
                    f"Installer exited with status {proc.returncode}.",
                    stream="error",
                )
                raise RuntimeError(f"Installation failed: {err_msg}")
            return stdout_lines

        cmd = [installer, "add", install_spec]
        if upgrade:
            cmd.append("--upgrade")
        await run_install_command(cmd, cwd=helper_root)
        self._emit_plugin_install_progress(spec, "Installer finished successfully.")

        self._emit_plugin_install_progress(spec, "Resolving helper site-packages...")
        purelib_output = await run_install_command(
            [
                installer,
                "run",
                "python",
                "-c",
                "import sysconfig; print(sysconfig.get_paths()['purelib'])",
            ],
            cwd=helper_root,
            emit_stdout=False,
        )
        purelib_text = next((line for line in purelib_output if line.strip()), "")
        if not purelib_text:
            raise RuntimeError("Helper site-packages path was not reported by PDM.")
        purelib = Path(purelib_text).expanduser()
        if not purelib.is_dir():
            raise RuntimeError(f"Helper site-packages not found: {purelib}")

        import importlib.metadata
        if __package__:
            from .plugins import normalize_dist_name, dist_name_from_metadata_dir
        else:
            from plugins import normalize_dist_name, dist_name_from_metadata_dir

        dist_name = None
        primary_name = self._distribution_name_from_spec(install_spec)
        for dist in importlib.metadata.distributions(path=[str(purelib)]):
            name = normalize_dist_name(dist.metadata.get("Name", ""))
            if name and name not in {"etui", "pdm", "pip", "setuptools", "wheel", "virtualenv", "installer", "pdm_backend"}:
                if name == primary_name:
                    dist_name = name
                    break
        if dist_name is None:
            dist_infos = list(purelib.glob("*.dist-info"))
            if not dist_infos:
                dist_infos = list(purelib.glob("*.egg-info"))
            if not dist_infos:
                raise RuntimeError("No distribution metadata (*.dist-info) found in installation.")
            dist_name = dist_name_from_metadata_dir(dist_infos[0])
        self._emit_plugin_install_progress(spec, f"Detected distribution: {dist_name}")

        target_dir = (user_plugin_dir / dist_name).resolve()
        if not target_dir.is_relative_to(user_plugin_dir.resolve()):
            self._emit_plugin_install_progress(spec, "Install target escapes plugin directory.", stream="error")
            raise ValueError("Plugin install target escapes the managed plugin directory.")
        if target_dir.exists():
            self._emit_plugin_install_progress(spec, f"Replacing existing install: {target_dir}")
            shutil.rmtree(target_dir)

        target_dir.mkdir(parents=True, exist_ok=True)
        self._emit_plugin_install_progress(spec, f"Copying installed packages into: {target_dir}")
        self._copy_distribution_files(purelib, target_dir, dist_name)

        if helper_root.exists():
            shutil.rmtree(helper_root)

        if hasattr(importlib.metadata, "invalidate_caches"):
            importlib.metadata.invalidate_caches()
        importlib.invalidate_caches()

        path_str = str(target_dir)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)

        self._emit_plugin_install_progress(spec, "Install complete. Reloading plugins...")
        self._emit_plugins_changed(added=[dist_name])
        return {"dist": dist_name, "success": True, "spec": install_spec}

    async def _svc_plugins_uninstall(self, dist: str, *, caller: str = "host") -> None:
        if __package__:
            from .plugins import normalize_dist_name
        else:
            from plugins import normalize_dist_name
        normalized_dist = normalize_dist_name(dist)
        lp = next(
            (
                lp
                for lp in self.plugins.loaded
                if normalize_dist_name(lp.dist_name or "") == normalized_dist
                or normalize_dist_name(lp.name) == normalized_dist
            ),
            None,
        )
        if lp and lp.source != "third-party":
            raise PermissionError("Only third-party plugins can be uninstalled.")

        approved = await self.confirm_action(
            f"Uninstall plugin '{dist}' requested by {caller}?"
        )
        if not approved:
            raise PermissionError("Uninstall cancelled by user.")

        import importlib
        import shutil

        user_plugin_dir = self.get_user_plugin_dir()
        target_dir = (user_plugin_dir / normalized_dist).resolve()
        if not target_dir.is_relative_to(user_plugin_dir.resolve()):
            raise ValueError("Plugin uninstall target escapes the managed plugin directory.")
        self._emit_plugin_install_progress(dist, f"Removing cached install: {target_dir}")

        target_name = lp.dist_name if lp and lp.dist_name else normalized_dist
        installed_dist = self._installed_distribution(target_name)
        if installed_dist is not None:
            installed_name = installed_dist.metadata.get("Name", normalized_dist)
            self._emit_plugin_install_progress(dist, f"Removing installed distribution: {installed_name}")
            self._remove_distribution_from_environment(installed_dist)

        if lp is not None:
            try:
                await self._hot_unmount_plugin_tab(lp.spec.id, {lp.spec.id: lp})
            except Exception:
                logger.exception("Failed to hot-unmount uninstalled plugin %s", lp.spec.id)
            self.plugins.loaded = [item for item in self.plugins.loaded if item.spec.id != lp.spec.id]
            self.plugins.errors = [
                item for item in self.plugins.errors if item[0] not in {lp.name, lp.spec.id}
            ]
        if target_dir.is_dir():
            import shutil
            shutil.rmtree(target_dir)
            path_str = str(target_dir)
            if path_str in sys.path:
                sys.path.remove(path_str)
            if hasattr(importlib.metadata, "invalidate_caches"):
                importlib.metadata.invalidate_caches()
            importlib.invalidate_caches()
            self._emit_plugins_changed(removed=[normalized_dist])
        elif lp is not None:
            if hasattr(importlib.metadata, "invalidate_caches"):
                importlib.metadata.invalidate_caches()
            importlib.invalidate_caches()
            self._emit_plugins_changed(removed=[normalized_dist])

    async def _svc_plugins_set_enabled(
        self, plugin_id: str, enabled: bool, *, caller: str = "host"
    ) -> None:
        if __package__:
            from .plugins import PINNED_PLUGIN_IDS
        else:
            from plugins import PINNED_PLUGIN_IDS
        if plugin_id in CORE_TAB_IDS or plugin_id in PINNED_PLUGIN_IDS:
            raise PermissionError(f"{plugin_id} cannot be disabled.")
        if self._plugin_by_id(plugin_id) is None:
            raise ValueError(f"Unknown plugin id: {plugin_id}")

        disabled = list(self.settings_manager.get("plugins", "disabled", []))
        if enabled:
            if plugin_id in disabled:
                disabled.remove(plugin_id)
        else:
            if plugin_id not in disabled:
                disabled.append(plugin_id)

        self.settings_manager.set("plugins", "disabled", disabled)
        if not enabled:
            try:
                await self._hot_unmount_plugin_tab(plugin_id)
            except Exception:
                logger.exception("Failed to hot-unmount disabled plugin %s", plugin_id)

        self._emit_plugins_changed(
            enabled=[plugin_id] if enabled else [],
            disabled=[] if enabled else [plugin_id],
        )

    async def _svc_plugins_set_order(self, order: list[str], *, caller: str = "host") -> None:
        clean_order = self._clean_plugin_order(order)

        self.settings_manager.set("plugins", "order", clean_order)
        self._emit_plugins_changed(order=clean_order)

    async def _svc_plugins_reload(self, *, caller: str = "host") -> dict:
        import sys
        import importlib
        import importlib.metadata
        if hasattr(importlib.metadata, "invalidate_caches"):
            importlib.metadata.invalidate_caches()
        importlib.invalidate_caches()

        self.load_user_plugins_sys_path()

        tabs = self.query_one(TabbedContent)
        mounted_ids = set()
        for pane in list(tabs.children):
            if pane.id and pane.id.startswith("plugin-") and pane.id not in CORE_TAB_IDS:
                mounted_ids.add(pane.id)
        old_loaded_by_id = {lp.spec.id: lp for lp in self.plugins.loaded}

        self.plugins.discover()

        disabled_set = set(self.settings_manager.get("plugins", "disabled", []))
        self.plugins.loaded = self._ordered_loaded_plugins()

        # Unmount disabled/uninstalled ones
        current_loaded_ids = {lp.spec.id for lp in self.plugins.loaded if lp.spec.id not in disabled_set}
        for pane_id in mounted_ids:
            if pane_id not in current_loaded_ids:
                try:
                    await self._hot_unmount_plugin_tab(pane_id, old_loaded_by_id)
                except Exception:
                    logger.exception("Failed to hot-unmount plugin %s", pane_id)

        # Mount newly enabled ones
        added = []
        for lp in self.plugins.loaded:
            if lp.spec.id in disabled_set:
                continue

            try:
                tabs.get_pane(lp.spec.id)
                continue
            except Exception:
                pass

            try:
                widget = lp.plugin.create_widget()
                if __package__:
                    from .plugins import ScopedBus
                else:
                    from plugins import ScopedBus
                lp.scoped_bus = ScopedBus(self.bus, lp.spec.id, lp.spec.provides)
                widget._bus = lp.scoped_bus

                active_ids = [l.spec.id for l in self.plugins.loaded if l.spec.id not in disabled_set]
                try:
                    idx = active_ids.index(lp.spec.id)
                    target = active_ids[idx - 1] if idx > 0 else None
                except ValueError:
                    target = None

                has_target = False
                if target:
                    try:
                        tabs.get_pane(target)
                        has_target = True
                    except Exception:
                        pass

                kwargs = {"after": target} if has_target else {}
                await tabs.add_pane(TabPane(lp.spec.title, widget, id=lp.spec.id), **kwargs)

                if lp.spec.help_doc and lp.spec.help_doc.is_file():
                    await self.bus.call(SVC_HELP_ADD_ENTRY, title=lp.spec.title, path=lp.spec.help_doc)

                added.append(lp.spec.id)
                logger.info("hot-mounted plugin tab %s", lp.spec.id)
            except Exception as exc:
                if lp.scoped_bus:
                    lp.scoped_bus.dispose_all()
                self.plugins.errors.append((lp.name, f"hot-mount failed: {exc!r}"))
                logger.exception("hot-mount crash isolation for plugin %s", lp.spec.id)
                self.notify(f"Plugin {lp.spec.title} failed to mount: {exc!r}", severity="error")

        self._emit_plugins_changed(added=added)
        return {"added": added}

    async def _svc_settings_focus_section(self, section: str) -> None:
        if __package__:
            from .tabs.settings import SettingsTab
        else:
            from tabs.settings import SettingsTab
        self.query_one(TabbedContent).active = "settings"
        settings_tab = self.query_one(SettingsTab)
        success = settings_tab.focus_section(section)
        if not success:
            self.notify(f"Unknown or disabled settings section: {section}", severity="warning")


class ConfirmModal(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    #confirm-modal-grid {
        grid-size: 1;
        grid-rows: auto 3;
        background: $surface;
        padding: 1 2;
        border: thick $accent;
        width: 60;
        height: auto;
    }
    #confirm-modal-buttons {
        layout: horizontal;
        align: right middle;
        height: 3;
        margin-top: 1;
    }
    #confirm-modal-buttons Button {
        margin-left: 1;
    }
    """
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        from textual.containers import Grid, Horizontal
        from textual.widgets import Button, Label
        yield Grid(
            Label(self.message),
            Horizontal(
                Button("Cancel", variant="error", id="no"),
                Button("Confirm", variant="primary", id="yes"),
                id="confirm-modal-buttons"
            ),
            id="confirm-modal-grid"
        )

    def on_button_pressed(self, event) -> None:
        if event.button.id == "yes":
            self.dismiss(True)
        else:
            self.dismiss(False)

    

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


def _resolve_workspace_arg(raw_path: str) -> str:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    if not path.is_dir():
        raise SystemExit(f"etui: workspace path is not a directory: {path}")
    return str(path)


def _parse_main_args(argv: list[str]) -> tuple[bool, str | None]:
    args = list(argv)
    debug = False
    if "--debug" in args:
        args = [arg for arg in args if arg != "--debug"]
        debug = True

    if args and args[0].startswith("-"):
        raise SystemExit(f"etui: unknown option: {args[0]}")
    if len(args) > 1:
        raise SystemExit("usage: etui [--debug] [WORKSPACE]")

    workspace_root = _resolve_workspace_arg(args[0]) if args else None
    return debug, workspace_root


def main(argv: list[str] | None = None):
    args = list(sys.argv[1:] if argv is None else argv)
    if "--debug" in args:
        args = [a for a in args if a != "--debug"]
        path = _setup_debug_logging()
        print(f"[etui] debug logging -> {path}")

    if len(args) >= 2 and args[0] == "--etui-xonsh-command":
        from xonsh.main import main as xonsh_main

        xonsh_main(["--no-rc", "-c", args[1]])
        return

    if len(args) >= 1 and args[0] == "--screenshots":
        _run_screenshots(Path(args[1]) if len(args) >= 2 else None)
        return

    if len(args) >= 1 and args[0] == "--self-test":
        _run_self_test()
        return

    _, startup_workspace_root = _parse_main_args(args)

    print("Hello from etui!")
    app = EtuiApp(startup_workspace_root=startup_workspace_root)
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
