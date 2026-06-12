# ST-LINK Probe Guide

Use an ST-LINK/V2, ST-LINK/V2.1, ST-LINK/V3, or ST-LINK/V3E probe to debug an
Arm Cortex-M target through pyOCD or the `st-util` GDB server.

## Supported Probes

etui recognizes these probe families:

- ST-LINK/V2
- ST-LINK/V2.1
- ST-LINK/V3
- ST-LINK/V3E

The preferred backend is **pyocd**. Select **stlink** to use `st-util` as a
fallback when pyOCD cannot initialize or support the target.

## Prerequisites

1. Connect the ST-LINK probe to the host and target.
2. Connect SWDIO, SWCLK, GND, and the target reference voltage.
3. Ensure the target is powered.
4. Open the **Tools** tab and verify that **LLDB Debugger** is installed.
5. For the `st-util` backend, verify that **stlink / st-util** is installed.
   pyOCD is installed as an etui Python dependency.
6. Install the operating-system USB/udev rules required for non-root ST-LINK
   access.

The **Tools** tab can install common packages where supported. System USB rules
and device permissions still require host administration.

## Start with pyOCD

1. Open the **Probe** tab.
2. Click **Detect**.
3. Select the detected **ST-LINK** entry.
4. Leave the backend set to **pyocd**.
5. Click **Start**.

pyOCD is the preferred path because it supports probe discovery and target
handling directly. Some targets require a CMSIS device pack.

## Missing pyOCD Target Pack

If the Probe log reports that the target type is not recognized or that no pack
is installed:

1. Select the displayed **Install Pack** action when available.
2. Wait for `pyocd pack update` and the target pack installation to finish.
3. Select **Start** again.

If pyOCD still reports debug-sequence, access-port, or target-initialization
errors, use the `st-util` fallback.

## Start with st-util

1. Install the ST-LINK host tools. In the **Tools** tab, select
   **stlink / st-util** and follow the installation action.
2. Return to the **Probe** tab.
3. Select **stlink** from the backend selector.
4. Select the detected ST-LINK probe.
5. Click **Start**.

etui starts `st-util` with the selected probe serial number and GDB port. The
default port is `4242`. When `st-util` reports that it is listening, etui opens
the **LLDB** tab and connects automatically.

## Load Firmware Symbols

For source-level debugging:

1. Build an ELF file with debug information.
2. Enter its path in **LLDB → Firmware ELF**.
3. Select **Load / Reconnect**.

Without an ELF, LLDB can attach to the target, but symbols, source lines, and
exact instruction boundaries are unavailable.

## Stop the Session

Use **Stop** in the Probe tab before unplugging the probe. This releases the
USB device and GDB port.

## Troubleshooting

### ST-LINK is not detected

- Confirm the USB cable supports data.
- Check host USB permissions and udev rules.
- Close STM32CubeProgrammer, OpenOCD, GDB servers, and other applications using
  the probe.
- Reconnect the probe and click **Detect**.

### "st-util not found"

Open the **Tools** tab, select **stlink / st-util**, and install or configure the
tool. If it is installed in a custom directory, add that directory under
**Settings → Tool Paths**.

### pyOCD reports "target type not recognized"

Install the required CMSIS pack using the Probe tab's **Install Pack** action.
If no matching pack exists, switch to the **stlink** backend.

### pyOCD reports an invalid AP address or debug-sequence failure

The target initialization sequence is not working through pyOCD. Select the
**stlink** backend and retry with `st-util`.

### LLDB disconnect causes st-util to exit

`st-util` is a single-client GDB server and may close after its LLDB client
aborts or disconnects. etui detects the LLDB memory-region failure, terminates
the old server if necessary, starts a fresh `st-util` process, and reconnects
LLDB after the new server begins listening.

### "Failed to connect port" or connection timeout

- Confirm the Probe tab still shows a running `st-util` process.
- Stop and start the Probe backend again.
- Use **Kill stale** to terminate abandoned GDB servers.
- Confirm no other process uses port `4242`.
- Change `stlink_gdb_port` in the Probe settings if another service requires
  that port.

### Unsupported register messages

Some `st-util` versions log unsupported-register requests from LLDB. These
messages do not always prevent basic debugging, but repeated failures may limit
register or dashboard data. Load the firmware ELF and keep the ST-LINK tools
updated.

## Related Documentation

- [Probe Tab](../tabs/probe.md)
- [LLDB Tab](../tabs/lldb.md)
- [Tools Tab](../tabs/tools.md)
- [Settings Tab](../tabs/settings.md)
