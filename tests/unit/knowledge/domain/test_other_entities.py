"""Experience, Source, Project, KnowledgeSpace, Assertion, CatalogEntry (FR-007..FR-009, AC-008)."""

import inspect

import pytest
from tests.support.knowledge_support import AGENT, NOW

from noesis.bounded_context.knowledge.domain.entities import (
    Assertion,
    CatalogEntry,
    Experience,
    KnowledgeSpace,
    Project,
    Source,
)
from noesis.bounded_context.knowledge.domain.events import (
    AssertionProposed,
    CatalogEntryRegistered,
    ExperienceRecorded,
    KnowledgeSpaceCreated,
    ProjectRegistered,
    SourceRecorded,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Applicability,
    AssertionPredicateEnum,
    CatalogEntryKindEnum,
    ContentHash,
    ExperienceSubtypeEnum,
    Key,
    RecordId,
    RecordStatusEnum,
    SourceKindEnum,
    SpaceId,
)
from noesis.exceptions import ExperienceWithoutSourceError, InvalidRecordError

pytestmark = pytest.mark.unit


def rid(n: int) -> RecordId:
    return RecordId(value=f"{n:026d}")


SPACE: SpaceId = SpaceId(value=f"{99:026d}")


def make_experience(**overrides: object) -> Experience:
    values: dict[str, object] = {
        "id": rid(1),
        "space_id": SPACE,
        "subtype": ExperienceSubtypeEnum.FAILURE,
        "body": "it broke",
        "occurred_at": NOW,
        "actor": AGENT,
        "source_ids": (rid(2),),
        "now": NOW,
    }
    return Experience.create(**{**values, **overrides})  # type: ignore[arg-type]


def test_experience_create_records_event_and_dedupes_sources() -> None:
    experience: Experience = make_experience(source_ids=(rid(2), rid(3), rid(2)), session="s")

    assert experience.source_ids == (rid(2), rid(3))
    assert experience.session == "s"
    assert experience.project_id is None
    events = experience.collect_events()
    assert [type(e) for e in events] == [ExperienceRecorded]
    assert events[0].subtype is ExperienceSubtypeEnum.FAILURE  # type: ignore[attr-defined]


def test_experience_without_source_raises_typed_error() -> None:
    with pytest.raises(ExperienceWithoutSourceError) as error:
        make_experience(source_ids=())
    assert error.value.error_code == "KNOWLEDGE_006_EXPERIENCE_WITHOUT_SOURCE"
    assert error.value.next_steps


def test_experience_rejects_blank_body() -> None:
    with pytest.raises(InvalidRecordError):
        make_experience(body="  ")


def test_experience_exposes_no_mutating_method() -> None:
    """AC-008: write-once, so the only public callable on the aggregate is `create`."""
    callables: set[str] = {
        name
        for name, member in inspect.getmembers(Experience)
        if not name.startswith("_") and callable(member)
    }

    forbidden: set[str] = {
        n for n in callables if n.startswith(("revise", "update", "set_", "change", "edit"))
    }
    assert forbidden == set()
    assert "status" not in set(Experience.__dataclass_fields__)
    assert "head" not in Experience.__dataclass_fields__


def test_source_is_created_observed_now_with_natural_key() -> None:
    digest: ContentHash = ContentHash.of(b"v1")

    source: Source = Source.create(
        id=rid(1),
        space_id=SPACE,
        kind=SourceKindEnum.FILE_VERSION,
        locator="  vault://v/a.md ",
        digest=digest,
        now=NOW,
    )

    assert source.locator == "vault://v/a.md"
    assert source.observed_at == NOW
    assert source.natural_key == (SPACE, SourceKindEnum.FILE_VERSION, "vault://v/a.md", digest)
    assert [type(e) for e in source.collect_events()] == [SourceRecorded]


def test_source_natural_key_differs_by_digest_kind_and_space() -> None:
    def make(**overrides: object) -> Source:
        values: dict[str, object] = {
            "id": rid(1),
            "space_id": SPACE,
            "kind": SourceKindEnum.URL,
            "locator": "https://x",
            "now": NOW,
        }
        return Source.create(**{**values, **overrides})  # type: ignore[arg-type]

    base = make().natural_key
    assert make(id=rid(9)).natural_key == base
    assert make(digest=ContentHash.of(b"a")).natural_key != base
    assert make(kind=SourceKindEnum.COMMIT).natural_key != base
    assert make(space_id=SpaceId(value=rid(5).value)).natural_key != base


