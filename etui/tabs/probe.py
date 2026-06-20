# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
import json
import re
import shutil
from pathlib import Path
from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button
from textual.widgets import Input
from textual.widgets import Label
from textual.widgets import RichLog
from textual.widgets import Select


# Available debugger backends: label -> command line (argv) launched as a
# line-oriented interactive console driven over stdin/stdout.
BACKENDS = {
    "pyocd":   ["pyocd", "gdbserver"],
    "openocd": ["openocd"],
    "stlink":  ["st-util"],
    "gdb":     ["gdb", "--quiet", "--interpreter=mi2"],
}

# Default GDB server port for st-util (OpenOCD uses 3333).
STLINK_GDB_PORT = 4242

# pyocd output patterns that indicate a fatal connection failure.
PYOCD_FATAL_PATTERNS = [
    "error: failed to open",
    "no connected probes",
    "failed to connect",
    "unable to open",
    "usb error",
    "not recognized",          # target type not in pyocd's built-in list
    "no pack installed",
    "pack not installed",
    "invalid ap address",      # STM32F7 DebugDeviceUnlock failure
    "error while initing target",
    "debug sequence",
]

# pyocd output patterns that indicate a missing CMSIS pack specifically.
PYOCD_PACK_PATTERNS = [
    "target type",
    "not recognized",
    "use 'pyocd pack",
    "use \"pyocd pack",
]

# Sentinel values for the Select widgets.
PROBE_AUTO = "__auto__"
TARGET_NONE = "__none__"

# OpenOCD interface configs for the XDS110 in its two firmware modes.
XDS110_NATIVE = "interface/xds110.cfg"
CMSIS_DAP_INTERFACE = "interface/cmsis-dap.cfg"
XDS110_CMSISDAP = CMSIS_DAP_INTERFACE

# MCU families selectable once an XDS110 probe is detected. They all share
# one OpenOCD target config (SWD); the label sets the OpenOCD chip name and
# the LLDB target architecture. label -> (chipname, lldb_arch).
TARGETS = {
    "MSPM0L": ("mspm0l", "thumbv6m-none-eabi"),
    "MSPM0G": ("mspm0g", "thumbv6m-none-eabi"),
    "MSPM0C": ("mspm0c", "thumbv6m-none-eabi"),
}
MSPM0_TARGET_CFG = "target/ti/mspm0.cfg"

# Known debug probes identified purely by USB VID:PID. This catches probes
# that pyocd cannot enumerate itself (e.g. TI XDS110 in native firmware mode).
# ST-LINK entries use driver="pyocd" (primary); st-util is the manual fallback.
# (vid, pid) -> (description, driver, interface_cfg)
KNOWN_USB_PROBES = {
    (0x0451, 0xBEF3): ("TI XDS110 (LaunchPad)", "openocd", XDS110_NATIVE),
    (0x0451, 0xBEF4): ("TI XDS110",             "openocd", XDS110_NATIVE),
    (0x1CBE, 0x00FD): ("TI XDS110",             "openocd", XDS110_NATIVE),
    (0x0483, 0x3748): ("ST-LINK/V2",             "pyocd",   None),
    (0x0483, 0x374b): ("ST-LINK/V2.1",           "pyocd",   None),
    (0x0483, 0x374e): ("ST-LINK/V3",             "pyocd",   None),
    (0x0483, 0x374f): ("ST-LINK/V3E",            "pyocd",   None),
    (0x1FC9, 0x0090): (
        "NXP LPC-LINK2 CMSIS-DAP",
        "pyocd",
        CMSIS_DAP_INTERFACE,
    ),
    (0x2E8A, 0x000C): (
        "Raspberry Pi Debug Probe",
        "pyocd",
        CMSIS_DAP_INTERFACE,
    ),
}


