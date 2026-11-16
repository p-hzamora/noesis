"""Ingest one work brief: judge it once, plan it, and write it through Knowledge's handlers."""

from pydantic import Field

from noesis.bounded_context.knowledge.application.dtos import CurationResultDto
from noesis.bounded_context.knowledge.application.mappers import WorkBriefMapper
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
    ActorKindEnum,
    CurationSubmission,
    Key,
    SubmissionKindEnum,
    WorkBrief,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.contracts import WorkBriefContract
from noesis.utils import FrozenObject

CURATOR_ACTOR_NAME: str = "noesis-curator"
"""Briefs and their retries run as this agent, with the brief's session (A-001)."""


class IngestWorkBriefCommand(FrozenObject):
    """Ingest `brief`.

    Attributes:
        brief: The published work brief.
        space_key: Key of the active space.
        max_attempts: Curator runs before giving up (2 = one automatic retry).
        park_on_failure: Whether to keep the ticket for a retry when the curator or the lookup
            fails.
        dry_run: Judge and report what would be written, writing and parking nothing.
        related_lookup: `required` (fail closed) or `off`.
    """

    brief: WorkBriefContract
    space_key: Key
    max_attempts: int = Field(default=2, ge=1)
    park_on_failure: bool = True
    dry_run: bool = False
    related_lookup: RelatedLookupModeEnum = RelatedLookupModeEnum.REQUIRED


class IngestWorkBriefHandler(IHandler[IngestWorkBriefCommand, CurationResultDto]):
    """Maps and redacts the brief, then runs the shared curation flow on it.

    The brief is redacted right after mapping, before the submission key, the inbox and the
    curator prompt (NFR-001).
    """

    def __init__(self, *, runner: CurationRunner) -> None:
        self._runner: CurationRunner = runner

    async def handle(self, action: IngestWorkBriefCommand) -> CurationResultDto:
        """Ingest the brief, or replay the earlier ingestion of the same work.

        Raises:
            InvalidKeyError: The repository name is not a valid project key.
            GraphStoreUnavailableError: The store is down; the brief is parked.
            CurationParkedError: The curator or a step failed; the brief is parked.
            RelatedLookupUnavailableError: The lookup is required and cannot answer.
            BriefAlreadyIngestedError: Registered in the store but no local plan matches.
            CurationInboxFailedError: The inbox cannot be used.
        """
        brief: WorkBrief = CurationRedactor.brief(WorkBriefMapper.to_domain(action.brief))
        Key(value=brief.repository)
        submission: CurationSubmission = CurationSubmission(
            kind=SubmissionKindEnum.BRIEF,
            submission_key=brief.submission_key(),
            project_key=brief.repository,
            session_id=brief.session_id,
            commit_shas=brief.commit_shas(),
            actor=Actor(
                kind=ActorKindEnum.AGENT, name=CURATOR_ACTOR_NAME, session=brief.session_id
            ),
            brief=brief,
        )
        return await self._runner.run(
            submission,
            RunOptions(
                space_key=action.space_key,
                related_lookup=action.related_lookup,
                max_attempts=action.max_attempts,
                park_on_failure=action.park_on_failure,
                dry_run=action.dry_run,
            ),
        )
