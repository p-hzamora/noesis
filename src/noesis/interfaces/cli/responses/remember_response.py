"""`noesis remember` output."""

from noesis.utils import FrozenObject

from .i_renderable_response import IRenderableResponse


class RememberScopeResponse(FrozenObject):
    """Where the memory applies.

    Attributes:
        project_key: The project it is anchored to; None when space-wide.
        source: How it was chosen: `space_wide`, `option`, `target_root`, `git_root` or `none`.
    """

    project_key: str | None = None
    source: str


class RememberReconciledResponse(FrozenObject):
    """An existing record that resembles the new one.

    Attributes:
        id: The existing record's id.
        score: Lexical overlap with the new text, 0..1.
        authority: Its authority tier.
        title: Its title; None for an experience.
    """

    id: str
    score: float
    authority: str
    title: str | None = None


class RememberReconciliationResponse(FrozenObject):
    """What the space already holds that resembles the new record; nothing is merged.

    Attributes:
        duplicates: Records at or above the duplicate threshold.
        related: Records at or above the related threshold.
        warnings: Why the lookup was partial or skipped, when it was.
    """

    duplicates: tuple[RememberReconciledResponse, ...] = ()
    related: tuple[RememberReconciledResponse, ...] = ()
    warnings: tuple[str, ...] = ()


class RememberAssertionResponse(FrozenObject):
    """A `refines` or `supersedes` assertion the request asked for.

    Attributes:
        id: The assertion id; None for a preview.
        predicate: `refines` or `supersedes`.
        object_ref: The target as written.
        status: `proposed` or `planned` (preview).
    """

    id: str | None = None
    predicate: str
    object_ref: str
    status: str


class RememberResponse(IRenderableResponse):
    """`noesis remember`: the record written (or, with `--check`, what would be written).

    Attributes:
        written: False for `--check`; nothing was written.
        record_id: The record's id; absent for `--check`.
        record_type: `knowledge` or `experience`.
        revision: Head revision (knowledge); None for an experience.
        status: `proposed` (knowledge); None for an experience.
        space_id: Space it lives in.
        project_id: Its project, when any.
        replayed: True when the idempotency key was already used and nothing was written.
        idempotency_key: The key used, given or derived.
        scope: Where it applies.
        reconciliation: Duplicates and related records.
        assertions: The requested assertions.
        next_steps: What to do next.
    """

    written: bool
    record_id: str | None = None
    record_type: str
    revision: int | None = None
    status: str | None = None
    space_id: str
    project_id: str | None = None
    replayed: bool = False
    idempotency_key: str
    scope: RememberScopeResponse
    reconciliation: RememberReconciliationResponse
    assertions: tuple[RememberAssertionResponse, ...] = ()
    next_steps: tuple[str, ...] = ()

    def render(self) -> str:
        if not self.written:
            lines: list[str] = [f"check: would remember a {self.record_type}; nothing written"]
        else:
            head: str = f"{self.record_type} {self.record_id}"
            if self.revision is not None:
                head += f" revision {self.revision} ({self.status})"
            note: str = " (replayed: nothing written)" if self.replayed else ""
            lines = [f"remembered {head}{note}"]
        for duplicate in self.reconciliation.duplicates:
            lines.append(
                f"duplicate {duplicate.id} ({duplicate.score:.2f}): {duplicate.title or ''}"
            )
        for related in self.reconciliation.related:
            lines.append(f"related {related.id} ({related.score:.2f}): {related.title or ''}")
        lines.extend(f"warning: {warning}" for warning in self.reconciliation.warnings)
        lines.extend(
            f"{assertion.predicate} {assertion.object_ref}: {assertion.status}"
            + (f" ({assertion.id})" if assertion.id else "")
            for assertion in self.assertions
        )
        lines.extend(f"next: {step}" for step in self.next_steps)
        return "\n".join(lines)
