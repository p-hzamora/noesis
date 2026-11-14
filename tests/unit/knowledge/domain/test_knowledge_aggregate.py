"""The Knowledge aggregate: creation, revision and its invariants (FR-004..FR-006, AC-007, AC-009)."""

from datetime import timedelta

import pytest
from tests.support.knowledge_support import AGENT, NOW

from noesis.bounded_context.knowledge.domain.entities import Knowledge
from noesis.bounded_context.knowledge.domain.events import KnowledgeProposed, KnowledgeRevised
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ActorKindEnum,
    Applicability,
    ContentHash,
    FileContent,
    GraphContent,
    OwnershipEnum,
    RecordId,
    RecordStatusEnum,
    Revision,
    Slug,
    SpaceId,
)
from noesis.exceptions import (
    InvalidRecordError,
    KnowledgeNotRevisableError,
    RevisionConflictError,
)

pytestmark = pytest.mark.unit

ID: RecordId = RecordId(value="0" * 25 + "1")
SPACE: SpaceId = SpaceId(value="0" * 25 + "2")
SRC_A: RecordId = RecordId(value="0" * 25 + "3")
SRC_B: RecordId = RecordId(value="0" * 25 + "4")
USER: Actor = Actor(kind=ActorKindEnum.USER, name="pablo")
LATER = NOW + timedelta(minutes=5)


def graph(title: str = "T", body: str = "B") -> GraphContent:
    return GraphContent(title=title, body=body)


def file_content() -> FileContent:
    return FileContent(
        content_hash=ContentHash.of(b"x"), file_version_source_id=SRC_A, title="From file"
    )


def make(
    ownership: OwnershipEnum = OwnershipEnum.GRAPH,
    content: GraphContent | FileContent | None = None,
    sources: tuple[RecordId, ...] = (SRC_A,),
) -> Knowledge:
    return Knowledge.create(
        id=ID,
        space_id=SPACE,
        ownership=ownership,
        subtype=Slug(value="decision"),
        applicability=Applicability(),
        actor=AGENT,
        source_ids=sources,
        content=content or graph(),
        now=NOW,
    )


def test_create_is_proposed_revision_one_with_proposed_event() -> None:
    knowledge: Knowledge = make()

    assert knowledge.status is RecordStatusEnum.PROPOSED
    assert knowledge.head_number == 1
    assert knowledge.head.actor == AGENT
    assert knowledge.head.created_at == NOW
    assert knowledge.created_at == knowledge.updated_at == NOW
    events = knowledge.collect_events()
    assert len(events) == 1
    assert isinstance(events[0], KnowledgeProposed)
    assert (events[0].aggregate_id, events[0].space_id, events[0].revision) == (
        ID.value,
        SPACE.value,
        1,
    )
    assert events[0].ownership is OwnershipEnum.GRAPH
    assert knowledge.collect_events() == []


def test_create_deduplicates_sources_keeping_order() -> None:
    knowledge: Knowledge = make(sources=(SRC_B, SRC_A, SRC_B))

    assert knowledge.head.source_ids == (SRC_B, SRC_A)


def test_create_requires_at_least_one_source() -> None:
    with pytest.raises(InvalidRecordError, match="at least one source"):
        make(sources=())


@pytest.mark.parametrize(
    ("ownership", "content"),
    [
        (OwnershipEnum.GRAPH, file_content()),
        (OwnershipEnum.FILE, graph()),
    ],
)
def test_create_rejects_content_shape_not_matching_ownership(
    ownership: OwnershipEnum, content: GraphContent | FileContent
) -> None:
    with pytest.raises(InvalidRecordError, match="owned revision needs"):
        make(ownership=ownership, content=content)


@pytest.mark.parametrize("field", ["title", "body"])
def test_graph_content_rejects_blank_text(field: str) -> None:
    values: dict[str, str] = {"title": "T", "body": "B", field: "   "}
    with pytest.raises(InvalidRecordError):
        GraphContent(**values)


def test_revise_appends_n_plus_one_and_records_event() -> None:
    knowledge: Knowledge = make()
    knowledge.collect_events()

    revision: Revision = knowledge.revise(
        expected_revision=1,
        actor=USER,
        source_ids=(SRC_B,),
        content=graph("T2", "B2"),
        now=LATER,
    )

    assert revision.number == 2
    assert knowledge.head is revision
    assert knowledge.head_number == 2
    assert knowledge.head.actor == USER
    assert knowledge.head.source_ids == (SRC_B,)
    assert knowledge.updated_at == LATER
    assert knowledge.created_at == NOW
    assert knowledge.status is RecordStatusEnum.PROPOSED
    events = knowledge.collect_events()
    assert [type(e) for e in events] == [KnowledgeRevised]
    assert events[0].revision == 2  # type: ignore[attr-defined]


