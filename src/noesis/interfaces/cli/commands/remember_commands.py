"""`noesis remember`: capture knowledge or an experience on purpose, reconciled with the store."""

from pathlib import Path
from typing import Annotated

import typer

from noesis.bounded_context.knowledge.application.dtos import RememberResultDto
from noesis.bounded_context.knowledge.application.handlers.commands.remember_handler import (
    RememberCommand,
    RememberKindEnum,
)
from noesis.bounded_context.knowledge.application.services.inputs import SourceInput
from noesis.bounded_context.knowledge.domain.value_objects import (
    ExperienceSubtypeEnum,
    Key,
    RecordId,
    Slug,
    Tag,
)
from noesis.core import Environment
from noesis.interfaces.cli import output
from noesis.interfaces.cli.actor import resolve_actor
from noesis.interfaces.cli.commands.record_commands import (
    BodyOption,
    SourceIdOption,
    SourceOption,
    parse_sources,
)
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.record_inputs import (
    experience_subtype,
    parse_occurred,
    read_body,
    required,
    usage,
)
from noesis.interfaces.cli.remember_support import execute_remember, resolve_scope
from noesis.interfaces.cli.responses import RememberResponse
from noesis.interfaces.cli.state import cli_state


def remember(
    context: typer.Context,
    kind: Annotated[
        RememberKindEnum,
        typer.Option("--as", help="What to remember: knowledge (a proposal) or experience."),
    ],
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
    source: SourceOption = None,
    source_id: SourceIdOption = None,
    project: Annotated[
        str | None,
        typer.Option(
            "--project",
            help="Project key (default: the git repository of the working directory).",
        ),
    ] = None,
    target_root: Annotated[
        Path | None,
        typer.Option(
            "--target-root",
            file_okay=False,
            help="Anchor it to the repository at this root instead of the working directory.",
        ),
    ] = None,
    space_wide: Annotated[
        bool, typer.Option("--space-wide", help="Apply to the whole space, not one project.")
    ] = False,
    tag: Annotated[
        list[str] | None, typer.Option("--tag", help="Knowledge: a tag (repeatable).")
    ] = None,
    refines: Annotated[
        list[str] | None,
        typer.Option(
            "--refines",
            help="Propose that this refines a knowledge record or catalog entry: an id, "
            "`record:<id>` or `catalog:<kind>:<name>` (repeatable).",
        ),
    ] = None,
    supersedes: Annotated[
        str | None,
        typer.Option(
            "--supersedes",
            help="Knowledge: id of the knowledge this should supersede (proposed; the old record "
            "is unchanged until a review accepts).",
        ),
    ] = None,
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
    idempotency_key: Annotated[
        str | None,
        typer.Option(
            "--idempotency-key",
            help="Key of this request (default: derived from the request, so a repeat replays). "
            "Rerun with the same key to complete assertions that failed.",
        ),
    ] = None,
    check: Annotated[
        bool,
        typer.Option("--check", help="Report duplicates and related records and write nothing."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Remember knowledge (proposed) or an experience; at least one source is required."""
    text: str = read_body(context, body, required=True) or ""
    sources: tuple[SourceInput, ...] = parse_sources(context, source, source_id)
    if not sources:
        raise usage(context, "Cite at least one source.", "--source")
    if sum((project is not None, target_root is not None, space_wide)) > 1:
        raise usage(
            context, "Choose only one of --project, --target-root and --space-wide.", "--project"
        )
    if kind is RememberKindEnum.EXPERIENCE and (supersedes or tag or title):
        raise usage(context, "--title, --tag and --supersedes apply to knowledge only.", "--as")
    env: Environment = cli_state(context).environment()
    scope_project, scope_source = resolve_scope(project, target_root, space_wide=space_wide)
    knowledge: bool = kind is RememberKindEnum.KNOWLEDGE
    command = RememberCommand(
        kind=kind,
        space_key=Key(value=env.knowledge.knowledge_space),
        actor=resolve_actor(env.identity),
        project=scope_project,
        sources=sources,
        body=text,
        title=required(context, title, "--title") if knowledge else None,
        knowledge_subtype=Slug(value=required(context, subtype, "--subtype"))
        if knowledge
        else None,
        tags=tuple(Tag(value=item) for item in tag or ()),
        experience_subtype=(
            ExperienceSubtypeEnum.OBSERVATION if knowledge else experience_subtype(context, subtype)
        ),
        occurred_at=parse_occurred(context, occurred),
        session=session,
        environment=environment,
        refines=tuple(refines or ()),
        supersedes=RecordId(value=supersedes) if supersedes else None,
        idempotency_key=idempotency_key,
        check=check,
    )
    result: RememberResultDto = execute_remember(env, command)
    output.emit(
        RememberResponse.model_validate(
            {
                **result.model_dump(),
                "scope": {
                    "project_key": scope_project.key.value if scope_project else None,
                    "source": scope_source,
                },
            }
        )
    )