def test_source_rejects_blank_locator_and_is_write_once() -> None:
    with pytest.raises(InvalidRecordError, match="locator"):
        Source.create(id=rid(1), space_id=SPACE, kind=SourceKindEnum.URL, locator="  ", now=NOW)
    callables: set[str] = {
        n for n, m in inspect.getmembers(Source) if not n.startswith("_") and callable(m)
    }
    assert not {n for n in callables if n.startswith(("revise", "update", "set_"))}


def test_project_create_trims_name_and_records_event() -> None:
    project: Project = Project.create(
        id=rid(1), space_id=SPACE, key=Key(value="noesis"), name=" Noesis ", now=NOW
    )

    assert project.name == "Noesis"
    events = project.collect_events()
    assert [type(e) for e in events] == [ProjectRegistered]
    assert events[0].key == Key(value="noesis")  # type: ignore[attr-defined]
    with pytest.raises(InvalidRecordError):
        Project.create(id=rid(1), space_id=SPACE, key=Key(value="x"), name=" ", now=NOW)


def test_knowledge_space_create_records_event_and_rejects_blank_name() -> None:
    space: KnowledgeSpace = KnowledgeSpace.create(
        id=SPACE, key=Key(value="default"), name="Default", now=NOW
    )

    assert space.key.value == "default"
    assert [type(e) for e in space.collect_events()] == [KnowledgeSpaceCreated]
    with pytest.raises(InvalidRecordError):
        KnowledgeSpace.create(id=SPACE, key=Key(value="x"), name="", now=NOW)


def test_assertion_is_proposed_and_requires_a_source() -> None:
    values: dict[str, object] = {
        "id": rid(1),
        "space_id": SPACE,
        "predicate": AssertionPredicateEnum.SUPPORTS,
        "subject_id": rid(2),
        "object_id": rid(3),
        "evidence_ids": (rid(4), rid(4)),
        "rationale": "because",
        "actor": AGENT,
        "applicability": Applicability(),
        "source_ids": (rid(5),),
        "now": NOW,
    }

    assertion: Assertion = Assertion.create(**values)  # type: ignore[arg-type]

    assert assertion.status is RecordStatusEnum.PROPOSED
    assert assertion.evidence_ids == (rid(4),)
    assert [type(e) for e in assertion.collect_events()] == [AssertionProposed]
    with pytest.raises(InvalidRecordError, match="at least one source"):
        Assertion.create(**{**values, "source_ids": ()})  # type: ignore[arg-type]


def test_assertion_statement_has_no_mutator() -> None:
    callables: set[str] = {
        n for n, m in inspect.getmembers(Assertion) if not n.startswith("_") and callable(m)
    }
    assert not {n for n in callables if n.startswith(("revise", "update", "set_", "change"))}


def test_catalog_kinds_are_exactly_the_four_capabilities() -> None:
    assert {kind.value for kind in CatalogEntryKindEnum} == {
        "skill",
        "agent",
        "cli_tool",
        "mcp_server",
    }


def test_catalog_entry_has_first_revision_and_no_status() -> None:
    entry: CatalogEntry = CatalogEntry.create(
        id=rid(1),
        space_id=SPACE,
        kind=CatalogEntryKindEnum.CLI_TOOL,
        name=" vectra ",
        purpose=" search ",
        version="1.0",
        prerequisites=("node",),
        location="/usr/bin/vectra",
        now=NOW,
    )

    assert entry.name == "vectra"
    assert [r.number for r in entry.revisions] == [1]
    assert entry.revisions[0].purpose == "search"
    assert entry.revisions[0].prerequisites == ("node",)
    assert "status" not in CatalogEntry.__dataclass_fields__
    assert [type(e) for e in entry.collect_events()] == [CatalogEntryRegistered]


@pytest.mark.parametrize(("name", "purpose"), [("", "p"), ("n", " "), (" ", " ")])
def test_catalog_entry_requires_name_and_purpose(name: str, purpose: str) -> None:
    with pytest.raises(InvalidRecordError):
        CatalogEntry.create(
            id=rid(1),
            space_id=SPACE,
            kind=CatalogEntryKindEnum.SKILL,
            name=name,
            purpose=purpose,
            now=NOW,
        )
