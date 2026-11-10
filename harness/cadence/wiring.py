"""Builds the Cadence core runtime: hub, catalogue, deciders, pipeline, schedules.

`build_runtime()` is called lazily (first `peers.get_runtime()`), never at
import time.
"""

import sys
from dataclasses import dataclass

from cadence.catalogue import Catalogue
from cadence.config import DB_PATH
from cadence.context import RollingContext
from cadence.core import Core
from cadence.deciders.base import DeciderUnavailable, UnavailableDecider
from cadence.deciders.jev import JevDecider, load_api_key
from cadence.deciders.llm import LlmDecider
from cadence.decisionlog import DecisionLog
from cadence.executor import Executor
from cadence.lamp import LampPresetPlugin
from cadence.livecontext import LiveContext
from cadence.llm import GoogleLLM
from cadence.peers import PeerHub
from cadence.pipeline import Pipeline
from cadence.plugins.registry import DeviceRegistry
from cadence.schedules import PendingQuestions, SchedulePlugin, ScheduleStore


@dataclass
class Runtime:
    registry: DeviceRegistry
    catalogue: Catalogue
    hub: PeerHub
    core: Core
    pipeline: Pipeline
    log: DecisionLog


def build_runtime() -> Runtime:
    registry = DeviceRegistry([])
    log = DecisionLog(DB_PATH)
    schedules = ScheduleStore(DB_PATH)
    pending = PendingQuestions()
    catalogue = Catalogue([SchedulePlugin(schedules, pending)])
    catalogue.add(LampPresetPlugin(catalogue))
    hub = PeerHub(catalogue, registry)

    try:
        jev = JevDecider(load_api_key())
    except DeciderUnavailable as exc:
        print(f"jev unavailable: {exc}", file=sys.stderr)
        jev = UnavailableDecider(str(exc))
    llm = LlmDecider(GoogleLLM(), RollingContext())

    executor = Executor(catalogue, registry)
    context = LiveContext(log, hub.now_playing)
    pipeline = Pipeline(jev, llm, catalogue, executor, log, context)
    core = Core(pipeline, hub, log, schedules, pending)
    return Runtime(registry, catalogue, hub, core, pipeline, log)
