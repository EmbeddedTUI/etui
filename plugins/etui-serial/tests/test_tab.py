import unittest
from textual.app import App, ComposeResult
from etui_serial.tab import SerialTab

class SerialTestApp(App):
    def compose(self) -> ComposeResult:
        yield SerialTab()

class SerialTabUnitTests(unittest.TestCase):
    def test_instantiation(self) -> None:
        tab = SerialTab()
        self.assertIsNone(tab.serial_port)

if __name__ == "__main__":
    unittest.main()
