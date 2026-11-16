"""`noesis curate` output: results, the parked list and the retry-all report."""

from typing import Literal

from noesis.utils import FrozenObject

from .error_response import ErrorDetail
from .i_renderable_response import IRenderableResponse


class CurationItemResponse(FrozenObject):
    """What one candidate became.

    Attributes:
        ordinal: Position in the plan, from 1.
        candidate: Its local key.
        kind: `experience`, `knowledge`, `skip`; None when unreadable.
        outcome: `recorded`, `proposed`, `revised`, `successor_proposed` or `skipped`.
        record_id: The record written or revised; null when skipped or on a dry run.
        type: Its record type.
        revision: Its head revision after the write; null for an experience.
        status: Its status; null for an experience.
        target_record_id: The record the candidate named, when any.
        assertion_ids: Assertions proposed for it.
        reason: Why it was skipped, or a note; null otherwise.
    """

    ordinal: int
    candidate: str
    kind: str | None = None
    outcome: str
    record_id: str | None = None
    type: str | None = None
    revision: int | None = None
    status: str | None = None
    target_record_id: str | None = None
    assertion_ids: tuple[str, ...] = ()
    reason: str | None = None


class CurationSourceResponse(FrozenObject):
    """A source every write cites.

    Attributes:
        id: Its id; null when not stored.
        kind: `work_brief`, `commit` or `agent_session`.
        locator: Its locator.
    """

    id: str | None = None
    kind: str
    locator: str


class RelatedLookupResponse(FrozenObject):
    """How the related lookup went.

    Attributes:
        state: `used` or `disabled`.
        pending_changes: The index lag it reported; null when disabled.
    """

    state: str
    pending_changes: int | None = None


class CurateResponse(IRenderableResponse):
    """`noesis curate brief|apply|retry`: what curation did.

    Attributes:
        ticket: The inbox ticket; null on a dry run.
        submission_key: The submission's key.
        dry_run: True when nothing was written.
        replayed: True when the plan was registered before this invocation.
        items: One per candidate, in plan order.
        sources: The sources of every write.
        related_lookup: How the related lookup went.
    """

    ticket: str | None = None
    submission_key: str
    dry_run: bool = False
    replayed: bool = False
    items: tuple[CurationItemResponse, ...] = ()
    sources: tuple[CurationSourceResponse, ...] = ()
    related_lookup: RelatedLookupResponse

    def render(self) -> str:
        head: str = f"submission {self.submission_key[:12]}"
        if self.ticket:
            head += f" (ticket {self.ticket})"
        if self.dry_run:
            head += " [dry run, nothing written]"
        elif self.replayed:
            head += " [replayed: nothing new written]"
        lines: list[str] = [head]
        for item in self.items:
            line: str = f"  {item.ordinal}. {item.candidate}: {item.outcome}"
            if item.record_id:
                line += f" {item.record_id}"
            if item.target_record_id:
                line += f" (target {item.target_record_id})"
            if item.reason:
                line += f" - {item.reason}"
            lines.append(line)
        if not self.items:
            lines.append("  nothing worth keeping")
        lines.append(f"  related lookup: {self.related_lookup.state}")
        return "\n".join(lines)


class CurateParkedItemResponse(FrozenObject):
    """One parked ticket.

    Attributes:
        ticket: Id to pass to `noesis curate retry`.
        stage: The stage it failed at; a retry returns to it.
        reason: Why it failed.
        repository: Project key of the submission.
        parked_at: When it last failed (ISO).
        age_seconds: Seconds since then.
    """

    ticket: str
    stage: str
    reason: str
    repository: str
    parked_at: str
    age_seconds: int


class CurateParkedResponse(IRenderableResponse):
    """`noesis curate parked`: every parked ticket, oldest first.

    Attributes:
        parked: The parked tickets.
    """

    parked: tuple[CurateParkedItemResponse, ...]

    def render(self) -> str:
        if not self.parked:
            return "nothing parked"
        return "\n".join(
            f"{item.ticket}  {item.repository}  {item.stage}  {item.reason}  {item.age_seconds}s"
            for item in self.parked
        )


class RetryTicketResponse(FrozenObject):
    """One ticket of `curate retry --all`.

    Attributes:
        ticket: The ticket.
        repository: Project key of the submission.
        stage: The stage it failed at.
        reason: Why it was parked.
        outcome: `pending` (listed only), `retried` or `failed`.
        result: The curation result, when it was retried.
        error: The failure, when it failed again.
    """

    ticket: str
    repository: str
    stage: str
    reason: str
    outcome: Literal["pending", "retried", "failed"]
    result: CurateResponse | None = None
    error: ErrorDetail | None = None


class CurateRetryAllResponse(IRenderableResponse):
    """`noesis curate retry --all [--yes]`: what would be retried, or what each retry did.

    Attributes:
        executed: False when `--yes` was missing and nothing was retried.
        tickets: One entry per parked ticket, oldest first.
        failed: How many tickets failed again.
    """

    executed: bool
    tickets: tuple[RetryTicketResponse, ...] = ()
    failed: int = 0

    def render(self) -> str:
        if not self.tickets:
            return "nothing parked"
        lines: list[str] = []
        if not self.executed:
            lines.append("would retry (pass --yes to run them):")
        for item in self.tickets:
            lines.append(f"{item.ticket}  {item.repository}  {item.stage}  {item.outcome}")
            if item.error is not None:
                lines.append(f"  [{item.error.code}] {item.error.message}")
        return "\n".join(lines)
