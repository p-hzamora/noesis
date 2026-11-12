"""Composition root: the only place that chooses concrete adapters and wires handlers.

One `<context>_handlers_builder.py` per context. Commands ask for a context's handlers
here; tests can pass replacement adapters through the keyword arguments instead of
patching anything.
"""

from .agent_hooks_handlers_builder import AgentHooksHandlers, build_agent_hooks
from .capture_handlers_builder import (
    CAPTURE_FOLDER,
    LOCK_TIMEOUT_SECONDS,
    CaptureHandlers,
    build_capture,
    curator_command,
)
from .diagnostics_handlers_builder import (
    DOCTOR_UPDATE_TIMEOUT_SECONDS,
    UPDATE_CHECK_TIMEOUT_SECONDS,
    build_diagnostics,
    build_update_check,
    installed_package_dir,
    run_diagnostics,
    run_update_check,
)
from .notes_handlers_builder import (
    APPLY_FAILED_FOLDER,
    PARKED_FOLDER,
    NotesHandlers,
    build_apply,
    build_curator,
    build_notes,
    build_unit_of_work_factory,
    curator_system_prompt,
    needs_vault,
    require_vault,
)
from .obsidian_mcp_client_builder import build_obsidian_mcp_client
from .vault_handlers_builder import VaultHandlers, build_vault

__all__ = [
    "AgentHooksHandlers",
    "CaptureHandlers",
    "NotesHandlers",
    "VaultHandlers",
    "APPLY_FAILED_FOLDER",
    "CAPTURE_FOLDER",
    "DOCTOR_UPDATE_TIMEOUT_SECONDS",
    "LOCK_TIMEOUT_SECONDS",
    "PARKED_FOLDER",
    "UPDATE_CHECK_TIMEOUT_SECONDS",
    "build_agent_hooks",
    "build_apply",
    "build_capture",
    "build_curator",
    "build_diagnostics",
    "build_notes",
    "build_obsidian_mcp_client",
    "build_update_check",
    "build_vault",
    "build_unit_of_work_factory",
    "curator_command",
    "curator_system_prompt",
    "installed_package_dir",
    "needs_vault",
    "require_vault",
    "run_diagnostics",
    "run_update_check",
]
