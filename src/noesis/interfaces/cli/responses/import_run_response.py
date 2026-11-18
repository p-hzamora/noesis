"""`noesis import run` output."""

from typing import Any

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer

from noesis.bounded_context.interop.application.dtos import VaultImportResultDto
from noesis.utils import FrozenObject

from .i_renderable_response import IRenderableResponse

TOTAL_LABELS: tuple[str, ...] = (
    "created",
    "unchanged",
    "changed_in_vault",
    "revised",
    "successor_proposed",
    "skipped_empty",
    "blocked",
)


class AmbiguousLinkResponse(FrozenObject):
    """Target text and candidate vault paths."""

    target: str
    candidates: tuple[str, ...]


class UnresolvedRelationResponse(FrozenObject):
    """A relation entry that created no edge, with candidate paths when ambiguous."""

    classification: str
    target: str
    relation: str
    candidates: tuple[str, ...] = ()


class ImportNoteRowResponse(FrozenObject):
    """One note of a run (`--verbose`).

    Attributes:
        path: Relative POSIX path of the note.
        outcome: What happened to the note.
        record_id: The record created, revised or matched, or the declared ULID.
        revision: Revision written, planned or matched.
        status: Status of the record.
        title: Mapped title.
        subtype: Mapped subtype.
        project_key: Mapped project key.
        tags: Tags including the origin tag.
        target_record_id: The accepted record a successor replaces.
        assertion_id: The proposed `supersedes` assertion.
        reason: Block reason or reduced-behaviour note.
        detail: Error code behind `invalid_metadata`.
        warnings: Warnings of the note.
    """

    path: str
    outcome: str
    record_id: str | None = None
    revision: int | None = None
    status: str | None = None
    title: str | None = None
    subtype: str | None = None
    project_key: str | None = None
    tags: tuple[str, ...] = ()
    target_record_id: str | None = None
    assertion_id: str | None = None
    reason: str | None = None
    detail: str | None = None
    warnings: tuple[str, ...] = ()
    links: dict[str, int | str | None] = Field(default_factory=dict)
    ambiguous: tuple[AmbiguousLinkResponse, ...] = ()
    relations: dict[str, int | str | None] = Field(default_factory=dict)
    unresolved_relations: tuple[UnresolvedRelationResponse, ...] = ()


class ImportTotalsResponse(FrozenObject):
    """Disjoint counts that add up to `notes`."""

    notes: int
    created: int
    unchanged: int
    changed_in_vault: int
    revised: int
    successor_proposed: int
    skipped_empty: int
    blocked: int


class ImportWarningCountsResponse(FrozenObject):
    """Warning counts over every note that reached the mapping step."""

    legacy_header: int
    dropped_tag: int
    ignored_field: int


class ImportRunResponse(IRenderableResponse):
    """`noesis import run`: the report of a preview or an apply.

    Attributes:
        applied: False for a preview.
        update: Whether `--update` was given.
        vault_key: The key used in locators.
        totals: Counts per outcome.
        blocked_reasons: One count per block reason that occurred.
        warnings: Warning counts.
        sources_skipped: Header source entries that did not map.
        complete: True when no note is blocked.
        notes: One row per note; present with `--verbose` only.
        next_steps: Commands to run next.
    """

    links: dict[str, int] = Field(default_factory=dict)
    link_sets: dict[str, int] = Field(default_factory=dict)
    relations: dict[str, int] = Field(default_factory=dict)
    applied: bool
    update: bool
    vault_key: str
    totals: ImportTotalsResponse
    blocked_reasons: dict[str, int]
    warnings: ImportWarningCountsResponse
    sources_skipped: int
    complete: bool
    notes: tuple[ImportNoteRowResponse, ...] | None = None
    next_steps: tuple[str, ...] = ()

    @model_serializer(mode="wrap")
    def _omit_absent_notes(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.notes is None:
            data.pop("notes", None)
        return data

    @classmethod
    def from_dto(cls, dto: VaultImportResultDto, *, verbose: bool) -> ImportRunResponse:
        """The response of `dto`; rows are kept only when `verbose`."""
        response: ImportRunResponse = cls.model_validate(dto, from_attributes=True)
        return response if verbose else response.model_copy(update={"notes": None})

    def render(self) -> str:
        counts: dict[str, int] = self.totals.model_dump()
        lines: list[str] = [
            f"{'applied' if self.applied else 'preview'}: {self.totals.notes} note(s) "
            f"in vault {self.vault_key}",
            *(f"  {label}: {counts[label]}" for label in TOTAL_LABELS if counts[label]),
        ]
        lines += [
            f"  blocked by {reason}: {count}" for reason, count in self.blocked_reasons.items()
        ]
        lines.append("links: " + ", ".join(f"{count} {name}" for name, count in self.links.items()))
        if any(self.relations.values()):
            lines.append(
                "relations: "
                + ", ".join(f"{count} {name}" for name, count in self.relations.items())
            )
        lines.append(f"complete: {'yes' if self.complete else 'no'}")
        for row in self.notes or ():
            suffix: str = f" ({row.reason})" if row.reason else ""
            lines.append(f"{row.outcome:<18} {row.path}{suffix}")
        lines += [f"next: {step}" for step in self.next_steps]
        return "\n".join(lines)
