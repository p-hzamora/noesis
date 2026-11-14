"""Resolves a command's space and ensures the project and sources it cites.

Each ensure is its own idempotent unit of work (D-005). One that loses a uniqueness race
re-reads and reuses the winner.
"""

from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.services.inputs import (
    ExistingSourceInput,
    NewSourceInput,
    ProjectRef,
    SourceInput,
)
from noesis.bounded_context.knowledge.application.services.secret_redactor import SecretRedactor
from noesis.bounded_context.knowledge.domain.entities import Project, Source
from noesis.bounded_context.knowledge.domain.value_objects import Key, RecordId, SpaceId
from noesis.exceptions import EntryAlreadyExistsError, ReferenceNotInSpaceError, SpaceNotFoundError
from noesis.shared_kernel.application.ports.clock import IClock


class RecordReferenceResolver:
    """Space lookup and the project and source ensures shared by the capture commands."""

    def __init__(
        self, *, uow_factory: KnowledgeUnitOfWorkFactory, clock: IClock, ids: IRecordIdGenerator
    ) -> None:
        self._uow_factory: KnowledgeUnitOfWorkFactory = uow_factory
        self._clock: IClock = clock
        self._ids: IRecordIdGenerator = ids

    async def resolve_space(self, key: Key) -> SpaceId:
        """Id of the space with `key`.

        Raises:
            SpaceNotFoundError: No such space; `noesis store init` creates the default one.
        """
        async with self._uow_factory() as uow:
            space = await uow.spaces.get_by_key(key)
        if space is None:
            raise SpaceNotFoundError(
                f"No knowledge space has the key {key.value!r}.",
                {"space_key": key.value},
                next_steps=["Run `noesis store init` or check the configured space key."],
            )
        return space.id

    async def ensure_project(self, space_id: SpaceId, ref: ProjectRef | None) -> RecordId | None:
        """Id of the project with the reference's key, creating it when unknown (D-022)."""
        if ref is None:
            return None
        try:
            async with self._uow_factory() as uow:
                found: Project | None = await uow.projects.get_by_key(ref.key, space_id=space_id)
                if found is not None:
                    return found.id
                project: Project = Project.create(
                    id=self._ids.new_record_id(),
                    space_id=space_id,
                    key=ref.key,
                    name=ref.name or ref.key.value,
                    now=self._clock.now(),
                )
                await uow.projects.add(project)
                await uow.commit()
                return project.id
        except EntryAlreadyExistsError:
            async with self._uow_factory() as uow:
                winner: Project | None = await uow.projects.get_by_key(ref.key, space_id=space_id)
            if winner is None:
                raise
            return winner.id

    async def ensure_sources(
        self, space_id: SpaceId, inputs: tuple[SourceInput, ...]
    ) -> tuple[RecordId, ...]:
        """Ids of the sources, in order and without repeats.

        Existing ids must belong to `space_id` (D-006) and are all checked before any new
        source is recorded; new descriptions are found by natural key or recorded, with the
        source's observed time set now.

        Raises:
            ReferenceNotInSpaceError: An existing id is unknown in the space; nothing is written.
        """
        await self.check_existing_sources(space_id, inputs)
        ids: list[RecordId] = []
        for source in inputs:
            match source:
                case ExistingSourceInput():
                    ids.append(await self._existing_source(space_id, source.source_id))
                case NewSourceInput():
                    ids.append(await self._ensure_source(space_id, source))
        return tuple(dict.fromkeys(ids))

    async def check_existing_sources(
        self, space_id: SpaceId, inputs: tuple[SourceInput, ...]
    ) -> None:
        """Fail before any write when a cited source id is not in `space_id` (D-006).

        Raises:
            ReferenceNotInSpaceError: An existing id is unknown in the space.
        """
        for source in inputs:
            if isinstance(source, ExistingSourceInput):
                await self._existing_source(space_id, source.source_id)

    async def _existing_source(self, space_id: SpaceId, source_id: RecordId) -> RecordId:
        async with self._uow_factory() as uow:
            found: Source | None = await uow.sources.get(source_id, space_id=space_id)
        if found is None:
            raise ReferenceNotInSpaceError(
                f"Source {source_id.value} does not exist in this space.",
                {"source_id": source_id.value, "space_id": space_id.value},
                next_steps=["Check the source id and the active space."],
            )
        return found.id

    async def _ensure_source(self, space_id: SpaceId, description: NewSourceInput) -> RecordId:
        # redacted before the natural key is computed so a retry with the same input still matches
        locator: str = SecretRedactor.redact(description.locator.strip())[0]
        try:
            async with self._uow_factory() as uow:
                found: Source | None = await uow.sources.get_by_natural_key(
                    space_id=space_id,
                    kind=description.kind,
                    locator=locator,
                    digest=description.digest,
                )
                if found is not None:
                    return found.id
                source: Source = Source.create(
                    id=self._ids.new_record_id(),
                    space_id=space_id,
                    kind=description.kind,
                    locator=locator,
                    digest=description.digest,
                    now=self._clock.now(),
                )
                await uow.sources.add(source)
                await uow.commit()
                return source.id
        except EntryAlreadyExistsError:
            async with self._uow_factory() as uow:
                winner: Source | None = await uow.sources.get_by_natural_key(
                    space_id=space_id,
                    kind=description.kind,
                    locator=locator,
                    digest=description.digest,
                )
            if winner is None:
                raise
            return winner.id
