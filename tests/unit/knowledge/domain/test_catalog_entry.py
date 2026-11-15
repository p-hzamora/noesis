"""The CatalogEntry aggregate: create, revise, conflicts, prerequisites (FR-001, AC-009)."""

import pytest
from tests.support.knowledge_support import AGENT, NOW

from noesis.bounded_context.knowledge.domain.entities import CatalogEntry
from noesis.bounded_context.knowledge.domain.events import (
    CatalogEntryRegistered,
    CatalogEntryRevised,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ActorKindEnum,
    CatalogEntryKindEnum,
    CatalogRevision,
    RecordId,
    SpaceId,
)
from noesis.bounded_context.knowledge.domain.value_objects.catalog_ref import CatalogRef
from noesis.exceptions import (
    InvalidCatalogNameError,
    InvalidCatalogPrerequisiteError,
    InvalidRecordError,
    RevisionConflictError,
)

pytestmark = pytest.mark.unit

SPACE: SpaceId = SpaceId(value=f"{99:026d}")
SOURCE: RecordId = RecordId(value=f"{2:026d}")
OTHER_ACTOR: Actor = Actor(kind=ActorKindEnum.USER, name="pablo")


def make_entry(**overrides: object) -> CatalogEntry:
    values: dict[str, object] = {
        "id": RecordId(value=f"{1:026d}"),
        "space_id": SPACE,
        "kind": CatalogEntryKindEnum.CLI_TOOL,
        "name": "gh",
        "purpose": "GitHub CLI",
        "version": "2.0.0",
        "prerequisites": (CatalogRef.parse("cli_tool:git"),),
        "location": "https://github.com/cli/cli",
        "actor": AGENT,
        "source_ids": (SOURCE,),
        "now": NOW,
    }
    return CatalogEntry.create(**{**values, **overrides})  # type: ignore[arg-type]


def revise(entry: CatalogEntry, **overrides: object) -> CatalogRevision:
    values: dict[str, object] = {
        "expected_revision": entry.head_number,
        "purpose": "GitHub CLI v2",
        "version": "2.1.0",
        "prerequisites": (),
        "location": "https://github.com/cli/cli",
        "actor": OTHER_ACTOR,
        "source_ids": (SOURCE,),
        "now": NOW,
    }
    return entry.revise(**{**values, **overrides})  # type: ignore[arg-type]


def test_create_builds_revision_one_with_every_envelope_field() -> None:
    entry: CatalogEntry = make_entry()

    assert [r.number for r in entry.revisions] == [1]
    assert entry.head is entry.revisions[0]
    assert entry.head_number == 1
    head: CatalogRevision = entry.head
    assert (head.purpose, head.version, head.location) == (
        "GitHub CLI",
        "2.0.0",
        "https://github.com/cli/cli",
    )
    assert head.prerequisites == (CatalogRef.parse("cli_tool:git"),)
    assert (head.actor, head.source_ids, head.created_at) == (AGENT, (SOURCE,), NOW)
    assert "status" not in CatalogEntry.__dataclass_fields__


def test_catalog_key_is_space_kind_and_name_as_typed() -> None:
    entry: CatalogEntry = make_entry(name="Gh")

    assert entry.catalog_key == f"{SPACE.value}:cli_tool:Gh"


def test_create_records_the_registered_event() -> None:
    events = make_entry().collect_events()

    assert [type(e) for e in events] == [CatalogEntryRegistered]
    assert events[0].kind is CatalogEntryKindEnum.CLI_TOOL  # type: ignore[attr-defined]


@pytest.mark.parametrize("name", ["", "-x", "Bad Name!", "a" * 129])
def test_create_rejects_a_name_outside_the_grammar(name: str) -> None:
    with pytest.raises(InvalidCatalogNameError):
        make_entry(name=name)


def test_create_rejects_a_self_prerequisite() -> None:
    with pytest.raises(InvalidCatalogPrerequisiteError) as error:
        make_entry(prerequisites=(CatalogRef.parse("cli_tool:gh"),))

    assert error.value.error_code == "KNOWLEDGE_062_INVALID_CATALOG_PREREQUISITE"


def test_a_prerequisite_may_share_the_name_when_the_kind_differs_or_name_is_not_cataloged() -> None:
    entry: CatalogEntry = make_entry(
        prerequisites=(CatalogRef.parse("skill:gh"), CatalogRef.parse("cli_tool:never-registered"))
    )

    assert len(entry.head.prerequisites) == 2


def test_create_requires_a_source() -> None:
    with pytest.raises(InvalidRecordError):
        make_entry(source_ids=())


def test_revise_appends_the_next_gap_free_revision_and_records_the_event() -> None:
    entry: CatalogEntry = make_entry()
    entry.collect_events()

    revision: CatalogRevision = revise(entry)

    assert revision.number == 2
    assert [r.number for r in entry.revisions] == [1, 2]
    assert entry.head is revision
    assert (revision.purpose, revision.version, revision.prerequisites) == (
        "GitHub CLI v2",
        "2.1.0",
        (),
    )
    assert revision.actor == OTHER_ACTOR
    assert entry.revisions[0].purpose == "GitHub CLI"
    events = entry.collect_events()
    assert [type(e) for e in events] == [CatalogEntryRevised]
    assert events[0].revision == 2  # type: ignore[attr-defined]


def test_revise_with_a_stale_head_conflicts_and_appends_nothing() -> None:
    """AC-009 (unit): `revise(expected_head=0)` on an entry at revision 1."""
    entry: CatalogEntry = make_entry()

    with pytest.raises(RevisionConflictError) as error:
        revise(entry, expected_revision=0)

    assert error.value.error_code == "KNOWLEDGE_202_REVISION_CONFLICT"
    assert error.value.metadata == {
        "record_id": entry.id.value,
        "expected_revision": 0,
        "actual_revision": 1,
    }
    assert error.value.next_steps
    assert [r.number for r in entry.revisions] == [1]


def test_revise_with_a_future_head_also_conflicts() -> None:
    entry: CatalogEntry = make_entry()

    with pytest.raises(RevisionConflictError):
        revise(entry, expected_revision=2)


def test_revise_rejects_a_self_prerequisite_and_appends_nothing() -> None:
    entry: CatalogEntry = make_entry()

    with pytest.raises(InvalidCatalogPrerequisiteError):
        revise(entry, prerequisites=(CatalogRef.parse("cli_tool:gh"),))

    assert [r.number for r in entry.revisions] == [1]


def test_revise_with_unchanged_content_still_appends_because_no_op_is_the_handlers_decision() -> (
    None
):
    entry: CatalogEntry = make_entry()
    head: CatalogRevision = entry.head

    revision: CatalogRevision = revise(
        entry,
        purpose=head.purpose,
        version=head.version,
        prerequisites=head.prerequisites,
        location=head.location,
    )

    assert revision.number == 2
    assert revision.content_equals(head)


def test_head_has_content_compares_without_mutating_the_aggregate() -> None:
    entry: CatalogEntry = make_entry()
    entry.collect_events()
    head: CatalogRevision = entry.head

    same: bool = entry.head_has_content(
        purpose=f"  {head.purpose} ",
        version=head.version,
        prerequisites=head.prerequisites,
        location=head.location,
    )
    different: bool = entry.head_has_content(
        purpose="Other",
        version=head.version,
        prerequisites=head.prerequisites,
        location=head.location,
    )

    assert (same, different) == (True, False)
    assert [r.number for r in entry.revisions] == [1]
    assert entry.pending_events == []
