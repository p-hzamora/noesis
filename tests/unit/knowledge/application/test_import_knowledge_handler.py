"""ImportKnowledgeHandler and AssessImportKnowledgeHandler over C2's in-memory fakes.

Driven through `KnowledgeImporterAdapter` (contracts in, contracts out). Covers decision rows
2..9 end to end, idempotency keys (D-008), stored-form comparison (review finding 2), header
sources (Q-014), races, the assess query and the system errors that must propagate.
"""

from collections.abc import Callable

import pytest
from tests.support.import_knowledge_support import (
    ASSERTION_ID,
    FakeImporterHarness,
    FakeSupersessionProposer,
    content_hash,
    file_digest,
    locator_hash,
    make_fake_importer,
)
from tests.support.knowledge_commands import experience_command, racing_factory, revise_command
from tests.support.knowledge_support import NOW, FakeKnowledgeUnitOfWork, KnowledgeEnv, make_env

from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.domain.entities import Knowledge, Source
from noesis.bounded_context.knowledge.domain.repositories import IKnowledgeRepository
from noesis.bounded_context.knowledge.domain.value_objects import (
    GraphContent,
    RecordId,
    RecordStatusEnum,
    Revision,
    SourceKindEnum,
    SpaceId,
)
from noesis.exceptions import (
    KnowledgeNotRevisableError,
    RevisionConflictError,
    SpaceNotFoundError,
    StoreNotInitialisedError,
)
from noesis.shared_kernel.contracts.knowledge import ImportKnowledgeOutcomeContract

pytestmark = pytest.mark.unit

LOCATOR = "vault://fixture/notes/a.md"


async def _setup(
    *, proposer: FakeSupersessionProposer | None = None
) -> tuple[KnowledgeEnv, FakeImporterHarness]:
    env: KnowledgeEnv = await make_env()
    return env, make_fake_importer(env, proposer=proposer)


def _sources(env: KnowledgeEnv, knowledge: Knowledge) -> list[Source]:
    return [env.store.sources[source_id.value] for source_id in knowledge.head.source_ids]


def _space_id(env: KnowledgeEnv) -> str:
    return next(iter(env.store.spaces.values())).id.value


def _ledger_entry(env: KnowledgeEnv, key: str) -> LedgerEntry:
    return env.store.ledger[(_space_id(env), key)]


async def test_row_2_create_stores_a_proposed_graph_record_with_origin_tag_project_and_sources() -> (
    None
):
    env, importer = await _setup()

    result = await importer.apply(
        title="Ports",
        body="Ports isolate the core.",
        subtype="concept",
        project_key="alpha",
        tags=["b", "a"],
        header_sources=[{"kind": "commit", "locator": "c" * 40}],
    )

    assert (result.outcome, result.revision, result.status, result.replayed) == (
        "created",
        1,
        "proposed",
        False,
    )
    assert result.record_id is not None and result.target_record_id is None
    knowledge: Knowledge = env.store.knowledge[result.record_id]
    assert knowledge.ownership.value == "graph" and knowledge.status is RecordStatusEnum.PROPOSED
    assert knowledge.subtype.value == "concept"
    assert sorted(tag.value for tag in knowledge.applicability.tags) == [
        "a",
        "b",
        "origin:migrated",
    ]
    assert isinstance(knowledge.head.content, GraphContent)
    assert (knowledge.head.content.title, knowledge.head.content.body) == (
        "Ports",
        "Ports isolate the core.",
    )
    assert [(s.kind, s.locator) for s in _sources(env, knowledge)] == [
        (SourceKindEnum.FILE_VERSION, LOCATOR),
        (SourceKindEnum.COMMIT, "c" * 40),
    ]
    assert _sources(env, knowledge)[0].digest is not None
    assert _sources(env, knowledge)[1].digest is None
    project = next(iter(env.store.projects.values()))
    assert project.key.value == "alpha"
    assert knowledge.applicability.project_id == project.id


