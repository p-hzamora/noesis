"""Which `related` entries are well-formed relations with a known vocabulary word (AC-009)."""

import pytest

from noesis.bounded_context.interop.domain.services.relation_rule import (
    RELATION_WORDS,
    RelationRule,
)
from noesis.bounded_context.interop.domain.value_objects.vault_relation import (
    RawRelation,
    RejectedRelation,
)

pytestmark = pytest.mark.unit


def test_the_vocabulary_is_the_eight_vault_words() -> None:
    assert {
        "refines",
        "part_of",
        "contains",
        "implements",
        "consumes",
        "extends",
        "contradicts",
        "supersedes",
    } == RELATION_WORDS


def test_known_words_pass_through_unchanged_in_header_order() -> None:
    result = RelationRule().parse(
        [
            {"id": "r--concept--b", "relation": "part_of"},
            {"id": "r--concept--a", "relation": "supersedes"},
        ]
    )
    assert result.relations == (
        RawRelation(target_key="r--concept--b", relation="part_of"),
        RawRelation(target_key="r--concept--a", relation="supersedes"),
    )
    assert result.rejected == ()


def test_absent_related_is_nothing() -> None:
    result = RelationRule().parse(None)
    assert result.relations == () and result.rejected == ()


def test_a_word_outside_the_eight_is_unknown_relation() -> None:
    result = RelationRule().parse([{"id": "r--concept--b", "relation": "Refines"}])
    assert result.relations == ()
    assert result.rejected == (
        RejectedRelation(
            classification="unknown_relation", target_key="r--concept--b", relation="Refines"
        ),
    )


@pytest.mark.parametrize(
    "entry",
    [
        "r--concept--b",
        {"relation": "refines"},
        {"id": "r--concept--b"},
        {"id": "  ", "relation": "refines"},
        {"id": "r--concept--b", "relation": ""},
        {"id": ["x"], "relation": "refines"},
        None,
    ],
)
def test_a_malformed_entry_is_invalid_relation(entry) -> None:
    result = RelationRule().parse([entry])
    assert result.relations == ()
    assert [item.classification for item in result.rejected] == ["invalid_relation"]


@pytest.mark.parametrize("value", ["refines", {"id": "x", "relation": "refines"}, 3])
def test_a_related_that_is_not_a_list_is_one_invalid_relation(value) -> None:
    result = RelationRule().parse(value)
    assert result.relations == ()
    assert [item.classification for item in result.rejected] == ["invalid_relation"]


def test_good_entries_survive_next_to_bad_ones() -> None:
    result = RelationRule().parse(
        [{"id": "r--c--a", "relation": "refines"}, {"id": "r--c--b", "relation": "nope"}, 4]
    )
    assert [item.target_key for item in result.relations] == ["r--c--a"]
    assert [item.classification for item in result.rejected] == [
        "unknown_relation",
        "invalid_relation",
    ]
