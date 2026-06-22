from etui.plugin import EtuiTabPlugin, TabSpec
from etui.tabs.plugin_manager import PluginManagerTab

class PluginManagerTabPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        return TabSpec(
            id="plugin-manager",
            title="Plugins",
            order=950,
        )

    def create_widget(self):
        return PluginManagerTab()
