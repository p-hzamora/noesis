"""Command builders and a racing unit-of-work factory for Knowledge handler unit tests."""

from collections.abc import Awaitable, Callable

from tests.support.knowledge_support import (
    AGENT,
    DEFAULT_SPACE_KEY,
    FakeKnowledgeStore,
    FakeKnowledgeUnitOfWork,
)

from noesis.bounded_context.knowledge.application.handlers.commands.capture_experience_handler import (
    CaptureExperienceCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.revise_knowledge_handler import (
    ReviseKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.services.inputs import (
    NewSourceInput,
    ProjectRef,
    SourceInput,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    ExperienceSubtypeEnum,
    Key,
    RecordId,
    Slug,
    SourceKindEnum,
)

DEFAULT_PROJECT: ProjectRef = ProjectRef(key=Key(value="noesis"))
COMMIT: NewSourceInput = NewSourceInput(kind=SourceKindEnum.COMMIT, locator="a" * 40)


def knowledge_command(
    key: str = "k1",
    *,
    title: str = "Retry policy",
    body: str = "Use retries.",
    project: ProjectRef | None = DEFAULT_PROJECT,
    sources: tuple[SourceInput, ...] = (COMMIT,),
    space_key: Key = DEFAULT_SPACE_KEY,
) -> CaptureKnowledgeCommand:
    """A valid capture command; override what a test cares about."""
    return CaptureKnowledgeCommand(
        idempotency_key=key,
        space_key=space_key,
        title=title,
        body=body,
        subtype=Slug(value="decision"),
        actor=AGENT,
        project=project,
        sources=sources,
    )


def experience_command(
    key: str = "e1",
    *,
    body: str = "deploy failed",
    sources: tuple[SourceInput, ...] = (COMMIT,),
    **overrides: object,
) -> CaptureExperienceCommand:
    """A valid experience command; override what a test cares about."""
    values: dict[str, object] = {
        "idempotency_key": key,
        "space_key": DEFAULT_SPACE_KEY,
        "subtype": ExperienceSubtypeEnum.FAILURE,
        "body": body,
        "actor": AGENT,
        "sources": sources,
    }
    return CaptureExperienceCommand(**{**values, **overrides})  # type: ignore[arg-type]


def revise_command(
    record_id: RecordId,
    key: str = "r1",
    *,
    expected: int = 1,
    **overrides: object,
) -> ReviseKnowledgeCommand:
    """A valid revise command; override what a test cares about."""
    values: dict[str, object] = {
        "idempotency_key": key,
        "space_key": DEFAULT_SPACE_KEY,
        "record_id": record_id,
        "expected_revision": expected,
        "actor": AGENT,
        "body": "Use retries with jitter.",
    }
    return ReviseKnowledgeCommand(**{**values, **overrides})  # type: ignore[arg-type]


class RacingUnitOfWork(FakeKnowledgeUnitOfWork):
    """Runs `hook` once, just before the first commit.

    The hook commits a competing unit of work, so this one loses the uniqueness or
    revision race exactly as a database constraint would make it.
    """

    def __init__(
        self, store: FakeKnowledgeStore, hook: Callable[[], Awaitable[None]], fired: list[bool]
    ) -> None:
        super().__init__(store)
        self._hook = hook
        self._fired = fired

    async def commit(self) -> None:
        """Let the competitor win first, once."""
        if not self._fired:
            self._fired.append(True)
            await self._hook()
        await super().commit()


def racing_factory(
    store: FakeKnowledgeStore, hook: Callable[[], Awaitable[None]]
) -> Callable[[], FakeKnowledgeUnitOfWork]:
    """A unit-of-work factory whose first commit is preceded by `hook`."""
    fired: list[bool] = []
    return lambda: RacingUnitOfWork(store, hook, fired)
