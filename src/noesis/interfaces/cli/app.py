"""The `noesis` command: root Typer application, global options, and error handling."""

import sys
from collections.abc import Sequence
from typing import Annotated

import typer

from noesis import __version__
from noesis.exceptions import AppException, ExitCodeEnum
from noesis.interfaces.cli import commands

from . import output
from .options import EnvFileOption
from .state import CliState

PROGRAM: str = "noesis"
EPILOG: str = (
    "Every command accepts --json and --help. "
    "Exit codes: 0 ok, 1 the operation failed, 2 invalid command line."
)

app: typer.Typer = typer.Typer(
    name=PROGRAM,
    help="Capture finished agent work, curate what is worth keeping, and store it as notes.",
    epilog=EPILOG,
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
app.add_typer(commands.capture_app, name="capture")
app.add_typer(commands.notes_app, name="notes")
app.add_typer(commands.hook_app, name="hook")
app.add_typer(commands.integrate_app, name="integrate")
app.add_typer(commands.skills_app, name="skills")
app.add_typer(commands.config_app, name="config")
app.add_typer(commands.update_app, name="update")
app.command("doctor")(commands.doctor)


def _print_version(enabled: bool) -> None:
    """Eager `--version` callback."""
    if enabled:
        sys.stdout.write(f"{PROGRAM} {__version__}\n")
        raise typer.Exit()


@app.callback()
def root(
    context: typer.Context,
    env_file: EnvFileOption = None,
    version: Annotated[
        bool,
        typer.Option(
            "--version", help="Show the version and exit.", callback=_print_version, is_eager=True
        ),
    ] = False,
) -> None:
    """Capture finished agent work, curate what is worth keeping, and store it as notes."""
    context.obj = CliState(env_file=env_file)


def run(argv: Sequence[str]) -> int:
    """Run one command line and return its exit code (the testable entry point).

    Args:
        argv: Arguments after the program name.

    Returns:
        The exit code (see `ExitCodeEnum`).
    """
    with output.output_scope():
        try:
            result: object = app(args=list(argv), prog_name=PROGRAM, standalone_mode=False)
        except typer.Abort:
            return ExitCodeEnum.FAILURE
        except typer.TyperException as error:  # usage errors raised by Typer's bundled click
            show: object = getattr(error, "show", None)
            if callable(show):
                show()
            return int(getattr(error, "exit_code", ExitCodeEnum.USAGE))
        except AppException as error:
            output.emit_error(error)
            return error.exit_code
        return result if isinstance(result, int) else ExitCodeEnum.OK


def main() -> None:
    """Console-script entry point."""
    sys.exit(run(sys.argv[1:]))
