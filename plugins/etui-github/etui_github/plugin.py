from textual.widget import Widget
from etui.plugin import EtuiTabPlugin, TabSpec

class GitHubTabPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        return TabSpec(
            id="plugin-github",
            title="GitHub",
            order=300,
        )

    def create_widget(self) -> Widget:
        from .tab import GitHubTab
        return GitHubTab()
