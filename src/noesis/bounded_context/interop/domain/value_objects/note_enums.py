"""Block reasons, outcomes and warnings of a note."""

from enum import StrEnum


class NoteBlockReasonEnum(StrEnum):
    """Why interop itself blocks a note before Knowledge is asked."""

    NOT_TEXT = "not_text"
    INVALID_HEADER = "invalid_header"
    INVALID_ID = "invalid_id"
    DUPLICATE_ID = "duplicate_id"
    INVALID_SCOPE = "invalid_scope"


class NoteOutcomeEnum(StrEnum):
    """What happened to a note in an import run."""

    CREATED = "created"
    UNCHANGED = "unchanged"
    CHANGED_IN_VAULT = "changed_in_vault"
    REVISED = "revised"
    SUCCESSOR_PROPOSED = "successor_proposed"
    SKIPPED_EMPTY = "skipped_empty"
    BLOCKED = "blocked"


class NoteWarningEnum(StrEnum):
    """Warnings of a note; `dropped_tag` and `ignored_field` are written `<warning>:<value>`."""

    LEGACY_HEADER = "legacy_header"
    DROPPED_TAG = "dropped_tag"
    IGNORED_SCOPE = "ignored_scope"
    IGNORED_FIELD = "ignored_field"
