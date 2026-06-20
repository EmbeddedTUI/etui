from textual.widget import Widget
from etui.plugin import EtuiTabPlugin, TabSpec

class GitTabPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        return TabSpec(
            id="plugin-git",
            title="Git",
            order=250,
        )

    def create_widget(self) -> Widget:
        from .tab import GitTab
        return GitTab()
