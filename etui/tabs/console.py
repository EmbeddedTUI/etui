# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import sys
import asyncio
import contextlib
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.widgets import RichLog

# Lazy-loaded xonsh resources
_execer = None
_xonsh_context = None

def get_xonsh_engine():
    global _execer, _xonsh_context
    if _execer is None:
        from xonsh.main import setup
        from xonsh.execer import Execer
        from xonsh.built_ins import XSH
        
        setup()
        # Enable capturing of subprocess stdout/stderr globally
        XSH.env['XONSH_CAPTURE_ALWAYS'] = True
        
        _execer = Execer()
        _xonsh_context = globals().copy()
        _xonsh_context.update(__xonsh__=XSH)
        
    return _execer, _xonsh_context


class LogWidget(RichLog):
    def __init__(self):
        super().__init__(highlight=True, markup=True)
        self.write("Log enabled (xonsh shell)")


class TextualLogStream:
    def __init__(self, app, log_widget, style=""):
        self.app = app
        self.log_widget = log_widget
        self.style = style
        self.buffer = ""

    def write(self, s):
        if not s:
            return 0
        self.buffer += s
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            line = line.rstrip("\r")
            if self.style:
                self.app.call_from_thread(self.log_widget.write, f"[{self.style}]{line}[/{self.style}]")
            else:
                self.app.call_from_thread(self.log_widget.write, line)
        return len(s)

    def flush(self):
        if self.buffer:
            line = self.buffer.rstrip("\r")
            if self.style:
                self.app.call_from_thread(self.log_widget.write, f"[{self.style}]{line}[/{self.style}]")
            else:
                self.app.call_from_thread(self.log_widget.write, line)
            self.buffer = ""

    def writable(self):
        return True

    @property
    def encoding(self):
        return "utf-8"


class ConsoleTab(Horizontal):
    """ Console tab powered by xonsh """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield LogWidget()

    def on_mount(self) -> None:
        try:
            self.execer, self.ctx = get_xonsh_engine()
        except Exception as e:
            log = self.query_one(LogWidget)
            log.write(f"[red]Failed to initialize xonsh engine: {e}[/red]")
            self.execer = None
            self.ctx = None

    async def run_command(self, command: str) -> None:
        log = self.query_one(LogWidget)
        if self.execer is None:
            log.write(f"[red]Console unavailable - xonsh failed to initialize.[/red]")
            return

        log.write(f"[bold cyan]xonsh>[/bold cyan] {command}")
        
        # Run xonsh execution in a background thread to prevent TUI freezing
        await asyncio.to_thread(self._execute_xonsh, command)

    def _execute_xonsh(self, command: str) -> None:
        log = self.query_one(LogWidget)
        
        # Build custom real-time streams
        stdout_stream = TextualLogStream(self.app, log)
        stderr_stream = TextualLogStream(self.app, log, style="red")
        
        # Redirect standard streams
        with contextlib.redirect_stdout(stdout_stream), contextlib.redirect_stderr(stderr_stream):
            try:
                self.execer.exec(command, glbs=self.ctx, locs=self.ctx)
            except Exception as e:
                import traceback
                traceback.print_exc(file=sys.stderr)
            finally:
                # Flush the streams to output any remaining buffers
                stdout_stream.flush()
                stderr_stream.flush()
