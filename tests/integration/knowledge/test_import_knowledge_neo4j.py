"""The import handlers over the real Neo4j adapters (AC-006, 023(a), 026(a); NFR-003; edge cases).

C4 and C5a are not built here: the importer is wired with no `ISupersessionProposer` unless a
test passes a fake, and no change feed is asserted. Every vault is a fixture copy under `tmp_path`.
"""

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import pytest
from tests.support.import_knowledge_support import (
    FakeImportCandidateReadRepository,
    FakeSupersessionProposer,
    build_importer,
    content_hash,
    file_digest,
    make_request,
)
from tests.support.import_support import (
    K1,
    K2,
    K3,
    K5,
    N2,
    N5,
    N8,
    VAULT_KEY,
    copy_fixture_vault,
    graph_counts,
    graph_digest,
    graph_session,
    knowledge_by_locator,
    ledger_keys,
    seed_node,
    seed_status,
    space_id_of,
)
from tests.support.interop_support import ACTOR, file_command
from tests.support.knowledge_cli_support import run_json, use_store
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv, make_neo4j_env, query
from tests.support.knowledge_support import DEFAULT_SPACE_KEY, NOW
from tests.support.neo4j_container import wipe_database

from noesis.bounded_context.interop.application.handlers import (
    ImportFileHandler,
    RunVaultImportCommand,
    RunVaultImportHandler,
)
from noesis.bounded_context.interop.infrastructure.outbound import (
    FilesystemFileReaderAdapter,
    FilesystemVaultReaderAdapter,
    YamlHeaderParserAdapter,
)
from noesis.bounded_context.knowledge.application.dtos import ImportCandidatesDto, RecordDto
from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
    InitialiseStoreCommand,
)
from noesis.bounded_context.knowledge.application.handlers.queries.get_record_handler import (
    GetRecordQuery,
)
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.domain.value_objects import Key, RecordId, SpaceId, Tag
from noesis.bounded_context.knowledge.infrastructure.inbound.import_contracts import (
    KnowledgeImporterAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence import (
    Neo4jImportCandidateReadRepositoryAdapter,
)
from noesis.exceptions import GraphStoreUnavailableError
from noesis.interfaces.cli.bootstrap.knowledge_handlers_builder import (
    EXTRA_SCHEMA_STEPS,
    registered_schema_step_names,
)
from noesis.shared_kernel.contracts.knowledge import (
    ImportKnowledgeOutcomeContract,
    ImportKnowledgeRequestContract,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

LOCATOR = "vault://fixture/notes/a.md"
SPACE = DEFAULT_SPACE_KEY.value


class _BlindCandidates(FakeImportCandidateReadRepository):
    """A candidate read that sees nothing: stands for a lost response (`replay` test)."""

    def __init__(self) -> None:
        super().__init__(None, blind=True)  # type: ignore[arg-type]


def _importer(
    env: Neo4jKnowledgeEnv,
    *,
    proposer: FakeSupersessionProposer | None = None,
    blind: bool = False,
) -> KnowledgeImporterAdapter:
    return build_importer(
        uow_factory=env.persistence.uow_factory,
        clock=env.clock,
        ids=env.persistence.ids,
        schema=env.persistence.schema,
        candidates=_BlindCandidates()
        if blind
        else Neo4jImportCandidateReadRepositoryAdapter(env.client),
        proposer=proposer,
    )


def _run_handler(
    env: Neo4jKnowledgeEnv, vault: Path, importer: KnowledgeImporterAdapter | Any
) -> RunVaultImportHandler:
    return RunVaultImportHandler(
        vault=FilesystemVaultReaderAdapter(vault),
        header_parser=YamlHeaderParserAdapter(),
        importer=importer,
        vault_key=VAULT_KEY,
        space_key=SPACE,
        actor=ACTOR,
    )


async def _apply(
    handler: RunVaultImportHandler, *, update: bool = False, strict: bool = False
) -> dict[str, Any]:
    result = await handler.handle(RunVaultImportCommand(update=update, strict=strict))
    return result.model_dump(mode="json")


def _row(result: dict[str, Any], path: str) -> dict[str, Any]:
    return next(item for item in result["notes"] if item["path"] == path)


async def _get(env: Neo4jKnowledgeEnv, record_id: str) -> RecordDto:
    return await env.get_record.handle(
        GetRecordQuery(space_key=DEFAULT_SPACE_KEY, record_id=RecordId(value=record_id))
    )


def _digest(settings: Neo4jConnectionSettings) -> str:
    with graph_session(settings) as session:
        return graph_digest(session)


def _knowledge_count(settings: Neo4jConnectionSettings) -> int:
    with graph_session(settings) as session:
        return int(session.run("MATCH (k:Knowledge) RETURN count(k) AS c").single()["c"])  # type: ignore[index]


async def test_create_rerun_revise_and_revert_through_the_real_unit_of_work(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    importer = _importer(env)
    created = await importer.apply(make_request(title="Ports", body="Original."))
    assert created.record_id is not None
    before_counts, before_digest = _snapshot(neo4j_settings)

    again = await importer.apply(make_request(title="Ports", body="Original."))

    assert (created.outcome, again.outcome, again.record_id) == (
        "created",
        "unchanged",
        created.record_id,
    )
    assert _snapshot(neo4j_settings) == (before_counts, before_digest)
    env.clock.advance()
    edited = await importer.apply(make_request(title="Ports", body="Edited."))
    env.clock.advance()
    reverted = await importer.apply(make_request(title="Ports", body="Original."))
    assert (edited.revision, reverted.revision) == (2, 3)
    head = await _get(env, created.record_id)
    assert head.head_revision == 3 and head.revision is not None
    assert (head.revision.title, head.revision.body) == ("Ports", "Original.")
    with graph_session(neo4j_settings) as session:
        keys = ledger_keys(session)
    assert any(key.startswith(f"import/v1/revise/{created.record_id}/1/") for key in keys)
    assert any(key.startswith(f"import/v1/revise/{created.record_id}/2/") for key in keys)
    assert any(key.startswith("import/v1/create/loc-") for key in keys)


def _snapshot(settings: Neo4jConnectionSettings) -> tuple[dict[str, Any], str]:
    with graph_session(settings) as session:
        return graph_counts(session), graph_digest(session)


async def test_candidate_read_finds_a_record_by_id_after_a_move_and_by_locator_and_origin_tag(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    importer = _importer(env)
    declared = await importer.apply(
        make_request(record_id=K1, title="Declared", body="Text one.", source_locator=LOCATOR)
    )
    by_locator = await importer.apply(
        make_request(title="Located", body="Text two.", source_locator="vault://fixture/notes/b.md")
    )
    with graph_session(neo4j_settings) as session:
        space = SpaceId(value=space_id_of(session, SPACE))
    candidates = Neo4jImportCandidateReadRepositoryAdapter(env.client)

    moved: ImportCandidatesDto = await candidates.find_candidates(
        RecordId(value=K1),
        "vault://fixture/archive/moved.md",
        Tag(value="origin:migrated"),
        space_id=space,
    )
    located: ImportCandidatesDto = await candidates.find_candidates(
        None, "vault://fixture/notes/b.md", Tag(value="origin:migrated"), space_id=space
    )
    wrong_tag: ImportCandidatesDto = await candidates.find_candidates(
        None, "vault://fixture/notes/b.md", Tag(value="origin:imported"), space_id=space
    )
    nothing: ImportCandidatesDto = await candidates.find_candidates(
        None, "vault://fixture/none.md", Tag(value="origin:migrated"), space_id=space
    )

    assert moved.id_holder == "graph_knowledge"
    assert [candidate.id for candidate in moved.candidates] == [declared.record_id]
    assert [candidate.id for candidate in located.candidates] == [by_locator.record_id]
    only = located.candidates[0]
    assert (only.status, only.head_revision, only.title, only.body) == (
        "proposed",
        1,
        "Located",
        "Text two.",
    )
    assert only.head_file_digests == (file_digest("Text two."),)
    assert wrong_tag.candidates == () and nothing.candidates == ()
    assert nothing.id_holder == "none"


async def test_candidate_read_is_scoped_to_the_space_and_reports_other_record_types(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    await env.initialise_store.handle(InitialiseStoreCommand(default_space_key=Key(value="other")))
    importer = _importer(env)
    await importer.apply(make_request(space_key="other", record_id=K1, title="T", body="B."))
    with graph_session(neo4j_settings) as session:
        space = SpaceId(value=space_id_of(session, SPACE))
        seed_node(session, ["Experience"], K3, space.value)
    candidates = Neo4jImportCandidateReadRepositoryAdapter(env.client)

    elsewhere = await candidates.find_candidates(
        RecordId(value=K1), LOCATOR, Tag(value="origin:migrated"), space_id=space
    )
    experience = await candidates.find_candidates(
        RecordId(value=K3), LOCATOR, Tag(value="origin:migrated"), space_id=space
    )

    assert (elsewhere.id_holder, elsewhere.candidates) == ("none", ())
    assert experience.id_holder == "other"


async def test_id_conflict_other_type_blocks_and_creates_no_knowledge(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    with graph_session(neo4j_settings) as session:
        seed_node(session, ["Experience"], K3, space_id_of(session, SPACE))
    importer = _importer(env)

    result = await importer.apply(make_request(record_id=K3, title="T", body="B."))

    assert (result.outcome, result.block_reason) == ("blocked", "id_conflict")
    assert _knowledge_count(neo4j_settings) == 0


async def test_id_conflict_other_space_blocks_because_the_create_loses_on_the_record_id(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    await env.initialise_store.handle(InitialiseStoreCommand(default_space_key=Key(value="other")))
    importer = _importer(env)
    created = await importer.apply(
        make_request(space_key="other", record_id=K1, title="T", body="B.")
    )
    assert created.outcome == "created"

    result = await importer.apply(make_request(space_key=SPACE, record_id=K1, title="T", body="B."))

    assert (result.outcome, result.block_reason) == ("blocked", "id_conflict")
    assert _knowledge_count(neo4j_settings) == 1


async def test_target_closed_reports_only_without_update_and_blocks_with_it(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    importer = _importer(env)
    created = await importer.apply(make_request(title="Ports", body="Original."))
    assert created.record_id is not None
    with graph_session(neo4j_settings) as session:
        seed_status(session, created.record_id, "retracted")
    digest: str = _digest(neo4j_settings)

    reported = await importer.apply(make_request(title="Ports", body="Edited.", on_change="report"))
    blocked = await importer.apply(make_request(title="Ports", body="Edited.", on_change="update"))

    assert reported.outcome == "changed"
    assert (blocked.outcome, blocked.block_reason) == ("blocked", "target_closed")
    assert _digest(neo4j_settings) == digest


async def test_a_ledger_entry_with_another_fingerprint_under_the_revise_key_blocks_the_revise(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    importer = _importer(env)
    created = await importer.apply(make_request(title="Ports", body="Original."))
    assert created.record_id is not None
    key: str = (
        f"import/v1/revise/{created.record_id}/1/"
        f"{content_hash('Ports', 'Edited.', file_digest('Edited.'))}"
    )
    with graph_session(neo4j_settings) as session:
        space = SpaceId(value=space_id_of(session, SPACE))
    async with env.uow() as uow:
        await uow.ledger.record(
            LedgerEntry(
                space_id=space,
                key=key,
                command="import_knowledge.revise",
                fingerprint="sha256:" + "0" * 64,
                recorded_at=NOW,
            )
        )
        await uow.commit()

    result = await importer.apply(make_request(title="Ports", body="Edited."))

    assert (result.outcome, result.block_reason) == ("blocked", "idempotency_key_reused")
    assert (await _get(env, created.record_id)).head_revision == 1


async def test_replay_after_a_lost_response_returns_the_first_result_and_writes_nothing(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    first = await _importer(env).apply(make_request(title="Ports", body="Text."))
    before = _snapshot(neo4j_settings)

    replay = await _importer(env, blind=True).apply(make_request(title="Ports", body="Text."))

    assert (replay.outcome, replay.replayed, replay.record_id) == ("created", True, first.record_id)
    assert _snapshot(neo4j_settings) == before


async def test_header_sources_are_stored_once_and_cited_again_by_the_next_revision(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    importer = _importer(env)
    sources: list[dict[str, str]] = [{"kind": "agent_session", "locator": "s-1"}]
    created = await importer.apply(
        make_request(title="Ports", body="Text.", header_sources=sources)
    )
    assert created.record_id is not None
    before = _snapshot(neo4j_settings)

    again = await importer.apply(make_request(title="Ports", body="Text.", header_sources=sources))
    env.clock.advance()
    revised = await importer.apply(
        make_request(title="Ports", body="Edited.", header_sources=sources)
    )

    assert again.outcome == "unchanged" and revised.revision == 2
    assert before[0]["labels"]["Source"] == 2
    head = (await _get(env, created.record_id)).revision
    assert head is not None
    assert sorted(source.kind for source in head.sources) == ["agent_session", "file_version"]
    with graph_session(neo4j_settings) as session:
        assert graph_counts(session)["labels"]["Source"] == 3  # the edited file's new digest


async def test_a_closed_record_found_by_locator_is_unchanged_then_changed_then_blocked(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    importer = _importer(env)
    created = await importer.apply(make_request(title="Readme", body="Text.", tags=[]))
    assert created.record_id is not None
    with graph_session(neo4j_settings) as session:
        seed_status(session, created.record_id, "retracted")

    same = await importer.apply(make_request(title="Readme", body="Text."))
    reported = await importer.apply(make_request(title="Readme", body="More.", on_change="report"))
    blocked = await importer.apply(make_request(title="Readme", body="More."))

    assert (same.outcome, same.record_id) == ("unchanged", created.record_id)
    assert reported.outcome == "changed"
    assert (blocked.outcome, blocked.block_reason) == ("blocked", "target_closed")
    assert _knowledge_count(neo4j_settings) == 1


async def test_successor_gap_d022_a_failing_proposer_leaves_the_successor_and_a_rerun_is_unchanged(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    proposer = FakeSupersessionProposer(error=RuntimeError("C4 is down"))
    importer = _importer(env, proposer=proposer)
    first = await importer.apply(make_request(title="Ports", body="Original."))
    assert first.record_id is not None
    with graph_session(neo4j_settings) as session:
        seed_status(session, first.record_id, "accepted")
    env.clock.advance()

    with pytest.raises(RuntimeError, match="C4 is down"):
        await importer.apply(make_request(title="Ports", body="Edited."))
    env.clock.advance()
    rerun = await importer.apply(make_request(title="Ports", body="Edited."))

    assert _knowledge_count(neo4j_settings) == 2
    assert rerun.outcome == "unchanged" and rerun.record_id != first.record_id
    assert len(proposer.calls) == 1


async def test_ac023a_accepted_note_gets_a_plain_successor_without_c4(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings, tmp_path: Path
) -> None:
    vault: Path = copy_fixture_vault(tmp_path)
    handler = _run_handler(env, vault, _importer(env))
    await _apply(handler)
    with graph_session(neo4j_settings) as session:
        seed_status(session, K5, "accepted")
    path: Path = vault / N5
    original: bytes = path.read_bytes()
    path.write_bytes(original + b"Also fast.\n")
    env.clock.advance()

    result = await _apply(handler, update=True)

    successor = _row(result, N5)
    assert successor["outcome"] == "created"
    new_id: str = successor["record_id"]
    assert new_id not in (None, K5)
    assert (successor["target_record_id"], successor["reason"]) == (
        K5,
        "assertions unavailable: target not linked",
    )
    record = await _get(env, new_id)
    assert (record.status, record.head_revision) == ("proposed", 1)
    assert record.applicability is not None and "origin:migrated" in record.applicability.tags
    file_source = next(s for s in record.sources if s.kind == "file_version")
    assert file_source.locator == f"vault://fixture/{N5}"
    assert file_source.digest == file_digest_of(path.read_bytes())
    old = await _get(env, K5)
    assert (old.status, old.head_revision) == ("accepted", 1)
    with graph_session(neo4j_settings) as session:
        assert session.run("MATCH (a:Assertion) RETURN count(a) AS c").single()["c"] == 0  # type: ignore[index]
    env.clock.advance()

    rerun = await _apply(handler, update=True)

    assert (_row(rerun, N5)["outcome"], _row(rerun, N5)["record_id"]) == ("unchanged", new_id)
    path.write_bytes(path.read_bytes() + b"Once more.\n")
    env.clock.advance()
    revised = await _apply(handler, update=True)
    assert (
        _row(revised, N5)["outcome"],
        _row(revised, N5)["record_id"],
        _row(revised, N5)["revision"],
    ) == (
        "revised",
        new_id,
        2,
    )


def file_digest_of(data: bytes) -> str:
    """`sha256:<hex>` of raw file bytes."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


async def test_ac026a_import_file_on_an_accepted_record_creates_a_plain_proposal_without_c4(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings, tmp_path: Path
) -> None:
    target: Path = tmp_path / "outside" / "design.md"
    target.parent.mkdir()
    target.write_text("# Design\n\nUse [[ports|the ports note]].\n", encoding="utf-8")
    handler = ImportFileHandler(
        files=FilesystemFileReaderAdapter(),
        header_parser=YamlHeaderParserAdapter(),
        importer=_importer(env),
        space_key=SPACE,
        actor=ACTOR,
    )

    async def register() -> dict[str, Any]:
        result = await handler.handle(
            file_command(
                str(target), title="Design notes", project_key="alpha", tags=("area:core",)
            )
        )
        return result.model_dump(mode="json")

    first = await register()
    with graph_session(neo4j_settings) as session:
        seed_status(session, first["record_id"], "accepted")
    target.write_text(target.read_text(encoding="utf-8") + "More.\n", encoding="utf-8")
    env.clock.advance()

    second = await register()
    third = await register()

    assert (first["outcome"], first["revision"], first["tags"]) == (
        "created",
        1,
        ["area:core", "origin:imported"],
    )
    assert second["outcome"] == "created" and second["record_id"] != first["record_id"]
    assert second["target_record_id"] == first["record_id"]
    assert second["reason"] == "assertions unavailable: target not linked"
    assert (await _get(env, first["record_id"])).status == "accepted"
    assert (third["outcome"], third["record_id"]) == ("unchanged", second["record_id"])


class _FailsOnApply:
    """Wraps the real importer; the n-th `apply` raises `INTEGRATION_103`."""

    def __init__(self, inner: KnowledgeImporterAdapter, fail_on: int) -> None:
        self._inner = inner
        self._fail_on = fail_on
        self._applies = 0

    async def assess(
        self, request: ImportKnowledgeRequestContract
    ) -> ImportKnowledgeOutcomeContract:
        return await self._inner.assess(request)

    async def apply(
        self, request: ImportKnowledgeRequestContract
    ) -> ImportKnowledgeOutcomeContract:
        self._applies += 1
        if self._applies == self._fail_on:
            raise GraphStoreUnavailableError("The connection was lost.")
        return await self._inner.apply(request)


async def test_a_rerun_after_a_connection_lost_mid_run_ends_with_every_note_migrated(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings, tmp_path: Path
) -> None:
    vault: Path = copy_fixture_vault(tmp_path)
    flaky = _run_handler(env, vault, _FailsOnApply(_importer(env), fail_on=3))

    with pytest.raises(GraphStoreUnavailableError):
        await _apply(flaky)
    written: int = _knowledge_count(neo4j_settings)
    rerun = await _apply(_run_handler(env, vault, _importer(env)))

    assert written == 2
    assert _knowledge_count(neo4j_settings) == 7
    assert rerun["totals"]["unchanged"] == 2 and rerun["totals"]["created"] == 5
    assert _row(rerun, N8)["outcome"] == "unchanged"


async def test_closed_note_without_a_ulid_is_found_by_locator_through_the_vault_run(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings, tmp_path: Path
) -> None:
    vault: Path = copy_fixture_vault(tmp_path)
    handler = _run_handler(env, vault, _importer(env))
    first = await _apply(handler)
    readme_id: str = _row(first, N8)["record_id"]
    with graph_session(neo4j_settings) as session:
        seed_status(session, readme_id, "retracted")

    again = await _apply(handler)
    (vault / N8).write_bytes((vault / N8).read_bytes() + b"More.\n")
    changed = await _apply(handler)
    blocked = await _apply(handler, update=True)

    assert (_row(again, N8)["outcome"], _row(again, N8)["record_id"]) == ("unchanged", readme_id)
    assert _row(changed, N8)["outcome"] == "changed_in_vault"
    assert (_row(blocked, N8)["outcome"], _row(blocked, N8)["reason"]) == (
        "blocked",
        "target_closed",
    )
    assert _knowledge_count(neo4j_settings) == 7
    with graph_session(neo4j_settings) as session:
        assert knowledge_by_locator(session, f"vault://fixture/{N8}") == [readme_id]


async def test_ac006_edit_and_revert_leave_three_revisions_citing_the_original_digest(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings, tmp_path: Path
) -> None:
    vault: Path = copy_fixture_vault(tmp_path)
    handler = _run_handler(env, vault, _importer(env))
    await _apply(handler)
    path: Path = vault / N2
    original: bytes = path.read_bytes()
    path.write_bytes(original + b"Extra step.\n")
    env.clock.advance()
    second = await _apply(handler, update=True)
    path.write_bytes(original)
    env.clock.advance()
    third = await _apply(handler, update=True)

    assert (_row(second, N2)["outcome"], _row(second, N2)["revision"]) == ("revised", 2)
    assert (_row(third, N2)["outcome"], _row(third, N2)["revision"]) == ("revised", 3)
    one = await _get_revision(env, K2, 1)
    three = await _get_revision(env, K2, 3)
    assert one.revision is not None and three.revision is not None
    assert (one.revision.title, one.revision.body) == (three.revision.title, three.revision.body)
    cited = [s.digest for s in three.revision.sources if s.kind == "file_version"]
    assert cited == [s.digest for s in one.revision.sources if s.kind == "file_version"]
    with graph_session(neo4j_settings) as session:
        revisions = session.run(
            "MATCH (:Revision {record_id: $id}) RETURN count(*) AS c", id=K2
        ).single()
        keys = ledger_keys(session)
        assert knowledge_by_locator(session, f"vault://fixture/{N2}") == [K2]
    assert revisions is not None and revisions["c"] == 3
    assert len([k for k in keys if k.startswith(f"import/v1/revise/{K2}/")]) == 2


async def _get_revision(env: Neo4jKnowledgeEnv, record_id: str, revision: int) -> RecordDto:
    return await env.get_record.handle(
        GetRecordQuery(
            space_key=DEFAULT_SPACE_KEY, record_id=RecordId(value=record_id), revision=revision
        )
    )


def _schema_listing(settings: Neo4jConnectionSettings) -> dict[str, list[dict[str, Any]]]:
    return {
        "constraints": sorted(
            query(
                settings,
                "SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties "
                "RETURN name, type, entityType, labelsOrTypes, properties",
            ),
            key=lambda row: row["name"],
        ),
        "indexes": sorted(
            query(
                settings,
                "SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, properties "
                "RETURN name, type, entityType, labelsOrTypes, properties",
            ),
            key=lambda row: row["name"],
        ),
        "steps": query(settings, "MATCH (m:StoreMeta) RETURN m.applied_steps AS steps"),
    }


async def _init_baseline_store(settings: Neo4jConnectionSettings) -> None:
    """`store init` with every step the other modules register (the composition without C3)."""
    baseline_env = make_neo4j_env(settings, extra_steps=EXTRA_SCHEMA_STEPS)
    try:
        await baseline_env.initialise_store.handle(
            InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY)
        )
    finally:
        await baseline_env.client.close()


def test_nfr003_no_schema_step(
    neo4j_settings: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`store init` of the composition with C3 registers exactly what one without C3 registers.

    Synchronous on purpose: the CLI runs its own event loop (`asyncio.run`), which cannot start
    inside a running one.
    """
    asyncio.run(_init_baseline_store(neo4j_settings))
    baseline = _schema_listing(neo4j_settings)
    wipe_database(neo4j_settings)
    use_store(monkeypatch, neo4j_settings)
    monkeypatch.setenv("NOESIS_VAULT_DIR", "/nonexistent-vault-for-composition-only")

    code, envelope = run_json(capsys, ["store", "init"])

    assert code == 0, envelope
    composed = _schema_listing(neo4j_settings)
    assert composed == baseline
    registered: tuple[str, ...] = registered_schema_step_names()
    assert composed["steps"] == [{"steps": list(registered)}]
    assert not [name for name in registered if "import" in name or "interop" in name]
