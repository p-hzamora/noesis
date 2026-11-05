"""The strict reader of `notes apply` input: every flaw is reported, nothing is downgraded."""

import json

import pytest

from noesis.bounded_context.notes.application.dtos import RejectedEntryDto
from noesis.bounded_context.notes.domain.value_objects import CurationActionEnum, NoteKindEnum
from noesis.bounded_context.notes.infrastructure.outbound.curation.apply_input_schema import (
    parse_decisions_strict,
)

pytestmark = pytest.mark.unit


def _entry(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "action": "create",
        "candidate": "ttl cache",
        "reason": "non-obvious choice",
        "kind": "decision",
        "slug": "use-ttl-cache",
        "title": "Use a TTL cache",
        "sections": [{"heading": "Decision", "body": "Keep tokens in memory."}],
    }
    return {**base, **overrides}


def _payload(*entries: dict[str, object]) -> str:
    return json.dumps({"decisions": list(entries)})


def test_a_valid_payload_becomes_decisions() -> None:
    decisions, rejected = parse_decisions_strict(_payload(_entry()))

    assert rejected == ()
    assert decisions[0].action is CurationActionEnum.CREATE
    assert decisions[0].draft is not None
    assert decisions[0].draft.kind is NoteKindEnum.DECISION
    assert decisions[0].draft.slug.value == "use-ttl-cache"
    assert decisions[0].draft.sections[0].heading == "Decision"


def test_an_empty_decisions_list_is_valid() -> None:
    assert parse_decisions_strict(_payload()) == ((), ())


def test_a_missing_slug_is_derived_from_the_title() -> None:
    decisions, rejected = parse_decisions_strict(_payload(_entry(slug=None)))

    assert rejected == ()
    assert decisions[0].draft is not None
    assert decisions[0].draft.slug.value == "use-a-ttl-cache"


def test_skip_entries_are_accepted() -> None:
    decisions, rejected = parse_decisions_strict(
        _payload({"action": "skip", "candidate": "typo", "reason": "already in the README"})
    )

    assert rejected == ()
    assert decisions[0].action is CurationActionEnum.SKIP
    assert decisions[0].draft is None


def test_invalid_json_rejects_the_whole_payload() -> None:
    decisions, rejected = parse_decisions_strict("{oops")

    assert decisions == ()
    assert rejected[0].index is None
    assert rejected[0].reason.startswith("not valid JSON")


@pytest.mark.parametrize(
    "text", ["[]", '"x"', '{"decisions": "no"}', "{}", '{"decisions": [], "x": 1}']
)
def test_a_payload_without_exactly_a_decisions_list_is_rejected(text: str) -> None:
    decisions, rejected = parse_decisions_strict(text)

    assert decisions == ()
    assert rejected == (
        RejectedEntryDto(index=None, reason='expected an object with a single "decisions" list'),
    )


def test_every_flawed_entry_is_reported_with_its_index_and_valid_ones_are_still_parsed() -> None:
    decisions, rejected = parse_decisions_strict(
        _payload(
            _entry(),
            _entry(kind=None),
            _entry(title=""),
            _entry(slug="Not A Slug"),
            _entry(action="merge"),
            _entry(unknown="x"),
            "not an object",
        )
    )

    assert len(decisions) == 1
    assert [entry.index for entry in rejected] == [1, 2, 3, 4, 5, 6]
    assert rejected[0].reason == "create and update need a kind and a title"
    assert rejected[1].reason == "create and update need a kind and a title"
    assert rejected[2].reason.startswith("invalid slug")
    assert "action" in rejected[3].reason
    assert "unknown" in rejected[4].reason
    assert rejected[5].reason == "entry is not an object"
