from textual.widget import Widget
from etui.plugin import EtuiTabPlugin, TabSpec

class ProbeTabPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        from .tab import ProbeTab
        return TabSpec(
            id="plugin-probe",
            title="Probe",
            order=700,
            provides=("debug.restart_probe", "debug.get_gdbserver_status"),
            settings_schema=ProbeTab.settings_schema,
        )

    def create_widget(self) -> Widget:
        from .tab import ProbeTab
        return ProbeTab()
