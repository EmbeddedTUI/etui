# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

"""In-process message bus for inter-tab communication.

Two primitives, both addressed by dotted string keys so a sender never imports
the receiver:

* **Events (pub/sub)** — :meth:`MessageBus.emit` delivers to zero or more
  subscribers, returns nothing, and never raises into the publisher.
* **RPC (request/response)** — :meth:`MessageBus.call` awaits the single
  registered provider for a service and returns its value (or raises).

See ``doc/message-bus-rpc.md`` for the design rationale.
"""

from __future__ import annotations

import asyncio
import fnmatch
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

log = logging.getLogger("etui.bus")

EventHandler = Callable[["Event"], "Awaitable[None] | None"]
RpcProvider = Callable[..., Awaitable[Any]]
Disposer = Callable[[], None]


@dataclass(frozen=True)
class Event:
    """A fact published on the bus."""

    topic: str
    payload: Any = None
    source: str | None = None


class RpcError(Exception):
    """Base class for RPC failures surfaced to the caller."""


class NoProvider(RpcError):
    """No provider is registered for the requested service."""


class RpcTimeout(RpcError):
    """The provider did not complete within the allotted time."""


class MessageBus:
    """A single-threaded, asyncio-native pub/sub + RPC hub."""

    def __init__(self) -> None:
        self._subs: dict[str, list[EventHandler]] = {}
        self._services: dict[str, RpcProvider] = {}

    # ------------------------------------------------------------ pub/sub
    def subscribe(self, topic: str, handler: EventHandler) -> Disposer:
        """Subscribe to ``topic`` (supports ``fnmatch`` globs, e.g. ``"repo.*"``).

        Returns a disposer; call it (typically in ``on_unmount``) to unsubscribe.
        """
        self._subs.setdefault(topic, []).append(handler)

        def _dispose() -> None:
            handlers = self._subs.get(topic)
            if handlers and handler in handlers:
                handlers.remove(handler)
                if not handlers:
                    self._subs.pop(topic, None)

        return _dispose

    def emit(self, topic: str, payload: Any = None, *, source: str | None = None) -> None:
        """Fire-and-forget delivery to all matching subscribers.

        Never raises into the caller: each handler is isolated and its errors
        are logged so one bad subscriber cannot break the publisher.
        """
        event = Event(topic, payload, source)
        for pattern, handlers in list(self._subs.items()):
            if pattern == topic or fnmatch.fnmatchcase(topic, pattern):
                for handler in list(handlers):
                    self._dispatch(handler, event)

    def _dispatch(self, handler: EventHandler, event: Event) -> None:
        try:
            result = handler(event)
        except Exception:  # pragma: no cover - defensive isolation
            log.exception("event handler failed for %r", event.topic)
            return
        if inspect.isawaitable(result):
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:  # pragma: no cover - no loop (sync context)
                log.error("async handler for %r needs a running loop", event.topic)
                return
            loop.create_task(self._await_handler(result, event.topic))

    @staticmethod
    async def _await_handler(awaitable: Awaitable[None], topic: str) -> None:
        try:
            await awaitable
        except Exception:  # pragma: no cover - defensive isolation
            log.exception("async event handler failed for %r", topic)

    # ---------------------------------------------------------------- rpc
    def provide(self, service: str, provider: RpcProvider) -> Disposer:
        """Register the single provider for ``service``.

        Raises :class:`RpcError` if a provider is already registered — this
        surfaces accidental duplicate registration loudly rather than silently
        picking one. Returns a disposer to deregister (call in ``on_unmount``).
        """
        if service in self._services:
            raise RpcError(f"service {service!r} already provided")
        self._services[service] = provider

        def _dispose() -> None:
            if self._services.get(service) is provider:
                self._services.pop(service, None)

        return _dispose

    def has(self, service: str) -> bool:
        """Whether a provider is currently registered for ``service``."""
        return service in self._services

    async def call(self, service: str, *, timeout: float | None = 30.0, **kwargs) -> Any:
        """Invoke ``service``'s provider and await its result.

        Raises :class:`NoProvider` when unregistered, :class:`RpcTimeout` on
        timeout, or propagates the provider's own exception.
        """
        provider = self._services.get(service)
        if provider is None:
            raise NoProvider(service)
        call = provider(**kwargs)
        if timeout is None:
            return await call
        try:
            return await asyncio.wait_for(call, timeout)
        except asyncio.TimeoutError as exc:
            raise RpcTimeout(service) from exc


class BusMixin:
    """Mixin giving a widget ``self.bus`` access to the app's :class:`MessageBus`.

    If the host app has no ``bus`` yet (e.g. lightweight test harness apps), one
    is created and cached on the app so tabs work uniformly.
    """

    @property
    def bus(self) -> MessageBus:
        app = self.app  # type: ignore[attr-defined]
        bus = getattr(app, "bus", None)
        if bus is None:
            bus = MessageBus()
            app.bus = bus
        return bus
