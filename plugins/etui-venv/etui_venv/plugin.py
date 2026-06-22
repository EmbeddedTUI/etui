from etui.plugin import EtuiTabPlugin, TabSpec
from etui.tabs.venv import VenvTab

class VenvTabPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        return TabSpec(
            id="plugin-venv",
            title="Venv",
            order=200,
        )

    def create_widget(self):
        return VenvTab()
