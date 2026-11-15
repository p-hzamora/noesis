"""`noesis catalog` output."""

from datetime import datetime

from noesis.utils import FrozenObject

from .i_renderable_response import IRenderableResponse
from .record_response import RecordActorResponse


class CatalogWriteResponse(IRenderableResponse):
    """`catalog register` and `catalog revise`: the entry written, or found unchanged.

    Attributes:
        id: The entry.
        kind: Entry kind.
        name: Entry name.
        revision: Revision written; the unchanged head number for a no-op revise.
        space_id: Space it lives in.
        replayed: True when the idempotency key was already used and nothing was written.
    """

    id: str
    kind: str
    name: str
    revision: int
    space_id: str
    replayed: bool = False

    def render(self) -> str:
        note: str = " (replayed: nothing written)" if self.replayed else ""
        return f"{self.kind}:{self.name} {self.id} at revision {self.revision}{note}"


class CatalogEntryResponse(FrozenObject):
    """A catalog entry with its head content.

    Attributes:
        id: Entry id.
        space_id: Owning space.
        kind: Entry kind.
        name: Entry name.
        head_revision: Number of the head revision.
        purpose: What it is for.
        declared_version: Declared version, when there is one.
        prerequisites: What must be present, as `kind:name`.
        location: Where its definition lives.
    """

    id: str
    space_id: str
    kind: str
    name: str
    head_revision: int
    purpose: str
    declared_version: str | None = None
    prerequisites: tuple[str, ...] = ()
    location: str


class CatalogListResponse(IRenderableResponse):
    """`catalog list`.

    Attributes:
        entries: The entries, by kind then name.
    """

    entries: tuple[CatalogEntryResponse, ...]

    def render(self) -> str:
        if not self.entries:
            return "no catalog entries"
        return "\n".join(
            f"{entry.kind}:{entry.name}  {entry.id}  rev {entry.head_revision}  {entry.purpose}"
            for entry in self.entries
        )


class CatalogShowResponse(CatalogEntryResponse, IRenderableResponse):
    """`catalog show`: the entry with one revision's content and envelope.

    `purpose`, `declared_version`, `prerequisites` and `location` are the shown revision's.

    Attributes:
        number: Number of the revision shown.
        actor: Who made it.
        created_at: When.
        sources: Ids of the sources it cites.
    """

    number: int
    actor: RecordActorResponse
    created_at: datetime
    sources: tuple[str, ...] = ()

    def render(self) -> str:
        lines: list[str] = [
            f"{self.kind}:{self.name} {self.id}",
            f"revision {self.number} of {self.head_revision}: {self.purpose}",
            f"location: {self.location}",
        ]
        if self.declared_version:
            lines.append(f"declared version: {self.declared_version}")
        if self.prerequisites:
            lines.append(f"requires: {', '.join(self.prerequisites)}")
        lines.append(f"by: {self.actor.kind} {self.actor.name}")
        lines.append(f"created: {self.created_at.isoformat()}")
        lines += [f"source: {source}" for source in self.sources]
        return "\n".join(lines)


class UnreadableKindResponse(FrozenObject):
    """A kind that could not be read.

    Attributes:
        kind: The kind.
        reason: `probe_failed` or `kind_not_probed`.
    """

    kind: str
    reason: str


