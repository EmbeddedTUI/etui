# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import serial
import serial.tools.list_ports
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, RichLog, Select, Label
from textual.message import Message
from textual.worker import WorkerState

class SerialTab(Vertical):
    """ Serial console tab"""

    def __init__(self):
        super().__init__()
        self.serial_port = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="serial-controls", classes="control-bar"):
            yield Label("Port: ", classes="control-label")
            yield Select([], id="serial-port", prompt="Select Port")
            yield Label("Baud: ", classes="control-label")
            yield Select(
                [(str(b), b) for b in [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]],
                id="serial-baud",
                value=115200
            )
            yield Button("Connect", id="serial-connect", variant="primary")
        
        yield RichLog(id="serial-log", highlight=True, markup=True)

    def on_mount(self) -> None:
        self.refresh_ports()

    def refresh_ports(self) -> None:
        ports = serial.tools.list_ports.comports()
        options = [(f"{p.device} ({p.description})", p.device) for p in ports]
        select = self.query_one("#serial-port", Select)
        select.set_options(options)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "serial-connect":
            if self.serial_port and self.serial_port.is_open:
                self.disconnect()
            else:
                await self.connect()

    async def connect(self) -> None:
        port_select = self.query_one("#serial-port", Select)
        baud_select = self.query_one("#serial-baud", Select)
        
        if port_select.value is Select.BLANK:
            self.app.notify("Please select a serial port", variant="error")
            return

        port = port_select.value
        baud = baud_select.value

        try:
            self.serial_port = serial.Serial(port, baud, timeout=0.1)
            self.query_one("#serial-connect", Button).label = "Disconnect"
            self.query_one("#serial-connect", Button).variant = "error"
            self.query_one("#serial-log", RichLog).write(f"Connected to [bold]{port}[/bold] at {baud} baud")
            self.run_worker(self.read_serial, name="serial-reader", group="serial", thread=True)
        except Exception as e:
            self.app.notify(f"Failed to connect: {e}", variant="error")
            if self.serial_port:
                self.serial_port.close()
                self.serial_port = None

    def disconnect(self) -> None:
        if self.serial_port:
            self.serial_port.close()
            self.serial_port = None
        
        self.query_one("#serial-connect", Button).label = "Connect"
        self.query_one("#serial-connect", Button).variant = "primary"
        self.query_one("#serial-log", RichLog).write("Disconnected")
        self.workers.cancel_group("serial")

    def read_serial(self) -> None:
        log = self.query_one("#serial-log", RichLog)
        while self.serial_port and self.serial_port.is_open:
            try:
                if self.serial_port.in_waiting > 0:
                    data = self.serial_port.read(self.serial_port.in_waiting)
                    if data:
                        text = data.decode(errors="replace")
                        self.app.call_from_thread(log.write, text)
                else:
                    # Small sleep to prevent CPU spinning if in_waiting is 0
                    import time
                    time.sleep(0.01)
            except Exception as e:
                self.app.call_from_thread(log.write, f"[red]Error reading serial: {e}[/red]")
                break
        
        # When loop finishes (port closed or error), ensure UI is updated
        self.app.call_from_thread(self.handle_worker_finish)

    def handle_worker_finish(self) -> None:
        # This runs in the main thread
        if self.serial_port and not self.serial_port.is_open:
             self.disconnect()

    def send_data(self, data: str) -> None:
        if self.serial_port and self.serial_port.is_open:
            try:
                # Add newline if not present? Usually serial consoles want \r\n
                if not data.endswith('\n'):
                    data += '\n'
                self.serial_port.write(data.encode())
            except Exception as e:
                self.query_one("#serial-log", RichLog).write(f"[red]Error writing to serial: {e}[/red]")
        else:
            self.app.notify("Serial port not connected", variant="warning")
