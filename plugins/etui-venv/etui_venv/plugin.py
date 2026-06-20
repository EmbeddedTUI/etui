from textual.widget import Widget
from etui.plugin import EtuiTabPlugin, TabSpec

class VenvTabPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        return TabSpec(
            id="plugin-venv",
            title="Venv",
            order=200,
        )

    def create_widget(self) -> Widget:
        from .tab import VenvTab
        return VenvTab()
