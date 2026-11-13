"""Checks citation identity against records read; does not verify semantic entailment."""

from collections.abc import Sequence

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
        """`draft` with every citation resolved against `notes`.

        IDs and unambiguous legacy paths resolve only to `notes`; other citations are removed.
        A constraint, decision, gotcha or context item left with no citation is moved to `unsupported`: the briefing never presents a claim
        as grounded unless it cites a note that was read. This does not verify claim truth. Open questions and inferences keep
        whatever valid paths they have, possibly none.

        Args:
            draft: The agent's answer.
            notes: The notes the agent was given.

        Returns:
            The checked briefing; call `markdown` separately to render it.
        """
        by_id: dict[str, NoteContentDto] = {note.id: note for note in notes}
        references: dict[str, set[str]] = {}
        for note in notes:
            for reference in (note.id, note.path):
                references.setdefault(reference, set()).add(note.id)
        unsupported: list[BriefingItemDto] = [
            item.model_copy(update={"sources": (), "source_ids": ()}) for item in draft.unsupported
        ]

        def resolve(item: BriefingItemDto) -> BriefingItemDto:
            ids: dict[str, None] = {}
            for source in item.sources:
                matches: set[str] = references.get(source.strip().lstrip("/"), set())
                if len(matches) == 1:
                    ids.setdefault(next(iter(matches)), None)
            return item.model_copy(
                update={
                    "sources": tuple(dict.fromkeys(by_id[note_id].path for note_id in ids)),
                    "source_ids": tuple(ids),
                }
            )

        def grounded(items: Sequence[BriefingItemDto]) -> tuple[BriefingItemDto, ...]:
            kept: list[BriefingItemDto] = []
            for item in items:
                checked_item: BriefingItemDto = resolve(item)
                (kept if checked_item.source_ids else unsupported).append(checked_item)
            return tuple(kept)

        def loose(items: Sequence[BriefingItemDto]) -> tuple[BriefingItemDto, ...]:
            return tuple(resolve(item) for item in items)

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
            f"- `{note.path}`: {note.title} [ID: `{note.id}`]"
            + (f" ({note.updated})" if note.updated else "")
            for note in notes
        ]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _bullet(item: BriefingItemDto) -> str:
        cited: str = ", ".join(f"`{path}`" for path in item.sources)
        text: str = f"- {item.text.strip()} [{cited}]" if cited else f"- {item.text.strip()}"
        identities: str = ", ".join(f"`{note_id}`" for note_id in item.source_ids)
        return f"{text} (IDs: {identities})" if identities else text
