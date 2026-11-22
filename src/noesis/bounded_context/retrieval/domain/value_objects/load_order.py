"""The result of ordering resources and their prerequisites."""

from noesis.shared_kernel.domain.value_objects import ValueObject


class LoadOrder(ValueObject):
    """Prerequisites first.

    Attributes:
        order: Every ref to load, each after its prerequisites.
        added: Refs in `order` that were not selected roots.
        warnings: Truncation and cycle notes.
    """

    order: tuple[str, ...] = ()
    added: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
