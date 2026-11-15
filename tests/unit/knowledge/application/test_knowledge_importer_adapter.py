"""KnowledgeImporterAdapter: system failures are never mapped to an outcome (Error mapping table)."""

import pytest
from tests.support.import_knowledge_support import make_fake_importer
from tests.support.knowledge_support import KnowledgeEnv, make_env

from noesis.exceptions import (
    AppException,
    GraphStoreAuthenticationFailedError,
    GraphStoreBusyError,
    GraphStoreQueryFailedError,
    GraphStoreUnavailableError,
    ReferenceNotInSpaceError,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "error",
    [
        GraphStoreUnavailableError("down"),
        GraphStoreAuthenticationFailedError("bad credentials"),
        GraphStoreBusyError("busy"),
        GraphStoreQueryFailedError("query failed"),
        ReferenceNotInSpaceError("source not in this space"),
    ],
    ids=lambda error: type(error).__name__,
)
@pytest.mark.parametrize("mode", ["apply", "assess"])
async def test_system_failures_propagate_as_their_typed_errors(
    error: AppException, mode: str
) -> None:
    env: KnowledgeEnv = await make_env()

    def failing_unit_of_work() -> object:
        raise error

    importer = make_fake_importer(env, uow_factory=failing_unit_of_work)  # type: ignore[arg-type]

    with pytest.raises(type(error)) as raised:
        await getattr(importer, mode)()

    assert raised.value is error


@pytest.mark.parametrize("mode", ["apply", "assess"])
async def test_unknown_header_source_kind_is_blocked_as_invalid_metadata(mode: str) -> None:
    importer = make_fake_importer(await make_env())

    outcome = await getattr(importer, mode)(
        header_sources=[{"kind": "carrier_pigeon", "locator": "vault://fixture/x.md"}]
    )

    assert outcome.outcome == "blocked"
    assert outcome.block_reason == "invalid_metadata"
    assert outcome.detail == "header_sources.kind"


@pytest.mark.parametrize("mode", ["apply", "assess"])
@pytest.mark.parametrize(
    "override",
    [
        {"actor": {"kind": "robot", "name": "tester", "session": None}},
        {"on_change": "explode"},
    ],
    ids=["actor-kind", "on-change"],
)
async def test_unknown_actor_kind_or_on_change_is_a_typed_invalid_metadata(
    mode: str, override: dict[str, object]
) -> None:
    importer = make_fake_importer(await make_env())

    outcome = await getattr(importer, mode)(**override)

    assert outcome.outcome == "blocked"
    assert outcome.block_reason == "invalid_metadata"
    assert outcome.detail == "KNOWLEDGE_007_INVALID_RECORD"
