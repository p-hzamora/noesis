"""Building the runtime inventories a check or a scan assesses entries against."""

from collections.abc import Mapping, Sequence

from noesis.bounded_context.knowledge.application.dtos import (
    CatalogEntryDto,
    InstalledArtifactDto,
    RuntimeEnum,
    RuntimeInventoryDto,
)
from noesis.bounded_context.knowledge.application.ports.runtime import (
    IHostToolProbe,
    IRuntimeInventoryProbe,
)
from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum, CatalogRef


def host_tool_names(entries: Sequence[CatalogEntryDto]) -> tuple[str, ...]:
    """Names to look up on the host: the `cli_tool` entries and every `cli_tool` prerequisite."""
    names: list[str] = []
    for entry in entries:
        if entry.kind is CatalogEntryKindEnum.CLI_TOOL:
            names.append(entry.name)
        for text in entry.prerequisites:
            prerequisite: CatalogRef = CatalogRef.parse(text)
            if prerequisite.kind is CatalogEntryKindEnum.CLI_TOOL:
                names.append(prerequisite.name.value)
    return tuple(dict.fromkeys(names))


async def build_inventories(
    probes: Mapping[RuntimeEnum, IRuntimeInventoryProbe],
    host_tools: IHostToolProbe,
    runtimes: Sequence[RuntimeEnum],
    entries: Sequence[CatalogEntryDto],
) -> tuple[RuntimeInventoryDto, ...]:
    """Probe each runtime once and the host once; the host's tools join every inventory.

    Args:
        probes: The runtime probes by runtime.
        host_tools: The `PATH` probe.
        runtimes: Runtimes to probe, in the order the blocks should come back.
        entries: The entries being assessed; they decide which tool names the host is asked for.

    Returns:
        One inventory per runtime, in the order asked.
    """
    names: tuple[str, ...] = host_tool_names(entries)
    found: tuple[InstalledArtifactDto, ...] = host_tools.find(names) if names else ()
    inventories: list[RuntimeInventoryDto] = []
    for runtime in runtimes:
        inventory: RuntimeInventoryDto = await probes[runtime].inventory()
        inventories.append(
            inventory.model_copy(update={"artifacts": (*inventory.artifacts, *found)})
        )
    return tuple(inventories)
