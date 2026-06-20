from textual.widget import Widget
from etui.plugin import EtuiTabPlugin, TabSpec

class WorkflowTabPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        return TabSpec(
            id="plugin-workflow",
            title="Workflow",
            order=600,
        )

    def create_widget(self) -> Widget:
        from .tab import WorkflowTab
        return WorkflowTab()
