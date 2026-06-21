# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.widgets import Label
from textual.widgets import Select
from textual.widgets import Static

if __package__ and "." in __package__:
    from ..bus import BusMixin
    from ..contracts import theme_set
else:
    from bus import BusMixin
    from contracts import theme_set


THEMES = {
    "vibrant": {
        "header": "yellow",
        "dim": "grey50",
        "reg_name": "bright_cyan",
        "value": "bright_green",
        "changed": "bold bright_yellow",
        "address": "bright_green",
        "current": "bold black on yellow",
        "mem_word": "magenta",
        "frame": "bright_yellow",
        "thread": "bright_magenta",
    },
    "ocean": {
        "header": "cyan",
        "dim": "grey46",
        "reg_name": "cyan",
        "value": "bright_white",
        "changed": "bold bright_cyan",
        "address": "bright_blue",
        "current": "bold black on cyan",
        "mem_word": "blue",
        "frame": "bright_cyan",
        "thread": "bright_blue",
    },
    "solarized": {
        "header": "#b58900",
        "dim": "#586e75",
        "reg_name": "#268bd2",
        "value": "#93a1a1",
        "changed": "bold #859900",
        "address": "#2aa198",
        "current": "bold #073642 on #b58900",
        "mem_word": "#6c71c4",
        "frame": "#cb4b16",
        "thread": "#d33682",
    },
    "subtle": {
        "header": "yellow",
        "dim": "grey58",
        "reg_name": "grey58",
        "value": "none",
        "changed": "bold green",
        "address": "grey58",
        "current": "bold",
        "mem_word": "none",
        "frame": "yellow",
        "thread": "grey58",
    },
    "mono": {
        "header": "white",
        "dim": "grey42",
        "reg_name": "grey70",
        "value": "none",
        "changed": "bold white",
        "address": "grey50",
        "current": "reverse",
        "mem_word": "none",
        "frame": "bold",
        "thread": "grey50",
    },
}


def _preview(theme: dict) -> Text:
    """ Render a small sample of the dashboard in the given theme. """
    def s(key):
        v = theme.get(key, "none")
        return None if v == "none" else v

    text = Text()
    text.append("Registers\n", style=s("header"))
    text.append("   r0", style=s("reg_name"))
    text.append(" = ", style=s("dim"))
    text.append("0x00000005", style=s("changed"))
    text.append("   (changed)\n", style=s("dim"))
    text.append("   r1", style=s("reg_name"))
    text.append(" = ", style=s("dim"))
    text.append("0x00000004\n", style=s("value"))
    text.append("Assembly\n", style=s("header"))
    text.append("->  0x114c: cmp r0, #0x0\n", style=s("current"))
    text.append("    0x114e", style=s("dim"))
    text.append(": ldrb r0, [r1]\n")
    text.append("Stack\n", style=s("header"))
    text.append("0x20000ff0: ", style=s("dim"))
    text.append("0xdeadbeef ", style=s("changed"))
    text.append("0x00000000", style=s("mem_word"))
    text.append("\n")
    return text


class ThemeTab(BusMixin, Vertical):
    """ Top-level tab to choose the LLDB dashboard color scheme. """

    DEFAULT_CSS = """
        ThemeTab #theme-bar { height: 3; }
        ThemeTab #theme-label { width: auto; height: 3; content-align: left middle; }
        ThemeTab #theme-select { width: 30; }
        ThemeTab #theme-preview { padding: 1 2; }
    """

    def __init__(self, current_theme: str | None = None) -> None:
        super().__init__()
        self.current_theme = current_theme

    def compose(self) -> ComposeResult:
        current = self.current_theme or "vibrant"
        if current not in THEMES:
            current = "vibrant"
        with Horizontal(id="theme-bar"):
            yield Label("Dashboard theme:  ", id="theme-label")
            yield Select(
                [(name, name) for name in THEMES],
                value=current,
                allow_blank=False,
                id="theme-select",
            )
        yield Static(_preview(THEMES[current]), id="theme-preview", markup=False)

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "theme-select":
            return
        theme = str(event.value)
        self.query_one("#theme-preview", Static).update(_preview(THEMES[theme]))
        await theme_set(self.bus, theme)
