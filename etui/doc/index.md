# etui — User Guide

**etui** is a terminal-based IDE for embedded development. It runs entirely in the terminal and provides an integrated environment for browsing files, running a shell, managing dependencies, working with Git and GitHub, building CMake projects, communicating over serial, debugging firmware with pyOCD / OpenOCD / LLDB, and managing Python virtual environments.

## Tabs

| Tab | Purpose |
|-----|---------|
| [Files](tabs/files.md) | Browse and preview workspace files |
| [Console](tabs/console.md) | Interactive xonsh shell |
| [Tools](tabs/tools.md) | Detect and install required external tools |
| [Git](tabs/git.md) | Stage, diff, and commit changes |
| [GitHub](tabs/github.md) | Browse issues and pull requests |
| [CMake](tabs/cmake.md) | Configure and build CMake projects |
| [Serial](tabs/serial.md) | Serial port terminal |
| [Probe](tabs/probe.md) | Debug probe control and GDB server |
| [LLDB](tabs/lldb.md) | LLDB dashboard (registers, assembly, stack, backtrace) |
| [Venv](tabs/venv.md) | PDM virtual environment manager |
| [Settings](tabs/settings.md) | Unified configuration |
| [Theme](tabs/theme.md) | LLDB dashboard color scheme |
| [About](tabs/about.md) | App info and screenshot capture |
| [Help](tabs/help.md) | Built-in documentation browser |

## Getting Started

1. Set the **workspace root** in the Files tab or in Settings → Workspace.
2. Run **Tools** to verify that required executables (cmake, pyocd, lldb-dap, …) are present.
3. Connect a debug probe, then use the **Probe** tab to start the GDB server.
4. Open the **LLDB** tab to attach and start debugging.

## Screenshots

Screenshots of each tab can be regenerated from the **About** tab using the *Capture Screenshots* button. They are saved as SVG files in `doc/screenshots/`.
