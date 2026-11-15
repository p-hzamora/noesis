"""Who runs the import, as interop sees it."""

from noesis.shared_kernel.domain.value_objects import ValueObject


class ImportActor(ValueObject):
    """The actor of an import.

    Attributes:
        kind: `user` or `agent`.
        name: Display name.
        session: Harness session id, when known.
    """

    kind: str
    name: str
    session: str | None = None
