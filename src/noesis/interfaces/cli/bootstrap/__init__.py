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
from .diagnostics_handlers_builder import build_diagnostics, run_diagnostics
from .knowledge_handlers_builder import (
    PARKED_FOLDER,
    KnowledgeHandlers,
    build_curator,
    build_knowledge,
    build_unit_of_work_factory,
    curator_system_prompt,
    needs_vault,
    require_vault,
)
from .obsidian_mcp_client_builder import build_obsidian_mcp_client

__all__ = [
    "AgentHooksHandlers",
    "CaptureHandlers",
    "KnowledgeHandlers",
    "CAPTURE_FOLDER",
    "LOCK_TIMEOUT_SECONDS",
    "PARKED_FOLDER",
    "build_agent_hooks",
    "build_capture",
    "build_curator",
    "build_diagnostics",
    "build_knowledge",
    "build_obsidian_mcp_client",
    "build_unit_of_work_factory",
    "curator_command",
    "curator_system_prompt",
    "needs_vault",
    "require_vault",
    "run_diagnostics",
]
