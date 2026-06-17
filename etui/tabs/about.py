# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Center, ScrollableContainer, Vertical
from textual.widgets import Button, Label, RichLog, Rule, Static, TabbedContent

if __package__:
    from ..version import COPYRIGHT
else:
    from version import COPYRIGHT


# Tab IDs in display order — must match the TabPane ids in main.py.
TAB_IDS = [
    "files",
    "console",
    "tools",
    "git",
    "github",
    "cmake",
    "workflow",
    "serial",
    "probe",
    "lldb",
    "venv",
    "settings",
    "theme",
    "about",
    "help",
]

DEFAULT_SCREENSHOT_DIR = Path(__file__).parents[1] / "doc" / "screenshots"

_LICENSE_PATH = Path(__file__).parents[2] / "LICENSE"
_OPENSOURCE_PATH = Path(__file__).parents[1] / "doc" / "opensource.md"

# Rich-markup table of direct open-source dependencies.
_OSS_TABLE = (
    "  [bold cyan]Component[/bold cyan]"
    "          [bold cyan]Version[/bold cyan]"
    "    [bold cyan]License[/bold cyan]\n"
    "  " + "─" * 54 + "\n"
    "  Textual              ≥ 8.1      MIT\n"
    "  pyOCD               ≥ 0.44     Apache 2.0\n"
    "  pySerial            ≥ 3.5      BSD\n"
    "  Pygments            ≥ 2.17     BSD 2-Clause\n"
    "  xonsh               ≥ 0.18     BSD 2-Clause\n"
    "  packaging           ≥ 22.0     Apache 2.0 / BSD 2-Clause\n"
    "  PyYAML              ≥ 6.0      MIT\n"
)


async def capture_screenshots(
    app: App,
    output_dir: Path,
    *,
    on_progress: object = None,
) -> tuple[list[str], list[str]]:
    """Switch to every tab, export an SVG screenshot, and write it to *output_dir*.

    Calls ``on_progress(tab_id)`` before each capture if provided.
    Returns ``(saved, failed)`` lists of tab IDs.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    tabs = app.query_one(TabbedContent)
    saved: list[str] = []
    failed: list[str] = []

    for tab_id in TAB_IDS:
        if callable(on_progress):
            on_progress(tab_id)
        try:
            tabs.active = tab_id
            await app.animator.wait_until_complete()
            await asyncio.sleep(0.15)
            svg = app.export_screenshot(title=f"etui — {tab_id}")
            (output_dir / f"{tab_id}.svg").write_text(svg, encoding="utf-8")
            saved.append(tab_id)
        except Exception as exc:
            failed.append(f"{tab_id} ({exc})")

    tabs.active = "about"
    return saved, failed


class AboutTab(Vertical):
    """About tab — app info and documentation screenshot capture."""

    DEFAULT_CSS = """
    AboutTab {
        height: 1fr;
        layout: vertical;
    }
    AboutTab #about-top {
        height: auto;
        align: center middle;
        padding: 1 2;
    }
    AboutTab #about-info {
        width: 54;
        height: auto;
        align: center middle;
    }
    AboutTab #about-motto {
        color: $accent;
        text-style: bold italic;
        background: $accent 15%;
        padding: 0 3;
        margin: 1 0;
        width: auto;
    }
    AboutTab Static {
        text-align: center;
        width: auto;
    }
    AboutTab #about-buttons {
        height: auto;
        layout: horizontal;
        align: center middle;
        padding: 0 2;
    }
    AboutTab #about-buttons Button {
        margin: 1 1;
    }
    AboutTab #about-status {
        height: auto;
        color: $text-muted;
        text-align: center;
        padding: 0 2;
    }
    AboutTab #about-oss {
        height: auto;
        align: center middle;
        padding: 0 4 1 4;
    }
    AboutTab #about-oss Static {
        text-align: left;
        width: auto;
    }
    AboutTab #self-test-log {
        height: 1fr;
        border-top: solid $accent;
        margin-top: 1;
        display: none;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="about-top"):
            with Center():
                with Vertical(id="about-info"):
                    yield Static("[bold]etui[/bold] — Embedded TUI")
                    yield Static("“Per aspera ad astra”", id="about-motto")
                    yield Static(COPYRIGHT)
                    yield Static("")
                    yield Static(
                        "A terminal-based IDE for embedded development.\n"
                        "Files · Console · Tools · Git · GitHub · CMake\n"
                        "Serial · Probe · LLDB · Venv · Settings · Theme"
                    )
            with Center(id="about-buttons"):
                yield Button("Capture Screenshots", id="btn-capture-screenshots", variant="primary")
                yield Button("Self Test", id="btn-self-test", variant="default")
                yield Button("View License", id="btn-license", variant="default")
                yield Button("Open Source", id="btn-opensource", variant="default")
            yield Label("", id="about-status")
        with Center(id="about-oss"):
            yield Rule()
            yield Static("[bold]Open-source components[/bold]\n")
            yield Static(_OSS_TABLE)
        yield RichLog(id="self-test-log", highlight=False, markup=True)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-capture-screenshots":
            await self._run_capture()
        elif event.button.id == "btn-self-test":
            await self._run_self_test()
        elif event.button.id == "btn-license":
            self._open_license()
        elif event.button.id == "btn-opensource":
            self._open_file_in_files(_OPENSOURCE_PATH)

    def _open_license(self) -> None:
        self._open_file_in_files(_LICENSE_PATH)

    def _open_file_in_files(self, path: Path) -> None:
        if not path.is_file():
            self.notify(f"File not found: {path.name}", severity="warning")
            return
        if __package__:
            from ..tabs.files import FilesTab
        else:
            from tabs.files import FilesTab
        from textual.widgets import TabbedContent
        self.app.query_one(TabbedContent).active = "files"
        self.app.query_one(FilesTab).open_file(path)

    async def _run_capture(self) -> None:
        button = self.query_one("#btn-capture-screenshots", Button)
        status = self.query_one("#about-status", Label)
        button.disabled = True

        def _progress(tab_id: str) -> None:
            status.update(f"Capturing {tab_id}…")

        saved, failed = await capture_screenshots(
            self.app, DEFAULT_SCREENSHOT_DIR, on_progress=_progress
        )

        button.disabled = False
        if failed:
            status.update(
                f"Done. {len(saved)} saved, {len(failed)} failed: {', '.join(failed)}"
            )
        else:
            status.update(f"Done. {len(saved)} screenshots saved to doc/screenshots/")

    async def _run_self_test(self) -> None:
        if __package__:
            from ..self_test import run_all
        else:
            from self_test import run_all

        btn = self.query_one("#btn-self-test", Button)
        status = self.query_one("#about-status", Label)
        log = self.query_one("#self-test-log", RichLog)

        btn.disabled = True
        log.display = True
        log.clear()
        status.update("Running self-tests…")

        import asyncio
        results = await asyncio.get_event_loop().run_in_executor(None, run_all)

        passed = sum(r.passed for r in results)
        total = len(results)
        for r in results:
            color = "green" if r.passed else "red"
            tag = "PASS" if r.passed else "FAIL"
            log.write(f"[{color}]{tag}[/{color}]  {r.name}: {r.message}")

        summary_color = "green" if passed == total else "red"
        log.write(f"\n[{summary_color}]{passed}/{total} passed[/{summary_color}]")
        status.update(f"Self-test: {passed}/{total} passed")
        btn.disabled = False
