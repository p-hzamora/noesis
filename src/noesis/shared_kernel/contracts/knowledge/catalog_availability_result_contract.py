"""Result of an availability check: what is installed, per runtime, at the time it ran.

Only an `available` entry may be presented as usable; `unknown` and `not_checked` mean not
verified. A result is valid for the invocation that produced it.
"""

from typing import Literal

from noesis.utils import FrozenObject

CATALOG_AVAILABILITY_RESULT_VERSION: Literal[1] = 1


class CatalogAvailabilityEntryContract(FrozenObject):
    """One cataloged entry assessed in one runtime.

    Attributes:
        entry_id: The entry.
        kind: `skill`, `agent`, `cli_tool` or `mcp_server`.
        name: Entry name.
        purpose: What it is for.
        declared_version: Version the catalog declares, when there is one.
        location: Where its definition lives (the install hint).
        status: `available`, `unavailable` or `unknown`.
        reason: `none`, `not_installed`, `prerequisite_missing`, `probe_failed` or
            `kind_not_probed`.
        observed_version: Installed version, when known.
        version_drift: On `available` only: whether declared and installed versions differ.
        missing_prerequisites: Prerequisites (`kind:name`) with no installed match.
    """

    entry_id: str
    kind: str
    name: str
    purpose: str
    declared_version: str | None = None
    location: str
    status: Literal["available", "unavailable", "unknown"]
    reason: Literal[
        "none", "not_installed", "prerequisite_missing", "probe_failed", "kind_not_probed"
    ]
    observed_version: str | None = None
    version_drift: bool | None = None
    missing_prerequisites: tuple[str, ...] = ()


class CatalogAvailabilityRuntimeContract(FrozenObject):
    """The entries assessed in one runtime.

    Attributes:
        runtime: `claude-code` or `codex`.
        host: Machine observed.
        observed_at: ISO-8601 UTC time of the observation.
        entries: One per requested entry.
    """

    runtime: Literal["claude-code", "codex"]
    host: str
    observed_at: str
    entries: tuple[CatalogAvailabilityEntryContract, ...] = ()


class CatalogAvailabilityResultContract(FrozenObject):
    """Version 1 of the availability result.

    Attributes:
        contract_version: Schema version of this payload.
        outcome: `checked`, or `not_checked` when no runtime could be resolved.
        reason_code: Why nothing was checked (`runtime_unresolved`); None when `checked`.
        runtimes: One block per requested runtime; empty when `not_checked`.
    """

    contract_version: Literal[1] = CATALOG_AVAILABILITY_RESULT_VERSION
    outcome: Literal["checked", "not_checked"]
    reason_code: str | None = None
    runtimes: tuple[CatalogAvailabilityRuntimeContract, ...] = ()