def test_revise_numbers_are_gap_free_over_several_revisions() -> None:
    knowledge: Knowledge = make()
    for expected in (1, 2, 3):
        revision = knowledge.revise(
            expected_revision=expected,
            actor=AGENT,
            source_ids=(SRC_A,),
            content=graph(body=f"v{expected}"),
            now=LATER,
        )
        assert revision.number == expected + 1


@pytest.mark.parametrize("expected", [0, 2, 7])
def test_revise_with_stale_expected_revision_conflicts_with_metadata(expected: int) -> None:
    knowledge: Knowledge = make()

    with pytest.raises(RevisionConflictError) as error:
        knowledge.revise(
            expected_revision=expected,
            actor=AGENT,
            source_ids=(SRC_A,),
            content=graph("T2"),
            now=LATER,
        )

    assert error.value.error_code == "KNOWLEDGE_202_REVISION_CONFLICT"
    assert error.value.metadata == {
        "record_id": ID.value,
        "expected_revision": expected,
        "actual_revision": 1,
    }
    assert knowledge.head_number == 1
    assert knowledge.collect_events()[0].__class__ is KnowledgeProposed


@pytest.mark.parametrize(
    "status",
    [RecordStatusEnum.ACCEPTED, RecordStatusEnum.SUPERSEDED, RecordStatusEnum.RETRACTED],
)
def test_revise_of_non_proposed_raises_typed_error_and_adds_no_revision(
    status: RecordStatusEnum,
) -> None:
    """AC-007: the status is checked before the head, so even a stale revision reports closed."""
    knowledge: Knowledge = make()
    knowledge.status = status
    knowledge.collect_events()

    with pytest.raises(KnowledgeNotRevisableError) as error:
        knowledge.revise(
            expected_revision=99, actor=AGENT, source_ids=(SRC_A,), content=graph("T2"), now=LATER
        )

    assert error.value.error_code == "KNOWLEDGE_005_KNOWLEDGE_NOT_REVISABLE"
    assert error.value.metadata["status"] == status.value
    assert knowledge.head_number == 1
    assert knowledge.collect_events() == []


def test_revise_requires_at_least_one_source() -> None:
    knowledge: Knowledge = make()

    with pytest.raises(InvalidRecordError, match="at least one source"):
        knowledge.revise(
            expected_revision=1, actor=AGENT, source_ids=(), content=graph("T2"), now=LATER
        )


def test_file_owned_revision_has_hash_source_and_title_but_no_editable_text() -> None:
    """AC-009 (domain shape)."""
    knowledge: Knowledge = make(ownership=OwnershipEnum.FILE, content=file_content())

    content = knowledge.head.content
    assert isinstance(content, FileContent)
    assert content.content_hash == ContentHash.of(b"x")
    assert content.file_version_source_id == SRC_A
    assert content.title == "From file"
    assert not hasattr(content, "body")
    assert not hasattr(content, "text")
    assert set(FileContent.model_fields) == {"content_hash", "file_version_source_id", "title"}


def test_file_owned_revision_must_cite_its_file_version_source() -> None:
    with pytest.raises(InvalidRecordError, match="file_version"):
        make(ownership=OwnershipEnum.FILE, content=file_content(), sources=(SRC_B,))


def test_file_owned_revise_is_rejected_even_when_proposed() -> None:
    knowledge: Knowledge = make(ownership=OwnershipEnum.FILE, content=file_content())

    with pytest.raises(InvalidRecordError, match="File-owned knowledge has no editable text"):
        knowledge.revise(
            expected_revision=1, actor=AGENT, source_ids=(SRC_A,), content=graph(), now=LATER
        )

    assert knowledge.head_number == 1


def test_revision_number_must_be_positive_and_needs_an_actor() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        Revision(number=0, actor=AGENT, source_ids=(SRC_A,), created_at=NOW, content=graph())
    with pytest.raises(ValueError, match="actor"):
        Revision(number=1, source_ids=(SRC_A,), created_at=NOW, content=graph())  # type: ignore[call-arg]


def test_ownership_and_space_have_no_mutator() -> None:
    """Ownership is fixed: the only public mutator is `revise`, which cannot change it."""
    public: set[str] = {n for n in dir(Knowledge) if not n.startswith("_")}

    mutators: set[str] = {n for n in public if n.startswith(("set_", "change_", "update_"))}
    assert mutators == set()
    knowledge: Knowledge = make()
    knowledge.revise(
        expected_revision=1, actor=AGENT, source_ids=(SRC_A,), content=graph("T2"), now=LATER
    )
    assert knowledge.ownership is OwnershipEnum.GRAPH
    assert knowledge.space_id == SPACE
