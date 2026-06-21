from textual.widget import Widget
from etui.plugin import EtuiTabPlugin, TabSpec
from etui.bus_contract import SVC_SERIAL_SEND

class SerialTabPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        return TabSpec(
            id="plugin-serial",
            title="Serial",
            order=500,
            provides=(SVC_SERIAL_SEND,),
        )

    def create_widget(self) -> Widget:
        from .tab import SerialTab
        return SerialTab()
