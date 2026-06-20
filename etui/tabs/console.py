# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

"""Console tab: a true terminal emulator backed by a PTY and pyte.

A persistent interactive shell runs in a pseudo-terminal; its screen is
emulated with pyte and rendered into a focusable Textual widget. Keystrokes
are forwarded to the shell, so interactive programs (sudo, apt, vim, …) work
exactly as in a normal terminal.
"""

import asyncio
import logging
import os
import re
import shlex
import signal
from pathlib import Path

log = logging.getLogger("etui.console")

from rich.segment import Segment
from rich.style import Style
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Button

if os.name == "posix":
    import fcntl
    import pty
    import struct
    import termios

import pyte

if __package__:
    from ..bus import BusMixin
    from ..bus_contract import (
        SVC_CONSOLE_FORCE_COMPLETE,
        SVC_CONSOLE_RUN,
        SVC_NAV_ACTIVATE,
    )
    from ..contracts import on_workspace_changed
else:  # pragma: no cover - script-mode import
    from bus import BusMixin
    from bus_contract import (
        SVC_CONSOLE_FORCE_COMPLETE,
        SVC_CONSOLE_RUN,
        SVC_NAV_ACTIVATE,
    )
    from contracts import on_workspace_changed


# Terminal escape sequences that can interleave with shell output (OSC title /
# shell-integration sequences, CSI cursor/colour codes, single-char escapes).
# Stripped before scanning for command-completion markers so that control bytes
# emitted by sudo, apt progress redraws, or VTE shell integration can't split a
# marker and defeat the match.
_ANSI_RE = re.compile(
    rb"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC ... BEL or ST
    rb"|\x1b\[[0-9;?]*[ -/]*[@-~]"          # CSI sequences
    rb"|\x1b[@-Z\\-_]"                       # two-byte escapes
)


# pyte colour names → Rich colour names (None == terminal default).
_PYTE_COLORS = {
    "black": "black",
    "red": "red",
    "green": "green",
    "brown": "yellow",
    "blue": "blue",
    "magenta": "magenta",
    "cyan": "cyan",
    "white": "white",
    "brightblack": "bright_black",
    "brightred": "bright_red",
    "brightgreen": "bright_green",
    "brightbrown": "bright_yellow",
    "brightyellow": "bright_yellow",
    "brightblue": "bright_blue",
    "brightmagenta": "bright_magenta",
    "brightcyan": "bright_cyan",
    "brightwhite": "bright_white",
    "default": None,
}

# Special keys → terminal byte sequences (xterm-style).
_KEY_SEQUENCES = {
    "enter": b"\r",
    "tab": b"\t",
    "escape": b"\x1b",
    "backspace": b"\x7f",
    "up": b"\x1b[A",
    "down": b"\x1b[B",
    "right": b"\x1b[C",
    "left": b"\x1b[D",
    "home": b"\x1b[H",
    "end": b"\x1b[F",
    "delete": b"\x1b[3~",
    "insert": b"\x1b[2~",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    "space": b" ",
    "f1": b"\x1bOP",
    "f2": b"\x1bOQ",
    "f3": b"\x1bOR",
    "f4": b"\x1bOS",
    "f5": b"\x1b[15~",
    "f6": b"\x1b[17~",
    "f7": b"\x1b[18~",
    "f8": b"\x1b[19~",
    "f9": b"\x1b[20~",
    "f10": b"\x1b[21~",
    "f12": b"\x1b[24~",
}


