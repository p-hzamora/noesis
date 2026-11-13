"""A group: an extra root of the vault that some repositories' notes live under."""

import re
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from pydantic import ConfigDict, field_validator

from noesis.exceptions import InvalidManifestError
from noesis.utils import FrozenObject

GROUP_NAME: re.Pattern[str] = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class GroupMatch(FrozenObject):
    """Which repositories belong to a group: any remote glob or any listed name.

    Attributes:
        remotes: Globs on the canonical remote (`host/path`, no scheme and no `.git`).
        repos: Repository names that belong to the group whatever their remote.
    """

    model_config = ConfigDict(extra="forbid")

    remotes: tuple[str, ...] = ()
    repos: tuple[str, ...] = ()


class GroupSpec(FrozenObject):
    """Where a set of repositories keeps its notes, and which repositories those are.

    Attributes:
        root: Vault-relative folder the group's notes live under, e.g. `company/acme`.
        match: Which repositories belong to it.
    """

    model_config = ConfigDict(extra="forbid")

    root: str
    match: GroupMatch = GroupMatch()

    @field_validator("root")
    @classmethod
    def _inside_the_vault(cls, root: str) -> str:
        path = PurePosixPath(root)
        if not root.strip("/") or path.is_absolute() or ".." in path.parts or "\\" in root:
            raise InvalidManifestError(
                f"Invalid group root {root!r}.",
                {"root": root},
                next_steps=["Use a relative folder inside the vault, without `..`."],
            )
        return path.as_posix()

    def matches(self, repository: str, remote: str | None) -> bool:
        """Whether the repository belongs to this group."""
        return repository in self.match.repos or (
            remote is not None and any(fnmatchcase(remote, g) for g in self.match.remotes)
        )


def check_group_name(name: str) -> str:
    """`name` when it is a valid group name.

    Raises:
        InvalidManifestError: The name is not lowercase letters, digits, `-` or `_`.
    """
    if not GROUP_NAME.match(name):
        raise InvalidManifestError(
            f"Invalid group name {name!r}.",
            {"group": name},
            next_steps=["Use lowercase letters, digits, `-` and `_`."],
        )
    return name