async def test_create_key_without_a_declared_id_uses_the_locator_hash() -> None:
    env, importer = await _setup()

    result = await importer.apply(title="Ports", body="Text.")

    key: str = (
        f"import/v1/create/loc-{locator_hash(LOCATOR)}/0/"
        f"{content_hash('Ports', 'Text.', file_digest('Text.'))}"
    )
    assert importer.ledger_keys() == [key]
    entry: LedgerEntry = _ledger_entry(env, key)
    assert entry.command == "import_knowledge.create"
    assert entry.record_id is not None and entry.record_id.value == result.record_id


async def test_create_with_a_declared_id_uses_that_id_and_its_key() -> None:
    env, importer = await _setup()
    declared: str = "01JCKMNP000000000000000001"

    result = await importer.apply(record_id=declared, title="Ports", body="Text.")

    assert result.record_id == declared and declared in env.store.knowledge
    assert importer.ledger_keys() == [
        f"import/v1/create/{declared}/0/{content_hash('Ports', 'Text.', file_digest('Text.'))}"
    ]


async def test_row_3_a_rerun_is_unchanged_and_writes_nothing() -> None:
    env, importer = await _setup()
    first = await importer.apply(title="Ports", body="Text.", project_key="alpha")
    commits: int = env.store.commits
    snapshot = (len(env.store.sources), len(env.store.projects), len(env.store.ledger))

    again = await importer.apply(title="Ports", body="Text.", project_key="alpha")

    assert (again.outcome, again.record_id, again.revision, again.status) == (
        "unchanged",
        first.record_id,
        1,
        "proposed",
    )
    assert env.store.commits == commits
    assert (len(env.store.sources), len(env.store.projects), len(env.store.ledger)) == snapshot


async def test_row_4_a_file_with_the_digest_of_the_head_is_unchanged_even_if_the_graph_text_moved() -> (
    None
):
    env, importer = await _setup()
    first = await importer.apply(title="Ports", body="Original.")
    assert first.record_id is not None
    # a curated revision keeps the head's Sources (C2 revise), so the file digest still matches
    await env.revise_knowledge.handle(
        revise_command(RecordId(value=first.record_id), body="Curated in the graph.")
    )
    assert env.store.knowledge[first.record_id].head_number == 2

    again = await importer.apply(title="Ports", body="Original.", on_change="update")

    assert (again.outcome, again.revision) == ("unchanged", 2)
    assert env.store.knowledge[first.record_id].head_number == 2


async def test_row_5_report_mode_reports_the_change_and_writes_nothing() -> None:
    env, importer = await _setup()
    first = await importer.apply(title="Ports", body="Text.")
    commits: int = env.store.commits

    result = await importer.apply(title="Ports", body="Edited text.", on_change="report")

    assert (result.outcome, result.record_id, result.revision) == ("changed", first.record_id, 1)
    assert env.store.commits == commits


async def test_row_6_revise_appends_revision_two_with_the_revise_key_and_keeps_metadata() -> None:
    env, importer = await _setup()
    first = await importer.apply(
        title="Ports", body="Text.", subtype="concept", project_key="alpha", tags=["keep"]
    )
    assert first.record_id is not None
    env.clock.advance()

    result = await importer.apply(
        title="Ports",
        body="Edited text.",
        subtype="decision",
        project_key="beta",
        tags=["changed"],
        header_sources=[{"kind": "agent_session", "locator": "s-1"}],
    )

    assert (result.outcome, result.record_id, result.revision) == ("revised", first.record_id, 2)
    knowledge: Knowledge = env.store.knowledge[first.record_id]
    assert knowledge.head_number == 2
    assert knowledge.subtype.value == "concept"
    assert sorted(tag.value for tag in knowledge.applicability.tags) == ["keep", "origin:migrated"]
    assert [project.key.value for project in env.store.projects.values()] == ["alpha"]
    assert isinstance(knowledge.head.content, GraphContent)
    assert knowledge.head.content.body == "Edited text."
    key: str = (
        f"import/v1/revise/{first.record_id}/1/"
        f"{content_hash('Ports', 'Edited text.', file_digest('Edited text.'))}"
    )
    assert key in importer.ledger_keys()
    assert _ledger_entry(env, key).command == "import_knowledge.revise"
    assert (_ledger_entry(env, key).revision, len(env.store.revisions[first.record_id])) == (2, 2)


