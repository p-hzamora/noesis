"""Wires the vault restructuring handlers: file-level, independent of the writer backend."""

from dataclasses import dataclass
from pathlib import Path

from noesis.bounded_context.notes.application.handlers.commands import MigrateVaultHandler
from noesis.bounded_context.notes.application.handlers.queries import DiagnoseVaultHandler
from noesis.bounded_context.notes.application.services.migration import NoteDocumentMigrator
from noesis.bounded_context.notes.infrastructure.outbound.frontmatter import (
    YamlFrontmatterCodecAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.ids import UlidNoteIdGeneratorAdapter
from noesis.bounded_context.notes.infrastructure.outbound.vault import (
    FilesystemVaultFilesAdapter,
)
from noesis.core import Environment
from noesis.shared_kernel.infrastructure.outbound.clock import SystemClockAdapter

from .notes_handlers_builder import build_manifest_provider, require_vault


@dataclass(frozen=True, slots=True, kw_only=True)
class VaultHandlers:
    """The vault restructuring actions, wired.

    Attributes:
        doctor: Count notes by frontmatter state and find duplicate projects.
        migrate: Plan or apply a restructure.
    """

    doctor: DiagnoseVaultHandler
    migrate: MigrateVaultHandler


def build_vault(environment: Environment) -> VaultHandlers:
    """Wire the vault handlers over the folder `NOESIS_VAULT_DIR` names.

    Raises:
        VaultNotConfiguredError: No vault folder is configured.
    """
    vault: Path = require_vault(environment)
    clock = SystemClockAdapter()
    codec = YamlFrontmatterCodecAdapter()
    files = FilesystemVaultFilesAdapter(vault)
    manifests = build_manifest_provider(vault)
    return VaultHandlers(
        doctor=DiagnoseVaultHandler(vault=files, manifests=manifests, codec=codec),
        migrate=MigrateVaultHandler(
            vault=files,
            manifests=manifests,
            migrator=NoteDocumentMigrator(
                codec, UlidNoteIdGeneratorAdapter(clock), clock.now().date()
            ),
        ),
    )
