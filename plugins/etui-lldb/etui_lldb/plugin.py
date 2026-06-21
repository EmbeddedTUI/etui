from textual.widget import Widget
from etui.plugin import EtuiTabPlugin, TabSpec

class LldbTabPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        from .tab import LldbTab
        return TabSpec(
            id="plugin-lldb",
            title="LLDB",
            order=800,
            settings_schema=LldbTab.settings_schema,
        )

    def create_widget(self) -> Widget:
        from .tab import LldbTab
        # settings tab looks at `settings_manager.settings["lldb"]`.
        # We can fetch it from the app or bus settings section.
        # But wait! The settings are accessible from self.app.settings_manager.settings["lldb"]
        # or defaults. We'll instantiate it without arguments (relying on on_mount load).
        # Wait, let's see how `LldbTab.__init__` is defined.
        # In lldb.py:
        #   def __init__(self, arch: str | None = None, settings: dict | None = None) -> None:
        # Let's instantiate LldbTab() with settings=None and load them in on_mount.
        # Wait, does __init__ require settings or can it handle settings=None?
        # Let's look at __init__ in lldb.py.
        return LldbTab()
