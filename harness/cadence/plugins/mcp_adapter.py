from __future__ import annotations

from cadence.plugins.base import Capability, Manifest, Plugin, Result


class McpPlugin(Plugin):
    def __init__(self, plugin_id: str, registry) -> None:
        self._id = plugin_id
        self._registry = registry
        self.manifest = Manifest(plugin_id, "service", ())

    async def start(self) -> None:
        await self._registry.start()
        caps = []
        for entry in self._registry.list_tools():
            fn = entry["function"]
            caps.append(Capability(
                f"{self._id}.{fn['name']}", fn["description"], fn["parameters"],
                free_args=tuple(fn["parameters"].get("properties", {})),
            ))
        self.manifest = Manifest(self._id, "service", tuple(caps))

    async def call(self, capability: str, args: dict, target, event) -> Result:
        data = await self._registry.call(capability[len(self._id) + 1:], args)
        return Result(True, data=data if isinstance(data, dict) else {"result": data})
