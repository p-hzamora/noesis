"""Installing, removing and inspecting agent hooks through the registry port."""

import pytest
from tests.support.capture_support import InMemoryAgentHookRegistry

from noesis.bounded_context.capture.application.handlers.commands import (
    InstallAgentHooksCommand,
    InstallAgentHooksHandler,
    UninstallAgentHooksCommand,
    UninstallAgentHooksHandler,
)
from noesis.bounded_context.capture.application.handlers.queries import (
    GetAgentHooksStatusHandler,
    GetAgentHooksStatusQuery,
)

pytestmark = pytest.mark.unit

COMMAND: str = "noesis hook claude-code"


async def test_install_without_apply_only_previews() -> None:
    registry: InMemoryAgentHookRegistry = InMemoryAgentHookRegistry()

    result = await InstallAgentHooksHandler(registry=registry).handle(
        InstallAgentHooksCommand(hook_command=COMMAND, apply=False)
    )

    assert registry.applied == []
    assert (result.changed, result.applied, result.backup, result.diff) == (
        True,
        False,
        None,
        "diff",
    )
    assert result.command == COMMAND
    assert result.installed == {"Stop": ["old"]}


async def test_install_with_apply_writes_and_reports_the_new_state() -> None:
    registry: InMemoryAgentHookRegistry = InMemoryAgentHookRegistry()

    result = await InstallAgentHooksHandler(registry=registry).handle(
        InstallAgentHooksCommand(hook_command=COMMAND, apply=True)
    )

    assert registry.planned == [COMMAND]
    assert len(registry.applied) == 1
    assert (result.applied, result.backup) == (True, "/tmp/settings.bak")  # noqa: S108
    assert result.installed == {"Stop": [COMMAND]}


async def test_nothing_is_written_when_nothing_would_change() -> None:
    registry: InMemoryAgentHookRegistry = InMemoryAgentHookRegistry(changed=False)

    result = await InstallAgentHooksHandler(registry=registry).handle(
        InstallAgentHooksCommand(hook_command=COMMAND, apply=True)
    )

    assert registry.applied == []
    assert (result.changed, result.applied, result.diff) == (False, False, "")


async def test_uninstall_plans_a_removal_and_applies_it_on_request() -> None:
    registry: InMemoryAgentHookRegistry = InMemoryAgentHookRegistry()
    handler: UninstallAgentHooksHandler = UninstallAgentHooksHandler(registry=registry)

    preview = await handler.handle(UninstallAgentHooksCommand(apply=False))
    applied = await handler.handle(UninstallAgentHooksCommand(apply=True))

    assert registry.planned == [None, None]
    assert (preview.applied, preview.command) == (False, None)
    assert (applied.applied, applied.installed) == (True, {})
    assert len(registry.applied) == 1


async def test_status_returns_what_the_registry_reports() -> None:
    result = await GetAgentHooksStatusHandler(registry=InMemoryAgentHookRegistry()).handle(
        GetAgentHooksStatusQuery()
    )

    assert result.missing_events == ["SessionEnd"]
