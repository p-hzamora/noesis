"""Typed relations inside the LinkSet aggregate, its digest and the importer adapter (D-001..D-003)."""

from dataclasses import replace

import pytest
from pydantic import ValidationError
from tests.support.knowledge_support import NOW
from tests.unit.knowledge.application.test_link_sets import setup_links

from noesis.bounded_context.knowledge.application.handlers.commands.replace_link_set_handler import (
    ReplaceLinkSetHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.assess_link_set_handler import (
    AssessLinkSetHandler,
)
from noesis.bounded_context.knowledge.domain.entities.link_set import LinkSet
from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    RecordId,
    RecordRelationEnum,
    SpaceId,
)
from noesis.bounded_context.knowledge.domain.value_objects.link_set_digest import LinkSetDigest
from noesis.bounded_context.knowledge.domain.value_objects.record_link import RecordLink
from noesis.bounded_context.knowledge.domain.value_objects.record_relation import RecordRelation
from noesis.bounded_context.knowledge.infrastructure.inbound.import_contracts import (
    knowledge_importer_adapter,
)
from noesis.exceptions import InvalidRecordError
from noesis.shared_kernel.contracts.knowledge import (
    ImportActorContract,
    ImportLinkSetRequestContract,
    ImportRelationContract,
)

pytestmark = pytest.mark.unit

SOURCE = RecordId(value="01JCKMNP000000000000000001")
TARGET = RecordId(value="01JCKMNP000000000000000002")
LINK = RecordLink(target_record_id=TARGET, link_type="links_to", count=1, anchors=("Z", "A"))
SPACE = SpaceId(value="01JCKMNP000000000000009998")


def relation(word: RecordRelationEnum, target: RecordId = TARGET) -> RecordRelation:
    return RecordRelation(target_record_id=target, relation=word)


def test_the_vocabulary_is_the_eight_vault_words_and_a_separate_type_from_assertion_predicates() -> (
    None
):
    assert {member.value for member in RecordRelationEnum} == {
        "refines",
        "part_of",
        "contains",
        "implements",
        "consumes",
        "extends",
        "contradicts",
        "supersedes",
    }
    assert not issubclass(RecordRelationEnum, AssertionPredicateEnum)
    assert RecordRelationEnum.CONTRADICTS.value == AssertionPredicateEnum.CONTRADICTS.value


def test_a_digest_without_relations_equals_the_value_computed_before_relations_existed() -> None:
    # Fixed values of the pre-change formula (base branch 33b4e88), computed independently.
    assert (
        LinkSetDigest.of([LINK], "migrated").value
        == "sha256:69af71cd81ed177b7367e81b1a127c317b3fa2416db3343852f4571fa1b405b6"
    )
    assert (
        LinkSetDigest.of([], "migrated").value
        == "sha256:3c07c8d97a5c29106ee51dc29321eae9887d5323b6a5d3f5443aa4c04aa373de"
    )
    assert LinkSetDigest.of([LINK], "migrated", ()) == LinkSetDigest.of([LINK], "migrated")


def test_relations_change_the_digest_and_their_order_does_not() -> None:
    refines, part_of = relation(RecordRelationEnum.REFINES), relation(RecordRelationEnum.PART_OF)
    base = LinkSetDigest.of([LINK], "migrated")
    assert LinkSetDigest.of([LINK], "migrated", [refines]) != base
    assert LinkSetDigest.of([LINK], "migrated", [refines]) != LinkSetDigest.of(
        [LINK], "migrated", [part_of]
    )
    assert LinkSetDigest.of([], "migrated", [refines, part_of]) == LinkSetDigest.of(
        [], "migrated", [part_of, refines]
    )


