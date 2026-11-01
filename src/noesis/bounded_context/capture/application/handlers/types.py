"""Shared type aliases of the Capture command handlers."""

from collections.abc import Callable

from noesis.bounded_context.capture.application.ports.uow import ICaptureUnitOfWork
from noesis.bounded_context.capture.domain.value_objects import SessionId

type UnitOfWorkFactory = Callable[[SessionId], ICaptureUnitOfWork]
"""Opens the unit of work of one session (which locks it)."""
