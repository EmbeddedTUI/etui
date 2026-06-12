# Probe Tab

Connect a hardware debug probe, start a GDB server, and launch a debug session.


## Layout

| Area | Description |
|------|-------------|
| Controls bar | Backend selector, probe selector, target selector, speed input |
| Port settings | GDB server port, Telnet port, TCL port |
| Action bar | **Connect Probe**, **Start GDB Server**, **Stop** buttons |
| Log area | GDB server and probe output |

## Supported Backends

| Backend | Description |
|---------|-------------|
| **pyocd** | Python-based probe server; auto-detects CMSIS-DAP and J-Link probes |
| **openocd** | Supports XDS110 (native firmware) and CMSIS-DAP adapters |
| **gdb** | Generic GDB MI2 session |

## Supported Targets

MSPM0L, MSPM0G, MSPM0C (TI Arm Cortex-M0+ family). Target support is driven by OpenOCD config files.

## Probe Guides

- [TI XDS110](../probes/xds110.md)
- [ST-LINK](../probes/stlink.md)

## Usage

1. Plug in a debug probe. The probe dropdown auto-populates with detected USB probes.
2. Select the **Backend** and **Target** family.
3. Adjust the adapter speed if needed (default: 4000 kHz).
4. Click **Start GDB Server**. The server port, telnet port, and TCL port are shown.
5. etui automatically opens the LLDB tab and connects once the server is ready.

## Notes

- pyocd cannot enumerate TI XDS110 probes in native firmware mode; etui detects them by USB VID:PID and switches to OpenOCD automatically.
- Settings (backend, target, ports, speed) persist across sessions via **Settings → Probe / Debugger**.
- Click **Stop** to terminate the GDB server and release the probe.
