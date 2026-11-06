"""Identity of a repository: its folder name plus a digest of where it lives."""

import hashlib
import re
from typing import Self

from pydantic import Field

from noesis.shared_kernel.domain.value_objects import ValueObject

MAX_NAME_LENGTH: int = 40
DIGEST_LENGTH: int = 8
_UNSAFE: re.Pattern[str] = re.compile(r"[^A-Za-z0-9_-]+")
FALLBACK_NAME: str = "repo"


class RepoId(ValueObject):
    """`<name>-<digest>`: two repositories sharing a folder name still get distinct ids.

    Attributes:
        name: The main folder name, sanitized and capped at 40 characters.
        digest: First 8 hex characters of the sha256 of the repository identity (the resolved
            absolute common git directory).
    """

    name: str = Field(pattern=rf"^[A-Za-z0-9_-]{{1,{MAX_NAME_LENGTH}}}$")
    digest: str = Field(pattern=rf"^[0-9a-f]{{{DIGEST_LENGTH}}}$")

    @classmethod
    def derive(cls, name: str, identity: str) -> Self:
        """The id of the repository called `name` that lives at `identity`.

        Args:
            name: Display name (the main folder name); unsafe characters become `-`.
            identity: The resolved absolute common git directory.
        """
        safe: str = _UNSAFE.sub("-", name).strip("-")[:MAX_NAME_LENGTH].strip("-")
        digest: str = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:DIGEST_LENGTH]
        return cls(name=safe or FALLBACK_NAME, digest=digest)

    @classmethod
    def parse(cls, value: str) -> Self:
        """The id a printed `<name>-<digest>` stands for.

        Raises:
            ValueError: `value` is not shaped like an id.
        """
        name, _, digest = value.rpartition("-")
        return cls(name=name, digest=digest)

    @property
    def value(self) -> str:
        """`<name>-<digest>`."""
        return f"{self.name}-{self.digest}"