async def test_row_6_edit_then_revert_makes_revision_three_with_revisions_one_content() -> None:
    env, importer = await _setup()
    first = await importer.apply(title="Ports", body="Original.")
    assert first.record_id is not None
    await importer.apply(title="Ports", body="Edited.")

    third = await importer.apply(title="Ports", body="Original.")

    assert (third.outcome, third.revision) == ("revised", 3)
    history = env.store.revisions[first.record_id]
    assert history[2].content == history[0].content
    revise_keys: list[str] = [k for k in importer.ledger_keys() if "/revise/" in k]
    assert sorted(k.split("/")[4] for k in revise_keys) == ["1", "2"]


async def test_row_8_an_accepted_target_without_a_proposer_gets_a_plain_successor() -> None:
    env, importer = await _setup()
    first = await importer.apply(title="Ports", body="Original.", subtype="concept")
    assert first.record_id is not None
    importer.set_status(first.record_id, RecordStatusEnum.ACCEPTED)
    env.clock.advance()

    result = await importer.apply(
        title="Ports", body="Edited.", subtype="decision", project_key="alpha", tags=["new"]
    )

    assert result.outcome == "created"
    assert result.record_id not in (None, first.record_id)
    assert result.target_record_id == first.record_id
    assert result.reason == "assertions unavailable: target not linked"
    assert result.assertion_id is None
    successor: Knowledge = env.store.knowledge[result.record_id or ""]
    assert successor.status is RecordStatusEnum.PROPOSED and successor.head_number == 1
    assert successor.subtype.value == "decision"
    assert sorted(tag.value for tag in successor.applicability.tags) == ["new", "origin:migrated"]
    target: Knowledge = env.store.knowledge[first.record_id]
    assert (target.status, target.head_number) == (RecordStatusEnum.ACCEPTED, 1)
    key: str = (
        f"import/v1/successor/{first.record_id}/1/"
        f"{content_hash('Ports', 'Edited.', file_digest('Edited.'))}"
    )
    entry: LedgerEntry = _ledger_entry(env, key)
    assert entry.command == "import_knowledge.successor"
    assert entry.extra["target_record_id"] == first.record_id


async def test_after_a_plain_successor_a_rerun_is_unchanged_then_revises_the_successor() -> None:
    env, importer = await _setup()
    first = await importer.apply(title="Ports", body="Original.")
    assert first.record_id is not None
    importer.set_status(first.record_id, RecordStatusEnum.ACCEPTED)
    env.clock.advance()
    successor = await importer.apply(title="Ports", body="Edited.")
    env.clock.advance()

    again = await importer.apply(title="Ports", body="Edited.")
    third = await importer.apply(title="Ports", body="Edited again.")

    assert (again.outcome, again.record_id) == ("unchanged", successor.record_id)
    assert (third.outcome, third.record_id, third.revision) == ("revised", successor.record_id, 2)
    assert env.store.knowledge[first.record_id].head_number == 1


async def test_row_7_an_accepted_target_with_a_proposer_gets_a_successor_and_a_supersedes_proposal() -> (
    None
):
    proposer = FakeSupersessionProposer()
    env, importer = await _setup(proposer=proposer)
    first = await importer.apply(title="Ports", body="Original.")
    assert first.record_id is not None
    importer.set_status(first.record_id, RecordStatusEnum.ACCEPTED)
    env.clock.advance()

    result = await importer.apply(title="Ports", body="Edited.")

    assert result.outcome == "successor_proposed"
    assert result.assertion_id == ASSERTION_ID
    assert result.target_record_id == first.record_id and result.record_id is not None
    assert result.reason is None
    (call,) = proposer.calls
    successor: Knowledge = env.store.knowledge[result.record_id]
    file_source = next(s for s in _sources(env, successor) if s.kind is SourceKindEnum.FILE_VERSION)
    assert call["subject_id"] == result.record_id and call["object_id"] == first.record_id
    assert call["rationale"] == f"content of {LOCATOR} changed after acceptance"
    assert call["source_ids"] == (file_source.id.value,)
    assert call["idempotency_key"] == f"import/v1/supersedes/{result.record_id}/{first.record_id}"
    assert call["space_id"] == _space_id(env)
    assert (call["actor"].kind.value, call["actor"].name) == ("user", "tester")