class TerminalWidget(Widget, can_focus=True):
    """A PTY-backed terminal emulator widget."""

    DEFAULT_CSS = """
    TerminalWidget {
        height: 1fr;
        background: $background;
    }
    """

    def __init__(self, *, initial_cwd: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cols = 80
        self.rows = 24
        self.pyte_screen = pyte.Screen(self.cols, self.rows)
        self.stream = pyte.ByteStream(self.pyte_screen)
        self._fd: int | None = None
        self._pid: int | None = None
        self._initial_cwd = initial_cwd
        self._exited = False
        self._pending_commands = []
        self._read_buffer = bytearray()
        self._shell = os.environ.get("SHELL") or "/bin/bash"
        self._command_counter = 0

    # ----------------------------------------------------------- lifecycle
    def on_mount(self) -> None:
        if os.name != "posix":
            self.pyte_screen.draw("Terminal is only supported on POSIX systems.")
            self.refresh()
            return
        self._spawn()

    async def on_unmount(self) -> None:
        self._cleanup()

    def _spawn(self) -> None:
        try:
            pid, fd = pty.fork()
        except OSError as exc:  # pragma: no cover - environment dependent
            self.pyte_screen.draw(f"Unable to start shell: {exc}")
            self.refresh()
            return
        if pid == 0:
            # Child process: become the shell.
            try:
                if self._initial_cwd and self._initial_cwd.is_dir():
                    os.chdir(self._initial_cwd)
            except OSError:
                pass
            os.environ["TERM"] = "xterm-256color"
            os.environ.setdefault("COLORTERM", "truecolor")
            shell = self._shell
            try:
                os.execvp(shell, [shell, "-i"])
            except Exception:
                os._exit(127)
        # Parent process.
        self._pid = pid
        self._fd = fd
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self._set_winsize()
        asyncio.get_event_loop().add_reader(fd, self._on_read)

    def _cleanup(self) -> None:
        if self._fd is not None:
            try:
                asyncio.get_event_loop().remove_reader(self._fd)
            except (OSError, ValueError, RuntimeError):
                pass
        if self._pid:
            try:
                os.killpg(self._pid, signal.SIGHUP)
            except OSError:
                try:
                    os.kill(self._pid, signal.SIGHUP)
                except OSError:
                    pass
            try:
                os.waitpid(self._pid, os.WNOHANG)
            except OSError:
                pass
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
        self._fd = None
        self._pid = None

    # ------------------------------------------------------------- I/O
    def _on_read(self) -> None:
        try:
            data = os.read(self._fd, 65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b""
        if not data:
            self._exited = True
            self._cleanup()
            self.pyte_screen.draw("\r\n[process exited]")
            self.refresh()
            self._resolve_pending_commands(-1)
            return
        self._read_buffer.extend(data)
        if len(self._read_buffer) > 1048576:
            del self._read_buffer[:-1048576]
        self.stream.feed(data)
        self.refresh()
        self._check_command_markers()

    def _resolve_pending_commands(self, exit_code: int) -> None:
        log.debug(
            "resolve_pending exit=%d count=%d", exit_code, len(self._pending_commands)
        )
        for cmd_info in self._pending_commands:
            cmd_info["exit_code"] = exit_code
            cmd_info["event"].set()
        self._pending_commands.clear()

    def _check_command_markers(self) -> None:
        if not self._pending_commands:
            return
        # Match against a copy with escape sequences removed: control bytes from
        # sudo/apt/shell-integration can otherwise interleave with the marker and
        # defeat a raw match. The echoed input carries `__ETUI_CMD_DONE_""N__`
        # (with embedded quotes), so it never matches the bare marker.
        clean = _ANSI_RE.sub(b"", bytes(self._read_buffer))
        resolved_indices = []
        for i, cmd_info in enumerate(self._pending_commands):
            marker = cmd_info["marker"]
            match = re.search(re.escape(marker) + b"\\s+(-?\\d+)", clean)
            if match:
                cmd_info["exit_code"] = int(match.group(1))
                cmd_info["event"].set()
                resolved_indices.append(i)
                log.debug("marker matched %r exit=%d", marker, cmd_info["exit_code"])
            elif log.isEnabledFor(logging.DEBUG) and marker in clean:
                # Marker text is present but the exit-code regex didn't match:
                # dump the surrounding bytes so we can see what interleaves.
                idx = clean.rfind(marker)
                log.debug(
                    "marker %r present but UNMATCHED; context=%r",
                    marker, clean[idx:idx + 48],
                )
        if resolved_indices:
            # Commands run sequentially, so once any pending marker resolves the
            # buffer up to here is consumed; clear it to avoid re-matching.
            self._read_buffer.clear()
            for index in sorted(resolved_indices, reverse=True):
                self._pending_commands.pop(index)

    async def run_command(self, command: str) -> int:
        """Type a command into the shell, wait for it to complete, and return exit code."""
        self._command_counter += 1
        marker = f"{self._command_counter}"
        event = asyncio.Event()
        cmd_info = {
            "marker": f"__ETUI_CMD_DONE_{marker}__".encode(),
            "event": event,
            "exit_code": -1
        }
        self._pending_commands.append(cmd_info)
        log.debug("run_command marker=%s command=%r", cmd_info["marker"], command)
        exit_var = "$status" if "fish" in self._shell else "$?"
        echo_marker = f"__ETUI_CMD_DONE_\"\"{marker}__"
        self.write(f"{command}; echo {echo_marker} {exit_var}\r".encode())
        try:
            await event.wait()
        finally:
            # On cancellation (e.g. workflow Abort) drop the stale pending entry
            # so a later marker can't resolve a command nobody is waiting on.
            if cmd_info in self._pending_commands:
                self._pending_commands.remove(cmd_info)
        return cmd_info["exit_code"]

    def write(self, data: bytes) -> None:
        """Write raw bytes to the shell's input."""
        if self._fd is None:
            return
        try:
            os.write(self._fd, data)
        except OSError:
            pass

    def feed_command(self, command: str) -> None:
        """Type a command into the shell followed by Enter."""
        self.write(command.encode() + b"\r")

    # ----------------------------------------------------------- sizing
    def on_resize(self, event) -> None:
        self._resize(event.size.width, event.size.height)

    def _resize(self, width: int, height: int) -> None:
        width = max(2, width)
        height = max(2, height)
        if width == self.cols and height == self.rows:
            return
        self.cols = width
        self.rows = height
        self.pyte_screen.resize(height, width)
        self._set_winsize()
        self.refresh()

    def _set_winsize(self) -> None:
        if self._fd is None:
            return
        try:
            winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    # ----------------------------------------------------------- input
    def on_key(self, event) -> None:
        if self._fd is None:
            return
        key = event.key
        data: bytes | None = None
        if key in _KEY_SEQUENCES:
            data = _KEY_SEQUENCES[key]
        elif key.startswith("ctrl+") and len(key) == 6 and "a" <= key[5] <= "z":
            data = bytes([ord(key[5]) - 96])
        elif event.character is not None and event.character.isprintable():
            data = event.character.encode()
        if data is not None:
            event.stop()
            event.prevent_default()
            self.write(data)

    def on_click(self) -> None:
        self.focus()

    # ----------------------------------------------------------- render
    def render_line(self, y: int) -> Strip:
        width = self.size.width
        if self._fd is None and not self._exited:
            return Strip.blank(width)
        if y >= self.rows:
            return Strip.blank(width)
        buffer_row = self.pyte_screen.buffer[y]
        cursor = self.pyte_screen.cursor
        show_cursor = self.has_focus and not cursor.hidden and not self._exited
        segments = []
        for x in range(self.cols):
            char = buffer_row[x]
            text = char.data or " "
            style = self._char_style(char)
            if show_cursor and y == cursor.y and x == cursor.x:
                style += Style(reverse=True)
            segments.append(Segment(text, style))
        return Strip(segments, self.cols).adjust_cell_length(width)

    def _char_style(self, char) -> Style:
        return Style(
            color=self._color(char.fg),
            bgcolor=self._color(char.bg),
            bold=bool(char.bold),
            italic=bool(char.italics),
            underline=bool(char.underscore),
            strike=bool(char.strikethrough),
            reverse=bool(char.reverse),
            blink=bool(getattr(char, "blink", False)),
        )

    @staticmethod
    def _color(value: str | None) -> str | None:
        if not value or value == "default":
            return None
        if value in _PYTE_COLORS:
            return _PYTE_COLORS[value]
        if len(value) == 6 and all(c in "0123456789abcdefABCDEF" for c in value):
            return f"#{value}"
        return None


class ConsoleTab(BusMixin, Vertical):
    """Console tab hosting a true terminal emulator."""

    DEFAULT_CSS = """
    ConsoleTab {
        height: 1fr;
    }
    ConsoleTab #console-actionbar {
        height: auto;
        align: right middle;
    }
    ConsoleTab #btn-console-sync {
        display: none;
        margin: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="console-tab")
        self._cwd = Path.cwd()
        self._disposers = []

    def on_mount(self) -> None:
        self._disposers = [
            self.bus.provide(SVC_CONSOLE_RUN, self._svc_run),
            self.bus.provide(SVC_CONSOLE_FORCE_COMPLETE, self._svc_force_complete),
            on_workspace_changed(self.bus, self._on_workspace_changed),
        ]

    def on_unmount(self) -> None:
        for dispose in self._disposers:
            dispose()
        self._disposers = []

    async def _svc_force_complete(self, exit_code: int = 0) -> None:
        """Bus service ``console.force_complete``: manually resolve the command
        the terminal is currently waiting on (the Sync override)."""
        self.force_complete(exit_code)

    def _on_workspace_changed(self, event) -> None:
        self.cwd = Path(event.root)

    def force_complete(self, exit_code: int = 0) -> None:
        try:
            term = self.query_one(TerminalWidget)
        except Exception:
            return
        term._resolve_pending_commands(exit_code)

    async def _svc_run(self, command: str, timeout: float | None = None) -> int:
        """Bus service ``console.run``: surface the console and run ``command``,
        awaiting its exit code."""
        if self.bus.has(SVC_NAV_ACTIVATE):
            await self.bus.call(SVC_NAV_ACTIVATE, tab_id="console")
        self.show_sync_button(True)
        try:
            return await self.run_command(command)
        finally:
            self.show_sync_button(False)

    def compose(self) -> ComposeResult:
        with Horizontal(id="console-actionbar"):
            yield Button(
                "Force Complete",
                id="btn-console-sync",
                variant="warning",
                tooltip="Mark the command a workflow step is waiting on as finished (exit 0).",
            )
        yield TerminalWidget(initial_cwd=self._cwd, id="console-terminal")

    def show_sync_button(self, visible: bool) -> None:
        """Reveal the Force Complete button while a step waits on this terminal."""
        try:
            self.query_one("#btn-console-sync", Button).display = visible
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "btn-console-sync":
            return
        event.stop()
        self.force_complete(0)

    @property
    def cwd(self) -> Path:
        return self._cwd

    @cwd.setter
    def cwd(self, value) -> None:
        path = Path(value)
        self._cwd = path
        # If the terminal is live, change its directory too.
        try:
            term = self.query_one(TerminalWidget)
        except Exception:
            return
        if term._fd is not None and path.is_dir():
            term.feed_command(f"cd {shlex.quote(str(path))}")

    async def run_command(self, command: str) -> int:
        """Type and run a command in the terminal, awaiting its completion."""
        try:
            return await self.query_one(TerminalWidget).run_command(command)
        except Exception:
            return -1

    def focus(self, scroll_visible: bool = True):  # type: ignore[override]
        try:
            self.query_one(TerminalWidget).focus(scroll_visible)
        except Exception:
            super().focus(scroll_visible)
        return self
