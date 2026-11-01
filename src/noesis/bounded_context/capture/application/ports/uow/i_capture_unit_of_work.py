"""Unit of Work over one capture session, held exclusively while open."""

import abc

from noesis.bounded_context.capture.domain.repositories import ICaptureSessionRepository
from noesis.shared_kernel.application.ports.uow import IUnitOfWork


class ICaptureUnitOfWork(IUnitOfWork["ICaptureUnitOfWork"]):
    """Opening it locks the session, so two hooks of one session never interleave."""

    @property
    @abc.abstractmethod
    def sessions(self) -> ICaptureSessionRepository:
        """The session repository of this unit of work."""
        ...
