"""Canonical references and the action that loads a resource."""

import re
from typing import Final

from ..enums import NextActionEnum

_NAME: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][\w.:@+/-]*$")
_ULID: Final[re.Pattern[str]] = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
CATALOG_PREFIX: Final[str] = "catalog:"


class ResourceRefPolicy:
    """Refs are built only from a kind in the closed set and a name made of safe characters.

    A name with spaces, quotes, `;`, `$` or any other shell-significant character has no ref, so
    stored text can never reach the caller as something to run.
    """

    def resource_ref(self, kind: str, name: str) -> str | None:
        """`catalog:<kind>:<name>`, or None when the kind or the name is not safe."""
        if self.action_for(kind) is None or not _NAME.fullmatch(name):
            return None
        return f"{CATALOG_PREFIX}{kind}:{name}"

    def prerequisite_ref(self, prerequisite: str) -> str | None:
        """The ref of a declared prerequisite written `kind:name`."""
        kind, _, name = prerequisite.partition(":")
        return self.resource_ref(kind, name)

    def lookup_key(self, ref: str) -> str:
        """The `kind:name` of a canonical ref."""
        return ref.removeprefix(CATALOG_PREFIX)

    def record_ref(self, record_id: str, revision: int | None) -> str | None:
        """`record:<ulid>@<revision>`, or None for a record without a revision or id."""
        if revision is None or not _ULID.fullmatch(record_id):
            return None
        return f"record:{record_id}@{revision}"

    def action_for(self, kind: str) -> NextActionEnum | None:
        """The action that loads a resource of `kind`."""
        match kind:
            case "skill":
                return NextActionEnum.LOAD_SKILL
            case "agent":
                return NextActionEnum.USE_AGENT
            case "cli_tool":
                return NextActionEnum.USE_CLI_TOOL
            case "mcp_server":
                return NextActionEnum.USE_MCP_SERVER
            case _:
                return None
