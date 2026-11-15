"""Command builders for the C4 review handler unit tests."""

from tests.support.knowledge_commands import COMMIT
from tests.support.knowledge_support import AGENT, DEFAULT_SPACE_KEY

from noesis.bounded_context.knowledge.application.handlers.commands.accept_assertion_handler import (
    AcceptAssertionCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.accept_knowledge_handler import (
    AcceptKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.apply_supersession_handler import (
    ApplySupersessionCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.bulk_accept_knowledge_by_tag_handler import (
    BulkAcceptKnowledgeByTagCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.propose_assertion_handler import (
    ProposeAssertionCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.repair_supersession_effects_handler import (
    RepairSupersessionEffectsCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.retract_assertion_handler import (
    RetractAssertionCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.retract_knowledge_handler import (
    RetractKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.services.inputs import ProjectRef, SourceInput
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ActorKindEnum,
    AssertionPredicateEnum,
    Key,
    RecordId,
    Tag,
)

USER: Actor = Actor(kind=ActorKindEnum.USER, name="pablo")


def propose_command(
    predicate: AssertionPredicateEnum,
    subject: RecordId,
    object_: RecordId,
    key: str | None = "p1",
    *,
    evidence: tuple[RecordId, ...] = (),
    rationale: str = "Both describe the same retry rule.",
    project: str | None = None,
    tags: tuple[str, ...] = (),
    sources: tuple[SourceInput, ...] = (COMMIT,),
    actor: Actor = AGENT,
) -> ProposeAssertionCommand:
    """A valid propose command; override what a test cares about."""
    return ProposeAssertionCommand(
        idempotency_key=key,
        space_key=DEFAULT_SPACE_KEY,
        actor=actor,
        predicate=predicate,
        subject_id=subject,
        object_id=object_,
        evidence_ids=evidence,
        rationale=rationale,
        project=ProjectRef(key=Key(value=project)) if project else None,
        tags=tuple(Tag(value=t) for t in tags),
        sources=sources,
    )


def accept_knowledge_command(
    record_id: RecordId,
    key: str | None = "a1",
    *,
    expected: int | None = 1,
    actor: Actor = AGENT,
    reason: str | None = None,
    apply: bool = True,
) -> AcceptKnowledgeCommand:
    """An accept command for Knowledge."""
    return AcceptKnowledgeCommand(
        idempotency_key=key,
        space_key=DEFAULT_SPACE_KEY,
        actor=actor,
        record_id=record_id,
        expected_revision=expected,
        reason=reason,
        apply=apply,
    )


def accept_assertion_command(
    assertion_id: RecordId,
    key: str | None = "a1",
    *,
    actor: Actor = AGENT,
    reason: str | None = None,
    apply: bool = True,
) -> AcceptAssertionCommand:
    """An accept command for an Assertion."""
    return AcceptAssertionCommand(
        idempotency_key=key,
        space_key=DEFAULT_SPACE_KEY,
        actor=actor,
        assertion_id=assertion_id,
        reason=reason,
        apply=apply,
    )


def retract_knowledge_command(
    record_id: RecordId,
    key: str | None = "r1",
    *,
    reason: str = "No longer true.",
    actor: Actor = USER,
    apply: bool = True,
) -> RetractKnowledgeCommand:
    """A reject-or-retract command for Knowledge."""
    return RetractKnowledgeCommand(
        idempotency_key=key,
        space_key=DEFAULT_SPACE_KEY,
        actor=actor,
        record_id=record_id,
        reason=reason,
        apply=apply,
    )


def retract_assertion_command(
    assertion_id: RecordId,
    key: str | None = "r1",
    *,
    reason: str = "Duplicate.",
    actor: Actor = USER,
    apply: bool = True,
) -> RetractAssertionCommand:
    """A reject-or-retract command for an Assertion."""
    return RetractAssertionCommand(
        idempotency_key=key,
        space_key=DEFAULT_SPACE_KEY,
        actor=actor,
        assertion_id=assertion_id,
        reason=reason,
        apply=apply,
    )


def apply_supersession_command(
    assertion_id: RecordId, object_id: RecordId, *, actor: Actor = USER
) -> ApplySupersessionCommand:
    """The effect step of an accepted `supersedes` assertion."""
    return ApplySupersessionCommand(
        space_key=DEFAULT_SPACE_KEY, actor=actor, assertion_id=assertion_id, object_id=object_id
    )


def bulk_command(
    tag: str = "origin:migrated",
    *,
    actor: Actor = USER,
    reason: str | None = None,
    apply: bool = True,
) -> BulkAcceptKnowledgeByTagCommand:
    """A bulk accept by tag."""
    return BulkAcceptKnowledgeByTagCommand(
        space_key=DEFAULT_SPACE_KEY, actor=actor, tag=Tag(value=tag), reason=reason, apply=apply
    )


def repair_command(*, actor: Actor = USER, apply: bool = True) -> RepairSupersessionEffectsCommand:
    """`review repair`."""
    return RepairSupersessionEffectsCommand(space_key=DEFAULT_SPACE_KEY, actor=actor, apply=apply)