class ObservationResponse(FrozenObject):
    """One entry assessed against one runtime.

    Attributes:
        entry_id: The entry.
        kind: Entry kind.
        name: Entry name.
        runtime: Runtime observed.
        host: Machine observed.
        observed_at: ISO-8601 UTC time.
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
    runtime: str
    host: str
    observed_at: str
    status: str
    reason: str
    observed_version: str | None = None
    version_drift: bool | None = None
    missing_prerequisites: tuple[str, ...] = ()


class AvailabilitySummaryResponse(FrozenObject):
    """Observation counts of one runtime.

    Attributes:
        available: Entries `available`.
        unavailable: Entries `unavailable`.
        unknown: Entries `unknown`.
    """

    available: int
    unavailable: int
    unknown: int


class CheckRuntimeResponse(FrozenObject):
    """The observations of one runtime.

    Attributes:
        runtime: The runtime.
        host: Machine observed.
        observed_at: ISO-8601 UTC time.
        observations: One per selected entry.
        summary: Counts per status.
        unreadable_kinds: Kinds that could not be read.
    """

    runtime: str
    host: str
    observed_at: str
    observations: tuple[ObservationResponse, ...] = ()
    summary: AvailabilitySummaryResponse
    unreadable_kinds: tuple[UnreadableKindResponse, ...] = ()


class CatalogCheckResponse(IRenderableResponse):
    """`catalog check`: what is available now, per runtime. Unavailability is data, not failure.

    Attributes:
        runtimes: One block per resolved runtime.
        next_steps: The location of each unavailable entry; `noesis catalog revise` for each
            entry whose installed version drifted.
    """

    runtimes: tuple[CheckRuntimeResponse, ...]
    next_steps: tuple[str, ...] = ()

    def render(self) -> str:
        lines: list[str] = []
        for block in self.runtimes:
            counts: AvailabilitySummaryResponse = block.summary
            lines.append(
                f"{block.runtime} on {block.host} at {block.observed_at}: "
                f"{counts.available} available, {counts.unavailable} unavailable, "
                f"{counts.unknown} unknown"
            )
            for item in block.observations:
                detail: str = item.reason if item.reason != "none" else ""
                if item.missing_prerequisites:
                    detail += f" ({', '.join(item.missing_prerequisites)})"
                if item.version_drift:
                    detail += f" (version drift: installed {item.observed_version})"
                lines.append(f"  {item.status:<11} {item.kind}:{item.name} {detail}".rstrip())
        lines += [f"next: {step}" for step in self.next_steps]
        return "\n".join(lines)


class UncatalogedResponse(FrozenObject):
    """An installed artifact with no entry.

    Attributes:
        kind: Artifact kind.
        name: Artifact name.
        observed_version: Installed version, when known.
    """

    kind: str
    name: str
    observed_version: str | None = None


class VersionDriftResponse(FrozenObject):
    """An available entry whose installed version differs from the declared one.

    Attributes:
        entry_id: The entry.
        kind: Entry kind.
        name: Entry name.
        declared_version: Version the catalog declares.
        observed_version: Version installed.
    """

    entry_id: str
    kind: str
    name: str
    declared_version: str
    observed_version: str


class NotInstalledResponse(FrozenObject):
    """An entry with no installed match.

    Attributes:
        entry_id: The entry.
        kind: Entry kind.
        name: Entry name.
        location: Where its definition lives.
    """

    entry_id: str
    kind: str
    name: str
    location: str


class ScanRuntimeResponse(FrozenObject):
    """The scan of one runtime.

    Attributes:
        runtime: The runtime.
        host: Machine observed.
        observed_at: ISO-8601 UTC time.
        uncataloged: Installed artifacts with no entry.
        version_drift: Entries whose installed version drifted.
        not_installed: Entries with no installed match.
        unreadable_kinds: Kinds that could not be read.
    """

    runtime: str
    host: str
    observed_at: str
    uncataloged: tuple[UncatalogedResponse, ...] = ()
    version_drift: tuple[VersionDriftResponse, ...] = ()
    not_installed: tuple[NotInstalledResponse, ...] = ()
    unreadable_kinds: tuple[UnreadableKindResponse, ...] = ()


class CatalogScanResponse(IRenderableResponse):
    """`catalog scan`: installed artifacts against the catalog, per runtime.

    Attributes:
        runtimes: One block per resolved runtime.
        next_steps: The location of each not-installed entry; `noesis catalog revise` for each
            entry whose installed version drifted.
    """

    runtimes: tuple[ScanRuntimeResponse, ...]
    next_steps: tuple[str, ...] = ()

    def render(self) -> str:
        lines: list[str] = []
        for block in self.runtimes:
            lines.append(f"{block.runtime} on {block.host} at {block.observed_at}")
            lines += [
                f"  uncataloged {item.kind}:{item.name} {item.observed_version or ''}".rstrip()
                for item in block.uncataloged
            ]
            lines += [
                f"  drift {item.kind}:{item.name} declared {item.declared_version}, "
                f"installed {item.observed_version}"
                for item in block.version_drift
            ]
            lines += [
                f"  not installed {item.kind}:{item.name} ({item.location})"
                for item in block.not_installed
            ]
            lines += [f"  unreadable {item.kind}: {item.reason}" for item in block.unreadable_kinds]
        lines += [f"next: {step}" for step in self.next_steps]
        return "\n".join(lines)
