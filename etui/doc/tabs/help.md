# Help Tab

Browse the built-in documentation for every tab without leaving etui.


## Layout

| Area | Description |
|------|-------------|
| Header | "Documentation" label |
| Menu list | Top-level **User Guide** entry and one sub-entry per tab |
| Hint bar | Keyboard reminder |

## Usage

Select any entry and press **Enter** (or click). etui switches to the **Files** tab and displays the corresponding Markdown documentation file in the viewer.

| Entry | Opens |
|-------|-------|
| User Guide | `doc/index.md` — overview and getting-started guide |
| Files … About | `doc/tabs/<name>.md` — tab-specific reference |

## Notes

- Documentation files are bundled with the installed package and are always available offline.
- To regenerate the screenshots embedded in the docs, use the **Capture Screenshots** button in the **About** tab.
