"""`noesis store`: prepare the knowledge store."""

import asyncio

import typer

from noesis.bounded_context.knowledge.application.dtos import StoreInitialisedDto
from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
    InitialiseStoreCommand,
)
from noesis.bounded_context.knowledge.domain.value_objects import Key
from noesis.core import Environment
from noesis.interfaces.cli import output
from noesis.interfaces.cli.bootstrap import with_knowledge
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.responses import StoreInitResponse
from noesis.interfaces.cli.state import cli_state

store_app: typer.Typer = typer.Typer(
    help="Prepare the knowledge store (Neo4j).", no_args_is_help=True
)


@store_app.command("init")
def init(context: typer.Context, as_json: JsonOption = False) -> None:
    """Apply the schema steps and create the default space; running it again changes nothing."""
    env: Environment = cli_state(context).environment()
    command = InitialiseStoreCommand(default_space_key=Key(value=env.knowledge.knowledge_space))
    result: StoreInitialisedDto = asyncio.run(
        with_knowledge(env, lambda handlers: handlers.initialise_store.handle(command))
    )
    output.emit(StoreInitResponse.model_validate(result, from_attributes=True))
