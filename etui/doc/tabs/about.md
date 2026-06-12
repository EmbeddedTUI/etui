# About Tab

App information and documentation screenshot capture.


## Layout

| Area | Description |
|------|-------------|
| Center content | App name, version, and copyright |
| **Capture Screenshots** button | Automatically screenshots every tab |
| Status label | Progress and result of the last capture run |

## Capturing Screenshots

Click **Capture Screenshots** to iterate through all tabs in order, export each as an SVG screenshot, and save them to `doc/screenshots/` relative to the etui project root.

The capture process:

1. Activates each tab in sequence: Files, Console, Tools, Git, GitHub, CMake, Serial, Probe, LLDB, Venv, Settings, Theme, About.
2. Waits for the tab to render.
3. Exports the full terminal as SVG using Textual's built-in exporter.
4. Writes `doc/screenshots/<tabname>.svg`.
5. Returns to the About tab when done.

The status label reports how many screenshots were saved and lists any that failed.

## Notes

- Screenshots capture the terminal state at the moment of capture. Tabs that require a connected device (Probe, LLDB, Serial) will show their idle/disconnected state.
- SVG files are self-contained and can be embedded in Markdown documentation directly.
- Re-running capture overwrites existing screenshots.
