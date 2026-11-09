import asyncio

from cadence_muse.adapter import MuseAdapter, run
from cadence_muse.client import MuseClient
from cadence_muse.config import MUSE_BASE_URL, MUSE_PROXY_URL
from cadence_muse.music import MusicPlugin

client = MuseClient(MUSE_BASE_URL, MUSE_PROXY_URL)
plugin = MusicPlugin(client)
plugin.check()
asyncio.run(run(MuseAdapter(plugin, None)))
