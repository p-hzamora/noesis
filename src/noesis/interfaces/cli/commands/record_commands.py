"""`noesis record`: revise and read records of the knowledge store."""

import asyncio
from typing import Annotated

import typer

from noesis.bounded_context.knowledge.application.dtos import (
    RecordDto,
    ReviseResultDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.revise_knowledge_handler import (
    ReviseKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.handlers.queries.get_record_handler import (
    GetRecordQuery,
)
from noesis.bounded_context.knowledge.application.services.inputs import (
    ExistingSourceInput,
    NewSourceInput,
    SourceInput,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Key,
    RecordId,
    SourceKindEnum,
)
from noesis.core import Environment
from noesis.interfaces.cli import output
from noesis.interfaces.cli.actor import resolve_actor
from noesis.interfaces.cli.bootstrap import with_knowledge
from noesis.interfaces.cli.bootstrap.retrieval_handlers_builder import trigger_index_sync
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.record_inputs import read_body, usage
from noesis.interfaces.cli.responses import RecordResponse, RecordReviseResponse
from noesis.interfaces.cli.state import cli_state

record_app: typer.Typer = typer.Typer(
    help="Revise and read records of the knowledge store.", no_args_is_help=True
)

IdempotencyKeyOption = Annotated[
    str,
    typer.Option(
        "--idempotency-key",
        help="Deterministic key of this request (required). Retrying with the same key and "
        "request returns the first result without writing again.",
    ),
]
BodyOption = Annotated[
    str | None,
    typer.Option("--body", help="The text; `-` reads it from stdin."),
]
SourceOption = Annotated[
    list[str] | None,
    typer.Option(
        "--source",
        help="A source as <kind>:<locator> (repeatable). Kinds: "
        + ", ".join(kind.value for kind in SourceKindEnum)
        + ".",
    ),
]
SourceIdOption = Annotated[
    list[str] | None,
    typer.Option(
        "--source-id", help="Id of a source already in the store, cited as is (repeatable)."
    ),
]


def parse_sources(
    context: typer.Context, sources: list[str] | None, source_ids: list[str] | None
) -> tuple[SourceInput, ...]:
    """Source inputs from `--source <kind>:<locator>` and `--source-id <ULID>` values."""
    parsed: list[SourceInput] = []
    for raw in sources or ():
        kind, separator, locator = raw.partition(":")
        if not separator or not locator.strip():
            raise usage(context, f"Expected <kind>:<locator>, got {raw!r}.", "--source")
        try:
            source_kind = SourceKindEnum(kind.strip())
        except ValueError:
            allowed: str = ", ".join(item.value for item in SourceKindEnum)
            raise usage(
                context, f"Unknown source kind {kind!r}; use one of: {allowed}.", "--source"
            ) from None
        parsed.append(NewSourceInput(kind=source_kind, locator=locator.strip()))
    parsed.extend(ExistingSourceInput(source_id=RecordId(value=item)) for item in source_ids or ())
    return tuple(parsed)


@record_app.command("revise")
def revise(
    context: typer.Context,
    record_id: Annotated[str, typer.Argument(help="Id of the knowledge to revise.")],
    expected_revision: Annotated[
        int,
        typer.Option(
            "--expected-revision",
            min=1,
            help="The head revision your change is based on (see `record get`).",
        ),
    ],
    idempotency_key: IdempotencyKeyOption,
    title: Annotated[str | None, typer.Option("--title", help="New title.")] = None,
    body: BodyOption = None,
    source: SourceOption = None,
    source_id: SourceIdOption = None,
    as_json: JsonOption = False,
) -> None:
    """Append a revision to proposed knowledge; what you leave out stays as it was."""
    text: str | None = read_body(context, body, required=False)
    sources: tuple[SourceInput, ...] = parse_sources(context, source, source_id)
    env: Environment = cli_state(context).environment()
    command = ReviseKnowledgeCommand(
        idempotency_key=idempotency_key,
        space_key=Key(value=env.knowledge.knowledge_space),
        record_id=RecordId(value=record_id),
        expected_revision=expected_revision,
        actor=resolve_actor(env.identity),
        title=title,
        body=text,
        sources=sources,
    )
    result: ReviseResultDto = asyncio.run(
        with_knowledge(env, lambda handlers: handlers.revise_knowledge.handle(command))
    )
    if not result.replayed:
        trigger_index_sync(env)
    output.emit(RecordReviseResponse.model_validate(result, from_attributes=True))


@record_app.command("get")
def get(
    context: typer.Context,
    record_id: Annotated[str, typer.Argument(help="Id of the record.")],
    revision: Annotated[
        int | None,
        typer.Option("--revision", min=1, help="Show this revision (default: the head)."),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Read a record of the active space, at its head or at one revision."""
    env: Environment = cli_state(context).environment()
    query = GetRecordQuery(
        space_key=Key(value=env.knowledge.knowledge_space),
        record_id=RecordId(value=record_id),
        revision=revision,
    )
    record: RecordDto = asyncio.run(
        with_knowledge(env, lambda handlers: handlers.get_record.handle(query))
    )
    output.emit(RecordResponse.model_validate(record, from_attributes=True))
