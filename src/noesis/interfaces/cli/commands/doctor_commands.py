"""`noesis doctor`: check that configuration and external tools are ready."""

import asyncio

import typer

from noesis.exceptions import ExitCodeEnum
from noesis.interfaces.cli.bootstrap import run_diagnostics
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.output import emit
from noesis.interfaces.cli.responses import DoctorResponse
from noesis.interfaces.cli.state import CliState, cli_state


def format_report(report: DoctorResponse) -> str:
    """Text rendering for `doctor`."""
    lines: list[str] = [
        f"{'ok ' if check.ok else 'FAIL'} {check.name}: {check.detail}"
        + (f"\n     next: {check.next_step}" if check.next_step else "")
        for check in report.checks
    ]
    return "\n".join(lines)


def doctor(context: typer.Context, as_json: JsonOption = False) -> None:
    """Check configuration, folders, and required executables; exit 1 if anything fails."""
    state: CliState = cli_state(context)
    report: DoctorResponse = DoctorResponse.model_validate(
        asyncio.run(run_diagnostics(state.environment(), state.claude_code()))
    )
    emit(report, format_report)
    if not report.ok:
        raise typer.Exit(ExitCodeEnum.FAILURE)
