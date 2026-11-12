"""One line of a migration plan."""

from noesis.utils import FrozenObject

from .migration_action_enum import MigrationActionEnum


class MigrationEntry(FrozenObject):
    """A file, where it goes, and what to do with it.

    Attributes:
        old: Current path, relative to the vault root.
        new: Target path; for `keep` it is the same as `old` and may be left out.
        action: `note`, `move` or `keep`.
        scope: `repo:<name>` or `topic:<name>`; required by `note`.
        kind: Kind name from the catalog; required by `note`.
    """

    old: str
    new: str | None = None
    action: MigrationActionEnum
    scope: str | None = None
    kind: str | None = None

    @property
    def target(self) -> str:
        """Where the file ends up."""
        return self.old if self.action is MigrationActionEnum.KEEP or not self.new else self.new

    @property
    def relocates(self) -> bool:
        """Whether the file changes path (its old path goes away once the target is verified)."""
        return self.action is not MigrationActionEnum.KEEP and self.target != self.old
