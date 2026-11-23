"""What `noesis remember` and the deprecated capture subcommand of `record` share: scope and execution."""

import asyncio
from pathlib import Path
from typing import Final

from noesis.bounded_context.knowledge.application.dtos import RememberResultDto
from noesis.bounded_context.knowledge.application.handlers.commands.remember_handler import (
    RememberCommand,
)
from noesis.bounded_context.knowledge.application.services.inputs import ProjectRef
from noesis.bounded_context.knowledge.domain.value_objects import Key
from noesis.core import Environment
from noesis.core.git_root import find_common_dir, repository_name
from noesis.interfaces.cli.bootstrap import with_remember
from noesis.interfaces.cli.bootstrap.retrieval_handlers_builder import trigger_index_sync

SPACE_WIDE: Final[str] = "space_wide"


def resolve_scope(
    project: str | None, target_root: Path | None, *, space_wide: bool
) -> tuple[ProjectRef | None, str]:
    """The project a memory is anchored to and how it was chosen.

    `--space-wide` anchors to none; `--project` names it; `--target-root` uses that checkout's
    repository name (none when it has no repository of its own); otherwise the repository of the
    working directory, as the capture subcommand of `record` always did.

    Returns:
        The project reference (None for space-wide) and its source: `space_wide`, `option`,
        `target_root`, `git_root` or `none`.
    """
    if space_wide:
        return None, SPACE_WIDE
    if project is not None:
        return ProjectRef(key=Key(value=project)), "option"
    if target_root is not None:
        root: Path = target_root.expanduser().resolve()
        common: Path | None = find_common_dir(root)
        if common is not None and ((root / ".git").exists() or common == root):
            return ProjectRef(key=Key(value=repository_name(common))), "target_root"
        return None, "target_root"
    common_dir: Path | None = find_common_dir(Path.cwd())
    if common_dir is None:
        return None, "none"
    return ProjectRef(key=Key(value=repository_name(common_dir))), "git_root"


def execute_remember(environment: Environment, command: RememberCommand) -> RememberResultDto:
    """Run the handler for one invocation and start the index sync after a fresh write."""
    result: RememberResultDto = asyncio.run(
        with_remember(environment, lambda handler: handler.handle(command))
    )
    if result.written and not result.replayed:
        trigger_index_sync(environment)
    return result