async def test_successor_gap_a_failing_proposer_leaves_an_unlinked_successor_and_a_rerun_does_not_repair_it() -> (
    None
):
    proposer = FakeSupersessionProposer(error=RuntimeError("C4 is down"))
    env, importer = await _setup(proposer=proposer)
    first = await importer.apply(title="Ports", body="Original.")
    assert first.record_id is not None
    importer.set_status(first.record_id, RecordStatusEnum.ACCEPTED)
    env.clock.advance()

    with pytest.raises(RuntimeError, match="C4 is down"):
        await importer.apply(title="Ports", body="Edited.")
    successors = [k for k in env.store.knowledge if k != first.record_id]
    env.clock.advance()
    rerun = await importer.apply(title="Ports", body="Edited.")

    assert len(successors) == 1
    assert (rerun.outcome, rerun.record_id) == ("unchanged", successors[0])
    assert len(proposer.calls) == 1


@pytest.mark.parametrize("status", [RecordStatusEnum.SUPERSEDED, RecordStatusEnum.RETRACTED])
async def test_row_9_a_closed_target_blocks_and_writes_nothing(status: RecordStatusEnum) -> None:
    env, importer = await _setup()
    first = await importer.apply(title="Ports", body="Original.")
    assert first.record_id is not None
    importer.set_status(first.record_id, status)
    commits: int = env.store.commits

    blocked = await importer.apply(title="Ports", body="Edited.")
    reported = await importer.apply(title="Ports", body="Edited.", on_change="report")

    assert (blocked.outcome, blocked.block_reason) == ("blocked", "target_closed")
    assert blocked.revision is None
    assert (reported.outcome, reported.record_id) == ("changed", first.record_id)
    assert env.store.commits == commits


async def test_a_closed_record_found_by_locator_is_unchanged_not_recreated() -> None:
    env, importer = await _setup()
    first = await importer.apply(title="Ports", body="Text.")
    assert first.record_id is not None
    importer.set_status(first.record_id, RecordStatusEnum.RETRACTED)

    again = await importer.apply(title="Ports", body="Text.")

    assert (again.outcome, again.record_id) == ("unchanged", first.record_id)
    assert len(env.store.knowledge) == 1


async def test_row_1_an_id_held_by_another_record_type_is_blocked_as_id_conflict() -> None:
    env, importer = await _setup()
    experience = await env.capture_experience.handle(experience_command())
    commits: int = env.store.commits

    result = await importer.apply(record_id=experience.record_id, title="Ports", body="Text.")

    assert (result.outcome, result.block_reason) == ("blocked", "id_conflict")
    assert result.record_id is None
    assert env.store.commits == commits


async def test_a_create_that_loses_the_record_id_race_with_no_ledger_winner_is_id_conflict() -> (
    None
):
    env: KnowledgeEnv = await make_env()
    declared: str = "01JCKMNP000000000000000001"
    competitor: FakeImporterHarness = make_fake_importer(env)

    async def hook() -> None:
        await competitor.apply(record_id=declared, title="Other", body="Other text.")

    racer = make_fake_importer(env, uow_factory=racing_factory(env.store, hook))

    result = await racer.apply(record_id=declared, title="Ports", body="Text.")

    assert (result.outcome, result.block_reason) == ("blocked", "id_conflict")
    assert len(env.store.knowledge) == 1


async def test_a_create_that_loses_the_ledger_race_returns_the_winners_result_as_a_replay() -> None:
    env: KnowledgeEnv = await make_env()
    competitor: FakeImporterHarness = make_fake_importer(env)
    winner_ids: list[str | None] = []

    async def hook() -> None:
        winner_ids.append((await competitor.apply(title="Ports", body="Text.")).record_id)

    racer = make_fake_importer(env, uow_factory=racing_factory(env.store, hook))

    result = await racer.apply(title="Ports", body="Text.")

    assert (result.outcome, result.replayed, result.record_id) == ("created", True, winner_ids[0])
    assert len(env.store.knowledge) == 1


