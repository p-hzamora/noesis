"""Decides what a briefing may claim: only what the notes that were read back, as Markdown."""

from collections.abc import Collection, Sequence

from noesis.bounded_context.notes.application.dtos import (
    BriefingItemDto,
    NoteContentDto,
    RecallBriefingDto,
)

_NONE_STATED: str = "_None stated in the notes._"
_NONE: str = "_None._"


class BriefingGrounder:
    """Checks a briefing's citations against the notes read, and writes it as Markdown."""

    @staticmethod
    def ground(draft: RecallBriefingDto, notes: Sequence[NoteContentDto]) -> RecallBriefingDto:
        """`draft` with every citation checked against `notes`, rendered as Markdown.

        Paths that are not among `notes` are removed. A constraint, decision, gotcha or context
        item left with no citation is moved to `unsupported`: the briefing never presents a claim
        as grounded unless a note that was read backs it. Open questions and inferences keep
        whatever valid paths they have, possibly none.

        Args:
            draft: The agent's answer.
            notes: The notes the agent was given.

        Returns:
            The checked briefing, with `markdown` set.
        """
        read: frozenset[str] = frozenset(note.path for note in notes)
        unsupported: list[BriefingItemDto] = list(draft.unsupported)

        def grounded(items: Sequence[BriefingItemDto]) -> tuple[BriefingItemDto, ...]:
            kept: list[BriefingItemDto] = []
            for item in items:
                sources: tuple[str, ...] = BriefingGrounder._valid(item.sources, read)
                (kept if sources else unsupported).append(
                    item.model_copy(update={"sources": sources})
                )
            return tuple(kept)

        def loose(items: Sequence[BriefingItemDto]) -> tuple[BriefingItemDto, ...]:
            return tuple(
                item.model_copy(update={"sources": BriefingGrounder._valid(item.sources, read)})
                for item in items
            )

        checked: RecallBriefingDto = draft.model_copy(
            update={
                "constraints": grounded(draft.constraints),
                "decisions": grounded(draft.decisions),
                "gotchas": grounded(draft.gotchas),
                "context": grounded(draft.context),
                "open_questions": loose(draft.open_questions),
                "inferences": loose(draft.inferences),
                "unsupported": tuple(unsupported),
            }
        )
        return checked

    @staticmethod
    def markdown(task: str, briefing: RecallBriefingDto, notes: Sequence[NoteContentDto]) -> str:
        """The briefing as a Markdown document that ends with the notes it was written from."""
        lines: list[str] = [f"# Recall briefing: {task.strip()}", "", briefing.summary.strip()]
        sections: tuple[tuple[str, tuple[BriefingItemDto, ...]], ...] = (
            ("Constraints", briefing.constraints),
            ("Decisions", briefing.decisions),
            ("Gotchas", briefing.gotchas),
            ("Context", briefing.context),
            ("Open questions", briefing.open_questions),
            (
                "Inferences (the agent's reasoning; the notes do not state these)",
                briefing.inferences,
            ),
            (
                "Unsupported (dropped from the sections above: no valid citation)",
                briefing.unsupported,
            ),
        )
        for heading, items in sections:
            lines += ["", f"## {heading}", ""]
            empty: str = _NONE if heading.startswith("Unsupported") else _NONE_STATED
            lines += [BriefingGrounder._bullet(item) for item in items] or [empty]
        lines += ["", "## Not covered by the notes", ""]
        lines += [f"- {gap}" for gap in briefing.not_covered] or [_NONE_STATED]
        lines += ["", "## Notes read", ""]
        lines += [
            f"- `{note.path}`: {note.title}" + (f" ({note.updated})" if note.updated else "")
            for note in notes
        ]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _valid(sources: Collection[str], read: Collection[str]) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                path.strip().lstrip("/") for path in sources if path.strip().lstrip("/") in read
            )
        )

    @staticmethod
    def _bullet(item: BriefingItemDto) -> str:
        cited: str = ", ".join(f"`{path}`" for path in item.sources)
        return f"- {item.text.strip()} [{cited}]" if cited else f"- {item.text.strip()}"
