from textual.widget import Widget
from etui.plugin import EtuiTabPlugin, TabSpec

class CMakeTabPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        return TabSpec(
            id="plugin-cmake",
            title="CMake",
            order=400,
        )

    def create_widget(self) -> Widget:
        from .tab import CMakeTab
        return CMakeTab()
