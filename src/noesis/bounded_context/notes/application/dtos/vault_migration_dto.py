"""What a vault migration did, or would do."""

from noesis.shared_kernel.application.dtos import BaseDto


class VaultMigrationDto(BaseDto):
    """The outcome of `MigrateVaultHandler`; on a dry run every count is a prediction.

    Attributes:
        applied: Whether files were written (false for a dry run).
        notes: Plan entries with action `note`.
        moves: Plan entries with action `move`.
        keeps: Plan entries with action `keep`.
        to_write: Target files not yet written.
        already_done: Targets already in place (a resumed or repeated run).
        to_delete: Old files waiting for their verified target to go away.
        links_rewritten: Wikilinks rewritten.
        link_files: Files that held rewritten links.
        unresolved_before: Wikilinks that point at no file before the migration.
        unresolved_after: Wikilinks that point at no file after it.
        dirs_removed: Empty folders removed.
        lines: One line per entry that has work left (or was done), for `--verbose`.
    """

    applied: bool
    notes: int
    moves: int
    keeps: int
    to_write: int
    already_done: int
    to_delete: int
    links_rewritten: int
    link_files: int
    unresolved_before: int
    unresolved_after: int
    dirs_removed: int
    lines: tuple[str, ...] = ()

    @property
    def pending(self) -> int:
        """Work a dry run still finds: zero means the vault already matches the plan."""
        return self.to_write + self.to_delete + self.links_rewritten + self.dirs_removed
