"""Requiring named schema steps (FR-019)."""

from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.exceptions import StoreNotInitialisedError

CORE_STEP: str = "core"
"""The step Knowledge registers itself: constraints for spaces, records, revisions, ledger."""

CHANGE_FEED_STEP: str = "change_feed"
"""C5a: uniqueness of the change entries and of the per-space change counter."""

KNOWLEDGE_FULLTEXT_STEP: str = "knowledge_fulltext"
"""C5a: Knowledge's full-text index over revision and experience text."""

REVIEW_STEP: str = "review"
"""The step C4 registers: uniqueness of decision keys and live assertion statements."""

LINKS_STEP: str = "links"
"""C3b: uniqueness of the per-source link set."""

CATALOG_STEP: str = "catalog"
"""The step C6 registers: the uniqueness constraint on `CatalogEntry.catalog_key`."""


CONSOLIDATION_STEP: str = "consolidation"
"""C9: uniqueness of the consolidation id and of the membership keys."""


async def require_steps(schema: IStoreSchema, *names: str) -> None:
    """Fail unless every named step is applied.

    Raises:
        StoreNotInitialisedError: Names the missing steps; the next step is `noesis store init`.
    """
    applied: frozenset[str] = await schema.applied_steps()
    missing: list[str] = [name for name in names if name not in applied]
    if missing:
        raise StoreNotInitialisedError(
            f"The store is not initialised: missing schema step(s) {', '.join(missing)}.",
            {"missing_steps": [*missing]},
            next_steps=["Run `noesis store init`."],
        )


async def require_initialised(schema: IStoreSchema) -> None:
    """Fail unless Knowledge's `core` step is applied; the error names every missing step.

    The C5a steps are not required here (writers do not need them: the change-log adapter
    creates the counter node on first use), but a store with no `core` step is uninitialised as
    a whole, so the error lists every registered step it still lacks.

    Raises:
        StoreNotInitialisedError: `core` is missing; the next step is `noesis store init`.
    """
    applied: frozenset[str] = await schema.applied_steps()
    if CORE_STEP in applied:
        return
    await require_steps(schema, *schema.registered_steps())
