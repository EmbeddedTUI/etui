# Raspberry Pi Debug Probe Guide

etui recognizes the Raspberry Pi Debug Probe CMSIS-DAP identity:

```text
USB ID:   2e8a:000c
Product:  Raspberry Pi Debug Probe
```

Firmware versions such as `V2.0.1` are displayed as diagnostic metadata. etui does not select a target or change probe firmware based on that version.

## Start a Session

1. Connect the Raspberry Pi Debug Probe to the host and target.
2. Open **Probe** and click **Detect**.
3. Select **Raspberry Pi Debug Probe**.
4. Click **List targets** and enter a search filter (e.g. `rp2040`) to query target IDs supported by the installed pyOCD.
5. Select the attached MCU from the target dropdown.
6. Leave **pyocd** selected and click **Start**.

When multiple Raspberry Pi Debug Probes are attached, select the entry containing the required serial or pyOCD UID.

## Important Target Rule

The Raspberry Pi Debug Probe is the debug adapter, not the target MCU. etui will not infer an RP2040 target from the probe. The existing MSPM0 target choices are OpenOCD profiles and cannot be used as pyOCD target IDs.

List available pyOCD targets with:

```text
pyocd list --targets
```

## USB Permissions

On Linux, direct access to `2e8a:000c` may require a distribution-specific udev rule. etui reports permission failures but does not install rules or run privileged commands.

Example udev rule:

```udev
# Raspberry Pi Debug Probe (CMSIS-DAP)
ATTRS{idVendor}=="2e8a", ATTRS{idProduct}=="000c", MODE="660", GROUP="plugdev", TAG+="uaccess"
```

After changing a udev rule, reload the rules as required by the operating system, disconnect the probe, reconnect it, and click **Detect** again.

## Troubleshooting

### Detected by USB but unavailable to pyOCD

- Check udev permissions.
- Close other GDB servers and vendor utilities using the probe.
- Confirm the probe is running CMSIS-DAP firmware (not native legacy Picoprobe firmware).
- Verify the installed pyOCD version supports the active transport.

### Missing CMSIS pack

Use the Probe tab's **Install Pack** action when it identifies the target pack. If no pack is available, verify the target ID and pyOCD target support.

### LLDB does not open

LLDB starts only after `pyocd gdbserver` reports a listening GDB port. Review the Probe log for target initialization, permissions, wiring, or port errors.

## Related Documentation

- [Generic CMSIS-DAP](cmsis-dap.md)
- [Probe Tab](../tabs/probe.md)
- [LLDB Tab](../tabs/lldb.md)
