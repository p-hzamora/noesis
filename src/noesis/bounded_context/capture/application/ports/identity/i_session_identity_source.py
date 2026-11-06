"""Where a session's identity comes from when the caller did not pass one."""

import abc


class ISessionIdentitySource(abc.ABC):
    """The harness-provided identity of the running session, or a brand-new one."""

    @abc.abstractmethod
    def ambient(self) -> str | None:
        """The identity the harness exposes to this process, or None when it exposes none."""
        ...

    @abc.abstractmethod
    def fresh(self) -> str:
        """A new random identity, for a harness that has none."""
        ...
