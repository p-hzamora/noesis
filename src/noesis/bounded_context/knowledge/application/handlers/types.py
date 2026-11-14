"""Shared type aliases of the Knowledge handlers."""

from collections.abc import Callable

from noesis.bounded_context.knowledge.application.ports.uow import IKnowledgeUnitOfWork

type KnowledgeUnitOfWorkFactory = Callable[[], IKnowledgeUnitOfWork]
"""Opens a new unit of work; every step of a command opens its own."""
