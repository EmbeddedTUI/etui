# NXP LPC-LINK2 Probe Guide

etui recognizes the LPC-LINK2 CMSIS-DAP identity:

```text
USB ID:   1fc9:0090
Product:  NXP LPC-LINK2 CMSIS-DAP
```

Firmware versions such as `V5.182` are displayed as diagnostic metadata. etui
does not select a target or change probe firmware based on that version.

## Start a Session

1. Connect LPC-LINK2 to the host and target.
2. Open **Probe** and click **Detect**.
3. Select **NXP LPC-LINK2 CMSIS-DAP**.
4. Open **Settings -> Probe / Debugger**.
5. Enter the pyOCD target ID for the attached MCU.
6. Return to **Probe**, leave **pyocd** selected, and click **Start**.

When multiple LPC-LINK2 probes are attached, select the entry containing the
required serial or pyOCD UID.

## Important Target Rule

LPC-LINK2 is the debug adapter, not the target MCU. etui will not infer an NXP
target from the probe. The existing MSPM0 target choices are OpenOCD profiles
and cannot be used as pyOCD target IDs.

List available pyOCD targets with:

```text
pyocd list --targets
```

## USB Permissions

On Linux, direct access to `1fc9:0090` may require a distribution-specific
udev rule. etui reports permission failures but does not install rules or run
privileged commands.

After changing a udev rule, reload the rules as required by the operating
system, disconnect the probe, reconnect it, and click **Detect** again.

## Troubleshooting

### Detected by USB but unavailable to pyOCD

- Check udev permissions.
- Close MCUXpresso, LinkServer, OpenOCD, and other probe clients.
- Confirm the probe is running CMSIS-DAP firmware.
- Verify the installed pyOCD version supports the active transport.

### Missing CMSIS pack

Use the Probe tab's **Install Pack** action when it identifies the target pack.
If no pack is available, verify the target ID and pyOCD target support.

### LLDB does not open

LLDB starts only after `pyocd gdbserver` reports a listening GDB port. Review
the Probe log for target initialization, permissions, wiring, or port errors.

## Related Documentation

- [Generic CMSIS-DAP](cmsis-dap.md)
- [Probe Tab](../tabs/probe.md)
- [LLDB Tab](../tabs/lldb.md)
