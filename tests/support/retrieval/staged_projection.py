"""An in-memory staged (`IStagedIndexWriter`) projection whose commits are fenced on the lease."""

from collections.abc import Callable

from tests.support.retrieval.retrieval_fakes import InMemoryIndexCursorStore

from noesis.bounded_context.retrieval.application.ports.indexing.i_index_writer import (
    ProjectionEntryDto,
)
from noesis.bounded_context.retrieval.application.ports.indexing.i_staged_index_writer import (
    IStagedIndexWriter,
)
from noesis.shared_kernel.domain import JsonValue

STAGED_KIND: str = "staged"


class InMemoryStagedProjection(IStagedIndexWriter[ProjectionEntryDto]):
    """Keeps record id to revision per space; `on_prepare` runs inside `prepare` (head churn)."""

    def __init__(
        self, cursors: InMemoryIndexCursorStore, profile: dict[str, JsonValue] | None = None
    ) -> None:
        self._cursors: InMemoryIndexCursorStore = cursors
        self._profile: dict[str, JsonValue] = profile or {"name": "staged", "version": 1}
        self._entries: dict[str, dict[str, int | None]] = {}
        self.prepared: list[ProjectionEntryDto] = []
        self.committed: list[ProjectionEntryDto] = []
        self.on_prepare: Callable[[ProjectionEntryDto], None] | None = None
        self.fail_on: str | None = None

    @property
    def kind(self) -> str:
        """Always `staged`."""
        return STAGED_KIND

    def set_profile(self, profile: dict[str, JsonValue]) -> None:
        """Change the configured profile."""
        self._profile = profile

    def profile(self) -> dict[str, JsonValue]:
        """The configured profile."""
        return dict(self._profile)

    async def prepare(self, entry: ProjectionEntryDto) -> ProjectionEntryDto:
        """Record the call; run the hook; fail for `fail_on`."""
        self.prepared.append(entry)
        if self.fail_on == entry.key.record_id:
            raise RuntimeError(f"embedding {entry.key.record_id} failed")
        if self.on_prepare is not None:
            self.on_prepare(entry)
        return entry

    def entry_of(self, prepared: ProjectionEntryDto) -> ProjectionEntryDto:
        """The entry itself."""
        return prepared

    async def commit(self, prepared: ProjectionEntryDto, *, owner: str) -> None:
        """Fenced write."""
        self._cursors.check_fence(STAGED_KIND, prepared.space_id, owner)
        self.committed.append(prepared)
        self._entries.setdefault(prepared.space_id, {})[prepared.key.record_id] = (
            prepared.key.revision
        )

    async def upsert(self, entry: ProjectionEntryDto) -> None:
        """Unfenced write."""
        self._entries.setdefault(entry.space_id, {})[entry.key.record_id] = entry.key.revision

    async def clear(self, space_id: str) -> None:
        """Unfenced clear."""
        self._entries.pop(space_id, None)

    async def clear_fenced(self, space_id: str, *, owner: str) -> None:
        """Fenced clear."""
        self._cursors.check_fence(STAGED_KIND, space_id, owner)
        self._entries.pop(space_id, None)

    async def entries(self, space_id: str) -> dict[str, int | None]:
        """Record id to revision."""
        return dict(self._entries.get(space_id, {}))
