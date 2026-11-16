"""`noesis import`: bring a vault, or one file, into the record store."""

import asyncio
from typing import Annotated

import typer

from noesis.bounded_context.interop.application.dtos import (
    ImportFileResultDto,
    VaultImportResultDto,
)
from noesis.bounded_context.interop.application.handlers import (
    ImportFileCommand,
    PlanVaultImportQuery,
    RunVaultImportCommand,
)
from noesis.core import Environment
from noesis.interfaces.cli import output
from noesis.interfaces.cli.bootstrap import open_file_import, open_vault_import
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.responses import ImportFileResponse, ImportRunResponse
from noesis.interfaces.cli.state import cli_state

import_app: typer.Typer = typer.Typer(
    help="Import a notes vault, or one file, as proposed records of the knowledge store.",
    no_args_is_help=True,
)


async def _run_vault(
    environment: Environment, *, apply: bool, update: bool, strict: bool
) -> VaultImportResultDto:
    async with open_vault_import(environment, apply=apply) as handlers:
        if apply:
            return await handlers.run.handle(RunVaultImportCommand(update=update, strict=strict))
        return await handlers.plan.handle(PlanVaultImportQuery(update=update, strict=strict))


async def _import_file(environment: Environment, command: ImportFileCommand) -> ImportFileResultDto:
    async with open_file_import(environment) as handler:
        return await handler.handle(command)


@import_app.command("run")
def run(
    context: typer.Context,
    yes: Annotated[
        bool, typer.Option("--yes", help="Apply the import (without it, only preview).")
    ] = False,
    update: Annotated[
        bool,
        typer.Option(
            "--update", help="Revise or supersede records whose note changed since the last run."
        ),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Refuse the run, writing nothing, if any note is blocked."),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="List every note with its outcome.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Preview (default) or apply (`--yes`) the import of every note of NOESIS_VAULT_DIR."""
    env: Environment = cli_state(context).environment()
    result: VaultImportResultDto = asyncio.run(
        _run_vault(env, apply=yes, update=update, strict=strict)
    )
    output.emit(ImportRunResponse.from_dto(result, verbose=verbose))


@import_app.command("file")
def file(
    context: typer.Context,
    path: Annotated[str, typer.Argument(help="The file to register; it is only read.")],
    title: Annotated[str | None, typer.Option("--title", help="Title of the record.")] = None,
    subtype: Annotated[
        str | None,
        typer.Option("--subtype", help="Subtype slug (default: the header kind, else note)."),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option("--project", help="Project key (default: from the header, else none)."),
    ] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", help="A tag (repeatable).")] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would happen without writing.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Register one file as a proposed record; running it again on the same file is safe."""
    env: Environment = cli_state(context).environment()
    command = ImportFileCommand(
        path=path,
        title=title,
        subtype=subtype,
        project_key=project,
        tags=tuple(tag or ()),
        dry_run=dry_run,
    )
    result: ImportFileResultDto = asyncio.run(_import_file(env, command))
    output.emit(ImportFileResponse.from_dto(result))
