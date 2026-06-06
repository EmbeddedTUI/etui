# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
import shutil
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.widgets import Button
from textual.widgets import Input
from textual.widgets import RichLog
from textual.widgets import Select


# Available debugger backends: label -> command line (argv) launched as a
# line-oriented interactive console driven over stdin/stdout.
BACKENDS = {
    "pyocd": ["pyocd", "commander"],
    "openocd": ["openocd"],
    "gdb": ["gdb", "--quiet", "--interpreter=mi2"],
}

# Sentinel value used in the probe Select when no specific probe is chosen.
PROBE_AUTO = "__auto__"

# Known debug probes identified purely by USB VID:PID. This catches probes
# that pyocd cannot enumerate itself (e.g. the TI XDS110 on LaunchPads).
# (vid, pid) -> (description, driver, openocd_config)
KNOWN_USB_PROBES = {
    (0x0451, 0xBEF3): (
        "TI XDS110 (CC1352R1 LaunchPad)",
        "openocd",
        "board/ti_cc13x2_launchpad.cfg",
    ),
    (0x0451, 0xBEF4): ("TI XDS110", "openocd", "interface/xds110.cfg"),
    (0x1CBE, 0x00FD): ("TI XDS110", "openocd", "interface/xds110.cfg"),
}


class DebuggerLog(RichLog):
    def __init__(self):
        super().__init__(highlight=True, markup=True)
        self.write("Debugger ready")


