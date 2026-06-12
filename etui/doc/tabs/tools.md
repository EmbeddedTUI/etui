# Tools Tab

Detect, validate, and install the external command-line tools that etui depends on.


## Layout

| Area | Description |
|------|-------------|
| Top bar | **Scan All** button and optional custom path input |
| Tool table | One row per tool: name, state, version, and install hint |
| Detail panel | Install instructions for the selected tool |
| Log area | Scan and installation output |

## Tool States

| State | Meaning |
|-------|---------|
| **Installed** | All required executables found and version verified |
| **Incomplete** | Some executables present but optional components missing |
| **Missing** | No executables found on PATH or configured paths |
| **Invalid** | Executable found but version check failed |
| **Unknown** | Scan not yet run |

## Usage

1. Click **Scan All** to probe PATH for every tool.
2. Select a tool row to see its install instructions in the detail panel.
3. Use **Settings → Tool Paths** to add custom search directories (e.g. `/opt/toolchain/bin`).

## Covered Tools

cmake, ninja, pyocd, openocd, lldb, arm-none-eabi-gcc, gdb-multiarch, and others as defined in the tool manifest.
