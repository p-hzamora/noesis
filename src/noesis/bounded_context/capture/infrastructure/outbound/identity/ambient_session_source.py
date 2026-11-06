"""One place a session id may be found."""

import abc


class AmbientSessionSource(abc.ABC):
    """A link of the identity chain: it knows one harness (or one variable)."""

    @abc.abstractmethod
    def read(self) -> str | None:
        """The session id this source sees, or None."""
        ...
