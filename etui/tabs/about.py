# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Center, Vertical
from textual.widgets import Button, Label, Static, TabbedContent


# Tab IDs in display order — must match the TabPane ids in main.py.
TAB_IDS = [
    "files",
    "console",
    "tools",
    "git",
    "github",
    "cmake",
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
        align: center middle;
    }
    AboutTab #about-content {
        width: auto;
        height: auto;
        align: center middle;
    }
    AboutTab Static {
        text-align: center;
        width: auto;
    }
    AboutTab #about-status {
        margin-top: 1;
        color: $text-muted;
        text-align: center;
        width: auto;
    }
    AboutTab Button {
        margin-top: 2;
    }
    """

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="about-content"):
                yield Static("[bold]etui[/bold] — Embedded TUI")
                yield Static("(c) 32bitmicro LLC 2026")
                yield Static("")
                yield Static(
                    "A terminal-based IDE for embedded development.\n"
                    "Files · Console · Tools · Git · GitHub · CMake\n"
                    "Serial · Probe · LLDB · Venv · Settings · Theme"
                )
                yield Button(
                    "Capture Screenshots",
                    id="btn-capture-screenshots",
                    variant="primary",
                )
                yield Label("", id="about-status")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-capture-screenshots":
            await self._run_capture()

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
