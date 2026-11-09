"""The JSON shape the recall agent must answer with, and its translation to the briefing DTO."""

import json

from pydantic import BaseModel, ConfigDict, Field

from noesis.bounded_context.notes.application.dtos import BriefingItemDto, RecallBriefingDto


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RecallItemModel(_Strict):
    """One statement and the notes behind it."""

    text: str = Field(description="One plain, specific statement.")
    sources: list[str] = Field(
        default_factory=list,
        description="`path` of each note that states it, copied exactly from the note blocks.",
    )


class RecallBriefingModel(_Strict):
    """The whole answer; any list may be empty."""

    summary: str
    constraints: list[RecallItemModel] = Field(default_factory=list)
    decisions: list[RecallItemModel] = Field(default_factory=list)
    gotchas: list[RecallItemModel] = Field(default_factory=list)
    context: list[RecallItemModel] = Field(default_factory=list)
    open_questions: list[RecallItemModel] = Field(default_factory=list)
    inferences: list[RecallItemModel] = Field(default_factory=list)
    not_covered: list[str] = Field(default_factory=list)

    def to_dto(self, *, model: str | None) -> RecallBriefingDto:
        """The unchecked briefing; the handler verifies the citations."""

        def items(values: list[RecallItemModel]) -> tuple[BriefingItemDto, ...]:
            return tuple(
                BriefingItemDto(text=value.text, sources=tuple(value.sources))
                for value in values
                if value.text.strip()
            )

        return RecallBriefingDto(
            summary=self.summary,
            constraints=items(self.constraints),
            decisions=items(self.decisions),
            gotchas=items(self.gotchas),
            context=items(self.context),
            open_questions=items(self.open_questions),
            inferences=items(self.inferences),
            not_covered=tuple(gap for gap in self.not_covered if gap.strip()),
            model=model,
        )


RESPONSE_JSON_SCHEMA: str = json.dumps(RecallBriefingModel.model_json_schema())
"""The schema passed to `claude --json-schema`."""