class DebuggerTab(Horizontal):
    """ Debugger tab - drives pyocd, openocd or gdb """

    def __init__(self):
        super().__init__()
        self._proc: asyncio.subprocess.Process | None = None
        self._backend = "pyocd"
        # Currently selected probe, populated by detect_probes().
        self._probe: dict | None = None
        # uid -> probe info dict, keyed by the value stored in the Select.
        self._probes: dict[str, dict] = {}

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="debugger-controls"):
                yield Select(
                    [(name, name) for name in BACKENDS],
                    value="pyocd",
                    allow_blank=False,
                    id="dbg-backend",
                )
                yield Button("Detect", id="dbg-detect", variant="primary")
                yield Select(
                    [("Auto-detect", PROBE_AUTO)],
                    value=PROBE_AUTO,
                    allow_blank=False,
                    id="dbg-probe",
                )
                yield Button("Start", id="dbg-start", variant="success")
                yield Button("Stop", id="dbg-stop", variant="error")
            yield DebuggerLog()
            yield Input(placeholder="debugger command", id="dbg-input")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "dbg-backend":
            self._backend = str(event.value)
        elif event.select.id == "dbg-probe":
            value = str(event.value)
            self._probe = self._probes.get(value)
            # Auto-switch the backend to whatever the chosen probe needs.
            if self._probe and self._probe.get("driver"):
                driver = self._probe["driver"]
                if driver in BACKENDS:
                    self._backend = driver
                    self.query_one("#dbg-backend", Select).value = driver

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "dbg-detect":
            await self.detect_probes()
        elif event.button.id == "dbg-start":
            await self.start()
        elif event.button.id == "dbg-stop":
            await self.stop()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        event.input.value = ""
        if command:
            await self.send_command(command)

    @staticmethod
    def _list_probes() -> list[dict]:
        """ Enumerate connected debug probes off the event loop.

        Combines pyocd's native probe enumeration with a USB VID:PID scan
        for known probes that pyocd cannot detect itself (e.g. TI XDS110).
        Returns a list of dicts: {uid, desc, driver, config}.
        """
        result: list[dict] = []
        seen_uids: set[str] = set()

        # 1. pyocd-native probes (CMSIS-DAP, J-Link, ST-Link, ...).
        try:
            from pyocd.probe.aggregator import DebugProbeAggregator

            for probe in DebugProbeAggregator.get_all_connected_probes():
                uid = probe.unique_id
                desc = probe.description or probe.product_name or "probe"
                seen_uids.add(uid)
                result.append(
                    {"uid": uid, "desc": desc, "driver": "pyocd", "config": None}
                )
        except Exception:
            pass

        # 2. USB VID:PID scan for known probes pyocd can't enumerate.
        try:
            import usb.core
            import usb.util

            for dev in usb.core.find(find_all=True):
                key = (dev.idVendor, dev.idProduct)
                if key not in KNOWN_USB_PROBES:
                    continue
                desc, driver, config = KNOWN_USB_PROBES[key]
                serial = None
                try:
                    serial = usb.util.get_string(dev, dev.iSerialNumber)
                except Exception:
                    pass
                uid = serial or f"{dev.idVendor:04x}:{dev.idProduct:04x}"
                if uid in seen_uids:
                    continue
                seen_uids.add(uid)
                result.append(
                    {"uid": uid, "desc": desc, "driver": driver, "config": config}
                )
        except Exception:
            pass

        return result

    async def detect_probes(self) -> None:
        log = self.query_one(DebuggerLog)
        probe_select = self.query_one("#dbg-probe", Select)
        log.write("[cyan]detecting probes...[/cyan]")
        try:
            probes = await asyncio.to_thread(self._list_probes)
        except Exception as e:  # pyocd / usb backend errors
            log.write(f"[red]probe detection failed: {e}[/red]")
            return

        self._probes = {}
        options = [("Auto-detect", PROBE_AUTO)]
        for p in probes:
            label = f"{p['desc']} [{p['uid']}]"
            self._probes[p["uid"]] = p
            options.append((label, p["uid"]))
            log.write(
                f"[green]found:[/green] {label}  [dim]driver={p['driver']}[/dim]"
            )
        if not probes:
            log.write("[yellow]no debug probes found[/yellow]")

        probe_select.set_options(options)
        probe_select.value = PROBE_AUTO
        self._probe = None

    def _build_argv(self, log: "DebuggerLog") -> list[str] | None:
        """ Build the backend command line for the selected probe. """
        backend = self._backend
        argv = list(BACKENDS[backend])

        if backend == "pyocd":
            if self._probe and self._probe["driver"] != "pyocd":
                log.write(
                    f"[red]{self._probe['desc']} needs the "
                    f"'{self._probe['driver']}' backend, not pyocd[/red]"
                )
                return None
            if self._probe:
                argv += ["--uid", self._probe["uid"]]
        elif backend == "openocd":
            config = self._probe.get("config") if self._probe else None
            if config:
                argv += ["-f", config]
            else:
                log.write(
                    "[yellow]openocd: no config for probe, "
                    "type commands manually[/yellow]"
                )
        return argv

    async def start(self) -> None:
        log = self.query_one(DebuggerLog)
        if self._proc is not None and self._proc.returncode is None:
            log.write("[yellow]debugger already running[/yellow]")
            return
        if shutil.which(BACKENDS[self._backend][0]) is None:
            log.write(f"[red]{BACKENDS[self._backend][0]} not found on PATH[/red]")
            return
        argv = self._build_argv(log)
        if argv is None:
            return
        if self._probe:
            log.write(f"[cyan]using probe {self._probe['uid']}[/cyan]")
        self._proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        log.write(f"[green]{self._backend} started[/green]")
        self.run_worker(self._read_output(), exclusive=False)

    async def stop(self) -> None:
        log = self.query_one(DebuggerLog)
        if self._proc is None or self._proc.returncode is not None:
            log.write("[yellow]debugger not running[/yellow]")
            return
        self._proc.terminate()
        await self._proc.wait()
        log.write(f"[green]{self._backend} stopped[/green]")
        self._proc = None

    async def send_command(self, command: str) -> None:
        log = self.query_one(DebuggerLog)
        if self._proc is None or self._proc.returncode is not None:
            log.write("[red]debugger not running - press Start[/red]")
            return
        log.write(f"[cyan]> {command}[/cyan]")
        assert self._proc.stdin is not None
        self._proc.stdin.write((command + "\n").encode())
        await self._proc.stdin.drain()

    async def _read_output(self) -> None:
        log = self.query_one(DebuggerLog)
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            log.write(line.decode(errors="replace").rstrip())
