"""Read-only access to the notes of a vault folder."""

import abc


class IVaultReader(abc.ABC):
    """Lists and reads notes; has no method that writes, renames or deletes (NFR-001)."""

    @abc.abstractmethod
    def list_notes(self) -> list[str]:
        """Relative POSIX paths of every note, sorted by code point.

        Raises:
            VaultReadFailedError: The vault folder is missing or unreadable.
        """
        ...

    @abc.abstractmethod
    def read(self, relative_path: str) -> bytes:
        """The raw bytes of one note.

        Raises:
            VaultReadFailedError: The note cannot be read.
        """
        ...
