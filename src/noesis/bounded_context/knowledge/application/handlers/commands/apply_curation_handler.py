"""Apply candidates a caller wrote: no curator, no related lookup, the same plan and steps."""

from noesis.bounded_context.knowledge.application.dtos import (
    CurationResultDto,
    RejectedEntryDto,
)
from noesis.bounded_context.knowledge.application.ports.curation import ICurationInbox
from noesis.bounded_context.knowledge.application.services.curation_redactor import (
    CurationRedactor,
)
from noesis.bounded_context.knowledge.application.services.curation_runner import (
    CurationRunner,
    RelatedLookupModeEnum,
    RunOptions,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    CurationCandidate,
    CurationSubmission,
    Key,
    SubmissionKindEnum,
    canonical_json,
    sha256_hex,
)
from noesis.exceptions import CurationRejectedError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject


class ApplyCurationCommand(FrozenObject):
    """Apply the caller's candidates.

    Attributes:
        space_key: Key of the active space.
        candidates: The entries of the payload that parsed.
        rejected: The entries that did not; any of them fails the whole call.
        project_key: The project every write is scoped to (the git root name).
        session: The agent session recorded as a source of every write.
        commits: The commits recorded as sources of every write.
        actor: Who the writes are made as (the CLI's actor resolution).
        raw_payload: The payload exactly as sent; kept, redacted, when it is rejected.
        dry_run: Plan and report, writing and keeping nothing.
    """

    space_key: Key
    candidates: tuple[CurationCandidate, ...] = ()
    rejected: tuple[RejectedEntryDto, ...] = ()
    project_key: str
    session: str
    commits: tuple[str, ...] = ()
    actor: Actor
    raw_payload: str = ""
    dry_run: bool = False


class ApplyCurationHandler(IHandler[ApplyCurationCommand, CurationResultDto]):
    """Redacts the payload, derives its key and runs the shared curation flow on it.

    The payload is redacted before its submission key, before the inbox (a kept rejected payload
    included) and before any write (NFR-001).
    """

    def __init__(self, *, runner: CurationRunner, inbox: ICurationInbox) -> None:
        self._runner: CurationRunner = runner
        self._inbox: ICurationInbox = inbox

    async def handle(self, action: ApplyCurationCommand) -> CurationResultDto:
        """Apply the candidates, or replay the earlier application of the same payload.

        Raises:
            CurationRejectedError: An entry is flawed; the redacted payload is kept (unless
                dry run) and nothing is staged or written.
            InvalidKeyError: The project key is invalid.
            GraphStoreUnavailableError: The store is down; the submission is parked.
            CurationParkedError: A step failed; the submission is parked.
            BriefAlreadyIngestedError: Registered in the store but no local plan matches.
            CurationInboxFailedError: The inbox cannot be used.
        """
        if action.rejected:
            await self._reject(action)
        Key(value=action.project_key)
        candidates: tuple[CurationCandidate, ...] = tuple(
            CurationRedactor.candidate(candidate) for candidate in action.candidates
        )
        key: str = payload_key(action.session, candidates)
        submission: CurationSubmission = CurationSubmission(
            kind=SubmissionKindEnum.APPLY,
            submission_key=key,
            project_key=action.project_key,
            session_id=action.session,
            commit_shas=action.commits,
            actor=action.actor,
            candidates=candidates,
        )
        return await self._runner.run(
            submission,
            RunOptions(
                space_key=action.space_key,
                related_lookup=RelatedLookupModeEnum.OFF,
                max_attempts=1,
                dry_run=action.dry_run,
            ),
        )

    async def _reject(self, action: ApplyCurationCommand) -> None:
        kept: str | None = None
        if not action.dry_run:
            kept = await self._inbox.keep_rejected(CurationRedactor.text(action.raw_payload))
        rejected: list[JsonValue] = [
            {"index": item.index, "reason": CurationRedactor.text(item.reason)}
            for item in action.rejected
        ]
        raise CurationRejectedError(
            f"The payload has {len(rejected)} flawed entr{'y' if len(rejected) == 1 else 'ies'}; "
            "nothing was staged or written.",
            {"rejected": rejected, "kept_file": kept},
            next_steps=[
                "Fix the entries named in `rejected`"
                + (", then apply the kept file." if kept else ".")
            ],
        )


def payload_key(session: str, candidates: tuple[CurationCandidate, ...]) -> str:
    """The submission key of an apply payload: SHA-256 of the session id and the canonical,
    redacted payload.
    """
    canonical: str = canonical_json(
        {"candidates": [candidate.model_dump(mode="json") for candidate in candidates]}
    )
    return sha256_hex(f"{session}\n{canonical}")
