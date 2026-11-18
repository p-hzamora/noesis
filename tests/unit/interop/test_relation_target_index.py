"""D-010 resolution order and the relation set builder (AC-002, AC-003, AC-004)."""

import pytest

from noesis.bounded_context.interop.domain.services.relation_set_builder import (
    RELATION_CLASSES,
    RelationSetBuilder,
)
from noesis.bounded_context.interop.domain.services.relation_target_index import (
    RelationTargetIndex,
)
from noesis.bounded_context.interop.domain.value_objects.vault_relation import (
    RawRelation,
    RejectedRelation,
)

pytestmark = pytest.mark.unit

PATHS = [
    "company/x/repos/r/concepts/b.md",
    "company/x/repos/r/architecture/overview.md",
    "company/x/repos/other/architecture/overview.md",
    "learning/unique-elsewhere.md",
    "learning/twice.md",
    "misc/twice.md",
    "company/x/repos/r/a/dup.md",
    "company/x/repos/r/b/dup.md",
    "repos/r/Café.md",
]


def resolve(key: str):
    return RelationTargetIndex(PATHS).resolve(key)


def test_the_slug_under_the_repo_folder_resolves_wherever_repos_sits() -> None:
    found = resolve("r--concept--b")
    assert (found.classification, found.path) == ("resolved", "company/x/repos/r/concepts/b.md")


def test_the_repo_folder_wins_over_the_same_slug_in_another_repo() -> None:
    found = resolve("r--architecture--overview")
    assert found.path == "company/x/repos/r/architecture/overview.md"


def test_a_slug_missing_from_the_repo_folder_falls_back_when_unique_vault_wide() -> None:
    found = resolve("r--concept--unique-elsewhere")
    assert (found.classification, found.path) == ("resolved", "learning/unique-elsewhere.md")


def test_the_fallback_can_cross_repos() -> None:
    found = resolve("missing--architecture--overview")
    assert found.classification == "ambiguous"
    assert found.candidates == (
        "company/x/repos/other/architecture/overview.md",
        "company/x/repos/r/architecture/overview.md",
    )


def test_a_slug_twice_elsewhere_is_ambiguous_with_sorted_candidates() -> None:
    found = resolve("r--concept--twice")
    assert found.classification == "ambiguous"
    assert found.candidates == ("learning/twice.md", "misc/twice.md")


def test_two_matches_under_the_repo_folder_are_ambiguous_without_fallback() -> None:
    found = resolve("r--concept--dup")
    assert found.classification == "ambiguous"
    assert found.candidates == ("company/x/repos/r/a/dup.md", "company/x/repos/r/b/dup.md")


def test_a_slug_that_exists_nowhere_is_dangling() -> None:
    assert resolve("r--concept--ghost").classification == "dangling"


def test_matching_is_nfc_and_casefold() -> None:
    assert resolve("R--concept--CAFÉ").path == "repos/r/Café.md"


@pytest.mark.parametrize("key", ["b", "r--b", "r--concept--", "--concept--b", "", "r----"])
def test_an_id_without_repo_and_slug_around_two_separators_is_invalid(key) -> None:
    assert resolve(key).classification == "invalid_relation"


def test_a_slug_may_hold_more_separators() -> None:
    index = RelationTargetIndex(["repos/r/a--b.md"])
    assert index.resolve("r--concept--a--b").path == "repos/r/a--b.md"


def build(raw, rejected=(), targets=None, source="repos/r/src.md"):
    paths = [*PATHS, source]
    return RelationSetBuilder().build(
        source=source,
        raw=tuple(raw),
        rejected=tuple(rejected),
        index=RelationTargetIndex(paths),
        targets=targets or {},
    )


def test_resolved_targets_with_a_record_become_sorted_deduplicated_edges() -> None:
    built = build(
        [
            RawRelation(target_key="r--concept--b", relation="refines"),
            RawRelation(target_key="r--concept--b", relation="refines"),
            RawRelation(target_key="r--concept--b", relation="part_of"),
        ],
        targets={"company/x/repos/r/concepts/b.md": "K-B"},
    )
    assert [(e.target_record_id, e.relation) for e in built.relations] == [
        ("K-B", "part_of"),
        ("K-B", "refines"),
    ]
    assert built.counts["resolved"] == 3


def test_every_other_class_is_counted_and_writes_no_edge() -> None:
    built = build(
        [
            RawRelation(target_key="r--concept--ghost", relation="refines"),
            RawRelation(target_key="r--concept--twice", relation="refines"),
            RawRelation(target_key="r--concept--b", relation="refines"),
            RawRelation(target_key="r--x--src", relation="refines"),
            RawRelation(target_key="nonsense", relation="refines"),
        ],
        rejected=[
            RejectedRelation(classification="unknown_relation", target_key="r--c--z", relation="w"),
            RejectedRelation(classification="invalid_relation", target_key="", relation=""),
        ],
        targets={"repos/r/src.md": "K-S"},
    )
    assert built.relations == ()
    assert built.counts == {
        "resolved": 0,
        "dangling": 1,
        "ambiguous": 1,
        "not_imported": 1,
        "self": 1,
        "unknown_relation": 1,
        "invalid_relation": 2,
    }
    assert tuple(built.counts) == RELATION_CLASSES
    ambiguous = next(e for e in built.entries if e.classification == "ambiguous")
    assert ambiguous.candidates == ("learning/twice.md", "misc/twice.md")
