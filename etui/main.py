# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("etui.main")

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
    )
else:
    from tabs.help import HelpTab, OpenDocFile
    from tabs.about import AboutTab
    from tabs.console import ConsoleTab
    from tabs.files import FilesTab
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
    )

class CommandMessage(Message):
    def __init__(self ,command: str) -> None:
        super().__init__()
        self.command = command

class EtuiApp(App):
    """ Embedded TUI App"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.settings_manager = SettingsManager()
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
        
        disabled_set = set(self.settings_manager.get("plugins", "disabled", []))
        order_list = self.settings_manager.get("plugins", "order", [])
        
        def sort_key(lp):
            try:
                return (order_list.index(lp.spec.id), lp.spec.title)
            except ValueError:
                return (len(order_list) + (lp.spec.order or 1000), lp.spec.title)
                
        self.plugins.loaded.sort(key=sort_key)
        
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
        if user_plugin_dir.is_dir():
            import sys
            for path in user_plugin_dir.iterdir():
                if path.is_dir() and not path.name.startswith("."):
                    path_str = str(path)
                    if path_str not in sys.path:
                        sys.path.insert(0, path_str)

    async def confirm_action(self, message: str) -> bool:
        if getattr(self, "testing", False) or os.environ.get("ETUI_TEST") == "1":
            return True
        screen = ConfirmModal(message)
        self.push_screen(screen)
        return await screen.wait_for_dismiss()

    async def _svc_plugins_list(self) -> list[dict]:
        try:
            import importlib.metadata as md
            ver = md.version("etui")
        except Exception:
            ver = "0.4.0"

        core_tabs = [
            {"id": "files", "dist": "etui", "version": ver, "source": "core", "enabled": True, "status": "loaded", "summary": "Workspace file explorer and editor", "errors": None},
            {"id": "console", "dist": "etui", "version": ver, "source": "core", "enabled": True, "status": "loaded", "summary": "Interactive command terminal", "errors": None},
            {"id": "settings", "dist": "etui", "version": ver, "source": "core", "enabled": True, "status": "loaded", "summary": "Application configuration", "errors": None},
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
                
            source = "default" if f"etui-{name}" in FIRST_PARTY_PLUGINS or name in FIRST_PARTY_PLUGINS else "third-party"
            
            plugin_dicts.append({
                "id": f"plugin-{name}",
                "dist": name,
                "version": None,
                "source": source,
                "enabled": is_enabled,
                "status": "error",
                "summary": f"Load failed: {name}",
                "errors": msg,
            })

        return core_tabs + plugin_dicts

    async def _svc_plugins_install(self, spec: str, *, upgrade: bool = False) -> dict:
        approved = await self.confirm_action(f"Are you sure you want to install plugin '{spec}'?")
        if not approved:
            raise PermissionError("Installation cancelled by user.")

        user_plugin_dir = self.get_user_plugin_dir()
        user_plugin_dir.mkdir(parents=True, exist_ok=True)

        if spec == "bootstrap-uv":
            bin_dir = user_plugin_dir.parent / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            local_uv = bin_dir / "uv"
            
            import urllib.request
            import platform
            import tarfile
            import tempfile
            arch = platform.machine()
            if arch == "x86_64":
                url = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz"
            elif arch in ("aarch64", "arm64"):
                url = "https://github.com/astral-sh/uv/releases/latest/download/uv-aarch64-unknown-linux-gnu.tar.gz"
            else:
                raise RuntimeError(f"Unsupported architecture for uv bootstrap: {arch}")
                
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp_file:
                tmp_path = Path(tmp_file.name)
                try:
                    urllib.request.urlretrieve(url, tmp_path)
                    with tarfile.open(tmp_path, "r:gz") as tar:
                        for member in tar.getmembers():
                            if member.name.endswith("/uv"):
                                f = tar.extractfile(member)
                                if f:
                                    local_uv.write_bytes(f.read())
                                    local_uv.chmod(0o755)
                                    break
                finally:
                    if tmp_path.exists():
                        tmp_path.unlink()
            
            return {"success": True, "installer": str(local_uv)}

        bin_dir = user_plugin_dir.parent / "bin"
        local_uv = bin_dir / "uv"
        installer = None
        if local_uv.is_file() and os.access(local_uv, os.X_OK):
            installer = str(local_uv)
        else:
            import shutil
            installer = shutil.which("uv") or shutil.which("pip") or shutil.which("pip3")

        if not installer:
            raise RuntimeError("No package installer (uv or pip) found on PATH.")

        tmp_dir = user_plugin_dir / ".tmp_install"
        if tmp_dir.exists():
            import shutil
            shutil.rmtree(tmp_dir)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        cmd = []
        if "uv" in installer:
            cmd = [installer, "pip", "install", "--target", str(tmp_dir), spec]
        else:
            cmd = [installer, "install", "--target", str(tmp_dir), spec]
        if upgrade:
            cmd.append("--upgrade")

        import asyncio
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err_msg = stderr.decode(errors="replace")
            import shutil
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir)
            raise RuntimeError(f"Installation failed: {err_msg}")

        dist_infos = list(tmp_dir.glob("*.dist-info"))
        if not dist_infos:
            dist_infos = list(tmp_dir.glob("*.egg-info"))
        if not dist_infos:
            import shutil
            shutil.rmtree(tmp_dir)
            raise RuntimeError("No distribution metadata (*.dist-info) found in installation.")

        dist_info = dist_infos[0]
        meta_name = dist_info.name
        name_parts = meta_name.replace(".dist-info", "").replace(".egg-info", "").split("-")
        dist_name = name_parts[0]

        target_dir = user_plugin_dir / dist_name
        import shutil
        if target_dir.exists():
            shutil.rmtree(target_dir)

        target_dir.mkdir(parents=True, exist_ok=True)
        for path in tmp_dir.iterdir():
            shutil.move(str(path), str(target_dir / path.name))

        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)

        import sys
        import importlib
        import importlib.metadata
        if hasattr(importlib.metadata, "invalidate_caches"):
            importlib.metadata.invalidate_caches()
        importlib.invalidate_caches()

        path_str = str(target_dir)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)

        if __package__:
            from .bus_contract import TOPIC_PLUGINS_CHANGED, PluginsChanged
        else:
            from bus_contract import TOPIC_PLUGINS_CHANGED, PluginsChanged

        self.bus.emit(
            TOPIC_PLUGINS_CHANGED,
            PluginsChanged(
                added=[dist_name],
                removed=[],
                enabled=[],
                disabled=[],
                order=list(self.settings_manager.get("plugins", "order", []))
            ),
            source="app"
        )
        return {"dist": dist_name, "success": True}

    async def _svc_plugins_uninstall(self, dist: str) -> None:
        approved = await self.confirm_action(f"Are you sure you want to uninstall plugin '{dist}'?")
        if not approved:
            raise PermissionError("Uninstall cancelled by user.")

        user_plugin_dir = self.get_user_plugin_dir()
        target_dir = user_plugin_dir / dist
        if target_dir.is_dir():
            import shutil
            shutil.rmtree(target_dir)

            if __package__:
                from .bus_contract import TOPIC_PLUGINS_CHANGED, PluginsChanged
            else:
                from bus_contract import TOPIC_PLUGINS_CHANGED, PluginsChanged

            self.bus.emit(
                TOPIC_PLUGINS_CHANGED,
                PluginsChanged(
                    added=[],
                    removed=[dist],
                    enabled=[],
                    disabled=[],
                    order=list(self.settings_manager.get("plugins", "order", []))
                ),
                source="app"
            )

    async def _svc_plugins_set_enabled(self, plugin_id: str, enabled: bool) -> None:
        core_ids = {"files", "console", "settings", "theme", "about", "help", "plugin-manager"}
        if plugin_id in core_ids:
            return

        disabled = list(self.settings_manager.get("plugins", "disabled", []))
        if enabled:
            if plugin_id in disabled:
                disabled.remove(plugin_id)
        else:
            if plugin_id not in disabled:
                disabled.append(plugin_id)

        self.settings_manager.set("plugins", "disabled", disabled)

        if __package__:
            from .bus_contract import TOPIC_PLUGINS_CHANGED, PluginsChanged
        else:
            from bus_contract import TOPIC_PLUGINS_CHANGED, PluginsChanged

        self.bus.emit(
            TOPIC_PLUGINS_CHANGED,
            PluginsChanged(
                added=[],
                removed=[],
                enabled=[plugin_id] if enabled else [],
                disabled=[] if enabled else [plugin_id],
                order=list(self.settings_manager.get("plugins", "order", []))
            ),
            source="app"
        )

    async def _svc_plugins_set_order(self, order: list[str]) -> None:
        core_ids = {"files", "console", "settings", "theme", "about", "help"}
        clean_order = [pid for pid in order if pid not in core_ids]

        self.settings_manager.set("plugins", "order", clean_order)

        if __package__:
            from .bus_contract import TOPIC_PLUGINS_CHANGED, PluginsChanged
        else:
            from bus_contract import TOPIC_PLUGINS_CHANGED, PluginsChanged

        self.bus.emit(
            TOPIC_PLUGINS_CHANGED,
            PluginsChanged(
                added=[],
                removed=[],
                enabled=[],
                disabled=[],
                order=clean_order
            ),
            source="app"
        )

    async def _svc_plugins_reload(self) -> dict:
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
            if pane.id and pane.id.startswith("plugin-") and pane.id != "plugin-manager":
                mounted_ids.add(pane.id)

        self.plugins.discover()

        disabled_set = set(self.settings_manager.get("plugins", "disabled", []))
        order_list = self.settings_manager.get("plugins", "order", [])

        def sort_key(lp):
            try:
                return (order_list.index(lp.spec.id), lp.spec.title)
            except ValueError:
                return (len(order_list) + (lp.spec.order or 1000), lp.spec.title)

        self.plugins.loaded.sort(key=sort_key)

        # Unmount disabled/uninstalled ones
        current_loaded_ids = {lp.spec.id for lp in self.plugins.loaded if lp.spec.id not in disabled_set}
        for pane_id in mounted_ids:
            if pane_id not in current_loaded_ids:
                try:
                    lp = next((lp for lp in self.plugins.loaded if lp.spec.id == pane_id), None)
                    if lp and lp.scoped_bus:
                        lp.scoped_bus.dispose_all()
                    tabs.remove_pane(pane_id)
                    logger.info("hot-unmounted plugin tab %s", pane_id)
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

        if __package__:
            from .bus_contract import TOPIC_PLUGINS_CHANGED, PluginsChanged
        else:
            from bus_contract import TOPIC_PLUGINS_CHANGED, PluginsChanged

        self.bus.emit(
            TOPIC_PLUGINS_CHANGED,
            PluginsChanged(
                added=added,
                removed=[],
                enabled=[],
                disabled=[],
                order=list(self.settings_manager.get("plugins", "order", []))
            ),
            source="app"
        )
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
