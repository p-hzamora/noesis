"""One explicit Neo4j transaction: run statements, then commit or roll back."""

from collections.abc import Mapping
from contextlib import suppress
from types import TracebackType
from typing import Any, LiteralString, Self

from neo4j import AsyncResult, AsyncSession, AsyncTransaction
from neo4j.time import Date, DateTime, Time

from .neo4j_connection_settings import Neo4jConnectionSettings
from .neo4j_error_translator import DRIVER_EXCEPTIONS, translate_neo4j_error
from .neo4j_phase_enum import Neo4jPhaseEnum


def _to_native(value: Any) -> Any:
    """`value` with Neo4j temporal types turned into the standard library's, recursively."""
    match value:
        case DateTime() | Date() | Time():
            return value.to_native()
        case list():
            return [_to_native(item) for item in value]
        case dict():
            return {key: _to_native(item) for key, item in value.items()}
        case _:
            return value


class Neo4jTransaction:
    """An open transaction on its own session, as a unit of work needs it.

    Built by `Neo4jClient.begin()`. Nothing is durable until `commit()`; leaving the
    `async with` block without a commit rolls back. Every driver failure surfaces as a
    `GraphStore*Error`.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        transaction: AsyncTransaction,
        settings: Neo4jConnectionSettings,
    ) -> None:
        self._session: AsyncSession = session
        self._transaction: AsyncTransaction = transaction
        self._settings: Neo4jConnectionSettings = settings
        self._finished: bool = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    @property
    def is_open(self) -> bool:
        """Whether the transaction can still run statements and commit."""
        return not self._finished

    async def run(
        self, query: LiteralString, parameters: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Run one Cypher statement and return every row as a dict of plain Python values.

        Neo4j temporal values come back as `datetime`, `date` and `time` (via `to_native`), so
        callers never import driver types.

        Args:
            query: A literal Cypher statement; values go in `parameters`, never in the text.
            parameters: Statement parameters.

        Returns:
            The rows, keyed by the statement's return names (empty for pure writes).

        Raises:
            GraphStoreUnavailableError: The connection was lost (phase `query`).
            GraphStoreConstraintViolatedError: The write breaks a uniqueness constraint.
            GraphStoreBusyError: A transient failure (deadlock, lock timeout).
            GraphStoreQueryFailedError: The statement is invalid.
        """
        try:
            result: AsyncResult = await self._transaction.run(query, dict(parameters or {}))
            rows: list[dict[str, Any]] = await result.data()
        except DRIVER_EXCEPTIONS as error:
            raise translate_neo4j_error(
                error, settings=self._settings, phase=Neo4jPhaseEnum.QUERY
            ) from error
        return [{name: _to_native(value) for name, value in row.items()} for row in rows]

    async def commit(self) -> None:
        """Make every statement of the transaction durable, then release the session.

        Raises:
            GraphStoreUnavailableError: The connection was lost while committing; metadata
                carries `commit_outcome: unknown` (retry with the same idempotency key).
            GraphStoreConstraintViolatedError: A constraint check failed at commit.
            GraphStoreBusyError: A transient failure.
        """
        try:
            await self._transaction.commit()
        except DRIVER_EXCEPTIONS as error:
            raise translate_neo4j_error(
                error, settings=self._settings, phase=Neo4jPhaseEnum.COMMIT
            ) from error
        finally:
            await self.close()

    async def rollback(self) -> None:
        """Discard the transaction's work and release the session.

        A rollback that cannot reach the server is not an error: Neo4j discards an
        uncommitted transaction whose connection is gone, so nothing was written either way.
        """
        await self.close()

    async def close(self) -> None:
        """Roll back if still open and release the session; safe to call more than once."""
        if self._finished:
            return
        self._finished = True
        # a dead connection cannot roll back or be released, and needs neither: the server
        # discards an uncommitted transaction whose connection is gone
        with suppress(*DRIVER_EXCEPTIONS):
            await self._transaction.close()  # rolls back unless committed
        with suppress(*DRIVER_EXCEPTIONS):
            await self._session.close()
