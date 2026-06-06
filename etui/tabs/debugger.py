# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
import json
import shutil
from pathlib import Path
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button
from textual.widgets import Input
from textual.widgets import Label
from textual.widgets import RichLog
from textual.widgets import Select


# Available debugger backends: label -> command line (argv) launched as a
# line-oriented interactive console driven over stdin/stdout.
BACKENDS = {
    "pyocd": ["pyocd", "commander"],
    "openocd": ["openocd"],
    "gdb": ["gdb", "--quiet", "--interpreter=mi2"],
}

# Sentinel values for the Select widgets.
PROBE_AUTO = "__auto__"
TARGET_NONE = "__none__"

# OpenOCD interface configs for the XDS110 in its two firmware modes.
XDS110_NATIVE = "interface/xds110.cfg"
XDS110_CMSISDAP = "interface/cmsis-dap.cfg"

# MCU families selectable once an XDS110 probe is detected. They all share
# one OpenOCD target config (SWD); the label only sets the chip name.
# label -> chipname passed to OpenOCD as CHIPNAME.
TARGETS = {
    "MSPM0L": "mspm0l",
    "MSPM0G": "mspm0g",
    "MSPM0C": "mspm0c",
}
MSPM0_TARGET_CFG = "target/ti/mspm0.cfg"

# Known debug probes identified purely by USB VID:PID. This catches the
# XDS110 in its native (non-CMSIS-DAP) firmware mode, which pyocd cannot
# enumerate itself. (vid, pid) -> (description, driver, interface_cfg)
KNOWN_USB_PROBES = {
    (0x0451, 0xBEF3): ("TI XDS110 (LaunchPad)", "openocd", XDS110_NATIVE),
    (0x0451, 0xBEF4): ("TI XDS110", "openocd", XDS110_NATIVE),
    (0x1CBE, 0x00FD): ("TI XDS110", "openocd", XDS110_NATIVE),
}


# Persisted debugger settings. The order here is the order shown in the
# settings dialog; the value type is inferred from the default.
DEFAULT_SETTINGS = {
    "adapter_speed_khz": 4000,
    "transport": "swd",
    "gdb_port": 3333,
    "telnet_port": 4444,
    "tcl_port": 6666,
}

SETTINGS_PATH = Path.home() / ".config" / "etui" / "debugger.json"


def load_settings() -> dict:
    """ Load persisted settings, falling back to defaults for missing keys. """
    settings = dict(DEFAULT_SETTINGS)
    try:
        saved = json.loads(SETTINGS_PATH.read_text())
        for key in DEFAULT_SETTINGS:
            if key in saved:
                settings[key] = saved[key]
    except Exception:
        pass
    return settings


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2))


