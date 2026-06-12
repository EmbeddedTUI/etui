# Theme Tab

Preview and select the color scheme for the LLDB dashboard.


## Layout

| Area | Description |
|------|-------------|
| Theme selector | Dropdown listing all available themes |
| Preview pane | Live sample of the dashboard in the selected theme |

## Available Themes

| Theme | Character |
|-------|-----------|
| **vibrant** | High-contrast yellows, cyans, and greens — the default |
| **ocean** | Cool blues and teals |
| **monochrome** | White, grey, and bold only — works on any terminal palette |
| **solarized** | Solarized-inspired warm neutrals |
| **dracula** | Purple and pink on dark backgrounds |

## Usage

Select a theme from the dropdown. The preview pane updates instantly, showing sample Registers, Assembly, and Stack output. The choice is applied to the live LLDB dashboard and persisted to `~/.config/etui/settings.yaml`.

## Notes

- The same theme can be changed in **Settings → LLDB Dashboard**.
- The preview renders using Rich styled text; actual terminal output may vary slightly depending on the terminal's color depth.
