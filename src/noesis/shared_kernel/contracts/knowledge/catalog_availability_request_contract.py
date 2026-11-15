"""Request to check whether cataloged capabilities are available in agent runtimes.

Retrieval sends it to Knowledge; it crosses the context boundary as JSON-native data.
"""

from typing import Annotated, Literal

from pydantic import StringConstraints

from noesis.utils import FrozenObject

CATALOG_AVAILABILITY_REQUEST_VERSION: Literal[1] = 1
ENTRY_ID_PATTERN: str = r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"
"""A ULID; defined here because a kernel contract imports no bounded context."""

type EntryId = Annotated[str, StringConstraints(pattern=ENTRY_ID_PATTERN)]


class CatalogAvailabilityRequestContract(FrozenObject):
    """Version 1 of the availability request.

    Attributes:
        contract_version: Schema version of this payload.
        space_id: The active knowledge space; only its entries are checked.
        entry_ids: Ids (ULIDs) of the catalog entries to check.
        runtimes: Runtimes to check, resolved by the caller; empty when none could be resolved.
    """

    contract_version: Literal[1] = CATALOG_AVAILABILITY_REQUEST_VERSION
    space_id: str
    entry_ids: tuple[EntryId, ...] = ()
    runtimes: tuple[Literal["claude-code", "codex"], ...] = ()