async def test_a_replay_after_a_lost_response_returns_created_replayed_and_changes_nothing() -> (
    None
):
    env, importer = await _setup()
    first = await importer.apply(title="Ports", body="Text.")
    blind = make_fake_importer(env, blind=True)  # the candidate read sees nothing
    commits: int = env.store.commits

    replay = await blind.apply(title="Ports", body="Text.")

    assert (replay.outcome, replay.replayed, replay.record_id) == ("created", True, first.record_id)
    assert env.store.commits == commits
    assert len(env.store.knowledge) == 1


class _FailingAppendRepository(IKnowledgeRepository):
    """Delegates to a real fake repository, but `append_revision` raises `error`."""

    def __init__(self, inner: IKnowledgeRepository, error: Exception) -> None:
        self._inner: IKnowledgeRepository = inner
        self._error: Exception = error

    async def add(self, knowledge: Knowledge) -> None:
        await self._inner.add(knowledge)

    async def get(self, record_id: RecordId, *, space_id: SpaceId) -> Knowledge | None:
        return await self._inner.get(record_id, space_id=space_id)

    async def get_for_update(self, record_id: RecordId, *, space_id: SpaceId) -> Knowledge | None:
        return await self._inner.get_for_update(record_id, space_id=space_id)

    async def append_revision(self, knowledge: Knowledge, revision: Revision) -> None:
        raise self._error


def _failing_append(env: KnowledgeEnv, error: Exception) -> Callable[[], FakeKnowledgeUnitOfWork]:
    class _Uow(FakeKnowledgeUnitOfWork):
        @property
        def knowledge(self) -> IKnowledgeRepository:
            return _FailingAppendRepository(super().knowledge, error)

    return lambda: _Uow(env.store)


@pytest.mark.parametrize("error_name", ["RevisionConflictError", "KnowledgeNotRevisableError"])
async def test_a_revise_that_conflicts_is_blocked_as_revision_conflict_with_no_ledger_entry(
    error_name: str,
) -> None:
    error: Exception = {
        "RevisionConflictError": RevisionConflictError("Revision 2 already exists."),
        "KnowledgeNotRevisableError": KnowledgeNotRevisableError("Not proposed."),
    }[error_name]
    env, importer = await _setup()
    await importer.apply(title="Ports", body="Original.")
    ledger_before: list[str] = importer.ledger_keys()
    failing = make_fake_importer(env, uow_factory=_failing_append(env, error))

    result = await failing.apply(title="Ports", body="Edited.")

    assert (result.outcome, result.block_reason) == ("blocked", "revision_conflict")
    assert importer.ledger_keys() == ledger_before