class SettingsScreen(ModalScreen[dict | None]):
    """ Modal dialog to edit and persist debugger settings. """

    CSS = """
        SettingsScreen {
            align: center middle;
        }
        #settings-box {
            width: 60;
            height: auto;
            border: thick $accent;
            background: $surface;
            padding: 1 2;
        }
        #settings-box Input {
            margin-bottom: 1;
        }
        #settings-buttons {
            height: auto;
            align-horizontal: right;
        }
        #settings-buttons Button {
            margin-left: 2;
        }
    """

    def __init__(self, settings: dict):
        super().__init__()
        self._settings = settings

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-box"):
            yield Label("Debugger Settings")
            for key, value in self._settings.items():
                yield Label(key)
                yield Input(value=str(value), id=f"set-{key}")
            with Horizontal(id="settings-buttons"):
                yield Button("Save", id="settings-save", variant="success")
                yield Button("Cancel", id="settings-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "settings-cancel":
            self.dismiss(None)
            return
        result = {}
        for key, default in self._settings.items():
            raw = self.query_one(f"#set-{key}", Input).value.strip()
            # Coerce to the default's type (int settings stay int).
            if isinstance(default, int):
                try:
                    result[key] = int(raw)
                except ValueError:
                    result[key] = default
            else:
                result[key] = raw
        self.dismiss(result)


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
        # Selected MCU target chipname (e.g. "mspm0l") or None.
        self._target: str | None = None
        # Persisted connection settings (adapter speed, ports, ...).
        self._settings = load_settings()

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
                yield Select(
                    [("Target...", TARGET_NONE)]
                    + [(label, label) for label in TARGETS],
                    value=TARGET_NONE,
                    allow_blank=False,
                    disabled=True,
                    id="dbg-target",
                )
                yield Button("Settings", id="dbg-settings")
                yield Button("Start", id="dbg-start", variant="success")
                yield Button("Stop", id="dbg-stop", variant="error")
                yield Button("Kill stale", id="dbg-kill-stale", variant="warning")
            yield DebuggerLog()
            yield Input(placeholder="debugger command", id="dbg-input")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "dbg-backend":
            self._backend = str(event.value)
        elif event.select.id == "dbg-probe":
            self._select_probe(self.query_one("#dbg-probe", Select), str(event.value))
        elif event.select.id == "dbg-target":
            value = str(event.value)
            self._target = TARGETS.get(value)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "dbg-settings":
            self.open_settings()
        elif event.button.id == "dbg-detect":
            await self.detect_probes()
        elif event.button.id == "dbg-start":
            await self.start()
        elif event.button.id == "dbg-stop":
            await self.stop()
        elif event.button.id == "dbg-kill-stale":
            await self.kill_stale()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        event.input.value = ""
        if command:
            await self.send_command(command)

    def open_settings(self) -> None:
        def _on_close(result: dict | None) -> None:
            if result is None:
                return
            self._settings = result
            save_settings(result)
            self.query_one(DebuggerLog).write(
                f"[green]settings saved[/green] [dim]{SETTINGS_PATH}[/dim]"
            )

        self.app.push_screen(SettingsScreen(dict(self._settings)), _on_close)

    @staticmethod
    def _list_probes() -> list[dict]:
        """ Enumerate connected debug probes off the event loop.

        Combines pyocd's native probe enumeration with a USB VID:PID scan
        for known probes that pyocd cannot detect itself (e.g. TI XDS110).
        Returns a list of dicts: {uid, desc, driver, interface}.
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
                driver, interface = DebuggerTab._classify(desc)
                result.append(
                    {"uid": uid, "desc": desc, "driver": driver,
                     "interface": interface}
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
                desc, driver, interface = KNOWN_USB_PROBES[key]
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
                    {"uid": uid, "desc": desc, "driver": driver,
                     "interface": interface}
                )
        except Exception:
            pass

        return result

    @staticmethod
    def _classify(desc: str) -> tuple[str, str | None]:
        """ Pick a backend + OpenOCD interface from a pyocd probe description.

        pyocd can enumerate an XDS110 running CMSIS-DAP firmware but cannot
        target TI MSPM0/CC13x2 devices, so route the XDS110 to OpenOCD using
        the matching interface. Anything else stays on pyocd.
        """
        d = desc.lower()
        if "xds110" in d:
            if "cmsis-dap" in d or "cmsis dap" in d:
                return "openocd", XDS110_CMSISDAP
            return "openocd", XDS110_NATIVE
        return "pyocd", None

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
        if len(probes) == 1:
            # Single probe: auto-select it so Start just works. Setting the
            # value drives on_select_changed, which also switches backend.
            self._select_probe(probe_select, probes[0]["uid"])
            log.write(
                f"[cyan]selected {probes[0]['desc']} "
                f"(backend: {self._backend})[/cyan]"
            )
        else:
            probe_select.value = PROBE_AUTO
            self._probe = None

    def _select_probe(self, probe_select: Select, uid: str) -> None:
        if probe_select.value != uid:
            probe_select.value = uid
        self._probe = self._probes.get(uid)
        if self._probe and self._probe.get("driver") in BACKENDS:
            self._backend = self._probe["driver"]
            self.query_one("#dbg-backend", Select).value = self._backend
        # An XDS110 (OpenOCD) probe can drive several MCU families - ask the
        # user which one before connecting.
        target_select = self.query_one("#dbg-target", Select)
        is_xds110 = bool(self._probe and self._probe.get("interface"))
        target_select.disabled = not is_xds110
        if is_xds110 and self._target is None:
            self.query_one(DebuggerLog).write(
                "[yellow]select target MCU (MSPM0L / MSPM0G / MSPM0C)[/yellow]"
            )

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
            interface = self._probe.get("interface") if self._probe else None
            if not interface:
                log.write(
                    "[yellow]openocd: no config for probe, "
                    "type commands manually[/yellow]"
                )
                return argv
            if self._target is None:
                log.write("[red]select a target MCU first[/red]")
                return None
            # interface selects the adapter driver, then bind this probe by
            # serial, then set the chip name before sourcing the target cfg.
            s = self._settings
            argv += ["-f", interface]
            uid = self._probe["uid"]
            if uid and ":" not in uid:
                argv += ["-c", f"adapter serial {uid}"]
            argv += ["-c", f"adapter speed {s['adapter_speed_khz']}"]
            argv += ["-c", f"gdb port {s['gdb_port']}"]
            argv += ["-c", f"telnet port {s['telnet_port']}"]
            argv += ["-c", f"tcl port {s['tcl_port']}"]
            argv += ["-c", f"set CHIPNAME {self._target}"]
            argv += ["-f", MSPM0_TARGET_CFG]
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

    def on_unmount(self) -> None:
        # Avoid orphaned debugger processes holding the probe / ports.
        if self._proc is not None and self._proc.returncode is None:
            self._proc.kill()

    async def stop(self) -> None:
        log = self.query_one(DebuggerLog)
        if self._proc is None or self._proc.returncode is not None:
            log.write("[yellow]debugger not running[/yellow]")
            return
        self._proc.terminate()
        await self._proc.wait()
        log.write(f"[green]{self._backend} stopped[/green]")
        self._proc = None

    @staticmethod
    def _kill_stale_procs(own_pid: int | None) -> list[int]:
        """ Terminate stray openocd/pyocd processes, skipping our own. """
        import psutil

        killed: list[int] = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if proc.pid == own_pid:
                    continue
                if "openocd" in name or "pyocd" in name:
                    proc.terminate()
                    killed.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        gone, alive = psutil.wait_procs(
            [p for p in psutil.process_iter() if p.pid in killed], timeout=2
        )
        for proc in alive:
            try:
                proc.kill()
            except psutil.NoSuchProcess:
                continue
        return killed

    async def kill_stale(self) -> None:
        log = self.query_one(DebuggerLog)
        own_pid = self._proc.pid if self._proc else None
        log.write("[cyan]killing stale debugger processes...[/cyan]")
        try:
            killed = await asyncio.to_thread(self._kill_stale_procs, own_pid)
        except Exception as e:
            log.write(f"[red]kill failed: {e}[/red]")
            return
        if killed:
            log.write(f"[green]killed:[/green] {', '.join(map(str, killed))}")
        else:
            log.write("[yellow]no stale processes found[/yellow]")

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
