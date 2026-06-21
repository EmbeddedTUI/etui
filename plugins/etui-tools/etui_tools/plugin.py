from textual.widget import Widget
from etui.plugin import EtuiTabPlugin, TabSpec
from etui.bus_contract import SVC_TOOLS_STATUS

class ToolsTabPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        from .tab import ToolsTab
        return TabSpec(
            id="plugin-tools",
            title="Tools",
            order=900,
            provides=(SVC_TOOLS_STATUS,),
            settings_schema=ToolsTab.settings_schema,
        )

    def create_widget(self) -> Widget:
        from .tab import ToolsTab
        return ToolsTab()
