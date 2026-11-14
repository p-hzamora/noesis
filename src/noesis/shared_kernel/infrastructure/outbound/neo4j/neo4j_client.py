"""Shared Neo4j client: driver lifecycle, explicit transactions, typed errors.

Any context's persistence adapters use it (A-2). The driver is built lazily on first store
access, so `--help`, usage errors and commands that never touch the store open no connection,
and an unreachable store is detected at that first access (D-014). The composition root
closes the client when the command ends.
"""

import logging
from contextlib import suppress
from types import TracebackType
from typing import Self

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession, AsyncTransaction

from .neo4j_connection_settings import Neo4jConnectionSettings
from .neo4j_error_translator import DRIVER_EXCEPTIONS, translate_neo4j_error
from .neo4j_phase_enum import Neo4jPhaseEnum
from .neo4j_transaction import Neo4jTransaction

# The driver logs failures (e.g. "Unable to retrieve routing information") on the `neo4j`
# logger. Without a handler Python prints them to stderr, next to the typed error the
# command already reports; a null handler keeps them for whoever configures logging.
logging.getLogger("neo4j").addHandler(logging.NullHandler())


class Neo4jClient:
    """Owns one driver per invocation and opens explicit transactions on it.

    Use as `async with Neo4jClient(settings) as client:`, or call `close()` when the
    command ends. The password is never part of a repr, an error or a log line.
    """

    def __init__(self, settings: Neo4jConnectionSettings) -> None:
        self._settings: Neo4jConnectionSettings = settings
        self._driver: AsyncDriver | None = None

    def __repr__(self) -> str:
        return (
            f"Neo4jClient(uri={self._settings.public_uri!r}, database={self._settings.database!r})"
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    def _get_driver(self) -> AsyncDriver:
        """The driver, built on first use; building it opens no connection."""
        if self._driver is None:
            timeout: float = self._settings.connect_timeout_seconds
            self._driver = AsyncGraphDatabase.driver(
                self._settings.uri,
                auth=(self._settings.user, self._settings.password.get_secret_value()),
                connection_timeout=timeout,
                connection_acquisition_timeout=timeout,
            )
        return self._driver

    async def begin(self) -> Neo4jTransaction:
        """Open a session and begin one explicit transaction on it.

        The first call of a command is where an unreachable store or bad credentials surface.

        Returns:
            The open transaction; commit it, or close it to roll back.

        Raises:
            GraphStoreUnavailableError: Neo4j is unreachable (phase `connect`), detected
                within the connect timeout.
            GraphStoreAuthenticationFailedError: The credentials were rejected.
        """
        session: AsyncSession = self._get_driver().session(database=self._settings.database)
        try:
            transaction: AsyncTransaction = await session.begin_transaction()
        except DRIVER_EXCEPTIONS as error:
            with suppress(*DRIVER_EXCEPTIONS):
                await session.close()
            raise translate_neo4j_error(
                error, settings=self._settings, phase=Neo4jPhaseEnum.CONNECT
            ) from error
        return Neo4jTransaction(session=session, transaction=transaction, settings=self._settings)

    async def close(self) -> None:
        """Close the driver and its connections; safe to call more than once or before use."""
        driver: AsyncDriver | None = self._driver
        self._driver = None
        if driver is not None:
            await driver.close()
