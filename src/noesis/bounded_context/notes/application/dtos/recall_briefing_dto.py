"""The task briefing an agent wrote from the notes it read."""

from noesis.shared_kernel.application.dtos import BaseDto


class BriefingItemDto(BaseDto):
    """One statement of a briefing.

    Attributes:
        text: The statement.
        sources: Paths of the notes that support it (for an inference: the notes it builds on).
    """

    text: str
    sources: tuple[str, ...]


class RecallBriefingDto(BaseDto):
    """What the notes say about a task, grounded in note paths.

    Every statement in `constraints`, `decisions`, `gotchas` and `context` cites at least one
    note that was read. What the notes do not say is kept apart: `inferences` (the agent's own
    reasoning), `unsupported` (statements whose citations did not check out) and `not_covered`
    (what the task needs and the notes lack).

    Attributes:
        summary: A few sentences on what matters for the task.
        constraints: Rules the work must respect.
        decisions: Choices already made, with their reasons.
        gotchas: Traps and past failures.
        context: Other background worth having.
        open_questions: Unresolved points the notes leave open.
        inferences: Conclusions the notes do not state themselves.
        unsupported: Statements dropped from the sections above for lacking a valid citation.
        not_covered: Aspects of the task the notes say nothing about.
        model: Model that answered, as its runtime reported it; None when unknown.
        markdown: The briefing as a Markdown document.
    """

    summary: str
    constraints: tuple[BriefingItemDto, ...] = ()
    decisions: tuple[BriefingItemDto, ...] = ()
    gotchas: tuple[BriefingItemDto, ...] = ()
    context: tuple[BriefingItemDto, ...] = ()
    open_questions: tuple[BriefingItemDto, ...] = ()
    inferences: tuple[BriefingItemDto, ...] = ()
    unsupported: tuple[BriefingItemDto, ...] = ()
    not_covered: tuple[str, ...] = ()
    model: str | None = None
    markdown: str = ""
