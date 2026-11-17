"""`noesis index`: keep search projections up to date, rebuild them and report on them.

`index model prepare` is the only command that downloads the semantic model; `index embedder
serve` is the only one that starts the resident embedder (in the foreground).
"""

import asyncio
import contextlib
import os
import signal
from typing import Annotated
from uuid import uuid4

import typer

from noesis.bounded_context.retrieval.application.dtos.index_dtos import (
    IndexStatusResultDto,
    RebuildIndexResultDto,
    SyncIndexResultDto,
)
from noesis.bounded_context.retrieval.application.handlers.commands.rebuild_index_handler import (
    RebuildIndexCommand,
)
from noesis.bounded_context.retrieval.application.handlers.commands.sync_index_handler import (
    SyncIndexCommand,
)
from noesis.bounded_context.retrieval.application.handlers.queries.get_index_status_handler import (
    GetIndexStatusQuery,
)
from noesis.core import Environment
from noesis.interfaces.cli import output
from noesis.interfaces.cli.bootstrap.retrieval_handlers_builder import (
    ResidentEmbedder,
    RetrievalHandlers,
    build_resident_embedder,
    prepare_semantic_model,
    registered_projection_kinds,
    serve_resident_embedder,
    with_retrieval,
)
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.responses import (
    EmbedderServeResponse,
    IndexRebuildResponse,
    IndexStatusResponse,
    IndexSyncResponse,
    ModelPrepareResponse,
)
from noesis.interfaces.cli.state import cli_state

index_app: typer.Typer = typer.Typer(
    help="Sync, rebuild and inspect the search projections.", no_args_is_help=True
)
model_app: typer.Typer = typer.Typer(
    help="Prepare the pinned semantic model (the only command that downloads).",
    no_args_is_help=True,
)
embedder_app: typer.Typer = typer.Typer(
    help="Run the resident semantic embedder (never started automatically).",
    no_args_is_help=True,
)
index_app.add_typer(model_app, name="model")
index_app.add_typer(embedder_app, name="embedder")


def _owner() -> str:
    """Identifies this process as a lock holder."""
    return f"noesis-index-{os.getpid()}-{uuid4().hex[:8]}"


@index_app.command("sync")
def sync(
    context: typer.Context,
    wait_seconds: Annotated[
        int,
        typer.Option("--wait-seconds", min=0, help="How long to wait for another sync to finish."),
    ] = 0,
    as_json: JsonOption = False,
) -> None:
    """Apply the changes since each projection's cursor (nothing to do with no projection)."""
    env: Environment = cli_state(context).environment()

    async def run(handlers: RetrievalHandlers, space_id: str) -> SyncIndexResultDto:
        return await handlers.sync_index.handle(
            SyncIndexCommand(space_id=space_id, wait_seconds=wait_seconds, owner=_owner())
        )

    result: SyncIndexResultDto = asyncio.run(with_retrieval(env, run, indexing=True))
    output.emit(IndexSyncResponse.model_validate(result, from_attributes=True))


@index_app.command("rebuild")
def rebuild(
    context: typer.Context,
    projection: Annotated[
        str | None, typer.Option("--projection", help="Rebuild only this projection.")
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="Confirm the rebuild (it clears and refills projections).")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Clear and refill the projections from the records, then catch up."""
    if not yes:
        raise typer.BadParameter(
            "A rebuild clears and refills the projections; confirm it with --yes.",
            ctx=context,
            param_hint="--yes",
        )
    env: Environment = cli_state(context).environment()
    if projection is not None and projection not in registered_projection_kinds(env):
        raise typer.BadParameter(
            f"No projection named {projection!r} is registered.",
            ctx=context,
            param_hint="--projection",
        )

    async def run(handlers: RetrievalHandlers, space_id: str) -> RebuildIndexResultDto:
        return await handlers.rebuild_index.handle(
            RebuildIndexCommand(space_id=space_id, projection=projection, owner=_owner())
        )

    result: RebuildIndexResultDto = asyncio.run(with_retrieval(env, run, indexing=True))
    output.emit(IndexRebuildResponse.model_validate(result, from_attributes=True))


@index_app.command("status")
def status(
    context: typer.Context,
    verify: Annotated[
        bool,
        typer.Option("--verify", help="Compare every record with the projections (slower)."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Report each projection's cursor, lag and profile (and divergences with --verify)."""
    env: Environment = cli_state(context).environment()

    async def run(handlers: RetrievalHandlers, space_id: str) -> IndexStatusResultDto:
        return await handlers.index_status.handle(
            GetIndexStatusQuery(space_id=space_id, verify=verify)
        )

    result: IndexStatusResultDto = asyncio.run(with_retrieval(env, run))
    output.emit(IndexStatusResponse.model_validate(result, from_attributes=True))


@model_app.command("prepare")
def prepare_model(context: typer.Context, as_json: JsonOption = False) -> None:
    """Download, verify and cache the pinned bge-small-en-v1.5 artifact (English only)."""
    env: Environment = cli_state(context).environment()
    prepared = prepare_semantic_model(env)
    output.emit(ModelPrepareResponse.model_validate(prepared, from_attributes=True))


@embedder_app.command("serve")
def serve_embedder(context: typer.Context, as_json: JsonOption = False) -> None:
    """Load the model once and serve embeddings on a private socket until interrupted.

    The socket path and its permissions are checked before the model is loaded.
    """
    env: Environment = cli_state(context).environment()
    embedder: ResidentEmbedder = build_resident_embedder(env)

    async def run() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(signum, stop.set)
        await serve_resident_embedder(
            embedder,
            stop,
            lambda socket: output.warn(f"embedder listening on {socket} (Ctrl-C to stop)"),
        )

    asyncio.run(run())
    output.emit(
        EmbedderServeResponse(socket=str(embedder.socket), profile_hash=embedder.profile_hash)
    )
