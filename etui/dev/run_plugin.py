"""Run a single etui tab plugin standalone, without the full host app.

Mounts one plugin's widget in a minimal one-tab Textual app wired the way
``etui/main.py`` wires plugins at mount: a real :class:`MessageBus`, a
namespace-scoped :class:`ScopedBus` on the widget, ``tab.activated`` emitted on
mount, and ``dispose_all`` on teardown. Host bus services the plugin may call
(``console.run``, ``settings.get/set``, ``nav.activate_tab``, ``help.add_entry``)
are registered as lightweight stubs so those calls resolve.

See ``doc/tab-plugin-standalone.md`` for the design.

Usage::

    etui-run-plugin gh                 # by etui.tabs entry-point name
    etui-run-plugin etui_gh.tab:GhTab  # by module:attr (widget or plugin class)
    etui-run-plugin gh --dev           # hint to use textual devtools

Or with Textual's devtools::

    textual run --dev "etui.dev.run_plugin:make_app('gh')"
"""

from __future__ import annotations

import argparse
import importlib
import logging

from textual.app import App, ComposeResult
from textual.widget import Widget
from textual.widgets import Footer, Header, TabbedContent, TabPane

if __package__:
    from ..bus import MessageBus
    from ..bus_contract import TOPIC_TAB_ACTIVATED, TabEvent
    from ..plugin import EtuiTabPlugin, TabSpec
    from ..plugins import ScopedBus
else:  # pragma: no cover - direct-script fallback, mirrors the rest of the pkg
    from bus import MessageBus
    from bus_contract import TOPIC_TAB_ACTIVATED, TabEvent
    from plugin import EtuiTabPlugin, TabSpec
    from plugins import ScopedBus

logger = logging.getLogger("etui.dev.run_plugin")

ENTRY_GROUP = "etui.tabs"


# --------------------------------------------------------------------------
# Resolution: turn a reference into (TabSpec, widget factory)
# --------------------------------------------------------------------------

class _Resolved:
    """A plugin resolved to the bits the runner needs to mount it."""

    def __init__(self, spec: TabSpec, make_widget) -> None:
        self.spec = spec
        self.make_widget = make_widget


def _from_plugin(plugin: EtuiTabPlugin) -> _Resolved:
    spec = plugin.spec()
    return _Resolved(spec, plugin.create_widget)


def resolve(ref: str) -> _Resolved:
    """Resolve ``ref`` to a mountable plugin.

    ``ref`` is either an ``etui.tabs`` entry-point name (e.g. ``"gh"``) or a
    dotted ``module:attr`` pointing at an :class:`EtuiTabPlugin` subclass, a
    plugin instance, or a bare :class:`~textual.widget.Widget` subclass.
    """
    if ":" in ref:
        return _resolve_dotted(ref)
    return _resolve_entry_point(ref)


def _resolve_entry_point(name: str) -> _Resolved:
    from importlib import metadata as md

    eps = md.entry_points()
    selected = eps.select(group=ENTRY_GROUP) if hasattr(eps, "select") else []
    available = [ep.name for ep in selected]
    for ep in selected:
        if ep.name == name:
            obj = ep.load()
            plugin = obj() if isinstance(obj, type) else obj
            return _from_plugin(plugin)
    raise SystemExit(
        f"no etui.tabs plugin named {name!r}. "
        f"Available: {', '.join(sorted(available)) or '(none installed)'}"
    )


def _resolve_dotted(ref: str) -> _Resolved:
    mod_name, _, attr = ref.partition(":")
    try:
        module = importlib.import_module(mod_name)
    except ImportError as exc:
        raise SystemExit(f"cannot import {mod_name!r}: {exc}") from exc
    try:
        obj = getattr(module, attr)
    except AttributeError as exc:
        raise SystemExit(f"{mod_name!r} has no attribute {attr!r}") from exc

    # An EtuiTabPlugin subclass or instance -> use its spec/create_widget.
    if isinstance(obj, EtuiTabPlugin):
        return _from_plugin(obj)
    if isinstance(obj, type) and issubclass(obj, EtuiTabPlugin):
        return _from_plugin(obj())

    # A bare Widget (class or instance): synthesize a minimal spec so it mounts.
    if isinstance(obj, type) and issubclass(obj, Widget):
        spec = TabSpec(id=_synth_id(attr), title=attr)
        return _Resolved(spec, obj)
    if isinstance(obj, Widget):
        spec = TabSpec(id=_synth_id(attr), title=attr)
        return _Resolved(spec, lambda: obj)

    raise SystemExit(
        f"{ref!r} is not an EtuiTabPlugin or Widget (got {type(obj).__name__})"
    )


