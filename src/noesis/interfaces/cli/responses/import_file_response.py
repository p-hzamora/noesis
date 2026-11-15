"""`noesis import file` output."""

from noesis.bounded_context.interop.application.dtos import ImportFileResultDto

from .i_renderable_response import IRenderableResponse


class ImportFileResponse(IRenderableResponse):
    """`noesis import file`: the record a file became, or would become with `--dry-run`.

    Attributes:
        applied: False with `--dry-run`.
        path: The resolved absolute path.
        source_locator: The locator recorded for the file.
        outcome: `created`, `unchanged`, `revised` or `successor_proposed`.
        record_id: The record created, revised or matched.
        revision: Revision written, planned or matched.
        status: Status of the record.
        title: Mapped title.
        subtype: Mapped subtype.
        project_key: Mapped project key.
        tags: Tags including `origin:imported`.
        target_record_id: The accepted record a successor replaces.
        assertion_id: The proposed `supersedes` assertion.
        reason: The reduced-behaviour note.
        warnings: Warnings of the file.
        next_steps: Commands to run next.
    """

    applied: bool
    path: str
    source_locator: str
    outcome: str
    record_id: str | None = None
    revision: int | None = None
    status: str | None = None
    title: str
    subtype: str
    project_key: str | None = None
    tags: tuple[str, ...] = ()
    target_record_id: str | None = None
    assertion_id: str | None = None
    reason: str | None = None
    warnings: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()

    @classmethod
    def from_dto(cls, dto: ImportFileResultDto) -> ImportFileResponse:
        """The response of `dto`."""
        return cls.model_validate(dto, from_attributes=True)

    def render(self) -> str:
        verb: str = self.outcome if self.applied else f"would be {self.outcome} (dry run)"
        head: str = f"{self.path}: {verb}"
        if self.record_id:
            head += f" as {self.record_id} revision {self.revision}"
        lines: list[str] = [head]
        if self.reason:
            lines.append(f"note: {self.reason}")
        lines += [f"warning: {warning}" for warning in self.warnings]
        lines += [f"next: {step}" for step in self.next_steps]
        return "\n".join(lines)
