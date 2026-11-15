"""Reading the catalog by reference: the space a query names and the entry a reference points at."""

from pydantic import model_validator

from noesis.bounded_context.knowledge.application.dtos import CatalogEntryDetailDto
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    ICatalogEntryReadRepository,
    IRecordReadRepository,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogRef,
    Key,
    RecordId,
    SpaceId,
)
from noesis.bounded_context.knowledge.domain.value_objects.ulid import ULID_PATTERN
from noesis.exceptions import (
    CatalogEntryNotFoundError,
    InvalidCatalogPrerequisiteError,
    SpaceNotFoundError,
)
from noesis.utils import FrozenObject


class SpaceScopedQuery(FrozenObject):
    """A query bound to one space, named by key (the CLI) or by id (the inbound adapter).

    Attributes:
        space_key: Key of the space.
        space_id: Id of the space; exactly one of the two is given.
    """

    space_key: Key | None = None
    space_id: SpaceId | None = None

    @model_validator(mode="after")
    def _exactly_one_space(self) -> SpaceScopedQuery:
        if (self.space_key is None) == (self.space_id is None):
            raise ValueError("Give exactly one of space_key and space_id.")
        return self


async def resolve_query_space(records: IRecordReadRepository, query: SpaceScopedQuery) -> SpaceId:
    """The id of the query's space.

    Raises:
        SpaceNotFoundError: The space key is unknown.
    """
    if query.space_id is not None:
        return query.space_id
    key: Key | None = query.space_key
    if key is None:  # pragma: no cover - the validator guarantees one of the two
        raise ValueError("Give exactly one of space_key and space_id.")
    space_id: SpaceId | None = await records.get_space_id(key)
    if space_id is None:
        raise SpaceNotFoundError(
            f"No knowledge space has the key {key.value!r}.",
            {"space_key": key.value},
            next_steps=["Run `noesis store init` or check the configured space key."],
        )
    return space_id


def catalog_entry_not_found(
    ref: str, space_id: SpaceId, *, revision: int | None = None
) -> CatalogEntryNotFoundError:
    """The error for a reference (or revision) that matches nothing in the space."""
    what: str = f"No catalog entry {ref!r} in this space."
    if revision is not None:
        what = f"Catalog entry {ref!r} has no revision {revision} in this space."
    return CatalogEntryNotFoundError(
        what,
        {"ref": ref, "space_id": space_id.value},
        next_steps=["Run `noesis catalog list` to see the entries of this space."],
    )


def is_record_id(ref: str) -> bool:
    """Whether a reference is an entry id (a ULID) rather than `kind:name`."""
    return ULID_PATTERN.fullmatch(ref) is not None


async def find_entry(
    read_repository: ICatalogEntryReadRepository,
    space_id: SpaceId,
    ref: str,
    *,
    revision: int | None = None,
) -> CatalogEntryDetailDto | None:
    """The entry an id or `kind:name` reference points at, or None.

    A reference that is neither an id nor `kind:name` matches nothing.
    """
    if is_record_id(ref):
        return await read_repository.get_by_id(
            RecordId(value=ref), space_id=space_id, revision=revision
        )
    try:
        parsed: CatalogRef = CatalogRef.parse(ref)
    except InvalidCatalogPrerequisiteError:
        return None
    return await read_repository.get_by_key(
        space_id, parsed.kind, parsed.name.value, revision=revision
    )