# Persisted debugger settings. The order here is the order shown in the
# settings dialog; the value type is inferred from the default.
DEFAULT_SETTINGS = {
    "adapter_speed_khz": 4000,
    "transport": "swd",
    "gdb_port": 3333,
    "telnet_port": 4444,
    "tcl_port": 6666,
    "stlink_gdb_port": STLINK_GDB_PORT,
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
            yield Label("Probe Settings")
            for key, value in self._settings.items():
                yield Label(key)
                yield Input(value=str(value), id=f"set-{key}")
            with Horizontal(id="settings-buttons"):
                yield Button("Save", id="settings-save", variant="success")
                yield Button("Cancel", id="settings-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()


FAMILIES = [
    ("i.MX RT (imxrt)", "imxrt"),
    ("LPC (lpc)", "lpc"),
    ("STM32 (stm32)", "stm32"),
    ("SAM (sam)", "sam"),
    ("nRF (nrf)", "nrf"),
    ("RP2040 (rp2040)", "rp2040"),
    ("All", "all"),
]


class TargetFilterScreen(ModalScreen[str | None]):
    """ Modal dialog to prompt for a target family/name filter. """

    CSS = """
        TargetFilterScreen {
            align: center middle;
        }
        #filter-box {
            width: 45;
            height: auto;
            border: thick $accent;
            background: $surface;
            padding: 1 2;
        }
        #filter-box Select {
            margin-bottom: 1;
        }
        #filter-box Input {
            margin-bottom: 1;
        }
        #filter-buttons {
            height: auto;
            align-horizontal: right;
        }
        #filter-buttons Button {
            margin-left: 2;
        }
    """

    def __init__(self, default_value: str = ""):
        super().__init__()
        self.default_value = default_value
        self.initial_select = "all"
        for _, val in FAMILIES:
            if val == default_value:
                self.initial_select = val
                break

    def compose(self) -> ComposeResult:
        with Vertical(id="filter-box"):
            yield Label("Filter pyOCD targets:")
            yield Select(
                [(label, val) for label, val in FAMILIES],
                value=self.initial_select,
                allow_blank=False,
                id="filter-select",
            )
            yield Input(
                value=self.default_value,
                placeholder="e.g. stm32, lpc, nrf",
                id="filter-input",
            )
            with Horizontal(id="filter-buttons"):
                yield Button("Query", id="filter-query", variant="success")
                yield Button("Cancel", id="filter-cancel")

    def on_mount(self) -> None:
        self.query_one("#filter-select", Select).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        event.stop()
        if event.select.id == "filter-select":
            val = str(event.value)
            inp = self.query_one("#filter-input", Input)
            if val != "all":
                inp.value = val
            else:
                inp.value = ""

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "filter-cancel":
            self.dismiss(None)
        elif event.button.id == "filter-query":
            val = self.query_one("#filter-input", Input).value.strip()
            self.dismiss(val)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        val = event.value.strip()
        self.dismiss(val)


class LldbStart(Message):
    """ Posted when the hardware debugger's gdb server is ready for lldb. """

    def __init__(self, port: int, arch: str | None = None) -> None:
        super().__init__()
        self.port = port
        self.arch = arch


class ProbeLog(RichLog):
    def __init__(self):
        super().__init__(highlight=True, markup=True)
        self.write("Probe ready")


class ProbeTab(Vertical):
    """ Probe tab - drives pyocd, openocd or gdb """

    DEFAULT_CSS = """
        ProbeTab {
            width: 1fr;
            height: 1fr;
        }

        ProbeTab #probe-layout {
            width: 1fr;
            height: 1fr;
        }

        ProbeTab #probe-content {
            width: 1fr;
            height: 1fr;
        }

        ProbeTab #probe-selectors {
            width: 1fr;
            height: 5;
        }

        ProbeTab #dbg-backend {
            width: 18;
        }

        ProbeTab #dbg-probe {
            width: 2fr;
            min-width: 30;
        }

        ProbeTab #dbg-target {
            width: 2fr;
            min-width: 26;
        }

        ProbeTab #probe-actions {
            width: 20;
            min-width: 20;
            height: 1fr;
            padding: 0 1;
        }

        ProbeTab #probe-actions Button {
            width: 1fr;
            min-width: 16;
            margin-bottom: 1;
        }

        ProbeTab ProbeLog {
            width: 1fr;
            height: 1fr;
        }

        ProbeTab #dbg-input {
            width: 1fr;
        }
    """

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
        # pyOCD target identifier configured by the user.
        self._pyocd_target: str | None = None
        self._custom_targets: set[str] = set()
        # LLDB target triple for the selected target.
        self._target_arch: str | None = None
        # Persisted connection settings (adapter speed, ports, ...).
        self._settings = load_settings()
        # Whether the LLDB tab has been opened for the current session.
        self._lldb_opened = False
        # Set when pyocd exits with a fatal error so the UI can suggest stlink.
        self._pyocd_failed = False
        # Target name extracted from a pyocd "not recognized" error, if any.
        self._missing_pack: str | None = None

    def compose(self) -> ComposeResult:
        if __package__:
            from ..plugin import ToolWarningBanner
        else:
            from plugin import ToolWarningBanner
        yield ToolWarningBanner("openocd", "OpenOCD", id="openocd-tool-warning")

        with Horizontal(id="probe-layout"):
            with Vertical(id="probe-content"):
                with Horizontal(id="probe-selectors"):
                    yield Select(
                        [(name, name) for name in BACKENDS],
                        value="pyocd",
                        allow_blank=False,
                        id="dbg-backend",
                    )
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
                yield ProbeLog()
                yield Input(placeholder="debugger command", id="dbg-input")
            with Vertical(id="probe-actions"):
                yield Button("Detect", id="dbg-detect", variant="primary")
                yield Button("List targets", id="dbg-list-targets")
                yield Button("Settings", id="dbg-settings")
                yield Button("Start", id="dbg-start", variant="success")
                yield Button("Stop", id="dbg-stop", variant="error")
                yield Button("Kill stale", id="dbg-kill-stale", variant="warning")
                yield Button(
                    "Install Pack",
                    id="dbg-install-pack",
                    variant="warning",
                )
                yield Button(
                    "Install stlink",
                    id="dbg-install-stlink",
                    variant="warning",
                )

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "dbg-backend":
            self._backend = str(event.value)
        elif event.select.id == "dbg-probe":
            self._select_probe(self.query_one("#dbg-probe", Select), str(event.value))
        elif event.select.id == "dbg-target":
            self._select_target(str(event.value))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "dbg-settings":
            self.open_settings()
        elif event.button.id == "dbg-detect":
            await self.detect_probes()
        elif event.button.id == "dbg-list-targets":
            self.query_targets()
        elif event.button.id == "dbg-start":
            await self.start()
        elif event.button.id == "dbg-stop":
            await self.stop()
        elif event.button.id == "dbg-kill-stale":
            await self.kill_stale()
        elif event.button.id == "dbg-install-pack":
            await self._install_pack()
        elif event.button.id == "dbg-install-stlink":
            await self._install_stlink()

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
            manager = getattr(self.app, "settings_manager", None)
            if manager is not None:
                try:
                    for key, value in result.items():
                        manager.settings["probe"][key] = value
                    manager.save_settings()
                except OSError:
                    pass
                settings_path = manager.path
            else:
                save_settings(result)
                settings_path = SETTINGS_PATH
            self.query_one(ProbeLog).write(
                f"[green]settings saved[/green] [dim]{settings_path}[/dim]"
            )

        self.app.push_screen(SettingsScreen(dict(self._settings)), _on_close)

    def apply_settings(self, settings: dict) -> None:
        """Apply unified settings to the mounted probe controls."""
        self._backend = str(settings.get("backend", "pyocd"))
        self._settings = {
            key: settings.get(key, default)
            for key, default in DEFAULT_SETTINGS.items()
        }
        try:
            self.query_one("#dbg-backend", Select).value = self._backend
        except Exception:
            pass

        target = str(settings.get("target", "")).upper()
        target_label = next(
            (label for label in TARGETS if target.startswith(label)),
            TARGET_NONE,
        )
        if target_label != TARGET_NONE:
            self._target, self._target_arch = TARGETS[target_label]
            self._pyocd_target = None
        elif target:
            target_label = str(settings.get("target", "")).strip()
            self._custom_targets.add(target_label)
            self._target = None
            self._target_arch = "thumb"
            self._pyocd_target = target_label
        try:
            target_select = self.query_one("#dbg-target", Select)
            self._refresh_target_options(target_select)
            target_select.value = target_label
        except Exception:
            pass

    def _refresh_target_options(self, target_select: Select) -> None:
        options = [("Target...", TARGET_NONE)]
        options.extend((label, label) for label in TARGETS)
        options.extend(
            (f"Configured: {target}", target)
            for target in sorted(self._custom_targets)
            if target not in TARGETS
        )
        target_select.set_options(options)

    def _select_target(self, value: str) -> None:
        chip_arch = TARGETS.get(value)
        if chip_arch:
            self._target, self._target_arch = chip_arch
            self._pyocd_target = None
        elif value and value != TARGET_NONE:
            self._target = None
            self._target_arch = "thumb"
            self._pyocd_target = value
            self._persist_target(value)
        else:
            self._target = None
            self._target_arch = None
            self._pyocd_target = None

    def _persist_target(self, target: str) -> None:
        manager = getattr(self.app, "settings_manager", None)
        if manager is None:
            return
        manager.settings["probe"]["target"] = target
        try:
            manager.save_settings()
        except OSError:
            self.query_one(ProbeLog).write(
                "[yellow]could not persist selected target[/yellow]"
            )

    @staticmethod
    def _parse_pyocd_targets(output: str, filter_str: str | None = None) -> list[tuple[str, str]]:
        targets: list[tuple[str, str]] = []
        seen: set[str] = set()
        for raw_line in output.splitlines():
            columns = raw_line.split()
            if len(columns) < 2:
                continue
            target_id = columns[0]
            if (
                target_id in seen
                or target_id.lower() == "name"
                or not ProbeTab._valid_pyocd_target(target_id)
            ):
                continue
            if filter_str and filter_str.lower() not in target_id.lower():
                continue
            vendor = columns[1]
            display_name = " ".join(columns[2:-1]) if len(columns) > 3 else ""
            label = f"{target_id} - {vendor}"
            if display_name:
                label += f" {display_name}"
            targets.append((label, target_id))
            seen.add(target_id)
        return targets

    def query_targets(self) -> None:
        default_query = ""
        if self._probe:
            desc = self._probe.get("desc", "").lower()
            if "lpc" in desc:
                default_query = "lpc"
            elif "st-link" in desc or "stlink" in desc or self._probe.get("transport") == "stlink":
                default_query = "stm32"
            elif "sam" in desc:
                default_query = "sam"
            elif "nrf" in desc or "nordic" in desc:
                default_query = "nrf"
            elif "rp2040" in desc or "pico" in desc:
                default_query = "rp2040"

        def _on_close(result: str | None) -> None:
            if result is None:
                return
            self.run_worker(self.list_targets(result), exclusive=True)

        self.app.push_screen(TargetFilterScreen(default_query), _on_close)

    async def list_targets(self, filter_str: str) -> None:
        log = self.query_one(ProbeLog)
        button = self.query_one("#dbg-list-targets", Button)
        pyocd_exe = shutil.which("pyocd")
        if pyocd_exe is None:
            log.write("[red]pyocd not found on PATH[/red]")
            return

        button.disabled = True
        if filter_str:
            log.write(f"[cyan]loading targets matching '{escape(filter_str)}' from pyocd...[/cyan]")
        else:
            log.write("[cyan]loading all targets from pyocd...[/cyan]")
        try:
            process = await asyncio.create_subprocess_exec(
                pyocd_exe,
                "list",
                "--targets",
                "-H",
                "-n",
                filter_str,
                "--color",
                "never",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=10.0,
            )
        except TimeoutError:
            if process.returncode is None:
                process.kill()
                await process.wait()
            log.write("[red]pyocd target query timed out[/red]")
            return
        except OSError as error:
            log.write(
                f"[red]could not run pyocd target query: "
                f"{escape(str(error))}[/red]"
            )
            return
        finally:
            button.disabled = False

        text = stdout.decode(errors="replace")
        if process.returncode != 0:
            log.write(
                f"[red]pyocd target query failed with exit code "
                f"{process.returncode}[/red]"
            )
            if text.strip():
                log.write(escape(text.strip()))
            return

        targets = self._parse_pyocd_targets(text, filter_str)
        if not targets:
            if filter_str:
                log.write(f"[yellow]pyocd reported no targets matching '{escape(filter_str)}'[/yellow]")
            else:
                log.write("[yellow]pyocd reported no targets[/yellow]")
            return

        self._custom_targets = set(target_id for _, target_id in targets)
        target_select = self.query_one("#dbg-target", Select)
        self._refresh_target_options(target_select)
        target_select.disabled = False
        current = self._pyocd_target
        if current in self._custom_targets:
            target_select.value = current
        else:
            target_select.value = TARGET_NONE
            self._pyocd_target = None
        if filter_str:
            log.write(
                f"[green]loaded {len(targets)} targets matching '{escape(filter_str)}'; "
                "select one from the target dropdown[/green]"
            )
        else:
            log.write(
                f"[green]loaded {len(targets)} targets; "
                "select one from the target dropdown[/green]"
            )

    @staticmethod
    def _list_probes() -> list[dict]:
        """ Enumerate connected debug probes off the event loop.

        Combines pyocd's native probe enumeration with a USB VID:PID scan
        for known probes that pyocd cannot detect itself (e.g. TI XDS110).
        Returns normalized dictionaries containing identity, transport, and
        backend metadata.
        """
        result: list[dict] = []
        seen_uids: set[str] = set()

        # 1. pyocd-native probes (CMSIS-DAP, J-Link, ST-Link, ...).
        try:
            from pyocd.probe.aggregator import DebugProbeAggregator

            for probe in DebugProbeAggregator.get_all_connected_probes():
                uid = str(probe.unique_id or "")
                desc = (
                    probe.description
                    or getattr(probe, "product_name", None)
                    or "probe"
                )
                desc = str(desc)
                if not uid:
                    continue
                seen_uids.add(uid)
                driver, interface = ProbeTab._classify(desc)
                result.append(
                    {
                        "uid": uid,
                        "desc": desc,
                        "driver": driver,
                        "interface": interface,
                        "transport": ProbeTab._transport(desc, interface),
                        "firmware": ProbeTab._firmware_version(desc),
                        "vid": getattr(probe, "vendor_id", None),
                        "pid": getattr(probe, "product_id", None),
                        "backend_uid": True,
                    }
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
                product = None
                try:
                    serial = usb.util.get_string(dev, dev.iSerialNumber)
                except Exception:
                    pass
                try:
                    product = usb.util.get_string(dev, dev.iProduct)
                except Exception:
                    pass
                bus = getattr(dev, "bus", None)
                address = getattr(dev, "address", None)
                location = (
                    f"@{bus}:{address}"
                    if bus is not None and address is not None
                    else ""
                )
                uid = serial or (
                    f"{dev.idVendor:04x}:{dev.idProduct:04x}{location}"
                )
                if uid in seen_uids:
                    continue
                seen_uids.add(uid)
                result.append(
                    {
                        "uid": uid,
                        "desc": desc,
                        "driver": driver,
                        "interface": interface,
                        "transport": ProbeTab._transport(desc, interface),
                        "firmware": ProbeTab._firmware_version(product or desc),
                        "vid": dev.idVendor,
                        "pid": dev.idProduct,
                        "backend_uid": bool(serial),
                    }
                )
        except Exception:
            pass

        return result

    @staticmethod
    def _firmware_version(text: str) -> str | None:
        match = re.search(r"\bV\d+(?:\.\d+)+\b", text, flags=re.IGNORECASE)
        return match.group(0) if match else None

    @staticmethod
    def _transport(desc: str, interface: str | None) -> str:
        normalized = desc.lower().replace("_", "-")
        if interface == CMSIS_DAP_INTERFACE or "cmsis-dap" in normalized \
                or "cmsis dap" in normalized:
            return "cmsis-dap"
        if "st-link" in normalized or "stlink" in normalized:
            return "stlink"
        if "xds110" in normalized:
            return "xds110"
        return "unknown"

    @staticmethod
    def _classify(desc: str) -> tuple[str, str | None]:
        """Pick a backend + OpenOCD interface from a pyocd probe description.

        XDS110 probes are routed to OpenOCD (pyocd cannot target TI MSPM0).
        ST-LINK probes are kept on pyocd (native support); st-util is the
        manual fallback the user can select via the Backend dropdown.
        Everything else also stays on pyocd.
        """
        d = desc.lower()
        if "xds110" in d:
            if "cmsis-dap" in d or "cmsis dap" in d:
                return "openocd", XDS110_CMSISDAP
            return "openocd", XDS110_NATIVE
        if "st-link" in d or "stlink" in d:
            return "pyocd", None
        if "cmsis-dap" in d or "cmsis dap" in d or "lpc-link2" in d:
            return "pyocd", CMSIS_DAP_INTERFACE
        return "pyocd", None

    @staticmethod
    def _valid_pyocd_target(target: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", target))

    async def detect_probes(self) -> None:
        log = self.query_one(ProbeLog)
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
            metadata = []
            if p.get("vid") is not None and p.get("pid") is not None:
                metadata.append(f"{p['vid']:04x}:{p['pid']:04x}")
            if p.get("transport"):
                metadata.append(p["transport"])
            if p.get("firmware"):
                metadata.append(p["firmware"])
            details = " ".join(metadata)
            log.write(
                f"[green]found:[/green] {escape(label)}  "
                f"[dim]driver={p['driver']} {escape(details)}[/dim]"
            )
        if not probes:
            log.write("[yellow]no debug probes found[/yellow]")

        probe_select.set_options(options)
        if len(probes) == 1:
            # Single probe: auto-select it so Start just works. Setting the
            # value drives on_select_changed, which also switches backend.
            self._select_probe(probe_select, probes[0]["uid"])
            log.write(
                f"[cyan]selected {escape(probes[0]['desc'])} "
                f"(backend: {self._backend})[/cyan]"
            )
        else:
            probe_select.value = PROBE_AUTO
            self._probe = None

        # Warn early if an ST-LINK was found but st-util is not installed.
        has_stlink = any("st-link" in p["desc"].lower() or "stlink" in p["desc"].lower() for p in probes)
        if has_stlink and not shutil.which("st-util"):
            install_cmd = self._stlink_install_cmd()
            log.write(
                f"[yellow]ST-LINK detected but st-util not installed — "
                f"needed as fallback if pyocd fails[/yellow]"
            )
            if install_cmd:
                log.write(f"[yellow]install: {install_cmd}[/yellow]")
            btn = self.query_one("#dbg-install-stlink", Button)
            btn.display = True

    def _select_probe(self, probe_select: Select, uid: str) -> None:
        if probe_select.value != uid:
            probe_select.value = uid
        self._probe = self._probes.get(uid)
        # Only force the backend when the probe requires a specific non-pyocd
        # driver (e.g. XDS110 → openocd). For pyocd probes, respect whatever
        # the user has selected — they may have deliberately chosen 'stlink'.
        probe_driver = self._probe.get("driver") if self._probe else None
        if probe_driver and probe_driver != "pyocd" and probe_driver in BACKENDS:
            self._backend = probe_driver
            self.query_one("#dbg-backend", Select).value = self._backend
        # Debug adapters do not identify the attached MCU. Every GDB-server
        # backend therefore requires a compatible explicit target.
        target_select = self.query_one("#dbg-target", Select)
        needs_target = bool(
            self._probe
            and self._probe.get("driver") in {"pyocd", "openocd"}
        )
        target_select.disabled = not needs_target
        missing_target = (
            self._pyocd_target is None
            if self._backend == "pyocd"
            else self._target is None
        )
        if needs_target and missing_target:
            if self._backend == "pyocd":
                self.query_one(ProbeLog).write(
                    "[yellow]configure the attached MCU's pyOCD target ID in "
                    "Settings (example: lpc55s69; list with "
                    "'pyocd list --targets -n lpc')[/yellow]"
                )
            elif self._backend == "openocd":
                self.query_one(ProbeLog).write(
                    "[yellow]select a packaged OpenOCD target profile[/yellow]"
                )

    def _build_argv(self, log: "ProbeLog") -> list[str] | None:
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
            if not self._pyocd_target:
                log.write(
                    "[red]configure an explicit pyOCD target ID in Settings "
                    "before starting this probe[/red]"
                )
                return None
            if not self._valid_pyocd_target(self._pyocd_target):
                log.write("[red]the configured pyOCD target ID is invalid[/red]")
                return None
            if self._probe:
                if not self._probe.get("backend_uid", True):
                    log.write(
                        "[red]the probe was found by USB but has no usable "
                        "serial; check pyOCD support and USB permissions[/red]"
                    )
                    return None
                argv += ["--uid", self._probe["uid"]]
            argv += ["--target", self._pyocd_target]
            argv += ["--port", str(self._settings["gdb_port"])]
            argv += ["--telnet-port", str(self._settings["telnet_port"])]
            frequency_hz = int(self._settings["adapter_speed_khz"]) * 1000
            argv += ["--frequency", str(frequency_hz), "--no-wait"]
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
        elif backend == "stlink":
            port = self._settings.get("stlink_gdb_port", STLINK_GDB_PORT)
            argv += ["--port", str(port)]
            if self._probe and self._probe.get("uid"):
                argv += ["--serial", self._probe["uid"]]
            argv += ["--verbose"]
        return argv

    async def start(self) -> None:
        log = self.query_one(ProbeLog)
        if self._proc is not None and self._proc.returncode is None:
            log.write("[yellow]debugger already running[/yellow]")
            return

        backend_exe = BACKENDS[self._backend][0]
        if self._backend == "openocd" and hasattr(self.app, "tool_registry"):
            res = self.app.tool_registry.get_result("openocd")
            if res and res.state.value == "Installed":
                primary_exe = res.executables[0] if res.executables else None
                if primary_exe and primary_exe.path:
                    backend_exe = primary_exe.path
        elif self._backend == "stlink" and hasattr(self.app, "tool_registry"):
            res = self.app.tool_registry.get_result("stlink")
            if res and res.state.value == "Installed":
                for exe in res.executables:
                    if exe.name == "st-util" and exe.path:
                        backend_exe = exe.path
                        break
        elif self._backend == "gdb" and hasattr(self.app, "tool_registry"):
            res = self.app.tool_registry.get_result("gnu-arm")
            if res and res.state.value == "Installed":
                for exe in res.executables:
                    if exe.name == "arm-none-eabi-gdb" and exe.path:
                        backend_exe = exe.path
                        break

        if shutil.which(backend_exe) is None:
            log.write(f"[red]{backend_exe} not found on PATH[/red]")
            return
        argv = self._build_argv(log)
        if argv is None:
            return

        argv[0] = backend_exe

        if self._probe:
            log.write(f"[cyan]using probe {escape(self._probe['uid'])}[/cyan]")
        self._proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        log.write(f"[green]{self._backend} started[/green]")
        self._lldb_opened = False
        self.run_worker(self._read_output(), exclusive=False)

    def on_mount(self) -> None:
        self.query_one("#dbg-install-pack", Button).display = False
        self.query_one("#dbg-install-stlink", Button).display = False
        manager = getattr(self.app, "settings_manager", None)
        if manager is not None:
            self.apply_settings(manager.settings.get("probe", {}))

    def on_unmount(self) -> None:
        # Avoid orphaned debugger processes holding the probe / ports.
        if self._proc is not None and self._proc.returncode is None:
            self._proc.kill()

    async def stop(self) -> None:
        log = self.query_one(ProbeLog)
        if self._proc is None or self._proc.returncode is not None:
            log.write("[yellow]debugger not running[/yellow]")
            return
        self._proc.terminate()
        await self._proc.wait()
        log.write(f"[green]{self._backend} stopped[/green]")
        self._proc = None

    async def restart_for_lldb(self) -> None:
        """Restart the gdb server after its LLDB client aborted."""
        log = self.query_one(ProbeLog)
        process = self._proc
        if process is not None and process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()

        self._proc = None
        self._lldb_opened = False
        log.write("[yellow]restarting probe gdb server after LLDB abort[/yellow]")
        await asyncio.sleep(0.25)
        await self.start()

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
                if "openocd" in name or "pyocd" in name or "st-util" in name:
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
        log = self.query_one(ProbeLog)
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

    @staticmethod
    def _stlink_install_cmd() -> str:
        """Return a platform-appropriate install command for stlink-tools."""
        if shutil.which("apt-get"):
            return "sudo apt-get install -y stlink-tools"
        if shutil.which("dnf"):
            return "sudo dnf install -y stlink"
        if shutil.which("pacman"):
            return "sudo pacman -S --noconfirm stlink"
        if shutil.which("brew"):
            return "brew install stlink"
        return ""

    async def _install_stlink(self) -> None:
        """Send the stlink install command to the Console tab for the user to run."""
        log = self.query_one(ProbeLog)
        cmd = self._stlink_install_cmd()
        if not cmd:
            log.write("[red]no supported package manager found — install stlink manually[/red]")
            return
        if __package__:
            from ..tabs.console import ConsoleTab
        else:
            from tabs.console import ConsoleTab
        from textual.widgets import TabbedContent
        self.app.query_one(TabbedContent).active = "console"
        console_input = self.app.query_one("#console-input", Input)
        console_input.value = cmd
        console_input.focus()

    @staticmethod
    def _extract_target_from_line(text: str) -> str:
        """Extract the target chip name from a pyocd 'not recognized' line."""
        # Expected form: "... Target type stm32f746zgtx not recognized ..."
        parts = text.split()
        for i, word in enumerate(parts):
            if word.lower() == "type" and i + 1 < len(parts):
                candidate = parts[i + 1].rstrip(".")
                if candidate.lower() not in ("not", "is", "the", "a"):
                    return candidate
        return ""

    async def _install_pack(self) -> None:
        """Run 'pyocd pack update && pyocd pack install <target>' and stream output."""
        target = self._missing_pack
        if not target:
            return
        log = self.query_one(ProbeLog)
        btn = self.query_one("#dbg-install-pack", Button)
        btn.disabled = True
        log.write(f"[cyan]installing pyocd pack for {target}...[/cyan]")

        async def _run(args: list[str]) -> int:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                log.write(line.decode(errors="replace").rstrip())
            await proc.wait()
            return proc.returncode or 0

        pyocd_exe = shutil.which("pyocd") or "pyocd"
        rc = await _run([pyocd_exe, "pack", "update"])
        if rc != 0:
            log.write("[red]pyocd pack update failed[/red]")
            btn.disabled = False
            return
        rc = await _run([pyocd_exe, "pack", "install", target])
        if rc == 0:
            log.write(f"[green]pack installed — press Start to retry[/green]")
            btn.display = False
            self._missing_pack = None
        else:
            log.write(f"[red]pyocd pack install {target} failed[/red]")
            btn.disabled = False

    async def send_command(self, command: str) -> None:
        log = self.query_one(ProbeLog)
        if self._proc is None or self._proc.returncode is not None:
            log.write("[red]debugger not running - press Start[/red]")
            return
        log.write(f"[cyan]> {command}[/cyan]")
        assert self._proc.stdin is not None
        self._proc.stdin.write((command + "\n").encode())
        await self._proc.stdin.drain()

    async def _read_output(self) -> None:
        log = self.query_one(ProbeLog)
        process = self._proc
        assert process is not None and process.stdout is not None
        self._pyocd_failed = False
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            log.write(text)
            tl = text.lower()
            # OpenOCD: GDB server ready.
            if (
                not self._lldb_opened
                and self._backend == "openocd"
                and "for gdb connections" in tl
            ):
                self._lldb_opened = True
                self.post_message(
                    LldbStart(self._settings["gdb_port"], self._target_arch)
                )
            # st-util: GDB server ready.
            elif (
                not self._lldb_opened
                and self._backend == "stlink"
                and "listening" in tl
            ):
                self._lldb_opened = True
                port = self._settings.get("stlink_gdb_port", STLINK_GDB_PORT)
                self.post_message(LldbStart(port, self._target_arch))
            # pyocd: track fatal errors so we can suggest stlink on exit.
            elif self._backend == "pyocd":
                if (
                    not self._lldb_opened
                    and "gdb server listening on port" in tl
                ):
                    self._lldb_opened = True
                    self.post_message(
                        LldbStart(self._settings["gdb_port"], self._target_arch)
                    )
                for pat in PYOCD_FATAL_PATTERNS:
                    if pat in tl:
                        self._pyocd_failed = True
                        # Show Install Pack button for missing CMSIS packs.
                        if any(p in tl for p in PYOCD_PACK_PATTERNS):
                            target_name = self._extract_target_from_line(text)
                            if target_name:
                                self._missing_pack = target_name
                                btn = self.query_one("#dbg-install-pack", Button)
                                btn.label = f"Install Pack: {target_name}"
                                btn.display = True
                            log.write(
                                f"[yellow]hint: pyocd pack update && "
                                f"pyocd pack install {target_name or '<target>'}[/yellow]"
                            )
                        # Immediate stlink nudge for target init / AP failures.
                        elif any(p in tl for p in ("invalid ap address", "error while initing target", "debug sequence")):
                            log.write(
                                "[yellow]pyocd cannot init this target — "
                                "switch Backend to 'stlink' and press Start[/yellow]"
                            )
                        break
        await process.wait()
        if self._proc is process:
            self._proc = None
        # Process exited — offer stlink fallback if pyocd failed.
        if self._pyocd_failed:
            log.write(
                "[yellow]pyocd failed — switch Backend to 'stlink' and press Start[/yellow]"
            )
