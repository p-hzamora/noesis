"""Parsing and validating a vault migration plan."""

import json

import pytest
from tests.support.notes_support import default_catalog

from noesis.bounded_context.notes.application.services.migration import (
    MigrationActionEnum,
    MigrationPlan,
)
from noesis.exceptions import InvalidMigrationPlanError

pytestmark = pytest.mark.unit


def _plan(*entries: dict[str, str]) -> str:
    return json.dumps({"entries": list(entries)})


NOTE: dict[str, str] = {
    "old": "a/x.md",
    "new": "repos/demo/decisions/x.md",
    "action": "note",
    "scope": "repo:demo",
    "kind": "decision",
}


def test_a_plan_is_a_list_or_an_object_with_entries() -> None:
    as_object = MigrationPlan.parse(_plan(NOTE))
    as_list = MigrationPlan.parse(json.dumps([NOTE]))
    assert as_object == as_list
    assert as_object.counts() == {"note": 1, "move": 0, "keep": 0}
    as_object.validate_against(default_catalog())


def test_a_keep_entry_needs_no_target_and_stays_where_it_is() -> None:
    plan = MigrationPlan.parse(_plan({"old": "README.md", "action": "keep"}))
    entry = plan.entries[0]
    assert entry.action is MigrationActionEnum.KEEP
    assert entry.target == "README.md" and not entry.relocates
    plan.validate_against(default_catalog())


@pytest.mark.parametrize("text", ["not json", '{"entries": 3}', '"x"', '[{"old": "a"}]'])
def test_malformed_plans_are_refused(text: str) -> None:
    with pytest.raises(InvalidMigrationPlanError):
        MigrationPlan.parse(text)


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"kind": "recipe"}, "not in the catalog"),
        ({"kind": None}, "not in the catalog"),
        ({"scope": "personal:me"}, "invalid scope"),
        ({"scope": "repo:a/b"}, "invalid scope"),
        ({"scope": None}, "invalid scope"),
        ({"new": "../out.md"}, "unsafe path"),
        ({"new": "/abs.md"}, "unsafe path"),
        ({"old": "a//x.md"}, "unsafe path"),
        ({"new": "repos/demo/x.txt"}, "Markdown"),
    ],
)
def test_a_note_entry_is_checked(change: dict[str, str | None], fragment: str) -> None:
    entry = {**NOTE, **change}
    plan = MigrationPlan.parse(json.dumps([{k: v for k, v in entry.items() if v is not None}]))
    with pytest.raises(InvalidMigrationPlanError) as caught:
        plan.validate_against(default_catalog())
    assert fragment in str(caught.value.metadata["problems"])


def test_new_kinds_are_valid_note_kinds() -> None:
    plan = MigrationPlan.parse(
        _plan(
            {**NOTE, "kind": "drift", "new": "repos/demo/drift/x.md"},
            {**NOTE, "old": "b/y.md", "kind": "dependency", "new": "repos/demo/dependencies/y.md"},
        )
    )
    plan.validate_against(default_catalog())


def test_two_entries_may_not_share_an_old_path_or_a_target() -> None:
    twice = MigrationPlan.parse(_plan(NOTE, {**NOTE, "new": "repos/demo/decisions/y.md"}))
    with pytest.raises(InvalidMigrationPlanError, match="old path listed twice"):
        twice.validate_against(default_catalog())
    same_target = MigrationPlan.parse(_plan(NOTE, {**NOTE, "old": "b/y.md"}))
    with pytest.raises(InvalidMigrationPlanError, match="target listed twice"):
        same_target.validate_against(default_catalog())


def test_a_move_to_itself_is_refused() -> None:
    plan = MigrationPlan.parse(_plan({"old": "a.json", "new": "a.json", "action": "move"}))
    with pytest.raises(InvalidMigrationPlanError, match="move to itself"):
        plan.validate_against(default_catalog())
