# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from textual.app import App, ComposeResult
from textual.widgets import Select

from etui.tabs.probe import (
    CMSIS_DAP_INTERFACE,
    KNOWN_USB_PROBES,
    LldbStart,
    ProbeTab,
)


class ProbeTestApp(App):
    def compose(self) -> ComposeResult:
        yield ProbeTab()


class FakeStdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = iter([*(f"{line}\n".encode() for line in lines), b""])

    async def readline(self) -> bytes:
        return next(self._lines)


class FakeProcess:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = FakeStdout(lines)
        self.returncode = None

    async def wait(self) -> int:
        self.returncode = 0
        return 0


class ProbeTabTests(unittest.IsolatedAsyncioTestCase):
    def test_lpc_link2_usb_identity_is_registered(self) -> None:
        desc, driver, interface = KNOWN_USB_PROBES[(0x1FC9, 0x0090)]

        self.assertEqual(desc, "NXP LPC-LINK2 CMSIS-DAP")
        self.assertEqual(driver, "pyocd")
        self.assertEqual(interface, CMSIS_DAP_INTERFACE)

    def test_lpc_link2_is_classified_as_cmsis_dap(self) -> None:
        driver, interface = ProbeTab._classify(
            "NXP Semiconductors LPC-LINK2 CMSIS-DAP V5.182"
        )

        self.assertEqual(driver, "pyocd")
        self.assertEqual(interface, CMSIS_DAP_INTERFACE)
        self.assertEqual(
            ProbeTab._transport(
                "NXP Semiconductors LPC-LINK2 CMSIS-DAP V5.182",
                interface,
            ),
            "cmsis-dap",
        )
        self.assertEqual(
            ProbeTab._firmware_version(
                "NXP Semiconductors LPC-LINK2 CMSIS-DAP V5.182"
            ),
            "V5.182",
        )

    def test_lpc_link2_usb_fallback_preserves_identity_metadata(self) -> None:
        device = SimpleNamespace(
            idVendor=0x1FC9,
            idProduct=0x0090,
            iSerialNumber=1,
            iProduct=2,
            bus=5,
            address=15,
        )

        def get_string(_device: object, index: int) -> str:
            if index == 1:
                return "LPC-LINK2-1"
            return "LPC-LINK2 CMSIS-DAP V5.182"

        with (
            patch(
                "pyocd.probe.aggregator.DebugProbeAggregator"
                ".get_all_connected_probes",
                return_value=[],
            ),
            patch("usb.core.find", return_value=[device]),
            patch("usb.util.get_string", side_effect=get_string),
        ):
            probes = ProbeTab._list_probes()

        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0]["uid"], "LPC-LINK2-1")
        self.assertEqual(probes[0]["vid"], 0x1FC9)
        self.assertEqual(probes[0]["pid"], 0x0090)
        self.assertEqual(probes[0]["transport"], "cmsis-dap")
        self.assertEqual(probes[0]["firmware"], "V5.182")
        self.assertTrue(probes[0]["backend_uid"])

    def test_pyocd_gdbserver_requires_explicit_target(self) -> None:
        tab = ProbeTab()
        tab._probe = {
            "uid": "LPC-LINK2-1",
            "desc": "NXP LPC-LINK2 CMSIS-DAP",
            "driver": "pyocd",
            "interface": CMSIS_DAP_INTERFACE,
        }
        log = MagicMock()

        self.assertIsNone(tab._build_argv(log))
        log.write.assert_called_once()
        self.assertIn("explicit pyOCD target", log.write.call_args.args[0])

    def test_pyocd_gdbserver_command_uses_uid_target_and_ports(self) -> None:
        tab = ProbeTab()
        tab._backend = "pyocd"
        tab._pyocd_target = "lpc55s69"
        tab._probe = {
            "uid": "LPC-LINK2-1",
            "desc": "NXP LPC-LINK2 CMSIS-DAP",
            "driver": "pyocd",
            "interface": CMSIS_DAP_INTERFACE,
        }
        tab._settings.update(
            {
                "adapter_speed_khz": 2000,
                "gdb_port": 3334,
                "telnet_port": 4445,
            }
        )

        argv = tab._build_argv(MagicMock())

        self.assertEqual(argv[:2], ["pyocd", "gdbserver"])
        self.assertIn(["--uid", "LPC-LINK2-1"], _pairs(argv))
        self.assertIn(["--target", "lpc55s69"], _pairs(argv))
        self.assertIn(["--port", "3334"], _pairs(argv))
        self.assertIn(["--telnet-port", "4445"], _pairs(argv))
        self.assertIn(["--frequency", "2000000"], _pairs(argv))
        self.assertIn("--no-wait", argv)

    def test_pyocd_rejects_option_like_target(self) -> None:
        tab = ProbeTab()
        tab._backend = "pyocd"
        tab._pyocd_target = "--config"
        log = MagicMock()

        self.assertIsNone(tab._build_argv(log))
        self.assertIn("target ID is invalid", log.write.call_args.args[0])

    def test_usb_only_probe_without_serial_is_not_used_as_pyocd_uid(self) -> None:
        tab = ProbeTab()
        tab._backend = "pyocd"
        tab._pyocd_target = "lpc55s69"
        tab._probe = {
            "uid": "1fc9:0090@5:15",
            "desc": "NXP LPC-LINK2 CMSIS-DAP",
            "driver": "pyocd",
            "interface": CMSIS_DAP_INTERFACE,
            "backend_uid": False,
        }
        log = MagicMock()

        self.assertIsNone(tab._build_argv(log))
        self.assertIn("no usable serial", log.write.call_args.args[0])

    def test_openocd_fallback_uses_generic_cmsis_dap_interface(self) -> None:
        tab = ProbeTab()
        tab._backend = "openocd"
        tab._target = "mspm0l"
        tab._probe = {
            "uid": "LPC-LINK2-1",
            "desc": "NXP LPC-LINK2 CMSIS-DAP",
            "driver": "pyocd",
            "interface": CMSIS_DAP_INTERFACE,
        }

        argv = tab._build_argv(MagicMock())

        self.assertIsNotNone(argv)
        self.assertIn(["-f", CMSIS_DAP_INTERFACE], _pairs(argv or []))
        self.assertIn(["-c", "adapter serial LPC-LINK2-1"], _pairs(argv or []))

    async def test_pyocd_readiness_posts_lldb_start(self) -> None:
        app = ProbeTestApp()
        async with app.run_test():
            tab = app.query_one(ProbeTab)
            process = FakeProcess(
                ["INFO:gdbserver:GDB server listening on port 3334 (core 0)"]
            )
            tab._backend = "pyocd"
            tab._settings["gdb_port"] = 3334
            tab._proc = process

            messages: list[object] = []
            with patch.object(tab, "post_message", side_effect=messages.append):
                await tab._read_output()

            self.assertEqual(len(messages), 1)
            self.assertIsInstance(messages[0], LldbStart)
            self.assertEqual(messages[0].port, 3334)
            self.assertIsNone(tab._proc)


def _pairs(argv: list[str]) -> list[list[str]]:
    return [argv[index:index + 2] for index in range(len(argv) - 1)]
