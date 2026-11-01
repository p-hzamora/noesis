"""The JSON shape the curator must answer with, and its translation to domain decisions.

This is the anti-corruption layer between the LLM's output and the Knowledge domain: the
schema is sent to `claude --json-schema`, and `to_decisions` turns a validated answer
into `CurationDecision`s, downgrading anything malformed to a reported skip.
"""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from noesis.bounded_context.knowledge.domain.value_objects import (
    CurationActionEnum,
    CurationDecision,
    NoteDraft,
    NoteKindEnum,
    NoteSection,
    NoteSlug,
)
from noesis.exceptions import DomainException


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CuratorSectionModel(_Strict):
    """One `##` section of a drafted note."""

    heading: str = Field(description="Section heading, e.g. 'Rationale'.")
    body: str = Field(description="Markdown body. Cite commit SHAs; never paste diffs.")


class CuratorDecisionModel(_Strict):
    """One verdict about one candidate piece of knowledge."""

    action: Literal["create", "update", "skip"]
    candidate: str = Field(description="Short name of the candidate knowledge.")
    reason: str = Field(description="One sentence: why it is kept or skipped.")
    kind: Literal["decision", "gotcha", "run", "glossary"] | None = Field(
        default=None, description="Required for create/update."
    )
    slug: str | None = Field(
        default=None,
        description="Lowercase-hyphenated file name. Reuse an existing auto note's slug to update it.",
    )
    title: str | None = Field(default=None, description="Required for create/update.")
    sections: list[CuratorSectionModel] = Field(default_factory=list)


class CuratorResponseModel(_Strict):
    """The whole answer. An empty `decisions` list is valid."""

    decisions: list[CuratorDecisionModel]

    def to_decisions(self) -> tuple[CurationDecision, ...]:
        """Translate into domain decisions; malformed create/update entries become skips."""
        return tuple(_to_decision(model) for model in self.decisions)


def _to_decision(model: CuratorDecisionModel) -> CurationDecision:
    """One model to one domain decision."""
    action = CurationActionEnum(model.action)
    if action is CurationActionEnum.SKIP:
        return CurationDecision(action=action, candidate=model.candidate, reason=model.reason)
    if model.kind is None or not model.title:
        return CurationDecision(
            action=CurationActionEnum.SKIP,
            candidate=model.candidate,
            reason="malformed decision: missing kind or title",
        )
    try:
        slug: NoteSlug = (
            NoteSlug(value=model.slug) if model.slug else NoteSlug.from_title(model.title)
        )
    except DomainException:
        slug = NoteSlug.from_title(model.slug or model.title)
    draft = NoteDraft(
        kind=NoteKindEnum(model.kind),
        slug=slug,
        title=model.title,
        sections=tuple(NoteSection(heading=s.heading, body=s.body) for s in model.sections),
    )
    return CurationDecision(
        action=action, candidate=model.candidate, reason=model.reason, draft=draft
    )


RESPONSE_JSON_SCHEMA: str = json.dumps(CuratorResponseModel.model_json_schema())
"""The schema passed to `claude --json-schema`."""
