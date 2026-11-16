"""The resident embedder: one loaded model served over a private Unix socket (Q-201).

`noesis index embedder serve` runs it in the foreground. It loads the model once, owns no store
access and never logs texts. One inference runs at a time, off the event loop; at most eight
requests wait, and more are refused at once (`overloaded`). Queries go before waiting passage
work, and a passage batch yields between passages, so indexing cannot starve searches.
"""

import asyncio
import contextlib
import os
import socket
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from ....application.ports.embedding import (
    MAX_PASSAGES_PER_REQUEST,
    MAX_QUERY_CHARACTERS,
    EmbeddedPassageDto,
    EmbedderUnavailableError,
)
from ....domain.value_objects import EmbeddingProfile
from ...outbound.embedding.embedder_protocol import (
    MAX_REQUEST_BYTES,
    PROTOCOL_VERSION,
    ProtocolError,
    ensure_private_directory,
    read_frame,
    write_frame,
)

MAX_WAITING: int = 8
READ_TIMEOUT_SECONDS: float = 5.0


class EngineLike(Protocol):
    """What the server needs from the engine."""

    @property
    def profile(self) -> EmbeddingProfile:
        """The profile it embeds with."""
        ...

    def embed_passage(self, text: str) -> EmbeddedPassageDto:
        """Every window of one passage."""
        ...

    def embed_query(self, text: str) -> tuple[float, ...]:
        """One query vector."""
        ...


class SocketInUseError(Exception):
    """A live embedder already listens on the socket path."""


class InferenceGate:
    """One inference at a time; queries first; at most `max_waiting` callers waiting."""

    def __init__(self, max_waiting: int = MAX_WAITING) -> None:
        self._max_waiting: int = max_waiting
        self._busy: bool = False
        self._waiting_queries: int = 0
        self._waiting: int = 0
        self._changed: asyncio.Condition = asyncio.Condition()

    @property
    def waiting(self) -> int:
        """Callers waiting for the model."""
        return self._waiting

    def admit(self) -> bool:
        """Whether one more request may wait (checked when it arrives)."""
        return self._waiting < self._max_waiting

    @contextlib.asynccontextmanager
    async def turn(self, *, query: bool) -> Any:
        """Hold the model; a passage turn waits while a query waits."""
        async with self._changed:
            self._waiting += 1
            self._waiting_queries += query
            try:
                await self._changed.wait_for(
                    lambda: not self._busy and (query or self._waiting_queries == 0)
                )
            finally:
                self._waiting -= 1
                self._waiting_queries -= query
            self._busy = True
        try:
            yield
        finally:
            async with self._changed:
                self._busy = False
                self._changed.notify_all()


class UnixSocketEmbedderServer:
    """Serves `ping`, `query` and `passages` for one profile.

    Args:
        engine: The loaded engine.
        socket_path: Where to listen (its directory is made private, mode 0700).
        run_blocking: Runs one inference off the event loop (`asyncio.to_thread`).
    """

    def __init__(
        self,
        engine: EngineLike,
        socket_path: Path,
        *,
        run_blocking: Callable[..., Any] | None = None,
        max_waiting: int = MAX_WAITING,
    ) -> None:
        self._engine: EngineLike = engine
        self._socket_path: Path = socket_path
        self._run_blocking: Callable[..., Any] = run_blocking or asyncio.to_thread
        self._gate: InferenceGate = InferenceGate(max_waiting)
        self._fingerprint: str = engine.profile.fingerprint()
        self._server: asyncio.Server | None = None

    @property
    def socket_path(self) -> Path:
        """Where the server listens."""
        return self._socket_path

    async def start(self) -> None:
        """Clean a stale socket we own, refuse a live one, listen with mode 0600.

        Raises:
            SocketInUseError: Another embedder answers on the path.
            PermissionError: The path or its directory belongs to another user.
        """
        ensure_private_directory(self._socket_path.parent)
        await self._remove_stale_socket()
        previous: int = os.umask(0o177)
        try:
            self._server = await asyncio.start_unix_server(self._serve, path=str(self._socket_path))
        finally:
            os.umask(previous)
        self._socket_path.chmod(0o600)

    async def serve_until(self, stop: asyncio.Event) -> None:
        """Serve until `stop` is set, then close and remove the socket."""
        if self._server is None:
            await self.start()
        try:
            await stop.wait()
        finally:
            await self.close()

    async def close(self) -> None:
        """Stop listening and remove the socket file."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        with contextlib.suppress(FileNotFoundError):
            self._socket_path.unlink()

    async def _remove_stale_socket(self) -> None:
        try:
            info: os.stat_result = self._socket_path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise PermissionError(f"{self._socket_path} is not a socket this user owns")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.25)
            probe.connect(str(self._socket_path))
        except OSError:
            self._socket_path.unlink()  # nobody answers: a stale socket of ours
            return
        finally:
            probe.close()
        raise SocketInUseError(f"an embedder already listens on {self._socket_path}")

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request: dict[str, Any] = await asyncio.wait_for(
                read_frame(reader, max_bytes=MAX_REQUEST_BYTES), READ_TIMEOUT_SECONDS
            )
        except ProtocolError, TimeoutError, OSError:
            writer.close()
            return
        reply: dict[str, Any] = await self._answer(request)
        with contextlib.suppress(OSError):
            await write_frame(writer, reply)
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()

    async def _answer(self, request: dict[str, Any]) -> dict[str, Any]:
        base: dict[str, Any] = {"protocol": PROTOCOL_VERSION, "id": request.get("id")}
        if request.get("protocol") != PROTOCOL_VERSION:
            return {**base, "ok": False, "error": "protocol_mismatch"}
        if request.get("profile") != self._fingerprint:
            return {**base, "ok": False, "error": "profile_mismatch"}
        operation: Any = request.get("op")
        if operation == "ping":
            return {
                **base,
                "ok": True,
                "profile": self._fingerprint,
                "model": self._engine.profile.model,
                "waiting": self._gate.waiting,
            }
        texts: Any = request.get("texts")
        if not isinstance(texts, list) or not all(isinstance(text, str) for text in texts):
            return {**base, "ok": False, "error": "bad_request"}
        if not self._gate.admit():
            return {**base, "ok": False, "error": "overloaded"}
        try:
            if operation == "query" and len(texts) == 1:
                return {**base, "ok": True, "vector": list(await self._query(texts[0]))}
            if operation == "passages" and len(texts) <= MAX_PASSAGES_PER_REQUEST:
                return {**base, "ok": True, "passages": await self._passages(texts)}
        except EmbedderUnavailableError:
            return {**base, "ok": False, "error": "inference_failed"}
        return {**base, "ok": False, "error": "bad_request"}

    async def _query(self, text: str) -> tuple[float, ...]:
        if len(text) > MAX_QUERY_CHARACTERS:
            raise EmbedderUnavailableError("query too long")
        async with self._gate.turn(query=True):
            vector: tuple[float, ...] = await self._run_blocking(self._engine.embed_query, text)
        return vector

    async def _passages(self, texts: list[str]) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for text in texts:  # one turn per passage: a waiting query goes next
            async with self._gate.turn(query=False):
                passage: EmbeddedPassageDto = await self._run_blocking(
                    self._engine.embed_passage, text
                )
            found.append(passage.model_dump(mode="json"))
        return found


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
