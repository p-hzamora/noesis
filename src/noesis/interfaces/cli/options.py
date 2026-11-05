"""Reusable Typer option declarations, so every command spells them the same way."""

from pathlib import Path
from typing import Annotated

import typer

from . import output

JsonOption = Annotated[
    bool,
    typer.Option(
        "--json", help="Print a JSON envelope instead of text.", callback=output.remember_json_mode
    ),
]
EnvFileOption = Annotated[
    Path | None,
    typer.Option(
        "--env-file",
        help="Explicit configuration file, overriding the repository profile (default: "
        "`.noesis-config` profile, else ~/.config/noesis/.env).",
        dir_okay=False,
    ),
]
SessionOption = Annotated[
    str,
    typer.Option(
        "--session",
        envvar="NOESIS_SESSION_ID",
        help="Agent session id (in Claude Code skills: ${CLAUDE_SESSION_ID}).",
        show_envvar=True,
    ),
]
