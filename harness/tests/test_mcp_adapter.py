"""Tests for McpPlugin (I16)."""

import pytest

from cadence.plugins.mcp_adapter import McpPlugin


class FakeRegistry:
    def __init__(self, result=None, error=None):
        self.started = False
        self.calls = []
        self.result = result
        self.error = error

    async def start(self):
        self.started = True

    def list_tools(self):
        return [{"type": "function", "function": {
            "name": "search", "description": "Search things",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
        }}]

    async def call(self, name, args):
        self.calls.append((name, args))
        if self.error:
            raise self.error
        return self.result


async def test_manifest_empty_before_start_populated_after():
    reg = FakeRegistry()
    plugin = McpPlugin("ext", reg)
    assert plugin.manifest.capabilities == ()
    await plugin.start()
    assert reg.started
    (cap,) = plugin.manifest.capabilities
    assert cap.name == "ext.search"
    assert cap.free_args == ("q",)


async def test_call_forwards_and_keeps_dict_data():
    reg = FakeRegistry(result={"hits": 3})
    plugin = McpPlugin("ext", reg)
    await plugin.start()
    res = await plugin.call("ext.search", {"q": 1}, None, None)
    assert reg.calls == [("search", {"q": 1})]
    assert res.ok and res.data == {"hits": 3}


async def test_call_wraps_non_dict_data():
    reg = FakeRegistry(result="text")
    plugin = McpPlugin("ext", reg)
    await plugin.start()
    res = await plugin.call("ext.search", {"q": 1}, None, None)
    assert res.ok and res.data == {"result": "text"}


async def test_registry_exception_propagates():
    reg = FakeRegistry(error=RuntimeError("boom"))
    plugin = McpPlugin("ext", reg)
    await plugin.start()
    with pytest.raises(RuntimeError):
        await plugin.call("ext.search", {}, None, None)
