from textual.widget import Widget
from etui.plugin import EtuiTabPlugin, TabSpec

class PluginManagerTabPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        from pathlib import Path
        help_doc = Path(__file__).parent / "doc" / "guide.md"
        return TabSpec(
            id="plugin-manager",
            title="Plugins",
            order=950,
            help_doc=help_doc if help_doc.is_file() else None,
        )

    def create_widget(self) -> Widget:
        from .tab import PluginManagerTab
        return PluginManagerTab()
