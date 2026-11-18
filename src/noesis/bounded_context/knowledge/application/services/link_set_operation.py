"""Shared assessment and atomic replacement of imported link sets."""

from noesis.bounded_context.knowledge.application.handlers.types import KnowledgeUnitOfWorkFactory
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.application.services.idempotency import (
    fingerprint_request,
    replay_of,
)
from noesis.bounded_context.knowledge.application.services.link_set_request import (
    LinkSetRequest,
    LinkSetResultDto,
)
from noesis.bounded_context.knowledge.domain.entities.link_set import LinkSet
from noesis.bounded_context.knowledge.domain.value_objects import RecordTypeEnum
from noesis.bounded_context.knowledge.domain.value_objects.link_set_digest import LinkSetDigest
from noesis.exceptions import IdempotencyKeyReusedError, SpaceNotFoundError
from noesis.shared_kernel.application.ports.clock import IClock


class LinkSetOperation:
    """Own the unit of work; unchanged exits before any ledger access."""

    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory, clock: IClock) -> None:
        self._uow_factory: KnowledgeUnitOfWorkFactory = uow_factory
        self._clock: IClock = clock

    async def execute(self, request: LinkSetRequest, *, apply: bool) -> LinkSetResultDto:
        """Assess without a lock, or lock, validate, record and replace atomically."""
        source = request.source_record_id
        origin: str = request.origin_tag.value.removeprefix("origin:")
        links = frozenset(request.links)
        relations = frozenset(request.relations)
        digest: LinkSetDigest = LinkSetDigest.of(links, origin, relations)
        async with self._uow_factory() as uow:
            space = await uow.spaces.get_by_key(request.space_key)
            if space is None:
                raise SpaceNotFoundError(f"No space {request.space_key.value!r}.")
            if apply:
                await uow.link_sets.lock(source)
            stored: LinkSet | None = await uow.link_sets.get(source)
            references = await uow.record_references.describe(
                [
                    source,
                    *(link.target_record_id for link in links),
                    *(relation.target_record_id for relation in relations),
                ],
                space.id,
            )
            found = {
                ref.record_id for ref in references if ref.record_type is RecordTypeEnum.KNOWLEDGE
            }
            if source not in found:
                return LinkSetResultDto(
                    outcome="blocked",
                    source_record_id=source.value,
                    edges=0,
                    block_reason="record_not_found",
                )
            if any(link.target_record_id not in found for link in links) or any(
                relation.target_record_id not in found for relation in relations
            ):
                return LinkSetResultDto(
                    outcome="blocked",
                    source_record_id=source.value,
                    edges=0,
                    block_reason="target_not_in_space",
                )
            link_set = LinkSet.create(
                source_record_id=source,
                space_id=space.id,
                origin=origin,
                version=stored.version + 1 if stored else 1,
                links=links,
                relations=relations,
                now=self._clock.now(),
            )
            edges: int = len(links) + len(relations)
            if (stored is not None and stored.digest == digest) or (stored is None and not edges):
                return LinkSetResultDto(
                    outcome="unchanged", source_record_id=source.value, edges=edges
                )
            result = LinkSetResultDto(
                outcome="replaced" if stored else "created",
                source_record_id=source.value,
                edges=edges,
            )
            if not apply:
                return result
            key: str = (
                f"import/v1/links/{source.value}/{stored.version if stored else 0}/{digest.value}"
            )
            canonical = request.model_copy(
                update={
                    "links": tuple(
                        sorted(
                            links, key=lambda link: (link.target_record_id.value, link.link_type)
                        )
                    ),
                    "relations": tuple(
                        sorted(
                            relations,
                            key=lambda relation: (
                                relation.target_record_id.value,
                                relation.relation.value,
                            ),
                        )
                    ),
                }
            )
            fingerprint: str = fingerprint_request("import_links", canonical)
            try:
                known = replay_of(
                    await uow.ledger.get(space.id, key),
                    command="import_links",
                    fingerprint=fingerprint,
                )
            except IdempotencyKeyReusedError:
                return LinkSetResultDto(
                    outcome="blocked",
                    source_record_id=source.value,
                    edges=0,
                    block_reason="idempotency_key_reused",
                )
            if known is not None:
                return result.model_copy(update={"replayed": True})
            await uow.ledger.record(
                LedgerEntry(
                    space_id=space.id,
                    key=key,
                    command="import_links",
                    fingerprint=fingerprint,
                    record_id=source,
                    revision=link_set.version,
                    recorded_at=link_set.updated_at,
                )
            )
            await uow.link_sets.save(link_set)
            await uow.commit()
            return result
