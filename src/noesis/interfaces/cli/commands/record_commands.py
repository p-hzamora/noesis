"""`noesis record`: capture, revise and read records of the knowledge store."""

import asyncio
import sys
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from noesis.bounded_context.knowledge.application.dtos import (
    CaptureResultDto,
    RecordDto,
    ReviseResultDto,
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
from noesis.bounded_context.knowledge.application.handlers.queries.get_record_handler import (
    GetRecordQuery,
)
from noesis.bounded_context.knowledge.application.services.inputs import (
    ExistingSourceInput,
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
    Tag,
)
from noesis.core import Environment
from noesis.core.git_root import find_common_dir, repository_name
from noesis.interfaces.cli import output
from noesis.interfaces.cli.actor import resolve_actor
from noesis.interfaces.cli.bootstrap import with_knowledge
from noesis.interfaces.cli.bootstrap.retrieval_handlers_builder import trigger_index_sync
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.responses import (
    RecordCaptureResponse,
    RecordResponse,
    RecordReviseResponse,
)
from noesis.interfaces.cli.state import cli_state

record_app: typer.Typer = typer.Typer(
    help="Capture, revise and read records of the knowledge store.", no_args_is_help=True
)

STDIN_MARKER: str = "-"


class RecordTypeOption(StrEnum):
    """The record types `record capture` can create."""

    KNOWLEDGE = "knowledge"
    EXPERIENCE = "experience"


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
ProjectOption = Annotated[
    str | None,
    typer.Option(
        "--project",
        help="Project key (default: the name of the git repository of the working directory).",
    ),
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


def _usage(context: typer.Context, message: str, hint: str) -> typer.BadParameter:
    return typer.BadParameter(message, ctx=context, param_hint=hint)


def _read_body(context: typer.Context, body: str | None, *, required: bool) -> str | None:
    """The text from `--body`; `-` reads stdin (never read implicitly, so nothing can block)."""
    if body is None:
        if required:
            raise _usage(context, "Give the text with --body (use `-` for stdin).", "--body")
        return None
    return sys.stdin.read() if body == STDIN_MARKER else body


def _parse_sources(
    context: typer.Context, sources: list[str] | None, source_ids: list[str] | None
) -> tuple[SourceInput, ...]:
    """Source inputs from `--source <kind>:<locator>` and `--source-id <ULID>` values."""
    parsed: list[SourceInput] = []
    for raw in sources or ():
        kind, separator, locator = raw.partition(":")
        if not separator or not locator.strip():
            raise _usage(context, f"Expected <kind>:<locator>, got {raw!r}.", "--source")
        try:
            source_kind = SourceKindEnum(kind.strip())
        except ValueError:
            allowed: str = ", ".join(item.value for item in SourceKindEnum)
            raise _usage(
                context, f"Unknown source kind {kind!r}; use one of: {allowed}.", "--source"
            ) from None
        parsed.append(NewSourceInput(kind=source_kind, locator=locator.strip()))
    parsed.extend(ExistingSourceInput(source_id=RecordId(value=item)) for item in source_ids or ())
    return tuple(parsed)


def _project_ref(project: str | None) -> ProjectRef | None:
    """The `--project` key, else the git repository name of the working directory (D-022)."""
    if project is not None:
        return ProjectRef(key=Key(value=project))
    common_dir: Path | None = find_common_dir(Path.cwd())
    return ProjectRef(key=Key(value=repository_name(common_dir))) if common_dir else None


def _parse_occurred(context: typer.Context, occurred: str | None) -> datetime | None:
    if occurred is None:
        return None
    try:
        moment: datetime = datetime.fromisoformat(occurred)
    except ValueError:
        raise _usage(
            context, f"Expected an ISO 8601 time, got {occurred!r}.", "--occurred"
        ) from None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _required(context: typer.Context, value: str | None, option: str) -> str:
    if value is None or not value.strip():
        raise _usage(context, f"{option} is required for this record type.", option)
    return value


@record_app.command("capture")
def capture(
    context: typer.Context,
    record_type: Annotated[
        RecordTypeOption, typer.Option("--type", help="What to record: knowledge or experience.")
    ],
    idempotency_key: IdempotencyKeyOption,
    title: Annotated[str | None, typer.Option("--title", help="Knowledge: short title.")] = None,
    body: BodyOption = None,
    subtype: Annotated[
        str | None,
        typer.Option(
            "--subtype",
            help="Knowledge: a slug such as `decision` or `gotcha` (required). Experience: "
            "observation, outcome or failure (default observation).",
        ),
    ] = None,
    project: ProjectOption = None,
    tag: Annotated[
        list[str] | None, typer.Option("--tag", help="Knowledge: a tag (repeatable).")
    ] = None,
    source: SourceOption = None,
    source_id: SourceIdOption = None,
    occurred: Annotated[
        str | None,
        typer.Option("--occurred", help="Experience: when it happened (ISO 8601; default now)."),
    ] = None,
    session: Annotated[
        str | None, typer.Option("--session", help="Experience: harness session id.")
    ] = None,
    environment: Annotated[
        str | None, typer.Option("--environment", help="Experience: where it happened.")
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Record knowledge (a proposal) or an experience; at least one source is required."""
    text: str = _read_body(context, body, required=True) or ""
    sources: tuple[SourceInput, ...] = _parse_sources(context, source, source_id)
    if not sources:
        raise _usage(context, "Cite at least one source.", "--source")
    result: CaptureResultDto
    if record_type is RecordTypeOption.KNOWLEDGE:
        title_text: str = _required(context, title, "--title")
        subtype_text: str = _required(context, subtype, "--subtype")
        env: Environment = cli_state(context).environment()
        knowledge_command = CaptureKnowledgeCommand(
            idempotency_key=idempotency_key,
            space_key=Key(value=env.knowledge.knowledge_space),
            title=title_text,
            body=text,
            subtype=Slug(value=subtype_text),
            actor=resolve_actor(env.identity),
            project=_project_ref(project),
            tags=tuple(Tag(value=item) for item in tag or ()),
            sources=sources,
        )
        result = asyncio.run(
            with_knowledge(
                env, lambda handlers: handlers.capture_knowledge.handle(knowledge_command)
            )
        )
    else:
        env = cli_state(context).environment()
        experience_command = CaptureExperienceCommand(
            idempotency_key=idempotency_key,
            space_key=Key(value=env.knowledge.knowledge_space),
            subtype=_experience_subtype(context, subtype),
            body=text,
            actor=resolve_actor(env.identity),
            occurred_at=_parse_occurred(context, occurred),
            project=_project_ref(project),
            session=session,
            environment=environment,
            sources=sources,
        )
        result = asyncio.run(
            with_knowledge(
                env, lambda handlers: handlers.capture_experience.handle(experience_command)
            )
        )
    if not result.replayed:
        trigger_index_sync(env)
    output.emit(RecordCaptureResponse.model_validate(result, from_attributes=True))


def _experience_subtype(context: typer.Context, subtype: str | None) -> ExperienceSubtypeEnum:
    try:
        return ExperienceSubtypeEnum(subtype or ExperienceSubtypeEnum.OBSERVATION.value)
    except ValueError:
        allowed: str = ", ".join(item.value for item in ExperienceSubtypeEnum)
        raise _usage(
            context, f"Unknown experience subtype {subtype!r}; use one of: {allowed}.", "--subtype"
        ) from None


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
    text: str | None = _read_body(context, body, required=False)
    sources: tuple[SourceInput, ...] = _parse_sources(context, source, source_id)
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
