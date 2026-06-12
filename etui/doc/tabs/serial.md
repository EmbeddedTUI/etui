# Serial Tab

A serial port terminal for communicating with embedded targets over UART.


## Layout

| Area | Description |
|------|-------------|
| Controls bar | Port selector, Baud rate selector, **Connect** / **Disconnect** button |
| Log area | Scrolling received data |

## Usage

1. Select the serial port from the **Port** dropdown (lists all detected `/dev/tty*` / `COMx` ports).
2. Select the baud rate (default: 115200).
3. Click **Connect**. The button label changes to **Disconnect** when connected.
4. Received data appears in the log. Type in the **main input** field at the bottom of the screen to send data.
5. Click **Disconnect** to close the port.

## Supported Baud Rates

9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600

## Notes

- Port enumeration runs on mount. Replug a device and switch to another tab then back to refresh the list.
- The serial input field is the global input bar at the bottom, which is shown only when the Serial tab is active.
