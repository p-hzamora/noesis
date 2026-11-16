"""Import writes append to C5a's change feed in their own transaction (C3 AC-016, FR-021).

The importer is wired as the CLI wires it, with C4's supersession proposer, over the pinned Neo4j.
The assertion a successor link proposes appends its own entry through C4's handler; it is C4's and
is not counted here (only `record_type: knowledge` entries are).
"""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from tests.support.import_knowledge_support import build_importer
from tests.support.import_support import (
    K2,
    K5,
    N2,
    N5,
    VAULT_KEY,
    copy_fixture_vault,
    graph_session,
    seed_status,
    space_id_of,
)
from tests.support.interop_support import ACTOR
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv, make_neo4j_env
from tests.support.knowledge_support import DEFAULT_SPACE_KEY

from noesis.bounded_context.interop.application.handlers import (
    RunVaultImportCommand,
    RunVaultImportHandler,
)
from noesis.bounded_context.interop.infrastructure.outbound import (
    FilesystemVaultReaderAdapter,
    YamlHeaderParserAdapter,
)
from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
    InitialiseStoreCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.propose_assertion_handler import (
    ProposeAssertionHandler,
)
from noesis.bounded_context.knowledge.application.services.assertion_supersession_proposer import (
    AssertionSupersessionProposer,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval import (
    Neo4jRecordChangeFeedAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence import (
    REVIEW_SCHEMA_STEP,
    Neo4jImportCandidateReadRepositoryAdapter,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

SPACE: str = DEFAULT_SPACE_KEY.value
Change = tuple[str, str, int | None, str | None]


@pytest.fixture
async def review_env(neo4j_settings: Neo4jConnectionSettings) -> AsyncIterator[Neo4jKnowledgeEnv]:
    """Real handlers over a store initialised with `core` and `review` (C4's proposer needs it)."""
    env: Neo4jKnowledgeEnv = make_neo4j_env(neo4j_settings, extra_steps=(REVIEW_SCHEMA_STEP,))
    await env.initialise_store.handle(InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY))
    yield env
    await env.client.close()


def _handler(env: Neo4jKnowledgeEnv, vault: Path) -> RunVaultImportHandler:
    persistence = env.persistence
    proposer = AssertionSupersessionProposer(
        uow_factory=persistence.uow_factory,
        propose=ProposeAssertionHandler(
            uow_factory=persistence.uow_factory,
            clock=env.clock,
            ids=persistence.ids,
            schema=persistence.schema,
        ),
    )
    importer = build_importer(
        uow_factory=persistence.uow_factory,
        clock=env.clock,
        ids=persistence.ids,
        schema=persistence.schema,
        candidates=Neo4jImportCandidateReadRepositoryAdapter(env.client),
        proposer=proposer,
    )
    return RunVaultImportHandler(
        vault=FilesystemVaultReaderAdapter(vault),
        header_parser=YamlHeaderParserAdapter(),
        importer=importer,
        vault_key=VAULT_KEY,
        space_key=SPACE,
        actor=ACTOR,
    )


async def _apply(handler: RunVaultImportHandler, *, update: bool = False) -> dict[str, Any]:
    result = await handler.handle(RunVaultImportCommand(update=update))
    return result.model_dump(mode="json")


def _row(result: dict[str, Any], path: str) -> dict[str, Any]:
    return next(item for item in result["notes"] if item["path"] == path)


async def _feed(env: Neo4jKnowledgeEnv, space_id: str, after: int) -> list[tuple[int, str, Change]]:
    """`(sequence, record_type, (record_id, change_kind, revision, status))` after `after`."""
    changes = await Neo4jRecordChangeFeedAdapter(env.client).changes_after(
        after, space_id=space_id, limit=1000
    )
    return [
        (c.sequence, c.record_type, (c.record_id, c.change_kind, c.revision, c.status))
        for c in changes
    ]


async def _head(env: Neo4jKnowledgeEnv, space_id: str) -> int:
    return max((sequence for sequence, _, _ in await _feed(env, space_id, 0)), default=0)


async def _knowledge_since(env: Neo4jKnowledgeEnv, space_id: str, mark: int) -> list[Change]:
    return [change for _, kind, change in await _feed(env, space_id, mark) if kind == "knowledge"]


async def test_ac016_imports_append_changes(
    review_env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings, tmp_path: Path
) -> None:
    vault: Path = copy_fixture_vault(tmp_path)
    handler = _handler(review_env, vault)
    with graph_session(neo4j_settings) as session:
        space_id: str = space_id_of(session, SPACE)

    applied = await _apply(handler)

    created_ids = sorted(
        row["record_id"] for row in applied["notes"] if row["outcome"] == "created"
    )
    assert len(created_ids) == 7
    changes = await _knowledge_since(review_env, space_id, 0)
    assert sorted(changes) == sorted((rid, "created", 1, "proposed") for rid in created_ids)
    assert [kind for _, kind, _ in await _feed(review_env, space_id, 0)] == ["knowledge"] * 7

    mark: int = await _head(review_env, space_id)
    (vault / N2).write_bytes((vault / N2).read_bytes() + b"Also small.\n")
    review_env.clock.advance()
    await _apply(handler, update=True)
    assert await _knowledge_since(review_env, space_id, mark) == [(K2, "revised", 2, "proposed")]

    mark = await _head(review_env, space_id)
    with graph_session(neo4j_settings) as session:
        seed_status(session, K5, "accepted")
    (vault / N5).write_bytes((vault / N5).read_bytes() + b"Also fast.\n")
    review_env.clock.advance()
    linked = await _apply(handler, update=True)
    successor = _row(linked, N5)
    assert successor["outcome"] == "successor_proposed"
    assert await _knowledge_since(review_env, space_id, mark) == [
        (successor["record_id"], "created", 1, "proposed")
    ]

    mark = await _head(review_env, space_id)
    review_env.clock.advance()
    await _apply(handler, update=True)
    await _apply(handler)
    assert await _feed(review_env, space_id, mark) == []
