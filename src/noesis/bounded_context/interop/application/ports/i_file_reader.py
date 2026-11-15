"""Read-only access to one file given to `import file`."""

import abc


class IFileReader(abc.ABC):
    """Resolves and reads a file; has no method that writes, renames or deletes (NFR-001)."""

    @abc.abstractmethod
    def resolve(self, path: str) -> str:
        """The absolute path with every symbolic link resolved.

        Raises:
            FileReadFailedError: Missing, not a regular file, or unreadable.
        """
        ...

    @abc.abstractmethod
    def read(self, absolute_path: str) -> bytes:
        """The raw bytes of a resolved file.

        Raises:
            FileReadFailedError: The file cannot be read.
        """
        ...
