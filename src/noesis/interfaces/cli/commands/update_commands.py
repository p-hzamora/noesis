"""`noesis update`: tell whether the installed checkout is behind its origin."""

import asyncio

import typer

from noesis.interfaces.cli import output
from noesis.interfaces.cli.bootstrap import run_update_check
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.responses import UpdateCheckResponse

update_app: typer.Typer = typer.Typer(
    help="Check whether this installation is behind its git origin.", no_args_is_help=True
)


@update_app.command("check")
def check(as_json: JsonOption = False) -> None:
    """Compare the checkout noesis runs from with its origin; exit 0 for every verdict."""
    output.emit(UpdateCheckResponse.model_validate(asyncio.run(run_update_check())))
