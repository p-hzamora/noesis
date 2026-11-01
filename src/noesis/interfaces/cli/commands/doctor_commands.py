"""`noesis doctor`: check that configuration and external tools are ready."""

import asyncio

import typer

from noesis.exceptions import ExitCodeEnum
from noesis.interfaces.cli import output
from noesis.interfaces.cli.bootstrap import run_diagnostics
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.responses import DoctorResponse
from noesis.interfaces.cli.state import CliState, cli_state


def doctor(context: typer.Context, as_json: JsonOption = False) -> None:
    """Check configuration, folders, and required executables; exit 1 if anything fails."""
    state: CliState = cli_state(context)
    report: DoctorResponse = DoctorResponse.model_validate(
        asyncio.run(run_diagnostics(state.environment(), state.claude_code()))
    )
    output.emit(report)
    if not report.ok:
        raise typer.Exit(ExitCodeEnum.FAILURE)
