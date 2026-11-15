"""CatalogEntryName, CatalogRef and CatalogRevision (FR-001; Q-008 name grammar, first-colon split)."""

from datetime import UTC, datetime

import pytest
from tests.support.knowledge_support import AGENT, NOW

from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    CatalogRevision,
    RecordId,
)
from noesis.bounded_context.knowledge.domain.value_objects.catalog_name import (
    CATALOG_NAME_PATTERN,
    CatalogEntryName,
)
from noesis.bounded_context.knowledge.domain.value_objects.catalog_ref import CatalogRef
from noesis.exceptions import (
    InvalidCatalogNameError,
    InvalidCatalogPrerequisiteError,
    InvalidRecordError,
)

pytestmark = pytest.mark.unit

ACCEPTED_NAMES: list[str] = [
    "python3.14",
    "gh",
    "A",
    "python-suite:ddd-hexagonal-python",
    "a_b",
    "a" * 128,
]
REJECTED_NAMES: list[str] = ["", "-x", ".x", ":x", "Bad Name!", "ñame", "a" * 129, " gh", "gh "]


def test_name_pattern_is_the_q008_grammar() -> None:
    assert CATALOG_NAME_PATTERN == r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"


@pytest.mark.parametrize("name", ACCEPTED_NAMES)
def test_name_accepts_the_grammar_and_keeps_it_as_typed(name: str) -> None:
    assert CatalogEntryName(value=name).value == name


@pytest.mark.parametrize("name", REJECTED_NAMES)
def test_name_outside_the_grammar_raises_061_with_next_steps(name: str) -> None:
    with pytest.raises(InvalidCatalogNameError) as error:
        CatalogEntryName(value=name)

    assert error.value.error_code == "KNOWLEDGE_061_INVALID_CATALOG_NAME"
    assert error.value.next_steps


def test_names_are_case_sensitive_and_never_normalised() -> None:
    assert CatalogEntryName(value="Gh") != CatalogEntryName(value="gh")
    assert CatalogEntryName(value="Gh").value == "Gh"


def test_ref_splits_on_the_first_colon_only() -> None:
    ref: CatalogRef = CatalogRef.parse("skill:python-suite:ddd-hexagonal-python")

    assert ref.kind is CatalogEntryKindEnum.SKILL
    assert ref.name == CatalogEntryName(value="python-suite:ddd-hexagonal-python")


@pytest.mark.parametrize(
    "text", ["skill:python-suite:ddd-hexagonal-python", "cli_tool:gh", "mcp_server:docs"]
)
def test_ref_round_trips_through_its_text_form(text: str) -> None:
    ref: CatalogRef = CatalogRef.parse(text)

    assert ref.as_text() == text
    assert str(ref) == text
    assert CatalogRef.parse(ref.as_text()) == ref


@pytest.mark.parametrize(
    "text", ["gh", "plugin:x", "skill:", "skill:Bad Name!", ":x", "", "Skill:x"]
)
def test_ref_missing_colon_unknown_kind_or_bad_name_raises_062(text: str) -> None:
    with pytest.raises(InvalidCatalogPrerequisiteError) as error:
        CatalogRef.parse(text)

    assert error.value.error_code == "KNOWLEDGE_062_INVALID_CATALOG_PREREQUISITE"
    assert error.value.next_steps


def make_revision(**overrides: object) -> CatalogRevision:
    values: dict[str, object] = {
        "number": 1,
        "purpose": "search",
        "version": "1.0",
        "prerequisites": (CatalogRef.parse("cli_tool:node"),),
        "location": "https://example.invalid/vectra",
        "actor": AGENT,
        "source_ids": (RecordId(value=f"{2:026d}"),),
        "created_at": NOW,
    }
    return CatalogRevision(**{**values, **overrides})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    [{"purpose": "  "}, {"location": ""}, {"location": "   "}, {"source_ids": ()}],
    ids=["blank-purpose", "empty-location", "blank-location", "no-source"],
)
def test_revision_requires_purpose_location_and_a_source(overrides: dict[str, object]) -> None:
    with pytest.raises(InvalidRecordError):
        make_revision(**overrides)


def test_revision_content_equals_compares_exactly_the_four_content_fields() -> None:
    base: CatalogRevision = make_revision()
    envelope_only: CatalogRevision = make_revision(
        number=2,
        actor=AGENT.model_copy(update={"session": "other"}),
        source_ids=(RecordId(value=f"{9:026d}"),),
        created_at=datetime(2030, 1, 1, tzinfo=UTC),
    )

    assert base.content_equals(envelope_only)
    for changed in (
        {"purpose": "other"},
        {"version": None},
        {"prerequisites": ()},
        {"location": "https://example.invalid/other"},
    ):
        assert not base.content_equals(make_revision(**changed))
