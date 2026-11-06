"""Which sessions were started by which (the sub-agent tree)."""

import abc

from noesis.bounded_context.capture.domain.value_objects import SessionId


class ICaptureSessionTreeReader(abc.ABC):
    """Read-only view of the parent links."""

    @abc.abstractmethod
    async def children_of(self, session_id: SessionId) -> list[SessionId]:
        """The sessions started directly by `session_id`, in a stable order."""
        ...
