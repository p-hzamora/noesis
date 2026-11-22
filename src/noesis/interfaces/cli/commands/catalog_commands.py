"""`noesis catalog`: register capabilities, sync them from what is installed, check availability."""

import asyncio
from typing import Annotated

import typer

from noesis.bounded_context.knowledge.application.dtos import (
    AvailabilityReportDto,
    CatalogEntryDetailDto,
    CatalogEntryDto,
    CatalogWriteResultDto,
    RuntimeEnum,
    ScanReportDto,
    SyncReportDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.register_catalog_entry_handler import (
    RegisterCatalogEntryCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.revise_catalog_entry_handler import (
    ReviseCatalogEntryCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.sync_runtime_catalog_handler import (
    SyncRuntimeCatalogCommand,
)
from noesis.bounded_context.knowledge.application.handlers.queries.catalog import (
    CheckCatalogAvailabilityQuery,
    GetCatalogEntryQuery,
    ListCatalogEntriesQuery,
    ScanRuntimeCatalogQuery,
)
from noesis.bounded_context.knowledge.application.services.inputs import SourceInput
from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum, Key
from noesis.core import Environment
from noesis.interfaces.cli import output
from noesis.interfaces.cli.actor import resolve_actor
from noesis.interfaces.cli.bootstrap import with_knowledge
from noesis.interfaces.cli.commands.record_commands import (
    IdempotencyKeyOption,
    SourceOption,
    parse_sources,
)
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.responses import (
    CatalogCheckResponse,
    CatalogListResponse,
    CatalogScanResponse,
    CatalogShowResponse,
    CatalogSyncResponse,
    CatalogWriteResponse,
)
from noesis.interfaces.cli.responses.record_response import RecordActorResponse
from noesis.interfaces.cli.runtime_resolution import parse_runtimes, resolve_runtimes
from noesis.interfaces.cli.state import cli_state

catalog_app: typer.Typer = typer.Typer(
    help="Register capabilities (skills, agents, CLI tools, MCP servers) and check what is "
    "available to run right now.",
    no_args_is_help=True,
)

RuntimeOption = Annotated[
    list[str] | None,
    typer.Option(
        "--runtime",
        help="A runtime to look at (repeatable): "
        + ", ".join(runtime.value for runtime in RuntimeEnum)
        + ". Default: the runtime of this session, else all of them.",
    ),
]
KindOption = Annotated[
    CatalogEntryKindEnum | None,
    typer.Option("--kind", help="Only entries of this kind."),
]
RefArgument = Annotated[str, typer.Argument(help="An entry id, or <kind>:<name>.")]


def _usage(message: str, hint: str) -> typer.BadParameter:
    return typer.BadParameter(message, param_hint=hint)


def _required_text(value: str, option: str) -> str:
    if not value.strip():
        raise _usage(f"{option} cannot be empty.", option)
    return value


def _sources(context: typer.Context, source: list[str] | None) -> tuple[SourceInput, ...]:
    sources: tuple[SourceInput, ...] = parse_sources(context, source, None)
    if not sources:
        raise _usage("Cite at least one source.", "--source")
    return sources


def _requires(requires: list[str] | None) -> tuple[str, ...] | None:
    """`--requires` values: None when not given, `()` for a lone empty value (clears)."""
    if requires is None:
        return None
    if requires == [""]:
        return ()
    if "" in requires:
        raise _usage("An empty --requires clears the list and must be given alone.", "--requires")
    return tuple(requires)


@catalog_app.command("register")
def register(
    context: typer.Context,
    kind: Annotated[
        CatalogEntryKindEnum, typer.Option("--kind", help="What it is.", case_sensitive=True)
    ],
    name: Annotated[
        str,
        typer.Option(
            "--name",
            help="Its name: the executable for a CLI tool, <plugin>:<name> for plugin artifacts.",
        ),
    ],
    purpose: Annotated[str, typer.Option("--purpose", help="What it is for.")],
    location: Annotated[
        str,
        typer.Option(
            "--location",
            help="Where its definition is version-controlled (URL, repository path or "
            "plugin@marketplace); never an install path.",
        ),
    ],
    source: SourceOption,
    idempotency_key: IdempotencyKeyOption,
    version: Annotated[
        str | None, typer.Option("--declared-version", help="The declared version.")
    ] = None,
    requires: Annotated[
        list[str] | None,
        typer.Option("--requires", help="A prerequisite as <kind>:<name> (repeatable)."),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Register a capability with explicit values; it says nothing about availability."""
    _required_text(purpose, "--purpose")
    _required_text(location, "--location")
    sources: tuple[SourceInput, ...] = _sources(context, source)
    env: Environment = cli_state(context).environment()
    command = RegisterCatalogEntryCommand(
        idempotency_key=idempotency_key,
        space_key=Key(value=env.knowledge.knowledge_space),
        kind=kind,
        name=name,
        purpose=purpose,
        version=version,
        prerequisites=_requires(requires) or (),
        location=location,
        actor=resolve_actor(env.identity),
        sources=sources,
    )
    result: CatalogWriteResultDto = asyncio.run(
        with_knowledge(env, lambda handlers: handlers.register_catalog_entry.handle(command))
    )
    output.emit(CatalogWriteResponse.model_validate(result.model_dump(mode="json")))


@catalog_app.command("revise")
def revise(
    context: typer.Context,
    ref: RefArgument,
    expected_revision: Annotated[
        int,
        typer.Option(
            "--expected-revision",
            min=1,
            help="The head revision your change is based on (see `catalog show`).",
        ),
    ],
    idempotency_key: IdempotencyKeyOption,
    source: SourceOption = None,
    purpose: Annotated[str | None, typer.Option("--purpose", help="New purpose.")] = None,
    version: Annotated[
        str | None,
        typer.Option("--declared-version", help="New declared version; an empty value clears it."),
    ] = None,
    requires: Annotated[
        list[str] | None,
        typer.Option(
            "--requires",
            help="Prerequisites as <kind>:<name> (repeatable), replacing the whole list; "
            "a single empty value clears it.",
        ),
    ] = None,
    location: Annotated[str | None, typer.Option("--location", help="New location.")] = None,
    as_json: JsonOption = False,
) -> None:
    """Append a revision; what you leave out stays as it was, and a no-op writes nothing."""
    if purpose is not None:
        _required_text(purpose, "--purpose")
    if location is not None:
        _required_text(location, "--location")
    prerequisites: tuple[str, ...] | None = _requires(requires)
    sources: tuple[SourceInput, ...] = _sources(context, source)
    env: Environment = cli_state(context).environment()
    command = ReviseCatalogEntryCommand(
        idempotency_key=idempotency_key,
        space_key=Key(value=env.knowledge.knowledge_space),
        ref=ref,
        expected_revision=expected_revision,
        purpose=purpose,
        version=version,
        prerequisites=prerequisites,
        location=location,
        actor=resolve_actor(env.identity),
        sources=sources,
    )
    result: CatalogWriteResultDto = asyncio.run(
        with_knowledge(env, lambda handlers: handlers.revise_catalog_entry.handle(command))
    )
    output.emit(CatalogWriteResponse.model_validate(result.model_dump(mode="json")))


@catalog_app.command("list")
def list_entries(
    context: typer.Context,
    kind: KindOption = None,
    name_prefix: Annotated[
        str | None, typer.Option("--name-prefix", help="Only names starting with this.")
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """List the catalog entries of the active space."""
    env: Environment = cli_state(context).environment()
    query = ListCatalogEntriesQuery(
        space_key=Key(value=env.knowledge.knowledge_space), kind=kind, name_prefix=name_prefix
    )
    entries: tuple[CatalogEntryDto, ...] = asyncio.run(
        with_knowledge(env, lambda handlers: handlers.list_catalog_entries.handle(query))
    )
    output.emit(
        CatalogListResponse.model_validate(
            {"entries": [entry.model_dump(mode="json") for entry in entries]}
        )
    )


@catalog_app.command("show")
def show(
    context: typer.Context,
    ref: RefArgument,
    revision: Annotated[
        int | None,
        typer.Option("--revision", min=1, help="Show this revision (default: the head)."),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Show one entry with the content and provenance of one revision."""
    env: Environment = cli_state(context).environment()
    query = GetCatalogEntryQuery(
        space_key=Key(value=env.knowledge.knowledge_space), ref=ref, revision=revision
    )
    detail: CatalogEntryDetailDto = asyncio.run(
        with_knowledge(env, lambda handlers: handlers.get_catalog_entry.handle(query))
    )
    output.emit(
        CatalogShowResponse.model_validate(
            {
                **detail.model_dump(
                    mode="json",
                    exclude={"actor_kind", "actor_name", "actor_session", "source_ids"},
                ),
                "actor": RecordActorResponse(
                    kind=detail.actor_kind, name=detail.actor_name, session=detail.actor_session
                ),
                "sources": list(detail.source_ids),
            }
        )
    )


@catalog_app.command("check")
def check(
    context: typer.Context,
    refs: Annotated[
        list[str] | None,
        typer.Argument(help="Entries to check, as ids or <kind>:<name> (default: every entry)."),
    ] = None,
    kind: KindOption = None,
    runtime: RuntimeOption = None,
    as_json: JsonOption = False,
) -> None:
    """Check what is available now, per runtime; unavailable entries are data (exit 0)."""
    parse_runtimes(runtime or [])
    env: Environment = cli_state(context).environment()
    query = CheckCatalogAvailabilityQuery(
        space_key=Key(value=env.knowledge.knowledge_space),
        refs=tuple(refs or ()),
        kind=kind,
        runtimes=resolve_runtimes(runtime or [], env.identity),
    )
    report: AvailabilityReportDto = asyncio.run(
        with_knowledge(env, lambda handlers: handlers.check_catalog_availability.handle(query))
    )
    output.emit(
        CatalogCheckResponse.model_validate(report.model_dump(mode="json", exclude={"entries"}))
    )


@catalog_app.command("scan")
def scan(
    context: typer.Context,
    runtime: RuntimeOption = None,
    as_json: JsonOption = False,
) -> None:
    """List what is installed but not cataloged, version drift, and cataloged but not installed."""
    parse_runtimes(runtime or [])
    env: Environment = cli_state(context).environment()
    query = ScanRuntimeCatalogQuery(
        space_key=Key(value=env.knowledge.knowledge_space),
        runtimes=resolve_runtimes(runtime or [], env.identity),
    )
    report: ScanReportDto = asyncio.run(
        with_knowledge(env, lambda handlers: handlers.scan_runtime_catalog.handle(query))
    )
    output.emit(CatalogScanResponse.model_validate(report.model_dump(mode="json")))


@catalog_app.command("sync")
def sync(
    context: typer.Context,
    runtime: RuntimeOption = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Report what would change without writing."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Register and revise entries for installed skills and agents; never deletes."""
    parse_runtimes(runtime or [])
    env: Environment = cli_state(context).environment()
    command = SyncRuntimeCatalogCommand(
        space_key=Key(value=env.knowledge.knowledge_space),
        runtimes=resolve_runtimes(runtime or [], env.identity),
        actor=resolve_actor(env.identity),
        dry_run=dry_run,
    )
    report: SyncReportDto = asyncio.run(
        with_knowledge(env, lambda handlers: handlers.sync_runtime_catalog.handle(command))
    )
    output.emit(CatalogSyncResponse.model_validate(report.model_dump(mode="json")))
