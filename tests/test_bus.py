# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import asyncio
import unittest

from etui.bus import MessageBus, NoProvider, RpcError, RpcTimeout


class BusEventTests(unittest.TestCase):
    def test_emit_delivers_to_subscribers(self) -> None:
        bus = MessageBus()
        seen = []
        bus.subscribe("repo.changed", lambda e: seen.append(e.payload))
        bus.emit("repo.changed", "/path", source="git")
        self.assertEqual(seen, ["/path"])

    def test_glob_subscription(self) -> None:
        bus = MessageBus()
        seen = []
        bus.subscribe("repo.*", lambda e: seen.append(e.topic))
        bus.emit("repo.changed")
        bus.emit("repo.opened")
        bus.emit("theme.changed")
        self.assertEqual(seen, ["repo.changed", "repo.opened"])

    def test_unsubscribe(self) -> None:
        bus = MessageBus()
        seen = []
        off = bus.subscribe("x", lambda e: seen.append(1))
        off()
        bus.emit("x")
        self.assertEqual(seen, [])

    def test_emit_isolates_handler_errors(self) -> None:
        bus = MessageBus()
        seen = []

        def boom(_event):
            raise RuntimeError("nope")

        bus.subscribe("t", boom)
        bus.subscribe("t", lambda e: seen.append("ok"))
        bus.emit("t")  # must not raise
        self.assertEqual(seen, ["ok"])


class BusRpcTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_returns_provider_result(self) -> None:
        bus = MessageBus()
        calls = []

        async def provider(command, timeout=None):
            calls.append(command)
            return 0

        bus.provide("console.run", provider)
        self.assertTrue(bus.has("console.run"))
        self.assertEqual(await bus.call("console.run", command="make"), 0)
        self.assertEqual(calls, ["make"])

    async def test_missing_provider_raises(self) -> None:
        with self.assertRaises(NoProvider):
            await MessageBus().call("nope")

    async def test_duplicate_provider_rejected(self) -> None:
        bus = MessageBus()
        bus.provide("s", lambda: None)
        with self.assertRaises(RpcError):
            bus.provide("s", lambda: None)

    async def test_deregister(self) -> None:
        bus = MessageBus()
        off = bus.provide("s", lambda: None)
        off()
        self.assertFalse(bus.has("s"))

    async def test_timeout(self) -> None:
        bus = MessageBus()

        async def slow():
            await asyncio.sleep(10)

        bus.provide("slow", slow)
        with self.assertRaises(RpcTimeout):
            await bus.call("slow", timeout=0.05)

    async def test_provider_exception_propagates(self) -> None:
        bus = MessageBus()

        async def bad():
            raise ValueError("boom")

        bus.provide("bad", bad)
        with self.assertRaises(ValueError):
            await bus.call("bad")


class BusDebugLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_emit_and_call_are_logged_at_debug(self) -> None:
        bus = MessageBus()

        async def provider(command, timeout=None):
            return 0

        bus.provide("svc.x", provider)
        with self.assertLogs("etui.bus", level="DEBUG") as cm:
            bus.emit("topic.y", 1)
            await bus.call("svc.x", command="go")
        joined = "\n".join(cm.output)
        self.assertIn("emit topic=topic.y", joined)
        self.assertIn("call service=svc.x", joined)
        self.assertIn("-> 0", joined)


if __name__ == "__main__":
    unittest.main()
