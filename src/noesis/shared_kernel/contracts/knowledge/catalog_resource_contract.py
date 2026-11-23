"""Search over cataloged and installed resources (skills, agents, CLI tools, MCP servers).

Retrieval sends the query to Knowledge and gets hits back; both cross the context boundary as
JSON-native data. A hit is either a head revision of a catalog entry (`cataloged`) or, when the
caller asked for unsynced artifacts, something a runtime has installed that has no entry yet.
"""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from noesis.utils import FrozenObject

CATALOG_RESOURCE_CONTRACT_VERSION: Literal[1] = 1
ENTRY_ID_PATTERN: str = r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"
"""A ULID; defined here because a kernel contract imports no bounded context."""

type ResourceEntryId = Annotated[str, StringConstraints(pattern=ENTRY_ID_PATTERN)]
type ResourceKind = Literal["skill", "agent", "cli_tool", "mcp_server"]
type ResourceRuntime = Literal["claude-code", "codex"]
type ResourceOrigin = Literal["registered", "discovered"]


class CatalogResourceQueryContract(FrozenObject):
    """Version 1 of the resource query.

    Attributes:
        contract_version: Schema version of this payload.
        space_id: The active knowledge space; only its entries are searched.
        text: The raw request text; used as the terms when `terms` is empty.
        terms: Search terms already extracted by the caller; may be empty.
        kinds: Kinds to return; empty for all.
        limit: At most this many hits.
        runtimes: Runtimes whose installed artifacts are looked at (discovery and
            `discovered_runtimes`); empty when none could be resolved.
        include_unsynced: Also return installed artifacts that have no catalog entry, read live
            from the runtimes and never written.
    """

    contract_version: Literal[1] = CATALOG_RESOURCE_CONTRACT_VERSION
    space_id: str
    text: str = ""
    terms: tuple[str, ...] = ()
    kinds: tuple[ResourceKind, ...] = ()
    limit: int = Field(default=20, ge=1, le=100)
    runtimes: tuple[ResourceRuntime, ...] = ()
    include_unsynced: bool = False


class CatalogResourceLookupContract(FrozenObject):
    """Version 1 of the exact lookup, used to follow prerequisites and recommendations.

    Attributes:
        contract_version: Schema version of this payload.
        space_id: The active knowledge space; only its entries are looked up.
        refs: Resources named `kind:name`.
        entry_ids: Catalog entry ids to look up.
        runtimes: Runtimes whose installed artifacts answer for refs the catalog lacks.
        include_unsynced: Also resolve refs from installed artifacts that have no entry yet,
            read live and never written.
    """

    contract_version: Literal[1] = CATALOG_RESOURCE_CONTRACT_VERSION
    space_id: str
    refs: tuple[str, ...] = ()
    entry_ids: tuple[ResourceEntryId, ...] = ()
    runtimes: tuple[ResourceRuntime, ...] = ()
    include_unsynced: bool = False


class CatalogResourceHitContract(FrozenObject):
    """One resource that matches the query.

    Attributes:
        catalog_id: The entry; None for an installed artifact that has no entry.
        kind: `skill`, `agent`, `cli_tool` or `mcp_server`.
        name: Entry or artifact name.
        revision: Head revision number; None when not cataloged.
        purpose: What it is for (the manifest description when not cataloged).
        capabilities: Capability tags of the head revision; empty when not cataloged.
        prerequisites: What must be present, as `kind:name`; what the manifest declares when not
            cataloged.
        manifest_digest: Hash of the manifest the revision (or the installed file) has, if any.
        origin: `registered` for an entry stated by hand; `discovered` for one a sync created
            and for every uncataloged artifact.
        cataloged: Whether a catalog entry exists.
        discovered_runtimes: Requested runtimes in which the artifact is installed.
        score: Relevance in 0..1; comparable between cataloged and uncataloged hits.
    """

    catalog_id: ResourceEntryId | None = None
    kind: ResourceKind
    name: str
    revision: int | None = None
    purpose: str
    capabilities: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()
    manifest_digest: str | None = None
    origin: ResourceOrigin = "registered"
    cataloged: bool
    discovered_runtimes: tuple[ResourceRuntime, ...] = ()
    score: float = Field(ge=0.0, le=1.0)
