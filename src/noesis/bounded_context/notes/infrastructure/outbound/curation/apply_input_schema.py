"""Strict reader of the decisions JSON that `noesis notes apply` accepts.

It reuses the curator's entry shape (`CuratorDecisionModel`) but never downgrades a flawed
entry to a skip: every flaw is reported with its position, so the caller can fix the input.
"""

import json

from pydantic import ValidationError

from noesis.bounded_context.notes.application.dtos import RejectedEntryDto
from noesis.bounded_context.notes.domain.value_objects import (
    CurationActionEnum,
    CurationDecision,
    NoteDraft,
    NoteKind,
    NoteSection,
    NoteSlug,
)
from noesis.exceptions import AppException

from .curator_response_schema import CuratorDecisionModel

DECISIONS_KEY: str = "decisions"


def parse_decisions_strict(
    text: str,
) -> tuple[tuple[CurationDecision, ...], tuple[RejectedEntryDto, ...]]:
    """Read an apply payload.

    Args:
        text: The JSON exactly as the caller sent it.

    Returns:
        The decisions that are valid and the entries that are not. An unusable payload gives
        no decisions and one rejection without an index.
    """
    try:
        payload: object = json.loads(text)
    except json.JSONDecodeError as error:
        return (), (RejectedEntryDto(index=None, reason=f"not valid JSON: {error}"),)
    if (
        not isinstance(payload, dict)
        or set(payload) != {DECISIONS_KEY}
        or not isinstance(payload[DECISIONS_KEY], list)
    ):
        return (), (
            RejectedEntryDto(
                index=None, reason=f'expected an object with a single "{DECISIONS_KEY}" list'
            ),
        )
    decisions: list[CurationDecision] = []
    rejected: list[RejectedEntryDto] = []
    for index, entry in enumerate(payload[DECISIONS_KEY]):
        outcome: CurationDecision | str = _read_entry(entry)
        if isinstance(outcome, str):
            rejected.append(RejectedEntryDto(index=index, reason=outcome))
        else:
            decisions.append(outcome)
    return tuple(decisions), tuple(rejected)


def _read_entry(entry: object) -> CurationDecision | str:
    """One decision, or the reason the entry cannot be one."""
    if not isinstance(entry, dict):
        return "entry is not an object"
    try:
        model = CuratorDecisionModel.model_validate(entry)
    except ValidationError as error:
        first = error.errors()[0]
        location: str = ".".join(str(part) for part in first["loc"])
        return f"{location}: {first['msg']}" if location else first["msg"]
    action = CurationActionEnum(model.action)
    if action is CurationActionEnum.SKIP:
        return CurationDecision(action=action, candidate=model.candidate, reason=model.reason)
    if model.kind is None or not model.title:
        return "create and update need a kind and a title"
    try:
        slug = NoteSlug(value=model.slug) if model.slug else NoteSlug.from_title(model.title)
    except AppException as error:
        return f"invalid slug {model.slug!r}: {error.message}"
    try:
        kind = NoteKind(value=model.kind)
    except AppException as error:
        return f"invalid kind {model.kind!r}: {error.message}"
    draft = NoteDraft(
        kind=kind,
        slug=slug,
        title=model.title,
        sections=tuple(NoteSection(heading=s.heading, body=s.body) for s in model.sections),
    )
    return CurationDecision(
        action=action, candidate=model.candidate, reason=model.reason, draft=draft
    )
