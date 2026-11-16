"""The post-write index sync trigger (AC-031 unit side, D-012, D-025)."""

import inspect
from collections.abc import Sequence

import pytest
from tests.support.retrieval.probe_projection import InMemoryProbeProjection

from noesis.interfaces.cli.bootstrap.retrieval_handlers_builder import (
    IndexSyncTrigger,
    RegisteredProjections,
)

pytestmark = pytest.mark.unit

COMMAND: tuple[str, ...] = ("python", "-m", "noesis", "--env-file", "/work/.env")


class RecordingStarter:
    """A fake process starter: remembers each argv it was asked to start."""

    def __init__(self) -> None:
        self.started: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str]) -> None:
        self.started.append(tuple(argv))


async def fire(trigger: IndexSyncTrigger) -> None:
    outcome = trigger.trigger()
    if inspect.isawaitable(outcome):
        await outcome


async def test_ac031_trigger() -> None:
    starter = RecordingStarter()
    empty = IndexSyncTrigger(
        registered=RegisteredProjections(writers=(), candidate_sources=()),
        start_process=starter,
        command=COMMAND,
    )

    await fire(empty)

    assert starter.started == []  # no projection registered: no detached process

    one = IndexSyncTrigger(
        registered=RegisteredProjections(
            writers=(InMemoryProbeProjection(),), candidate_sources=()
        ),
        start_process=starter,
        command=COMMAND,
    )

    await fire(one)

    assert starter.started == [(*COMMAND, "index", "sync", "--json")]
