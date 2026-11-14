"""Requiring named schema steps (FR-019)."""

from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.exceptions import StoreNotInitialisedError

CORE_STEP: str = "core"
"""The step Knowledge registers itself: constraints for spaces, records, revisions, ledger."""


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