async def test_a_ledger_entry_with_another_fingerprint_under_the_revise_key_is_blocked() -> None:
    env, importer = await _setup()
    first = await importer.apply(title="Ports", body="Original.")
    assert first.record_id is not None
    key: str = (
        f"import/v1/revise/{first.record_id}/1/"
        f"{content_hash('Ports', 'Edited.', file_digest('Edited.'))}"
    )
    env.store.ledger[(_space_id(env), key)] = LedgerEntry(
        space_id=next(iter(env.store.spaces.values())).id,
        key=key,
        command="import_knowledge.revise",
        fingerprint="sha256:" + "0" * 64,
        recorded_at=NOW,
    )

    result = await importer.apply(title="Ports", body="Edited.")

    assert (result.outcome, result.block_reason) == ("blocked", "idempotency_key_reused")
    assert env.store.knowledge[first.record_id].head_number == 1


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        pytest.param(
            {"record_id": "not-a-ulid"}, "KNOWLEDGE_001_INVALID_RECORD_ID", id="record-id"
        ),
        pytest.param({"subtype": "Big Kind"}, "KNOWLEDGE_002_INVALID_SLUG", id="subtype"),
        pytest.param({"tags": ["bad tag"]}, "KNOWLEDGE_002_INVALID_SLUG", id="tag"),
        pytest.param({"origin_tag": "Origin Tag"}, "KNOWLEDGE_002_INVALID_SLUG", id="origin-tag"),
        pytest.param(
            {"source_digest": "sha256:short"}, "KNOWLEDGE_003_INVALID_CONTENT_HASH", id="digest"
        ),
        pytest.param({"project_key": "bad key"}, "KNOWLEDGE_004_INVALID_KEY", id="project-key"),
        pytest.param({"body": "   \n"}, "KNOWLEDGE_007_INVALID_RECORD", id="blank-body"),
        pytest.param({"title": " "}, "KNOWLEDGE_007_INVALID_RECORD", id="blank-title"),
    ],
)
@pytest.mark.parametrize("mode", ["apply", "assess"])
async def test_invalid_metadata_is_blocked_with_the_domain_code_and_nothing_is_written(
    overrides: dict[str, object], detail: str, mode: str
) -> None:
    env, importer = await _setup()
    commits: int = env.store.commits

    result: ImportKnowledgeOutcomeContract = await getattr(importer, mode)(**overrides)

    assert (result.outcome, result.block_reason, result.detail) == (
        "blocked",
        "invalid_metadata",
        detail,
    )
    assert env.store.commits == commits
    assert env.store.ledger == {} and env.store.knowledge == {}


async def test_a_secret_is_stored_masked_and_the_rerun_is_unchanged() -> None:
    env, importer = await _setup()
    body: str = "Example: api_key = abcdefghijklmnop1234"

    first = await importer.apply(title="Ports", body=body)
    again = await importer.apply(title="Ports", body=body)

    assert first.record_id is not None
    stored = env.store.knowledge[first.record_id].head.content
    assert isinstance(stored, GraphContent)
    assert stored.body == "Example: api_key = [REDACTED]"
    assert again.outcome == "unchanged"


async def test_a_secret_in_the_locator_is_masked_in_the_stored_source() -> None:
    env, importer = await _setup()
    locator: str = "https://x.y/?token=abcdefghijklmnop1234"

    result = await importer.apply(source_locator=locator, title="Ports", body="Text.")
    again = await importer.apply(source_locator=locator, title="Ports", body="Text.")

    assert result.outcome == "created" and again.outcome == "unchanged"
    assert all("abcdefghijklmnop1234" not in s.locator for s in env.store.sources.values())


async def test_stored_form_comparison_an_indented_first_line_and_trailing_spaces_are_unchanged() -> (
    None
):
    env, importer = await _setup()
    body: str = "  indented first line\nmiddle\nlast line   "

    first = await importer.apply(title="  Ports  ", body=body)
    again = await importer.apply(title="  Ports  ", body=body)

    assert first.outcome == "created" and again.outcome == "unchanged"
    assert first.record_id is not None
    stored = env.store.knowledge[first.record_id].head.content
    assert isinstance(stored, GraphContent)
    assert (stored.title, stored.body) == ("Ports", "indented first line\nmiddle\nlast line")


async def test_header_sources_become_sources_of_revision_one_and_a_rerun_adds_none() -> None:
    env, importer = await _setup()
    sources = [
        {"kind": "agent_session", "locator": "s-1"},
        {"kind": "url", "locator": "https://x.y/z"},
    ]

    first = await importer.apply(title="Ports", body="Text.", header_sources=sources)
    count: int = len(env.store.sources)
    again = await importer.apply(title="Ports", body="Text.", header_sources=sources)

    assert first.record_id is not None
    kinds = [s.kind for s in _sources(env, env.store.knowledge[first.record_id])]
    assert kinds == [SourceKindEnum.FILE_VERSION, SourceKindEnum.AGENT_SESSION, SourceKindEnum.URL]
    assert again.outcome == "unchanged" and len(env.store.sources) == count


