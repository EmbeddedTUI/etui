# Plugins Guide

The **Plugins** tab allows you to manage EmbeddedTUI plugins at runtime.

## Core capabilities:
- **Enable/Disable**: Disable non-core plugins to clean up your interface or disable unneeded background services.
- **Tab Reordering**: Arrange the layout and tab ordering of plugins to suit your workspace preferences.
- **Installation**: Install third-party plugins directly from PyPI, a Git repository, or a local file directory path.
- **Uninstallation**: Uninstall user-added third-party plugins safely.
- **Configuration**: Directly configure plugin settings schemas.

## Important Security Note:
Installing a plugin executes arbitrary Python code in the same process context as the TUI itself. Install only plugins from trusted sources.
