"""`noesis config`: show the effective settings or create the configuration file."""

from pathlib import Path
from typing import Annotated

import typer

from noesis.core import (
    Environment,
    write_env_file,
)
from noesis.exceptions import (
    ConfigFileExistsError,
)
from noesis.interfaces.cli import output
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.responses import ConfigInitResponse, ConfigShowResponse
from noesis.interfaces.cli.state import cli_state

config_app: typer.Typer = typer.Typer(
    help="Show or create the noesis configuration.", no_args_is_help=True
)


def _view(environment: Environment) -> ConfigShowResponse:
    """Collect the effective settings into a printable model."""
    return ConfigShowResponse(
        env_file=str(environment.env_file),
        env_file_exists=environment.env_file.is_file(),
        settings={
            "runtime": environment.runtime.model_dump(mode="json"),
            "knowledge": environment.knowledge.model_dump(mode="json"),
            "capture": environment.capture.model_dump(mode="json"),
            "curator": environment.curator.model_dump(mode="json"),
        },
    )


def _format_view(view: ConfigShowResponse) -> str:
    """Text rendering for `config show`."""
    lines: list[str] = [
        f"env file: {view.env_file} ({'found' if view.env_file_exists else 'missing'})"
    ]
    for concern, values in view.settings.items():
        lines.append(f"[{concern}]")
        if isinstance(values, dict):
            lines += [f"  {key} = {value}" for key, value in values.items()]
    return "\n".join(lines)


@config_app.command("show")
def show(context: typer.Context, as_json: JsonOption = False) -> None:
    """Print the effective settings and the file they were read from."""
    output.emit(_view(cli_state(context).environment()), _format_view)


@config_app.command("init")
def init(
    context: typer.Context,
    vault_dir: Annotated[
        Path | None,
        typer.Option("--vault-dir", help="Folder that stores notes (writes NOESIS_VAULT_DIR)."),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False,
    as_json: JsonOption = False,
) -> None:
    """Write a commented configuration file to ~/.config/noesis/.env (or --env-file)."""
    target: Path = cli_state(context).environment().env_file
    if target.exists() and not force:
        raise ConfigFileExistsError(
            f"{target} already exists.",
            {"env_file": str(target)},
            next_steps=["Edit the file directly, or re-run with --force to replace it."],
        )
    write_env_file(target, vault_dir=vault_dir)
    output.emit(
        ConfigInitResponse(env_file=str(target), vault_dir=str(vault_dir) if vault_dir else None),
        lambda result: f"wrote {result.env_file}",
    )
