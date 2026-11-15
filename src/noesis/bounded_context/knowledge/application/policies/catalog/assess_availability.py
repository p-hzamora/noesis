"""The availability policy: one cataloged entry against one runtime inventory."""

from noesis.bounded_context.knowledge.application.dtos import (
    AvailabilityObservationDto,
    AvailabilityReasonEnum,
    AvailabilityStatusEnum,
    CatalogEntryDto,
    InstalledArtifactDto,
    RuntimeInventoryDto,
)
from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum, CatalogRef


def assess_availability(
    entry: CatalogEntryDto, inventory: RuntimeInventoryDto
) -> AvailabilityObservationDto:
    """Decide `status` and `reason` of `entry` in `inventory`; the first matching rule wins.

    1. The entry's kind is unreadable: `unknown`, with that kind's reason.
    2. No installed artifact has the same kind and exact name: `unavailable / not_installed`.
    3. A prerequisite of a readable kind has no installed match: `unavailable /
       prerequisite_missing`, listing every such prerequisite in declared order (one level deep).
    4. A prerequisite is of an unreadable kind (none missing): `unknown`, with the reason of the
       first such prerequisite; nothing is reported missing.
    5. Otherwise `available / none`.

    Matching is exact on kind and name. `version_drift` is set only on `available`.

    Args:
        entry: The entry with its head content.
        inventory: What the runtime (and host) has installed, and what could not be read.

    Returns:
        The observation, never stored.
    """
    unreadable: dict[CatalogEntryKindEnum, AvailabilityReasonEnum] = {
        item.kind: item.reason for item in inventory.unreadable_kinds
    }
    installed: dict[tuple[CatalogEntryKindEnum, str], InstalledArtifactDto] = {
        (artifact.kind, artifact.name): artifact for artifact in reversed(inventory.artifacts)
    }
    match: InstalledArtifactDto | None = installed.get((entry.kind, entry.name))
    observed_version: str | None = match.observed_version if match else None

    def observe(
        status: AvailabilityStatusEnum,
        reason: AvailabilityReasonEnum,
        *,
        missing: tuple[str, ...] = (),
        drift: bool | None = None,
    ) -> AvailabilityObservationDto:
        return AvailabilityObservationDto(
            entry_id=entry.id,
            kind=entry.kind,
            name=entry.name,
            runtime=inventory.runtime,
            host=inventory.host,
            observed_at=inventory.observed_at,
            status=status,
            reason=reason,
            observed_version=observed_version,
            version_drift=drift,
            missing_prerequisites=missing,
        )

    if entry.kind in unreadable:
        return observe(AvailabilityStatusEnum.UNKNOWN, unreadable[entry.kind])
    if match is None:
        return observe(AvailabilityStatusEnum.UNAVAILABLE, AvailabilityReasonEnum.NOT_INSTALLED)
    prerequisites: tuple[CatalogRef, ...] = tuple(CatalogRef.parse(p) for p in entry.prerequisites)
    missing: tuple[str, ...] = tuple(
        ref.as_text()
        for ref in prerequisites
        if ref.kind not in unreadable and (ref.kind, ref.name.value) not in installed
    )
    if missing:
        return observe(
            AvailabilityStatusEnum.UNAVAILABLE,
            AvailabilityReasonEnum.PREREQUISITE_MISSING,
            missing=missing,
        )
    unreadable_prerequisite: CatalogRef | None = next(
        (ref for ref in prerequisites if ref.kind in unreadable), None
    )
    if unreadable_prerequisite is not None:
        return observe(AvailabilityStatusEnum.UNKNOWN, unreadable[unreadable_prerequisite.kind])
    declared: str | None = entry.declared_version
    drift: bool | None = (
        declared != observed_version
        if declared is not None and observed_version is not None
        else None
    )
    return observe(AvailabilityStatusEnum.AVAILABLE, AvailabilityReasonEnum.NONE, drift=drift)
