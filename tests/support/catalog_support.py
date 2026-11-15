"""In-memory fakes, probes and builders for the catalog handler tests (C6).

The unit of work here extends C2's `FakeKnowledgeUnitOfWork` with `catalog_entries`, so the C2
fakes stay untouched. Committed catalog state lives in `FakeCatalogStore`, next to C2's store.
"""

import copy
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

from tests.support.knowledge_support import (
    AGENT,
    DEFAULT_SPACE_KEY,
    FakeKnowledgeStore,
    FakeKnowledgeUnitOfWork,
    FakeRecordReadRepository,
    KnowledgeEnv,
    make_env,
)

from noesis.bounded_context.knowledge.application.dtos import (
    CatalogEntryDetailDto,
    CatalogEntryDto,
    InstalledArtifactDto,
    RuntimeEnum,
    RuntimeInventoryDto,
    UnreadableKindDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.register_catalog_entry_handler import (
    RegisterCatalogEntryCommand,
    RegisterCatalogEntryHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.revise_catalog_entry_handler import (
    ReviseCatalogEntryCommand,
    ReviseCatalogEntryHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.catalog import (
    CheckCatalogAvailabilityHandler,
    CheckCatalogAvailabilityQuery,
    GetCatalogEntryHandler,
    ListCatalogEntriesHandler,
    ScanRuntimeCatalogHandler,
    ScanRuntimeCatalogQuery,
)
from noesis.bounded_context.knowledge.application.ports.read_repositories.i_catalog_entry_read_repository import (
    ICatalogEntryReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.runtime.i_host_tool_probe import (
    IHostToolProbe,
)
from noesis.bounded_context.knowledge.application.ports.runtime.i_runtime_inventory_probe import (
    IRuntimeInventoryProbe,
)
from noesis.bounded_context.knowledge.application.services.inputs import (
    NewSourceInput,
    SourceInput,
)
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CATALOG_STEP,
    CORE_STEP,
)
from noesis.bounded_context.knowledge.domain.entities import CatalogEntry
from noesis.bounded_context.knowledge.domain.repositories.i_catalog_entry_repository import (
    ICatalogEntryRepository,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    CatalogRevision,
    Key,
    RecordId,
    SourceKindEnum,
    SpaceId,
)
from noesis.exceptions import (
    EntryAlreadyExistsError,
    GraphStoreUnavailableError,
    RevisionConflictError,
)

CLAUDE: RuntimeEnum = RuntimeEnum("claude-code")
CODEX: RuntimeEnum = RuntimeEnum("codex")
HOST: str = "host-1"
OBSERVED_AT: str = "2026-11-14T12:00:00+00:00"
CATALOG_SOURCE: NewSourceInput = NewSourceInput(
    kind=SourceKindEnum.URL, locator="https://example.invalid/catalog"
)
SKILL: CatalogEntryKindEnum = CatalogEntryKindEnum.SKILL
AGENT_KIND: CatalogEntryKindEnum = CatalogEntryKindEnum.AGENT
CLI_TOOL: CatalogEntryKindEnum = CatalogEntryKindEnum.CLI_TOOL
MCP_SERVER: CatalogEntryKindEnum = CatalogEntryKindEnum.MCP_SERVER


# --- inventory and DTO builders ---------------------------------------------------------------


def artifact(kind: str, name: str, version: str | None = None) -> InstalledArtifactDto:
    """An installed artifact with a fake install location."""
    return InstalledArtifactDto(
        kind=kind, name=name, observed_version=version, install_location=f"/fake/{kind}/{name}"
    )


def unreadable(kind: str, reason: str) -> UnreadableKindDto:
    """A kind a probe could not read."""
    return UnreadableKindDto(kind=kind, reason=reason)


def inventory_of(
    runtime: RuntimeEnum = CLAUDE,
    *artifacts: InstalledArtifactDto,
    unreadable_kinds: tuple[UnreadableKindDto, ...] = (),
    host: str = HOST,
    observed_at: str = OBSERVED_AT,
) -> RuntimeInventoryDto:
    """A runtime inventory with the given artifacts."""
    return RuntimeInventoryDto(
        runtime=runtime,
        host=host,
        observed_at=observed_at,
        artifacts=artifacts,
        unreadable_kinds=unreadable_kinds,
    )


def entry_dto(
    kind: str = "skill",
    name: str = "demo",
    *,
    purpose: str = "purpose",
    version: str | None = None,
    prerequisites: tuple[str, ...] = (),
    location: str = "plugin@market",
    entry_id: str = "0" * 25 + "7",
    space_id: str = "0" * 25 + "1",
    head_revision: int = 1,
) -> CatalogEntryDto:
    """A catalog entry as the policy sees it."""
    return CatalogEntryDto(
        id=entry_id,
        space_id=space_id,
        kind=kind,
        name=name,
        head_revision=head_revision,
        purpose=purpose,
        declared_version=version,
        prerequisites=prerequisites,
        location=location,
    )


# --- probes -----------------------------------------------------------------------------------


class FakeRuntimeInventoryProbe(IRuntimeInventoryProbe):
    """Returns a fixed inventory and counts how often it was asked."""

    def __init__(self, inventory: RuntimeInventoryDto) -> None:
        self._inventory: RuntimeInventoryDto = inventory
        self.calls: int = 0

    @property
    def runtime(self) -> RuntimeEnum:
        """The runtime of the fixed inventory."""
        return self._inventory.runtime

    async def inventory(self) -> RuntimeInventoryDto:
        """The fixed inventory."""
        self.calls += 1
        return self._inventory


class FakeHostToolProbe(IHostToolProbe):
    """Finds the fixed names among those asked for and records every request."""

    def __init__(self, found: tuple[str, ...] = ()) -> None:
        self._found: tuple[str, ...] = found
        self.requests: list[tuple[str, ...]] = []

    @property
    def calls(self) -> int:
        """How many times `find` ran."""
        return len(self.requests)

    def find(self, names: tuple[str, ...]) -> tuple[InstalledArtifactDto, ...]:
        """The requested names that are in the fixed set, as `cli_tool` artifacts."""
        self.requests.append(tuple(names))
        return tuple(artifact("cli_tool", n) for n in names if n in self._found)


def probes_of(*probes: IRuntimeInventoryProbe) -> Mapping[RuntimeEnum, IRuntimeInventoryProbe]:
    """Runtime probes keyed by their runtime."""
    return {probe.runtime: probe for probe in probes}


# --- catalog store, unit of work, read repository ---------------------------------------------


@dataclass(slots=True)
class FakeCatalogStore:
    """Committed catalog entries (each holds its own revisions), by record id."""

    entries: dict[str, CatalogEntry] = field(default_factory=dict)


def _exists(key: str) -> EntryAlreadyExistsError:
    return EntryAlreadyExistsError(
        f"catalog entry {key} already exists.", {"kind": "catalog_entry", "key": key}
    )


class _CatalogRepo(ICatalogEntryRepository):
    def __init__(
        self,
        catalog: FakeCatalogStore,
        added: dict[str, CatalogEntry],
        revised: list[tuple[CatalogEntry, CatalogRevision]],
    ) -> None:
        self._catalog, self._added, self._revised = catalog, added, revised

    def _all(self) -> list[CatalogEntry]:
        return [*self._catalog.entries.values(), *self._added.values()]

    async def add(self, entry: CatalogEntry) -> None:
        if any(e.id == entry.id or e.catalog_key == entry.catalog_key for e in self._all()):
            raise _exists(entry.catalog_key)
        self._added[entry.id.value] = copy.deepcopy(entry)

    async def get(self, record_id: RecordId, *, space_id: SpaceId) -> CatalogEntry | None:
        return next(
            (copy.deepcopy(e) for e in self._all() if e.id == record_id and e.space_id == space_id),
            None,
        )

    async def get_by_key(
        self, space_id: SpaceId, kind: CatalogEntryKindEnum, name: object
    ) -> CatalogEntry | None:
        wanted: str = f"{space_id.value}:{CatalogEntryKindEnum(kind).value}:{name}"
        return next((copy.deepcopy(e) for e in self._all() if e.catalog_key == wanted), None)

    async def get_for_update(
        self, record_id: RecordId, *, space_id: SpaceId
    ) -> CatalogEntry | None:
        # No real lock; tests simulate a lost race by committing in between.
        return await self.get(record_id, space_id=space_id)

    async def append_revision(self, entry: CatalogEntry, revision: CatalogRevision) -> None:
        self._revised.append((copy.deepcopy(entry), revision))


class FakeCatalogUnitOfWork(FakeKnowledgeUnitOfWork):
    """C2's fake unit of work plus `catalog_entries`; commit re-checks the catalog constraints.

    Whoever commits second gets the error a constraint would raise: C2's
    `EntryAlreadyExistsError` for a duplicate `catalog_key`, `RevisionConflictError` for a
    revision number that already exists.
    """

    def __init__(self, store: FakeKnowledgeStore, catalog: FakeCatalogStore) -> None:
        super().__init__(store)
        self._catalog: FakeCatalogStore = catalog
        self._added: dict[str, CatalogEntry] = {}
        self._revised: list[tuple[CatalogEntry, CatalogRevision]] = []
        self._catalog_entries = _CatalogRepo(catalog, self._added, self._revised)

    @property
    def catalog_entries(self) -> ICatalogEntryRepository:
        """Fake catalog entry repository."""
        return self._catalog_entries

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self._added.clear()
        self._revised.clear()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.rollback()

    def _check_constraints(self) -> None:
        committed = self._catalog.entries
        for entry in self._added.values():
            if any(e.catalog_key == entry.catalog_key for e in committed.values()):
                raise _exists(entry.catalog_key)
        for entry, revision in self._revised:
            stored: CatalogEntry | None = committed.get(entry.id.value)
            if stored is not None and len(stored.revisions) >= revision.number:
                raise RevisionConflictError(
                    f"Revision {revision.number} already exists.",
                    {
                        "record_id": entry.id.value,
                        "expected_revision": revision.number - 1,
                        "actual_revision": stored.head_number,
                    },
                )

    async def commit(self) -> None:
        """Apply the staged writes, or raise the error a constraint would."""
        self._check_constraints()
        added: list[CatalogEntry] = list(self._added.values())
        revised: list[tuple[CatalogEntry, CatalogRevision]] = list(self._revised)
        await super().commit()
        for entry in added:
            self._catalog.entries[entry.id.value] = entry
        for entry, _ in revised:
            self._catalog.entries[entry.id.value] = entry

    async def rollback(self) -> None:
        """Drop everything staged."""
        self._added.clear()
        self._revised.clear()
        await super().rollback()


class _RacingCatalogUnitOfWork(FakeCatalogUnitOfWork):
    def __init__(
        self,
        store: FakeKnowledgeStore,
        catalog: FakeCatalogStore,
        hook: Callable[[], Awaitable[None]],
        fired: list[bool],
    ) -> None:
        super().__init__(store, catalog)
        self._hook, self._fired = hook, fired

    async def commit(self) -> None:
        """Let the competitor win first, once."""
        if not self._fired:
            self._fired.append(True)
            await self._hook()
        await super().commit()


def racing_catalog_factory(
    store: FakeKnowledgeStore, catalog: FakeCatalogStore, hook: Callable[[], Awaitable[None]]
) -> Callable[[], FakeCatalogUnitOfWork]:
    """A unit-of-work factory whose first commit is preceded by `hook`."""
    fired: list[bool] = []
    return lambda: _RacingCatalogUnitOfWork(store, catalog, hook, fired)


class FakeCatalogEntryReadRepository(ICatalogEntryReadRepository):
    """Builds read DTOs from the committed catalog; records which methods were called."""

    def __init__(self, catalog: FakeCatalogStore) -> None:
        self._catalog: FakeCatalogStore = catalog
        self.calls: list[str] = []

    @staticmethod
    def _entry_dto(entry: CatalogEntry) -> CatalogEntryDto:
        head: CatalogRevision = entry.head
        return CatalogEntryDto(
            id=entry.id.value,
            space_id=entry.space_id.value,
            kind=entry.kind.value,
            name=entry.name.value,
            head_revision=entry.head_number,
            purpose=head.purpose,
            declared_version=head.version,
            prerequisites=tuple(p.as_text() for p in head.prerequisites),
            location=head.location,
        )

    @staticmethod
    def _detail(entry: CatalogEntry, revision: CatalogRevision) -> CatalogEntryDetailDto:
        return CatalogEntryDetailDto(
            id=entry.id.value,
            space_id=entry.space_id.value,
            kind=entry.kind.value,
            name=entry.name.value,
            head_revision=entry.head_number,
            purpose=revision.purpose,
            declared_version=revision.version,
            prerequisites=tuple(p.as_text() for p in revision.prerequisites),
            location=revision.location,
            number=revision.number,
            actor_kind=revision.actor.kind.value,
            actor_name=revision.actor.name,
            actor_session=revision.actor.session,
            created_at=revision.created_at,
            source_ids=tuple(s.value for s in revision.source_ids),
        )

    def _detail_of(
        self, entry: CatalogEntry | None, revision: int | None
    ) -> CatalogEntryDetailDto | None:
        if entry is None:
            return None
        number: int = revision if revision is not None else entry.head_number
        if not 1 <= number <= len(entry.revisions):
            return None
        return self._detail(entry, entry.revisions[number - 1])

    async def get_by_id(
        self, record_id: RecordId, *, space_id: SpaceId, revision: int | None = None
    ) -> CatalogEntryDetailDto | None:
        """The entry with the requested revision (head by default), or None."""
        self.calls.append("get_by_id")
        entry: CatalogEntry | None = self._catalog.entries.get(record_id.value)
        if entry is not None and entry.space_id != space_id:
            entry = None
        return self._detail_of(entry, revision)

    async def get_by_key(
        self,
        space_id: SpaceId,
        kind: CatalogEntryKindEnum,
        name: object,
        *,
        revision: int | None = None,
    ) -> CatalogEntryDetailDto | None:
        """The entry with the requested revision (head by default), or None."""
        self.calls.append("get_by_key")
        wanted: str = f"{space_id.value}:{CatalogEntryKindEnum(kind).value}:{name}"
        entry: CatalogEntry | None = next(
            (e for e in self._catalog.entries.values() if e.catalog_key == wanted), None
        )
        return self._detail_of(entry, revision)

    async def find(
        self,
        space_id: SpaceId,
        *,
        kind: CatalogEntryKindEnum | None = None,
        name_prefix: str | None = None,
    ) -> tuple[CatalogEntryDto, ...]:
        """Entries of the space, optionally narrowed by kind and name prefix."""
        self.calls.append("find")
        return tuple(
            self._entry_dto(e)
            for e in self._catalog.entries.values()
            if e.space_id == space_id
            and (kind is None or e.kind == kind)
            and (name_prefix is None or e.name.value.startswith(name_prefix))
        )


class UnreachableCatalogReadRepository(ICatalogEntryReadRepository):
    """Every read fails the way a closed Neo4j port does."""

    @staticmethod
    def _down() -> GraphStoreUnavailableError:
        return GraphStoreUnavailableError(
            "Neo4j is unreachable.",
            {"phase": "connect"},
            next_steps=["Start Neo4j and check NOESIS_NEO4J_URI."],
        )

    async def get_by_id(
        self, record_id: RecordId, *, space_id: SpaceId, revision: int | None = None
    ) -> CatalogEntryDetailDto | None:
        """Always raises."""
        raise self._down()

    async def get_by_key(
        self,
        space_id: SpaceId,
        kind: CatalogEntryKindEnum,
        name: object,
        *,
        revision: int | None = None,
    ) -> CatalogEntryDetailDto | None:
        """Always raises."""
        raise self._down()

    async def find(
        self,
        space_id: SpaceId,
        *,
        kind: CatalogEntryKindEnum | None = None,
        name_prefix: str | None = None,
    ) -> tuple[CatalogEntryDto, ...]:
        """Always raises."""
        raise self._down()


# --- command and query builders ---------------------------------------------------------------


def register_command(
    key: str = "k1", *, sources: tuple[SourceInput, ...] = (CATALOG_SOURCE,), **overrides: object
) -> RegisterCatalogEntryCommand:
    """A valid register command (CLI tool `gh`); override what a test cares about."""
    values: dict[str, object] = {
        "idempotency_key": key,
        "space_key": DEFAULT_SPACE_KEY,
        "kind": CLI_TOOL,
        "name": "gh",
        "purpose": "GitHub CLI",
        "version": None,
        "prerequisites": (),
        "location": "https://github.com/cli/cli",
        "actor": AGENT,
        "sources": sources,
    }
    return RegisterCatalogEntryCommand(**{**values, **overrides})  # type: ignore[arg-type]


def revise_command(
    ref: str,
    key: str = "r1",
    *,
    expected: int = 1,
    sources: tuple[SourceInput, ...] = (CATALOG_SOURCE,),
    **overrides: object,
) -> ReviseCatalogEntryCommand:
    """A revise command that changes nothing unless `overrides` say so."""
    values: dict[str, object] = {
        "idempotency_key": key,
        "space_key": DEFAULT_SPACE_KEY,
        "ref": ref,
        "expected_revision": expected,
        "purpose": None,
        "version": None,
        "prerequisites": None,
        "location": None,
        "actor": AGENT,
        "sources": sources,
    }
    return ReviseCatalogEntryCommand(**{**values, **overrides})  # type: ignore[arg-type]


def check_query(
    *refs: str,
    kind: CatalogEntryKindEnum | None = None,
    runtimes: tuple[RuntimeEnum, ...] = (CLAUDE,),
    space_key: Key | None = DEFAULT_SPACE_KEY,
    space_id: SpaceId | None = None,
) -> CheckCatalogAvailabilityQuery:
    """A check query with exactly one of `space_key` and `space_id`."""
    space: dict[str, object] = (
        {"space_id": space_id} if space_id is not None else {"space_key": space_key}
    )
    return CheckCatalogAvailabilityQuery(refs=refs, kind=kind, runtimes=runtimes, **space)  # type: ignore[arg-type]


def scan_query(
    *,
    runtimes: tuple[RuntimeEnum, ...] = (CLAUDE,),
    space_key: Key | None = DEFAULT_SPACE_KEY,
    space_id: SpaceId | None = None,
) -> ScanRuntimeCatalogQuery:
    """A scan query with exactly one of `space_key` and `space_id`."""
    space: dict[str, object] = (
        {"space_id": space_id} if space_id is not None else {"space_key": space_key}
    )
    return ScanRuntimeCatalogQuery(runtimes=runtimes, **space)  # type: ignore[arg-type]


# --- environment ------------------------------------------------------------------------------


@dataclass(slots=True)
class CatalogEnv:
    """C2's fakes plus the catalog store, wired to the catalog handlers."""

    base: KnowledgeEnv
    catalog: FakeCatalogStore
    read: FakeCatalogEntryReadRepository

    @property
    def store(self) -> FakeKnowledgeStore:
        """C2's committed state."""
        return self.base.store

    @property
    def records(self) -> FakeRecordReadRepository:
        """C2's record read repository (space lookup)."""
        return self.base.read

    @property
    def space_id(self) -> SpaceId:
        """Id of the default space."""
        return next(iter(self.base.store.spaces.values())).id

    def uow(self) -> FakeCatalogUnitOfWork:
        """A fresh unit of work over both stores."""
        return FakeCatalogUnitOfWork(self.base.store, self.catalog)

    def state(self) -> tuple[int, int, int, int]:
        """Commits, entries, revisions and ledger entries: what a read must leave unchanged."""
        return (
            self.base.store.commits,
            len(self.catalog.entries),
            sum(len(e.revisions) for e in self.catalog.entries.values()),
            len(self.base.store.ledger),
        )

    @property
    def register(self) -> RegisterCatalogEntryHandler:
        """Handler wired to the fakes."""
        return RegisterCatalogEntryHandler(
            uow_factory=self.uow, clock=self.base.clock, ids=self.base.ids, schema=self.base.schema
        )

    @property
    def revise(self) -> ReviseCatalogEntryHandler:
        """Handler wired to the fakes."""
        return ReviseCatalogEntryHandler(
            uow_factory=self.uow, clock=self.base.clock, ids=self.base.ids, schema=self.base.schema
        )

    @property
    def list_entries(self) -> ListCatalogEntriesHandler:
        """Handler wired to the fakes."""
        return ListCatalogEntriesHandler(
            read_repository=self.read, records=self.records, schema=self.base.schema
        )

    @property
    def get_entry(self) -> GetCatalogEntryHandler:
        """Handler wired to the fakes."""
        return GetCatalogEntryHandler(
            read_repository=self.read, records=self.records, schema=self.base.schema
        )

    def checker(
        self,
        *probes: IRuntimeInventoryProbe,
        host_tools: IHostToolProbe | None = None,
        read_repository: ICatalogEntryReadRepository | None = None,
    ) -> CheckCatalogAvailabilityHandler:
        """Check handler over the given probes (a fresh empty host probe by default)."""
        return CheckCatalogAvailabilityHandler(
            read_repository=read_repository or self.read,
            records=self.records,
            schema=self.base.schema,
            runtime_probes=probes_of(*probes),
            host_tools=host_tools or FakeHostToolProbe(),
        )

    def scanner(
        self,
        *probes: IRuntimeInventoryProbe,
        host_tools: IHostToolProbe | None = None,
        read_repository: ICatalogEntryReadRepository | None = None,
    ) -> ScanRuntimeCatalogHandler:
        """Scan handler over the given probes (a fresh empty host probe by default)."""
        return ScanRuntimeCatalogHandler(
            read_repository=read_repository or self.read,
            records=self.records,
            schema=self.base.schema,
            runtime_probes=probes_of(*probes),
            host_tools=host_tools or FakeHostToolProbe(),
        )


async def make_catalog_env(
    *, steps: tuple[str, ...] = (CORE_STEP, CATALOG_STEP), initialised: bool = True
) -> CatalogEnv:
    """A fresh environment; by default `store init` ran with the `core` and `catalog` steps."""
    base: KnowledgeEnv = await make_env(initialised=initialised, steps=steps)
    catalog = FakeCatalogStore()
    return CatalogEnv(base=base, catalog=catalog, read=FakeCatalogEntryReadRepository(catalog))