def _synth_id(attr: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in attr.lower()).strip("-")
    return f"plugin-{slug or 'standalone'}"


# --------------------------------------------------------------------------
# Host-service stubs
# --------------------------------------------------------------------------

def install_host_stubs(bus: MessageBus) -> dict:
    """Register no-op/echo providers for host services plugins may call.

    Returns the in-memory settings store (handy for assertions in tests).
    """
    settings: dict[tuple[str, str], object] = {}

    async def console_run(command: str, timeout=None) -> int:
        logger.info("[stub console.run] %s", command)
        return 0

    async def console_force_complete(exit_code: int = 0) -> None:
        logger.info("[stub console.force_complete] %s", exit_code)

    async def settings_get(section: str, key: str, default=None):
        return settings.get((section, key), default)

    async def settings_set(section: str, key: str, value) -> None:
        settings[(section, key)] = value

    async def nav_activate(tab_id: str) -> None:
        logger.info("[stub nav.activate_tab] %s", tab_id)

    async def help_add(title: str, path) -> None:
        logger.info("[stub help.add_entry] %s -> %s", title, path)

    bus.provide("console.run", console_run)
    bus.provide("console.force_complete", console_force_complete)
    bus.provide("settings.get", settings_get)
    bus.provide("settings.set", settings_set)
    bus.provide("nav.activate_tab", nav_activate)
    bus.provide("help.add_entry", help_add)
    return settings


# --------------------------------------------------------------------------
# The standalone app
# --------------------------------------------------------------------------

class StandaloneApp(App):
    """A one-tab Textual app hosting a single plugin widget."""

    BINDINGS = [("ctrl+q", "quit", "Quit")]

    def __init__(self, resolved: _Resolved, *, stubs: bool = True) -> None:
        super().__init__()
        self.bus = MessageBus()
        self._resolved = resolved
        self._stubs = stubs
        self._scoped: ScopedBus | None = None
        self.settings_store: dict = {}
        self.title = f"etui-run-plugin · {resolved.spec.title}"

    def compose(self) -> ComposeResult:
        yield Header()
        spec = self._resolved.spec
        with TabbedContent():
            widget = self._resolved.make_widget()
            # A widget may carry its own DOM id (e.g. GhTab sets id="plugin-gh"),
            # which is the namespace its provide() calls expect. Prefer it over a
            # synthesized spec id so a bare-widget ref still scopes correctly.
            scope_id = getattr(widget, "id", None) or spec.id
            self._scoped = ScopedBus(self.bus, scope_id)
            widget._bus = self._scoped  # BusMixin walks parents for _bus
            yield TabPane(spec.title, widget, id=spec.id)
        yield Footer()

    def on_mount(self) -> None:
        if self._stubs:
            self.settings_store = install_host_stubs(self.bus)
        # Drive the lifecycle the host would: announce this tab active.
        self.bus.emit(TOPIC_TAB_ACTIVATED, TabEvent(self._resolved.spec.id))

    def on_unmount(self) -> None:
        if self._scoped is not None:
            self._scoped.dispose_all()


def make_app(ref: str, *, stubs: bool = True) -> StandaloneApp:
    """Build (but do not run) the app for ``ref`` — handy for ``textual run``."""
    return StandaloneApp(resolve(ref), stubs=stubs)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="etui-run-plugin",
        description="Run a single etui tab plugin standalone.",
    )
    parser.add_argument(
        "ref",
        help="etui.tabs entry-point name (e.g. 'gh') or 'module:attr'",
    )
    parser.add_argument(
        "--no-stubs",
        action="store_true",
        help="do not register host-service stubs",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="print the equivalent `textual run --dev` command and exit",
    )
    args = parser.parse_args(argv)

    if args.dev:
        print(f'textual run --dev "etui.dev.run_plugin:make_app({args.ref!r})"')
        return 0

    app = make_app(args.ref, stubs=not args.no_stubs)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
