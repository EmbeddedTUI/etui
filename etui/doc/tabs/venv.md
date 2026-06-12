# Venv Tab

Manage an external [PDM](https://pdm-project.org) project's virtual environment and packages without leaving etui.


## Layout

| Area | Description |
|------|-------------|
| Project bar | Path to the PDM project root |
| Info bar | Python version, virtual environment path, PDM version |
| Package table (50%) | Installed packages with name and version |
| Controls pane (50%) | Package input, **Add**, **Remove**, **Update All** buttons |
| Log area | pdm command output |

## Usage

1. Enter the path to a PDM project directory (containing `pyproject.toml`) and press **Enter** or **Open**.
2. The package table populates with installed packages.
3. To install a new package, type its name (PEP 508 specifier supported, e.g. `requests>=2.31`) and click **Add**.
4. Select a package row and click **Remove** to uninstall it.
5. Click **Update All** to run `pdm update`.

## Notes

- The Venv tab manages an *external* project, not etui's own environment.
- Operations run `pdm` from the selected project directory; PDM must be installed and on PATH.
- Package specs are validated locally before being passed to PDM.
