from textual.widget import Widget
from etui.plugin import EtuiTabPlugin, TabSpec
from etui.bus_contract import SVC_DEBUG_RESTART_PROBE, SVC_DEBUG_GET_GDBSERVER_STATUS

class ProbeTabPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        from .tab import ProbeTab
        return TabSpec(
            id="plugin-probe",
            title="Probe",
            order=700,
            provides=(SVC_DEBUG_RESTART_PROBE, SVC_DEBUG_GET_GDBSERVER_STATUS),
            settings_schema=ProbeTab.settings_schema,
        )

    def create_widget(self) -> Widget:
        from .tab import ProbeTab
        return ProbeTab()
