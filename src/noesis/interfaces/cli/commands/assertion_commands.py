"""`noesis assertion`: propose an assertion about two records and list the ones about a record."""

import asyncio
from typing import Annotated

import typer

from noesis.bounded_context.knowledge.application.dtos import (
    AssertionDto,
    ProposeAssertionResultDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.propose_assertion_handler import (
    ProposeAssertionCommand,
)
from noesis.bounded_context.knowledge.application.handlers.queries.list_assertions_handler import (
    ListAssertionsQuery,
)
from noesis.bounded_context.knowledge.application.services.inputs import ProjectRef, SourceInput
from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    AssertionRoleEnum,
    Key,
    RecordId,
    RecordStatusEnum,
    Tag,
)
from noesis.core import Environment
from noesis.interfaces.cli import output
from noesis.interfaces.cli.actor import resolve_actor
from noesis.interfaces.cli.bootstrap import with_knowledge
from noesis.interfaces.cli.commands.record_commands import (
    IdempotencyKeyOption,
    SourceIdOption,
    SourceOption,
    _parse_sources,
    _usage,
)
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.responses import AssertionListResponse, AssertionProposeResponse
from noesis.interfaces.cli.state import cli_state

assertion_app: typer.Typer = typer.Typer(
    help="Propose assertions about records and list the ones about a record.",
    no_args_is_help=True,
)


@assertion_app.command("propose")
def propose(
    context: typer.Context,
    predicate: Annotated[
        AssertionPredicateEnum,
        typer.Option("--predicate", help="How the subject relates to the object."),
    ],
    subject: Annotated[str, typer.Option("--subject", help="Id of the subject record.")],
    object_: Annotated[str, typer.Option("--object", help="Id of the object record.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why the assertion holds.")],
    idempotency_key: IdempotencyKeyOption,
    evidence: Annotated[
        list[str] | None,
        typer.Option("--evidence", help="Id of a record that evidences it (repeatable)."),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option(
            "--project",
            help="Project key it applies to (default: space-wide; no git fallback here).",
        ),
    ] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", help="A tag (repeatable).")] = None,
    source: SourceOption = None,
    source_id: SourceIdOption = None,
    as_json: JsonOption = False,
) -> None:
    """Propose an assertion (status proposed); at least one source is required."""
    sources: tuple[SourceInput, ...] = _parse_sources(context, source, source_id)
    if not sources:
        raise _usage(context, "Cite at least one source.", "--source")
    if not rationale.strip():
        raise _usage(context, "Give a non-empty rationale.", "--rationale")
    env: Environment = cli_state(context).environment()
    command = ProposeAssertionCommand(
        idempotency_key=idempotency_key,
        space_key=Key(value=env.knowledge.knowledge_space),
        actor=resolve_actor(env.identity),
        predicate=predicate,
        subject_id=RecordId(value=subject),
        object_id=RecordId(value=object_),
        evidence_ids=tuple(RecordId(value=item) for item in evidence or ()),
        rationale=rationale,
        project=ProjectRef(key=Key(value=project)) if project else None,
        tags=tuple(Tag(value=item) for item in tag or ()),
        sources=sources,
    )
    result: ProposeAssertionResultDto = asyncio.run(
        with_knowledge(env, lambda handlers: handlers.propose_assertion.handle(command))
    )
    output.emit(AssertionProposeResponse.from_dto(result))


@assertion_app.command("list")
def list_assertions(
    context: typer.Context,
    about: Annotated[
        str, typer.Option("--about", help="Id of the record to list assertions about.")
    ],
    role: Annotated[
        AssertionRoleEnum,
        typer.Option("--role", help="The part the record plays: subject, object, evidence, any."),
    ] = AssertionRoleEnum.ANY,
    predicate: Annotated[
        list[AssertionPredicateEnum] | None,
        typer.Option("--predicate", help="Keep this predicate (repeatable)."),
    ] = None,
    status: Annotated[
        list[RecordStatusEnum] | None,
        typer.Option("--status", help="Keep this stored status (repeatable)."),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """List the assertions about a record, ascending id, with the state of both ends."""
    env: Environment = cli_state(context).environment()
    query = ListAssertionsQuery(
        space_key=Key(value=env.knowledge.knowledge_space),
        record_id=RecordId(value=about),
        role=role,
        predicates=tuple(predicate or ()),
        statuses=tuple(status or ()),
    )
    found: list[AssertionDto] = asyncio.run(
        with_knowledge(env, lambda handlers: handlers.list_assertions.handle(query))
    )
    output.emit(AssertionListResponse.from_dtos(found))
