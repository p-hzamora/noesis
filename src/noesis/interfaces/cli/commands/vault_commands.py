"""`noesis vault`: check the vault's notes and restructure it from a plan."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from noesis.bounded_context.notes.application.dtos import VaultDiagnosisDto, VaultMigrationDto
from noesis.bounded_context.notes.application.handlers.commands import MigrateVaultCommand
from noesis.bounded_context.notes.application.handlers.queries import DiagnoseVaultQuery
from noesis.exceptions import InvalidMigrationPlanError
from noesis.interfaces.cli import output
from noesis.interfaces.cli.bootstrap import VaultHandlers, build_vault
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.responses import VaultDoctorResponse, VaultMigrationResponse
from noesis.interfaces.cli.state import cli_state

vault_app: typer.Typer = typer.Typer(
    help="Check the vault's notes and restructure it from a plan.", no_args_is_help=True
)

VerboseOption = Annotated[
    bool, typer.Option("--verbose", help="Also list the files behind the counts.")
]


def _handlers(context: typer.Context) -> VaultHandlers:
    return build_vault(cli_state(context).environment())


@vault_app.command("doctor")
def doctor(
    context: typer.Context,
    root: Annotated[
        list[str] | None,
        typer.Option(
            "--root",
            help="A vault folder whose subfolders are projects (repeatable); the repository "
            "folder of the manifest is always checked.",
        ),
    ] = None,
    verbose: VerboseOption = False,
    as_json: JsonOption = False,
) -> None:
    """Count notes with and without noesis frontmatter, and find projects under two roots."""
    diagnosis: VaultDiagnosisDto = asyncio.run(
        _handlers(context).doctor.handle(DiagnoseVaultQuery(roots=tuple(root or ())))
    )
    response = VaultDoctorResponse.model_validate(diagnosis)
    if not verbose:
        response = response.model_copy(update={"without_paths": (), "invalid_paths": ()})
    output.emit(response)


@vault_app.command("migrate")
def migrate(
    context: typer.Context,
    plan: Annotated[
        Path,
        typer.Option("--plan", help="Plan file: entries {old, new, action, scope?, kind?}."),
    ],
    apply: Annotated[
        bool, typer.Option("--apply", help="Write the changes (the default is a dry run).")
    ] = False,
    verbose: VerboseOption = False,
    as_json: JsonOption = False,
) -> None:
    """Restructure the vault as the plan says: counts by default, a dry run unless `--apply`."""
    try:
        text: str = plan.expanduser().read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise InvalidMigrationPlanError(
            f"Cannot read the plan {plan}: {error}",
            {"path": str(plan)},
            next_steps=["Pass the plan file with --plan."],
        ) from error
    result: VaultMigrationDto = asyncio.run(
        _handlers(context).migrate.handle(MigrateVaultCommand(plan_text=text, apply=apply))
    )
    response = VaultMigrationResponse.model_validate(result, from_attributes=True)
    response = response.model_copy(
        update={"pending": result.pending, "lines": result.lines if verbose else ()}
    )
    output.emit(response)
