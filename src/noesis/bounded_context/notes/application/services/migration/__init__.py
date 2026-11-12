"""Vault migration: the plan, the wikilink rewriting and the note header conversion."""

from .migration_action_enum import MigrationActionEnum
from .migration_entry import MigrationEntry
from .migration_plan import MigrationPlan
from .note_document_migrator import LEGACY_KEYS, NoteDocumentMigrator
from .wikilink_rewriter import WikilinkRewriter

__all__ = [
    "LEGACY_KEYS",
    "MigrationActionEnum",
    "MigrationEntry",
    "MigrationPlan",
    "NoteDocumentMigrator",
    "WikilinkRewriter",
]
