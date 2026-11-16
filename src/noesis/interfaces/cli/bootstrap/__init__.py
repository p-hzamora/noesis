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
    curate_brief_argv,
    curator_command,
)
from .curation_handlers_builder import (
    CURATION_FOLDER,
    CurationHandlers,
    build_claude_curator,
    build_curation,
    build_curation_inbox,
    build_parked_listing,
    curation_system_prompt,
    open_curation,
    related_lookup_mode,
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
from .import_handlers_builder import (
    VaultImportHandlers,
    open_file_import,
    open_vault_import,
)
from .knowledge_handlers_builder import (
    KnowledgeHandlers,
    build_catalog_availability_adapter,
    build_knowledge,
    open_knowledge,
    registered_schema_step_names,
    with_knowledge,
)

__all__ = [
    "AgentHooksHandlers",
    "CaptureHandlers",
    "CurationHandlers",
    "KnowledgeHandlers",
    "VaultImportHandlers",
    "CAPTURE_FOLDER",
    "CURATION_FOLDER",
    "DOCTOR_UPDATE_TIMEOUT_SECONDS",
    "LOCK_TIMEOUT_SECONDS",
    "UPDATE_CHECK_TIMEOUT_SECONDS",
    "build_agent_hooks",
    "build_catalog_availability_adapter",
    "build_capture",
    "build_claude_curator",
    "build_curation",
    "build_curation_inbox",
    "build_diagnostics",
    "build_knowledge",
    "build_parked_listing",
    "build_update_check",
    "curate_brief_argv",
    "curation_system_prompt",
    "curator_command",
    "installed_package_dir",
    "open_curation",
    "open_file_import",
    "open_knowledge",
    "open_vault_import",
    "registered_schema_step_names",
    "related_lookup_mode",
    "run_diagnostics",
    "run_update_check",
    "with_knowledge",
]
