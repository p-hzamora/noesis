"""Wires the curation handlers (`noesis curate`) over one Neo4j client per invocation.

The composition root of curation: it hands the process manager C2's capture and revise handlers
and C4's `ProposeAssertion` (never an accept handler: capture never accepts, Q-002), gives the
runner the Claude CLI curator and Retrieval's related-record adapter, and puts the inbox under
`<state_dir>/knowledge/curation/`. Tests pass replacement adapters as keyword arguments.

`curate parked` and `curate retry --all` without `--yes` read only the inbox (`build_parked_listing`),
so they work with Neo4j down and without a password.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from noesis.bounded_context.knowledge.application.dtos import RelatedRecordDto
from noesis.bounded_context.knowledge.application.handlers.commands.apply_curation_handler import (
    ApplyCurationHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_experience_handler import (
    CaptureExperienceHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.ingest_work_brief_handler import (
    IngestWorkBriefHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.propose_assertion_handler import (
    ProposeAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.register_curation_plan_handler import (
    RegisterCurationPlanHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.retry_parked_curation_handler import (
    RetryParkedCurationHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.revise_knowledge_handler import (
    ReviseKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.list_parked_curations_handler import (
    ListParkedCurationsHandler,
)
from noesis.bounded_context.knowledge.application.ports.curation import (
    ICurationInbox,
    ICurator,
    IRelatedRecordFinder,
)
from noesis.bounded_context.knowledge.application.services.curation_process_manager import (
    CurationProcessManager,
    StepHook,
)
from noesis.bounded_context.knowledge.application.services.curation_runner import (
    CurationRunner,
    RelatedLookupModeEnum,
)
from noesis.bounded_context.knowledge.domain.services import CurationAdmissionPolicy
from noesis.bounded_context.knowledge.domain.value_objects import (
    CurationCandidate,
    CurationSubtypes,
    WorkBrief,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.curation import (
    ClaudeCliCuratorAdapter,
    JsonFileCurationInboxAdapter,
    default_system_prompt,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence import (
    KnowledgePersistence,
    build_knowledge_persistence,
)
from noesis.bounded_context.retrieval.infrastructure.inbound.knowledge.related_record_finder_adapter import (
    RelatedRecordFinderAdapter,
)
from noesis.core import CuratorRelatedLookupEnum, Environment
from noesis.exceptions import CuratorPromptUnreadableError
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.infrastructure.outbound.clock import SystemClockAdapter
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

from .knowledge_handlers_builder import EXTRA_SCHEMA_STEPS
from .retrieval_handlers_builder import build_retrieval

CURATION_FOLDER: tuple[str, ...] = ("knowledge", "curation")
"""Where the inbox lives, under the state folder."""

type Sleeper = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True, kw_only=True)
class CurationHandlers:
    """The curation actions of one invocation, wired.

    Attributes:
        ingest: Curate a work brief (`curate brief`).
        apply: Apply caller-written candidates (`curate apply`).
        retry: Retry a parked ticket (`curate retry`).
        list_parked: List the parked tickets (`curate parked`).
        inbox: The inbox the handlers share.
    """

    ingest: IngestWorkBriefHandler
    apply: ApplyCurationHandler
    retry: RetryParkedCurationHandler
    list_parked: ListParkedCurationsHandler
    inbox: ICurationInbox


def related_lookup_mode(environment: Environment) -> RelatedLookupModeEnum:
    """The related-lookup mode `NOESIS_CURATOR_RELATED_LOOKUP` selects."""
    if environment.curator.related_lookup is CuratorRelatedLookupEnum.OFF:
        return RelatedLookupModeEnum.OFF
    return RelatedLookupModeEnum.REQUIRED


def curation_system_prompt(environment: Environment) -> str:
    """The curator's system prompt: the configured file, else the packaged one.

    Raises:
        CuratorPromptUnreadableError: `NOESIS_CURATOR_SYSTEM_PROMPT_FILE` cannot be read.
    """
    prompt_file: Path | None = environment.curator.system_prompt_file
    if prompt_file is None:
        return default_system_prompt()
    path: Path = prompt_file.expanduser()
    try:
        prompt: str = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CuratorPromptUnreadableError(
            f"Cannot read the curator system prompt {path}: {error}",
            {"setting": "NOESIS_CURATOR_SYSTEM_PROMPT_FILE", "path": str(path)},
            next_steps=[
                "Fix the file, or unset NOESIS_CURATOR_SYSTEM_PROMPT_FILE to use the packaged prompt."
            ],
        ) from error
    if not prompt.strip():
        raise CuratorPromptUnreadableError(
            f"The curator system prompt {path} is empty.",
            {"setting": "NOESIS_CURATOR_SYSTEM_PROMPT_FILE", "path": str(path)},
            next_steps=[
                "Write the prompt, or unset NOESIS_CURATOR_SYSTEM_PROMPT_FILE to use the packaged prompt."
            ],
        )
    return prompt


def build_claude_curator(environment: Environment) -> ICurator:
    """The Claude CLI curator configured by `environment`."""
    return ClaudeCliCuratorAdapter(
        claude_bin=environment.curator.claude_bin,
        model=environment.curator.model,
        max_budget_usd=environment.curator.max_budget_usd,
        timeout_seconds=environment.curator.timeout_seconds,
        system_prompt=curation_system_prompt(environment),
    )


class _DeferredCurator(ICurator):
    """Builds the Claude CLI curator on first use, so `curate apply` (which never judges) does
    not read the system prompt file.
    """

    def __init__(self, environment: Environment) -> None:
        self._environment: Environment = environment
        self._curator: ICurator | None = None

    async def judge(
        self,
        brief: WorkBrief,
        related: Sequence[RelatedRecordDto],
        subtypes: CurationSubtypes,
    ) -> tuple[CurationCandidate, ...]:
        if self._curator is None:
            self._curator = build_claude_curator(self._environment)
        return await self._curator.judge(brief, related, subtypes)


def build_curation_inbox(environment: Environment, clock: IClock) -> ICurationInbox:
    """The inbox under `<state_dir>/knowledge/curation/` (nothing is created until a write)."""
    return JsonFileCurationInboxAdapter(
        environment.runtime.state_dir.joinpath(*CURATION_FOLDER), clock=clock
    )


def build_parked_listing(environment: Environment) -> ListParkedCurationsHandler:
    """The parked-ticket listing: inbox only, no Neo4j client, no password needed."""
    clock: IClock = SystemClockAdapter()
    return ListParkedCurationsHandler(inbox=build_curation_inbox(environment, clock), clock=clock)


def build_curation(
    client: Neo4jClient,
    environment: Environment,
    *,
    curator: ICurator | None = None,
    related_finder: IRelatedRecordFinder | None = None,
    step_hook: StepHook | None = None,
    assertions_available: bool = True,
    sleep: Sleeper = asyncio.sleep,
) -> CurationHandlers:
    """Wire the curation handlers over `client` (the caller closes it); opens no connection.

    Args:
        client: The invocation's Neo4j client.
        environment: Loaded settings.
        curator: Curator to use instead of the Claude CLI adapter (tests, other providers).
        related_finder: Related-record lookup to use instead of Retrieval's (tests).
        step_hook: Called before every write step with its ordinal and name; raising fails the
            step (tests).
        assertions_available: Whether C4's `ProposeAssertion` is wired. When False, no
            assertion step runs and the policy plans no `supersedes` or `supports`.
        sleep: Awaited between curator attempts (tests).
    """
    clock: IClock = SystemClockAdapter()
    persistence: KnowledgePersistence = build_knowledge_persistence(
        client, clock=clock, extra_steps=EXTRA_SCHEMA_STEPS
    )
    inbox: ICurationInbox = build_curation_inbox(environment, clock)
    finder: IRelatedRecordFinder = related_finder or RelatedRecordFinderAdapter(
        build_retrieval(client, environment).searcher
    )
    manager = CurationProcessManager(
        capture_experience=CaptureExperienceHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
        ),
        capture_knowledge=CaptureKnowledgeHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
        ),
        revise_knowledge=ReviseKnowledgeHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
        ),
        propose_assertion=(
            ProposeAssertionHandler(
                uow_factory=persistence.uow_factory,
                clock=clock,
                ids=persistence.ids,
                schema=persistence.schema,
            )
            if assertions_available
            else None
        ),
        step_hook=step_hook,
    )
    runner = CurationRunner(
        inbox=inbox,
        curator=curator or _DeferredCurator(environment),
        finder=finder,
        records=persistence.read_repository,
        uow_factory=persistence.uow_factory,
        manager=manager,
        register=RegisterCurationPlanHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
        ),
        policy=CurationAdmissionPolicy(assertions_available=assertions_available),
        retry_delay_seconds=environment.curator.retry_seconds,
        sleep=sleep,
    )
    return CurationHandlers(
        ingest=IngestWorkBriefHandler(runner=runner),
        apply=ApplyCurationHandler(runner=runner, inbox=inbox),
        retry=RetryParkedCurationHandler(runner=runner),
        list_parked=ListParkedCurationsHandler(inbox=inbox, clock=clock),
        inbox=inbox,
    )


@asynccontextmanager
async def open_curation(
    environment: Environment,
    *,
    curator: ICurator | None = None,
    related_finder: IRelatedRecordFinder | None = None,
    step_hook: StepHook | None = None,
    assertions_available: bool = True,
    sleep: Sleeper = asyncio.sleep,
) -> AsyncIterator[CurationHandlers]:
    """Handlers over a client that is closed when the block ends, however it ends.

    Raises:
        InvalidConfigurationError: `NOESIS_NEO4J_PASSWORD` is not set.
    """
    async with Neo4jClient(environment.knowledge.neo4j_connection()) as client:
        yield build_curation(
            client,
            environment,
            curator=curator,
            related_finder=related_finder,
            step_hook=step_hook,
            assertions_available=assertions_available,
            sleep=sleep,
        )
