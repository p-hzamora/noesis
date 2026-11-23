"""`noesis review`: the queue, accept, retract, the decision log and repair.

Check order (20-review.md): usage errors (exit 2, no I/O); user presence, then the bulk
accept's actor check (the handler, before any store access); store access; the rest is the
handlers'. Without `--yes` a command runs every check and writes nothing.
"""

import asyncio
from enum import StrEnum
from typing import Annotated

import typer

from noesis.bounded_context.knowledge.application.dtos import (
    AcceptResultDto,
    BulkAcceptResultDto,
    RepairResultDto,
    RetractResultDto,
    ReviewDecisionDto,
    ReviewQueuePageDto,
    ReviewStateDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.accept_assertion_handler import (
    AcceptAssertionCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.accept_knowledge_handler import (
    AcceptKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.bulk_accept_knowledge_by_tag_handler import (
    BulkAcceptKnowledgeByTagCommand,
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
from noesis.bounded_context.knowledge.application.handlers.queries.get_review_states_handler import (
    GetReviewStatesQuery,
)
from noesis.bounded_context.knowledge.application.handlers.queries.list_review_decisions_handler import (
    ListReviewDecisionsQuery,
)
from noesis.bounded_context.knowledge.application.handlers.queries.list_review_queue_handler import (
    ListReviewQueueQuery,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    AssertionPredicateEnum,
    Key,
    RecordId,
    RecordTypeEnum,
    Tag,
)
from noesis.core import Environment
from noesis.exceptions import RecordNotFoundError, RecordNotReviewableError
from noesis.interfaces.cli import output
from noesis.interfaces.cli.actor import resolve_actor
from noesis.interfaces.cli.bootstrap import KnowledgeHandlers, with_knowledge
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.record_inputs import usage
from noesis.interfaces.cli.responses import (
    ReviewAcceptResponse,
    ReviewBulkAcceptResponse,
    ReviewLogResponse,
    ReviewQueueResponse,
    ReviewRepairResponse,
    ReviewRetractResponse,
)
from noesis.interfaces.cli.state import cli_state
from noesis.interfaces.cli.user_presence import require_user_presence

review_app: typer.Typer = typer.Typer(
    help="Review what agents proposed: the queue, accept, retract, the log and repair.",
    no_args_is_help=True,
)

DEFAULT_QUEUE_LIMIT: int = 50

YesOption = Annotated[
    bool, typer.Option("--yes", help="Apply the decision (without it, only preview it).")
]
ReasonOption = Annotated[str | None, typer.Option("--reason", help="Why; stored on the decision.")]


class QueueTypeOption(StrEnum):
    """The record types the review queue holds."""

    KNOWLEDGE = "knowledge"
    ASSERTION = "assertion"


async def _state_of(
    handlers: KnowledgeHandlers, space_key: Key, record_id: RecordId
) -> ReviewStateDto:
    """The review state of the record a transition targets.

    Raises:
        RecordNotFoundError: Unknown id, or a record of another space.
        RecordNotReviewableError: The record's type has no status.
    """
    states: list[ReviewStateDto] = await handlers.get_review_states.handle(
        GetReviewStatesQuery(space_key=space_key, record_ids=(record_id,))
    )
    if not states:
        raise RecordNotFoundError(
            f"No record {record_id.value} in this space.",
            {"record_id": record_id.value},
            next_steps=["Check the id and the active space."],
        )
    state: ReviewStateDto = states[0]
    if state.record_type not in (RecordTypeEnum.KNOWLEDGE.value, RecordTypeEnum.ASSERTION.value):
        raise RecordNotReviewableError(
            f"A {state.record_type} has no review status.",
            {"record_id": record_id.value, "record_type": state.record_type},
        )
    return state


@review_app.command("queue")
def queue(
    context: typer.Context,
    project: Annotated[
        str | None,
        typer.Option("--project", help="This project's items plus the space-wide ones."),
    ] = None,
    global_only: Annotated[bool, typer.Option("--global", help="Only space-wide items.")] = False,
    record_type: Annotated[
        QueueTypeOption | None, typer.Option("--type", help="Only knowledge or only assertions.")
    ] = None,
    predicate: Annotated[
        AssertionPredicateEnum | None,
        typer.Option("--predicate", help="Only assertions with this predicate."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, show_default=True, help="Page size (a positive integer)."),
    ] = DEFAULT_QUEUE_LIMIT,
    cursor: Annotated[
        str | None, typer.Option("--cursor", help="The previous page's next_cursor.")
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """List proposed knowledge and assertions, ascending id, and who may decide each."""
    if project is not None and global_only:
        raise usage(context, "--project and --global exclude each other.", "--global")
    env: Environment = cli_state(context).environment()
    query = ListReviewQueueQuery(
        space_key=Key(value=env.knowledge.knowledge_space),
        actor=resolve_actor(env.identity),
        project=Key(value=project) if project else None,
        global_only=global_only,
        record_type=RecordTypeEnum(record_type.value) if record_type else None,
        predicate=predicate,
        limit=limit,
        cursor=cursor,
    )
    page: ReviewQueuePageDto = asyncio.run(
        with_knowledge(env, lambda handlers: handlers.list_review_queue.handle(query))
    )
    output.emit(ReviewQueueResponse.from_dto(page))


def _check_accept_usage(
    context: typer.Context,
    record_id: str | None,
    tag: str | None,
    all_records: bool,
    expected_revision: int | None,
    yes: bool,
    idempotency_key: str | None,
) -> bool:
    """Validate the shape of `review accept`; True for the bulk form."""
    if tag is None and not all_records:
        if record_id is None:
            raise usage(context, "Give a record id, or --tag with --all.", "ID")
        if yes and not idempotency_key:
            raise usage(context, "--idempotency-key is required with --yes.", "--idempotency-key")
        return False
    if tag is None or not all_records:
        raise usage(context, "The bulk accept needs both --tag and --all.", "--tag")
    if record_id is not None:
        raise usage(context, "--tag cannot be combined with a record id.", "ID")
    if expected_revision is not None:
        raise usage(context, "--expected-revision does not apply to --tag.", "--expected-revision")
    if idempotency_key is not None:
        raise usage(context, "--idempotency-key does not apply to --tag.", "--idempotency-key")
    return True


@review_app.command("accept")
def accept(
    context: typer.Context,
    record_id: Annotated[
        str | None, typer.Argument(help="Id of the knowledge or assertion to accept.")
    ] = None,
    expected_revision: Annotated[
        int | None,
        typer.Option(
            "--expected-revision",
            min=1,
            help="Knowledge: the head revision you judged (see `record get`).",
        ),
    ] = None,
    reason: ReasonOption = None,
    yes: YesOption = False,
    idempotency_key: Annotated[
        str | None,
        typer.Option(
            "--idempotency-key", help="Key of this decision (required with --yes for an id)."
        ),
    ] = None,
    tag: Annotated[
        str | None,
        typer.Option("--tag", help="Bulk accept: every proposed knowledge record with this tag."),
    ] = None,
    all_records: Annotated[
        bool, typer.Option("--all", help="Bulk accept: confirms the whole tag.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Accept a proposed record, or (--tag T --all) every proposed record carrying a tag.

    Without --yes nothing is written: the result shows what would happen. Only the user
    applies the bulk accept, in a terminal.
    """
    bulk: bool = _check_accept_usage(
        context, record_id, tag, all_records, expected_revision, yes, idempotency_key
    )
    env: Environment = cli_state(context).environment()
    actor: Actor = resolve_actor(env.identity)
    require_user_presence(actor, applying=yes)
    space_key: Key = Key(value=env.knowledge.knowledge_space)
    if bulk:
        bulk_command = BulkAcceptKnowledgeByTagCommand(
            space_key=space_key,
            actor=actor,
            tag=Tag(value=tag or ""),
            reason=reason,
            apply=yes,
        )
        bulk_result: BulkAcceptResultDto = asyncio.run(
            with_knowledge(env, lambda handlers: handlers.bulk_accept.handle(bulk_command))
        )
        output.emit(ReviewBulkAcceptResponse.from_dto(bulk_result))
        return
    target: RecordId = RecordId(value=record_id or "")

    async def run(handlers: KnowledgeHandlers) -> AcceptResultDto:
        state: ReviewStateDto = await _state_of(handlers, space_key, target)
        if state.record_type == RecordTypeEnum.KNOWLEDGE.value:
            return await handlers.accept_knowledge.handle(
                AcceptKnowledgeCommand(
                    space_key=space_key,
                    actor=actor,
                    apply=yes,
                    idempotency_key=idempotency_key,
                    record_id=target,
                    expected_revision=expected_revision,
                    reason=reason,
                )
            )
        return await handlers.accept_assertion.handle(
            AcceptAssertionCommand(
                space_key=space_key,
                actor=actor,
                apply=yes,
                idempotency_key=idempotency_key,
                assertion_id=target,
                reason=reason,
            )
        )

    result: AcceptResultDto = asyncio.run(with_knowledge(env, run))
    output.emit(ReviewAcceptResponse.from_dto(result))


@review_app.command("retract")
def retract(
    context: typer.Context,
    record_id: Annotated[str, typer.Argument(help="Id of the knowledge or assertion.")],
    reason: Annotated[str, typer.Option("--reason", help="Why (required; stored).")],
    yes: YesOption = False,
    idempotency_key: Annotated[
        str | None,
        typer.Option("--idempotency-key", help="Key of this decision (required with --yes)."),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Reject a proposed record or retract an accepted one; nothing is deleted.

    Without --yes nothing is written: the result shows what would happen.
    """
    if not reason.strip():
        raise usage(context, "Give a non-empty reason.", "--reason")
    if yes and not idempotency_key:
        raise usage(context, "--idempotency-key is required with --yes.", "--idempotency-key")
    env: Environment = cli_state(context).environment()
    actor: Actor = resolve_actor(env.identity)
    require_user_presence(actor, applying=yes)
    space_key: Key = Key(value=env.knowledge.knowledge_space)
    target: RecordId = RecordId(value=record_id)

    async def run(handlers: KnowledgeHandlers) -> RetractResultDto:
        state: ReviewStateDto = await _state_of(handlers, space_key, target)
        if state.record_type == RecordTypeEnum.KNOWLEDGE.value:
            return await handlers.retract_knowledge.handle(
                RetractKnowledgeCommand(
                    space_key=space_key,
                    actor=actor,
                    apply=yes,
                    idempotency_key=idempotency_key,
                    record_id=target,
                    reason=reason,
                )
            )
        return await handlers.retract_assertion.handle(
            RetractAssertionCommand(
                space_key=space_key,
                actor=actor,
                apply=yes,
                idempotency_key=idempotency_key,
                assertion_id=target,
                reason=reason,
            )
        )

    result: RetractResultDto = asyncio.run(with_knowledge(env, run))
    output.emit(ReviewRetractResponse.from_dto(result))


@review_app.command("log")
def log(
    context: typer.Context,
    record_id: Annotated[str, typer.Argument(help="Id of the record.")],
    as_json: JsonOption = False,
) -> None:
    """Show the decisions taken on a record, ordered by sequence."""
    env: Environment = cli_state(context).environment()
    query = ListReviewDecisionsQuery(
        space_key=Key(value=env.knowledge.knowledge_space), record_id=RecordId(value=record_id)
    )
    decisions: list[ReviewDecisionDto] = asyncio.run(
        with_knowledge(env, lambda handlers: handlers.list_review_decisions.handle(query))
    )
    output.emit(ReviewLogResponse.from_dtos(decisions))


@review_app.command("repair")
def repair(
    context: typer.Context,
    yes: YesOption = False,
    as_json: JsonOption = False,
) -> None:
    """Run every supersession effect that is still pending (a crash can leave one behind).

    Without --yes it only lists them.
    """
    env: Environment = cli_state(context).environment()
    command = RepairSupersessionEffectsCommand(
        space_key=Key(value=env.knowledge.knowledge_space),
        actor=resolve_actor(env.identity),
        apply=yes,
    )
    result: RepairResultDto = asyncio.run(
        with_knowledge(env, lambda handlers: handlers.repair_supersession.handle(command))
    )
    output.emit(ReviewRepairResponse.from_dto(result))
