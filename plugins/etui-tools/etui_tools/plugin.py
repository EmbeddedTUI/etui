from textual.widget import Widget
from etui.plugin import EtuiTabPlugin, TabSpec

class ToolsTabPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        from .tab import ToolsTab
        return TabSpec(
            id="plugin-tools",
            title="Tools",
            order=900,
            provides=("tools.status",),
            settings_schema=ToolsTab.settings_schema,
        )

    def create_widget(self) -> Widget:
        from .tab import ToolsTab
        return ToolsTab()