async def test_a_revision_after_an_edit_cites_the_file_and_the_header_sources_again() -> None:
    env, importer = await _setup()
    sources = [{"kind": "agent_session", "locator": "s-1"}]
    first = await importer.apply(title="Ports", body="Text.", header_sources=sources)
    assert first.record_id is not None

    await importer.apply(title="Ports", body="Edited.", header_sources=sources)

    head = env.store.knowledge[first.record_id].head
    cited = [
        (env.store.sources[i.value].kind, env.store.sources[i.value].locator)
        for i in head.source_ids
    ]
    assert head.number == 2
    assert cited == [
        (SourceKindEnum.FILE_VERSION, LOCATOR),
        (SourceKindEnum.AGENT_SESSION, "s-1"),
    ]


async def test_a_store_that_was_not_initialised_raises_and_is_not_blocked() -> None:
    env: KnowledgeEnv = await make_env(initialised=False)
    importer = make_fake_importer(env)

    with pytest.raises(StoreNotInitialisedError):
        await importer.apply()
    with pytest.raises(StoreNotInitialisedError):
        await importer.assess()


async def test_an_unknown_space_raises_and_is_not_blocked() -> None:
    _, importer = await _setup()

    with pytest.raises(SpaceNotFoundError):
        await importer.apply(space_key="ghost")
    with pytest.raises(SpaceNotFoundError):
        await importer.assess(space_key="ghost")


async def test_assess_predicts_a_create_without_writing_anything() -> None:
    env, importer = await _setup()

    planned = await importer.assess(title="Ports", body="Text.", project_key="alpha")
    declared = await importer.assess(
        record_id="01JCKMNP000000000000000001", title="Ports", body="Text."
    )

    assert (planned.outcome, planned.record_id, planned.revision) == ("created", None, 1)
    assert (declared.outcome, declared.record_id) == ("created", "01JCKMNP000000000000000001")
    assert env.store.knowledge == {} and env.store.sources == {} and env.store.projects == {}
    assert env.store.ledger == {}


async def test_assess_reports_what_apply_would_do_for_an_existing_record() -> None:
    env, importer = await _setup()
    first = await importer.apply(title="Ports", body="Text.")
    commits: int = env.store.commits

    same = await importer.assess(title="Ports", body="Text.")
    reported = await importer.assess(title="Ports", body="Edited.", on_change="report")
    updated = await importer.assess(title="Ports", body="Edited.", on_change="update")

    assert (same.outcome, same.record_id, same.revision, same.status) == (
        "unchanged",
        first.record_id,
        1,
        "proposed",
    )
    assert (reported.outcome, reported.record_id, reported.revision) == (
        "changed",
        first.record_id,
        1,
    )
    assert (updated.outcome, updated.record_id, updated.revision) == ("revised", first.record_id, 2)
    assert env.store.commits == commits


async def test_assess_of_an_accepted_target_follows_whether_a_proposer_is_bound() -> None:
    env, plain = await _setup()
    first = await plain.apply(title="Ports", body="Text.")
    assert first.record_id is not None
    plain.set_status(first.record_id, RecordStatusEnum.ACCEPTED)
    linked = make_fake_importer(env, proposer=FakeSupersessionProposer())

    reduced = await plain.assess(title="Ports", body="Edited.")
    with_c4 = await linked.assess(title="Ports", body="Edited.")

    assert (reduced.outcome, reduced.record_id, reduced.target_record_id) == (
        "created",
        None,
        first.record_id,
    )
    assert reduced.reason == "assertions unavailable: target not linked"
    assert (with_c4.outcome, with_c4.target_record_id, with_c4.assertion_id) == (
        "successor_proposed",
        first.record_id,
        None,
    )


async def test_assess_blocks_a_closed_target_and_an_id_conflict() -> None:
    env, importer = await _setup()
    first = await importer.apply(title="Ports", body="Text.")
    assert first.record_id is not None
    importer.set_status(first.record_id, RecordStatusEnum.RETRACTED)
    experience = await env.capture_experience.handle(experience_command())

    closed = await importer.assess(title="Ports", body="Edited.")
    conflict = await importer.assess(record_id=experience.record_id, title="X", body="Y.")

    assert (closed.outcome, closed.block_reason) == ("blocked", "target_closed")
    assert (conflict.outcome, conflict.block_reason) == ("blocked", "id_conflict")
