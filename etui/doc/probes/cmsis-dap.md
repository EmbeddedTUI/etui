# CMSIS-DAP Probe Guide

CMSIS-DAP is a debug transport used by probes from multiple vendors. The probe
model does not identify the target MCU, so etui requires an explicit pyOCD
target ID before starting a debug session.

## Setup

1. Connect the probe to USB and connect SWDIO, SWCLK, GND, and target voltage.
2. Open **Probe** and click **Detect**.
3. Select the detected CMSIS-DAP probe.
4. Click **List targets**, enter a search filter (e.g. `lpc` or `stm32`), and select the target ID loaded from pyOCD. Other target IDs can also be entered under **Settings -> Probe / Debugger**.
5. Leave the backend set to **pyocd** and click **Start**.

etui starts `pyocd gdbserver` with the selected probe UID, target, adapter
frequency, and GDB port. LLDB opens only after pyOCD reports that the GDB
server is listening.

## OpenOCD Fallback

CMSIS-DAP probes can use OpenOCD when the selected target has a packaged
OpenOCD target configuration. Select **openocd** only for a supported target.
etui uses `interface/cmsis-dap.cfg`; it does not accept arbitrary OpenOCD
command text.

## Troubleshooting

### Probe appears in USB tools but not etui

- Close other GDB servers and vendor utilities using the probe.
- Check host USB permissions and udev rules.
- Confirm pyOCD supports the probe transport.
- Reconnect the probe and click **Detect**.

### Target type is not recognized

Verify the target ID with `pyocd list --targets`. Some targets require a CMSIS
device pack; use the Probe tab's pack-install action when offered.

### GDB server does not start

- Confirm the target is powered and wired correctly.
- Reduce the adapter speed.
- Check whether the configured GDB port is already in use.
- Verify that the selected target ID describes the attached MCU.

## Related Documentation

- [Probe Tab](../tabs/probe.md)
- [LPC-LINK2](lpc-link2.md)
- [LLDB Tab](../tabs/lldb.md)
