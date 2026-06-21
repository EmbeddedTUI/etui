import asyncio
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    RichLog,
)

from etui.plugin import CancelOnLeaveMixin, BusMixin
from etui.contracts import (
    plugins_list,
    plugins_install,
    plugins_uninstall,
    plugins_set_enabled,
    plugins_set_order,
    plugins_reload,
    settings_focus_section,
    on_plugins_changed,
)

SOURCE_ORDER = {"core": 0, "default": 1, "third-party": 2}


class PluginManagerTab(CancelOnLeaveMixin, BusMixin, Vertical):
    DEFAULT_CSS = """
    PluginManagerTab {
        layout: vertical;
        height: 1fr;
    }
    #install-bar {
        height: auto;
        padding: 1 2;
        background: $surface;
        border-bottom: solid $accent;
        layout: horizontal;
        align: left middle;
    }
    #install-bar Input {
        width: 40;
        margin-right: 1;
    }
    #install-bar Button {
        margin-right: 1;
    }
    #install-summary {
        margin-left: 2;
        color: $text-muted;
    }
    #middle-layout {
        layout: horizontal;
        height: 1fr;
    }
    #table-container {
        width: 60%;
        height: 1fr;
        padding: 1;
    }
    #detail-container {
        width: 40%;
        height: 1fr;
        padding: 1;
        background: $surface;
        border-left: solid $accent;
        layout: vertical;
    }
    .detail-section {
        margin-bottom: 1;
    }
    .detail-header {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #lbl-detail-select {
        color: $text-muted;
        margin-top: 2;
        align: center middle;
    }
    #detail-actions {
        layout: horizontal;
        height: auto;
        margin-top: 1;
        align: left middle;
    }
    #detail-actions Button {
        margin-right: 1;
        min-width: 12;
    }
    #detail-order-actions {
        layout: horizontal;
        height: auto;
        margin-top: 1;
        align: left middle;
    }
    #detail-order-actions Button {
        margin-right: 1;
        min-width: 12;
    }
    #log-container {
        height: 10;
        border-top: solid $accent;
        background: $surface;
        padding: 0 1;
    }
    #log-view {
        height: 100%;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.plugins_data: list[dict] = []
        self.selected_plugin_id: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="install-bar"):
            yield Input(placeholder="Package name, Git URL, or local path", id="txt-install-spec")
            yield Button("Install", id="btn-install", variant="primary")
            yield Button("Set Up Installer", id="btn-bootstrap-uv", variant="warning")
            yield Label("", id="install-summary")

        with Horizontal(id="middle-layout"):
            with Container(id="table-container"):
                yield DataTable(id="plugins-table", cursor_type="row")
            with Vertical(id="detail-container"):
                yield Label("PLUGIN DETAILS", classes="detail-header")
                yield Label("Select a plugin from the table to view details.", id="lbl-detail-select")
                
                with Vertical(id="plugin-detail-view"):
                    with Horizontal(id="detail-actions"):
                        yield Button("Disable", id="btn-toggle-enable", variant="success")
                        yield Button("Configure", id="btn-configure", variant="primary")
                        yield Button("Uninstall", id="btn-uninstall", variant="error")

                    with Horizontal(id="detail-order-actions"):
                        yield Button("Move Up", id="btn-move-up")
                        yield Button("Move Down", id="btn-move-down")

                    yield Label("ID: --", id="lbl-detail-id", classes="detail-section")
                    yield Label("Distribution: --", id="lbl-detail-dist", classes="detail-section")
                    yield Label("Version: --", id="lbl-detail-ver", classes="detail-section")
                    yield Label("Source: --", id="lbl-detail-source", classes="detail-section")
                    yield Label("Status: --", id="lbl-detail-status", classes="detail-section")
                    yield Label("Summary: --", id="lbl-detail-summary", classes="detail-section")
                    yield Label("Errors: --", id="lbl-detail-errors", classes="detail-section")

        with Container(id="log-container"):
            yield RichLog(id="log-view", highlight=True, max_lines=100)

    async def on_mount(self) -> None:
        parent_on_mount = getattr(super(), "on_mount", None)
        if parent_on_mount is not None:
            parent_on_mount()
        self.selected_plugin_id = None
        self.update_detail_view()
        await self.populate_table()
        
        # Subscribe to plugins changed notifications
        self._disposer = on_plugins_changed(self.bus, self._refresh)

    def on_unmount(self) -> None:
        if hasattr(self, "_disposer"):
            self._disposer()
        parent_on_unmount = getattr(super(), "on_unmount", None)
        if parent_on_unmount is not None:
            parent_on_unmount()

    def _refresh(self, event: Any) -> None:
        self.run_worker(self.populate_table())

    async def populate_table(self) -> None:
        table = self.query_one("#plugins-table", DataTable)
        table.clear(columns=True)
        table.add_columns("#", "Plugin", "Version", "Source", "Enabled", "Status")
        
        plugins = await plugins_list(self.bus)
        self.plugins_data = sorted(
            plugins,
            key=lambda item: (
                SOURCE_ORDER.get(item.get("source"), 99),
                plugins.index(item),
            ),
        )
        
        disabled_count = 0
        non_core_index = 1
        
        for item in self.plugins_data:
            pid = item["id"]
            source = item["source"]
            is_enabled = item["enabled"]
            status = item["status"]
            
            if not is_enabled:
                disabled_count += 1
                
            if source == "core":
                order_col = "—"
            else:
                order_col = str(non_core_index)
                non_core_index += 1
                
            if status == "loaded":
                status_str = "✓ loaded"
            elif status == "disabled":
                status_str = "○ disabled"
            else:
                status_str = "! error"
                
            enabled_str = "Yes" if is_enabled else "No"
            
            table.add_row(
                order_col,
                pid,
                item["version"] or "--",
                source,
                enabled_str,
                status_str,
                key=pid
            )
            
        summary_lbl = self.query_one("#install-summary", Label)
        summary_lbl.update(f"* {len(self.plugins_data)} plugins, {disabled_count} disabled")
        
        # Restore selection
        if self.selected_plugin_id:
            try:
                table.move_cursor(row=table.get_row_index(self.selected_plugin_id))
            except Exception:
                self.selected_plugin_id = None
                self.update_detail_view()
        elif self.plugins_data and table.row_count:
            self._select_plugin_id(str(table.get_row_at(table.cursor_row)[1]))

    def update_detail_view(self) -> None:
        detail_view = self.query_one("#plugin-detail-view", Vertical)
        select_hint = self.query_one("#lbl-detail-select", Label)
        
        if not self.selected_plugin_id:
            detail_view.display = False
            select_hint.display = True
            return
            
        item = next((p for p in self.plugins_data if p["id"] == self.selected_plugin_id), None)
        if not item:
            detail_view.display = False
            select_hint.display = True
            return
            
        detail_view.display = True
        select_hint.display = False
        
        self.query_one("#lbl-detail-id", Label).update(f"ID: {item['id']}")
        self.query_one("#lbl-detail-dist", Label).update(f"Distribution: {item['dist']}")
        self.query_one("#lbl-detail-ver", Label).update(f"Version: {item['version'] or '--'}")
        self.query_one("#lbl-detail-source", Label).update(f"Source: {item['source']}")
        self.query_one("#lbl-detail-status", Label).update(f"Status: {item['status']}")
        self.query_one("#lbl-detail-summary", Label).update(f"Summary: {item['summary'] or '--'}")
        
        errs = item.get("errors")
        self.query_one("#lbl-detail-errors", Label).update(f"Errors: {errs or 'None'}")
        
        source = item["source"]
        is_enabled = item["enabled"]
        
        btn_toggle = self.query_one("#btn-toggle-enable", Button)
        btn_config = self.query_one("#btn-configure", Button)
        btn_uninstall = self.query_one("#btn-uninstall", Button)
        btn_up = self.query_one("#btn-move-up", Button)
        btn_down = self.query_one("#btn-move-down", Button)
        
        is_pinned = item["id"] == "plugin-manager"
        if source == "core":
            btn_toggle.disabled = True
            btn_uninstall.disabled = True
            btn_up.disabled = True
            btn_down.disabled = True
            btn_toggle.label = "Enable"
            btn_config.disabled = item["id"] not in ("settings", "theme", "files")
        else:
            btn_toggle.disabled = is_pinned
            btn_toggle.label = "Disable" if is_enabled else "Enable"
            btn_uninstall.disabled = source != "third-party"
            btn_up.disabled = is_pinned
            btn_down.disabled = is_pinned
            btn_config.disabled = not bool(item.get("settings_section"))

    def _select_plugin_id(self, plugin_id: str) -> None:
        self.selected_plugin_id = plugin_id
        self.update_detail_view()

    def _select_row_key(self, row_key: Any) -> None:
        if row_key and row_key.value:
            self._select_plugin_id(row_key.value)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._select_row_key(event.row_key)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._select_row_key(event.row_key)

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
        self._select_row_key(event.cell_key.row_key)

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        self._select_row_key(event.cell_key.row_key)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-install":
            await self.install_plugin()
        elif btn_id == "btn-bootstrap-uv":
            await self.bootstrap_uv()
        elif btn_id == "btn-toggle-enable":
            await self.toggle_plugin_enable()
        elif btn_id == "btn-configure":
            await self.configure_plugin()
        elif btn_id == "btn-uninstall":
            await self.uninstall_plugin()
        elif btn_id == "btn-move-up":
            await self.move_plugin(-1)
        elif btn_id == "btn-move-down":
            await self.move_plugin(1)

    async def install_plugin(self) -> None:
        spec_input = self.query_one("#txt-install-spec", Input)
        spec = spec_input.value.strip()
        if not spec:
            return
            
        log = self.query_one("#log-view", RichLog)
        log.write(f"Installing plugin '{spec}'...")
        
        spec_input.value = ""
        btn_install = self.query_one("#btn-install", Button)
        btn_install.disabled = True
        
        try:
            res = await plugins_install(self.bus, spec)
            log.write(f"✓ Successfully installed plugin: {res.get('dist', spec)}")
            await plugins_reload(self.bus)
        except Exception as exc:
            log.write(f"❌ Installation failed: {exc!r}", style="color: $error;")
            self.notify(f"Install failed: {exc!r}", severity="error")
        finally:
            btn_install.disabled = False
            await self.populate_table()

    async def bootstrap_uv(self) -> None:
        log = self.query_one("#log-view", RichLog)
        log.write("Bootstrapping uv package manager...")
        btn = self.query_one("#btn-bootstrap-uv", Button)
        btn.disabled = True
        
        try:
            res = await plugins_install(self.bus, "bootstrap-uv")
            log.write(f"✓ uv bootstrapper finished. Installer path: {res.get('installer')}")
        except Exception as exc:
            log.write(f"❌ uv bootstrap failed: {exc!r}", style="color: $error;")
            self.notify(f"Bootstrap failed: {exc!r}", severity="error")
        finally:
            btn.disabled = False
            await self.populate_table()

    async def uninstall_plugin(self) -> None:
        if not self.selected_plugin_id:
            return
            
        item = next((p for p in self.plugins_data if p["id"] == self.selected_plugin_id), None)
        if not item or item["source"] != "third-party":
            return
            
        dist_name = item["dist"]
        log = self.query_one("#log-view", RichLog)
        log.write(f"Uninstalling third-party plugin '{dist_name}'...")
        
        try:
            await plugins_uninstall(self.bus, dist_name)
            log.write(f"✓ Successfully uninstalled plugin: {dist_name}")
            await plugins_reload(self.bus)
            self.selected_plugin_id = None
        except Exception as exc:
            log.write(f"❌ Uninstallation failed: {exc!r}", style="color: $error;")
            self.notify(f"Uninstall failed: {exc!r}", severity="error")
        finally:
            await self.populate_table()

    async def toggle_plugin_enable(self) -> None:
        if not self.selected_plugin_id:
            return
            
        item = next((p for p in self.plugins_data if p["id"] == self.selected_plugin_id), None)
        if (
            not item
            or item["source"] == "core"
            or item["id"] == "plugin-manager"
        ):
            return
            
        new_state = not item["enabled"]
        action_str = "Enabling" if new_state else "Disabling"
        
        log = self.query_one("#log-view", RichLog)
        log.write(f"{action_str} plugin {item['id']}...")
        
        try:
            await plugins_set_enabled(self.bus, item["id"], new_state)
            log.write(f"✓ {action_str} plugin {item['id']} success. Reloading...")
            await plugins_reload(self.bus)
        except Exception as exc:
            log.write(f"❌ Failed to toggle enabled: {exc!r}", style="color: $error;")
            self.notify(f"Failed to toggle plugin: {exc!r}", severity="error")
        finally:
            await self.populate_table()

    async def configure_plugin(self) -> None:
        if not self.selected_plugin_id:
            return
        item = next((p for p in self.plugins_data if p["id"] == self.selected_plugin_id), None)
        if not item:
            return
        section = item.get("settings_section") or self.selected_plugin_id.replace("plugin-", "")
        await settings_focus_section(self.bus, section)

    async def move_plugin(self, direction: int) -> None:
        if not self.selected_plugin_id:
            return
            
        non_core_ids = [
            p["id"]
            for p in self.plugins_data
            if p["source"] != "core" and p["id"] != "plugin-manager"
        ]
        if self.selected_plugin_id not in non_core_ids:
            return
            
        idx = non_core_ids.index(self.selected_plugin_id)
        new_idx = idx + direction
        
        if 0 <= new_idx < len(non_core_ids):
            non_core_ids[idx], non_core_ids[new_idx] = non_core_ids[new_idx], non_core_ids[idx]
            await plugins_set_order(self.bus, non_core_ids)
            
            log = self.query_one("#log-view", RichLog)
            log.write(f"Reordered plugin {self.selected_plugin_id} -> index {new_idx}")
            await self.populate_table()
