"""`noesis recall`: scoped, grounded guidance from graph bodies."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from noesis.bounded_context.retrieval.application.dtos.briefing_dtos import (
    RecallRequestDto,
    RecallResultDto,
)
from noesis.bounded_context.retrieval.application.dtos.record_search_dtos import (
    RecordSearchRequestDto,
)
from noesis.interfaces.cli import output
from noesis.interfaces.cli.bootstrap.retrieval_handlers_builder import (
    RetrievalHandlers,
    with_retrieval,
)
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.responses.recall_response import RecallRecordResponse, RecallResponse
from noesis.interfaces.cli.runtime_resolution import parse_runtimes, resolve_runtimes
from noesis.interfaces.cli.search_presentation import resolve_project, search_response
from noesis.interfaces.cli.state import cli_state


def recall(
    context: typer.Context,
    task: Annotated[str, typer.Argument(help="The task to prepare for.")],
    target_root: Annotated[
        Path | None,
        typer.Option(
            "--target-root",
            file_okay=False,
            help="Root of the existing or planned target repository.",
        ),
    ] = None,
    project: Annotated[
        str | None, typer.Option("--project", help="Project key; defaults to git repository name.")
    ] = None,
    runtime: Annotated[
        list[str] | None, typer.Option("--runtime", help="claude-code or codex (repeatable).")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=50)] = 10,
    no_synthesis: Annotated[
        bool, typer.Option("--no-synthesis", help="Deterministic digest; needs no model.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Read task guidance with revision citations and observed tool availability."""
    if not task.strip():
        raise typer.BadParameter("Give a non-empty task.", ctx=context, param_hint="TASK")
    parse_runtimes(runtime or [])
    key, source = resolve_project(project, False, target_root)
    env = cli_state(context).environment()
    runtimes = resolve_runtimes(runtime or [], env.identity)

    async def run(handlers: RetrievalHandlers, space_id: str) -> RecallResultDto:
        if handlers.recall is None:
            raise RuntimeError("Recall handler was not wired")
        request = RecallRequestDto.model_validate(
            {
                "search": RecordSearchRequestDto(
                    text=task, space_id=space_id, project_key=key, limit=limit
                ),
                "runtimes": tuple(item.value for item in runtimes),
                "no_synthesis": no_synthesis,
            }
        )
        return await handlers.recall.handle(request)

    result = asyncio.run(with_retrieval(env, run))
    search = search_response(
        result.search, space=env.knowledge.knowledge_space, key=key, source=source
    )
    output.emit(
        RecallResponse(
            synthesis=result.synthesis,
            scope=search.scope,
            index=search.index,
            records=tuple(
                RecallRecordResponse.model_validate(record.model_dump(exclude={"body"}))
                for record in result.records
            ),
            constraints=result.constraints,
            decisions=result.decisions,
            context=result.context,
            unconfirmed=result.unconfirmed,
            unsupported=result.unsupported,
            tools=result.tools,
            tools_state=result.tools_state,
            capabilities=result.capabilities,
            warnings=result.warnings,
            next_steps=result.next_steps,
        )
    )