def test_link_set_invariants_with_relations() -> None:
    refines = relation(RecordRelationEnum.REFINES)
    item = LinkSet.create(
        source_record_id=SOURCE,
        space_id=SPACE,
        origin="migrated",
        version=1,
        links=frozenset({LINK}),
        relations=frozenset({refines}),
        now=NOW,
    )
    assert item.digest == LinkSetDigest.of([LINK], "migrated", [refines])
    with pytest.raises(InvalidRecordError):
        replace(item, relations=frozenset({relation(RecordRelationEnum.REFINES, SOURCE)}))
    with pytest.raises(InvalidRecordError):
        replace(item, relations=frozenset())
    with pytest.raises(ValidationError):
        RecordRelation(target_record_id=TARGET, relation="friends_with")  # type: ignore[arg-type]
    # A relation and a wiki link to the same target coexist.
    assert {link.target_record_id for link in item.links} == {
        r.target_record_id for r in item.relations
    }


def test_a_link_set_without_relations_keeps_its_old_shape() -> None:
    item = LinkSet.create(
        source_record_id=SOURCE,
        space_id=SPACE,
        origin="migrated",
        version=1,
        links=frozenset({LINK}),
        now=NOW,
    )
    assert item.relations == frozenset()
    assert item.digest.value.endswith("405b6")


async def test_replace_with_relations_only_creates_replaces_and_reports_unchanged() -> None:
    env, factory, request, stored, _ = await setup_links()
    write = ReplaceLinkSetHandler(uow_factory=factory, clock=env.clock)
    read = AssessLinkSetHandler(uow_factory=factory, clock=env.clock)
    target = request.links[0].target_record_id
    only = request.model_copy(
        update={"links": (), "relations": (relation(RecordRelationEnum.REFINES, target),)}
    )
    assert (await read.handle(only)).outcome == "created"
    assert not stored
    result = await write.handle(only)
    assert (result.outcome, result.edges) == ("created", 1)
    assert next(iter(stored.values())).relations == frozenset(only.relations)
    assert (await write.handle(only)).outcome == "unchanged"
    other = only.model_copy(
        update={"relations": (relation(RecordRelationEnum.SUPERSEDES, target),)}
    )
    assert (await write.handle(other)).outcome == "replaced"
    assert next(iter(stored.values())).version == 2
    assert (await write.handle(request)).outcome == "replaced"
    assert next(iter(stored.values())).relations == frozenset()


async def test_a_relation_target_outside_the_space_blocks_the_whole_set() -> None:
    env, factory, request, stored, _ = await setup_links()
    missing = RecordId(value="01JCKMNP000000000000009999")
    blocked = request.model_copy(
        update={"relations": (relation(RecordRelationEnum.REFINES, missing),)}
    )
    result = await ReplaceLinkSetHandler(uow_factory=factory, clock=env.clock).handle(blocked)
    assert result.block_reason == "target_not_in_space"
    assert not stored


def contract(**changes) -> ImportLinkSetRequestContract:
    values = {
        "space_key": "personal",
        "source_record_id": SOURCE.value,
        "origin_tag": "origin:migrated",
        "links": (),
        "actor": ImportActorContract(kind="user", name="tester"),
        "relations": (ImportRelationContract(target_record_id=TARGET.value, relation="refines"),),
    }
    return ImportLinkSetRequestContract(**(values | changes))


def test_the_request_contract_is_version_2_and_rejects_version_1() -> None:
    assert contract().contract_version == 2
    assert contract(relations=()).relations == ()
    with pytest.raises(ValidationError):
        contract(contract_version=1)


def test_the_adapter_turns_relation_words_into_the_knowledge_enum() -> None:
    request = knowledge_importer_adapter._link_request(contract())
    assert request.relations == (relation(RecordRelationEnum.REFINES),)


def test_an_unknown_relation_word_is_a_typed_error_not_a_bare_value_error() -> None:
    bad = contract(
        relations=(ImportRelationContract(target_record_id=TARGET.value, relation="friends"),)
    )
    with pytest.raises(InvalidRecordError):
        knowledge_importer_adapter._link_request(bad)
