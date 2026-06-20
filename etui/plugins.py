# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

"""Internal host machinery to discover, load, validate, and isolate tab plugins."""

from __future__ import annotations

import importlib.metadata as md
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from textual.widgets import TabbedContent
    from .plugin import EtuiTabPlugin, TabSpec

if __package__:
    from .plugin import API_VERSION
    from .bus import MessageBus, RpcProvider, EventHandler, Disposer
else:
    from plugin import API_VERSION
    from bus import MessageBus, RpcProvider, EventHandler, Disposer

log = logging.getLogger("etui.plugins")
ENTRY_GROUP = "etui.tabs"
ALLOWED_PROVIDES = {
    "debug.restart_probe",
    "debug.get_gdbserver_status",
    "tools.status",
}


class ScopedBus:
    """A namespace-enforcing facade around the central MessageBus for plugins.

    Restricts plugins to only provide services matching their `plugin.<id>.*` prefix.
    Stamps all emitted events with the plugin's ID as the source for diagnostic attribution.
    Tracks all disposers created by the plugin to clean them up on unmount.
    """

    def __init__(self, bus: MessageBus, plugin_id: str, provides: tuple[str, ...] = ()) -> None:
        self._bus = bus
        self._id = plugin_id
        bus_id = plugin_id.replace("-", ".")
        self._prefix = f"{bus_id}."
        self._provides = set(provides)
        self._disposers: list[Disposer] = []

    def provide(self, service: str, fn: RpcProvider) -> Disposer:
        """Register the plugin as a provider for a service starting with its prefix."""
        if not (service.startswith(self._prefix) or service in self._provides):
            raise PermissionError(
                f"plugin may only provide '{self._prefix}*' or allowlisted services, got {service!r}"
            )
        disp = self._bus.provide(service, fn)
        self._disposers.append(disp)
        return disp

    def subscribe(self, topic: str, handler: EventHandler) -> Disposer:
        """Subscribe to a topic on the global bus."""
        disp = self._bus.subscribe(topic, handler)
        self._disposers.append(disp)
        return disp

    def emit(self, topic: str, payload: Any = None, *, source: str | None = None) -> None:
        """Publish an event on the global bus, stamping the source as this plugin."""
        # Overrides the source parameter with this plugin's id to ensure diagnostic integrity
        return self._bus.emit(topic, payload, source=self._id)

    def has(self, service: str) -> bool:
        """Check if a service is registered on the global bus."""
        return self._bus.has(service)

    async def call(self, service: str, *, timeout: float | None = 30.0, **kwargs) -> Any:
        """Invoke a service provider. Intercepts and prefixes plugin-scoped settings calls."""
        if service in ("settings.get", "settings.set") and "section" in kwargs:
            # Namespace settings section key to <dotted_id>.<section>
            bus_id = self._id.replace("-", ".")
            kwargs["section"] = f"{bus_id}.{kwargs['section']}"
        return await self._bus.call(service, timeout=timeout, **kwargs)

    def dispose_all(self) -> None:
        """Clean up all providers and subscriptions registered through this scoped bus."""
        for disp in self._disposers:
            try:
                disp()
            except Exception:
                log.exception("Error during scoped bus cleanup for plugin %s", self._id)
        self._disposers.clear()


@dataclass
class LoadedPlugin:
    """A successfully imported, loaded, and validated plugin."""

    name: str  # entry-point name
    dist: str | None  # distribution name+version, for diagnostics
    plugin: EtuiTabPlugin
    spec: TabSpec
    scoped_bus: ScopedBus | None = None


@dataclass
class PluginManager:
    """Manages plugin discovery, validation, and metadata."""

    loaded: list[LoadedPlugin] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)  # (name, message)

    def discover(self) -> None:
        """Enumerate entry points and validate; never raises."""
        for ep in _entry_points():
            try:
                cls = ep.load()
                plugin = cls()
                self._validate(ep, plugin)
            except Exception as exc:  # import/ctor failure
                self._fail(ep.name, f"load failed: {exc!r}")
        self.loaded.sort(key=lambda lp: (lp.spec.order, lp.spec.title))

    def _validate(self, ep: md.EntryPoint, plugin: EtuiTabPlugin) -> None:
        if getattr(plugin, "api_version", 0) != API_VERSION:
            return self._fail(
                ep.name,
                f"needs etui plugin API v{getattr(plugin, 'api_version', '?')}, "
                f"host is v{API_VERSION}",
            )
        spec = plugin.spec()
        if not spec.id.startswith("plugin-"):
            return self._fail(ep.name, f"tab id {spec.id!r} must start with 'plugin-'")
        if any(lp.spec.id == spec.id for lp in self.loaded):
            return self._fail(ep.name, f"duplicate tab id {spec.id!r}")
        for service in spec.provides:
            if service not in ALLOWED_PROVIDES:
                return self._fail(
                    ep.name,
                    f"plugin provides unauthorized service name {service!r}",
                )
        self.loaded.append(LoadedPlugin(ep.name, _dist_of(ep), plugin, spec))

    def _fail(self, name: str, message: str) -> None:
        log.warning("plugin %s: %s", name, message)
        self.errors.append((name, message))


def _entry_points() -> list[md.EntryPoint]:
    try:
        eps = md.entry_points()
        if hasattr(eps, "select"):
            return list(eps.select(group=ENTRY_GROUP))
        return list(eps.get(ENTRY_GROUP, []))
    except Exception:  # pragma: no cover
        log.exception("entry-point discovery failed")
        return []


def _dist_of(ep: md.EntryPoint) -> str | None:
    dist = getattr(ep, "dist", None)
    if dist:
        return f"{dist.name} {dist.version}"
    return None
