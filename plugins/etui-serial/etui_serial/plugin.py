from textual.widget import Widget
from etui.plugin import EtuiTabPlugin, TabSpec

class SerialTabPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        return TabSpec(
            id="plugin-serial",
            title="Serial",
            order=500,
            provides=("serial.send",),
        )

    def create_widget(self) -> Widget:
        from .tab import SerialTab
        return SerialTab()
