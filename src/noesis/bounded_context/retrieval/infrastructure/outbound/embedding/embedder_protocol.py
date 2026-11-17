"""The resident embedder's local wire protocol (version 1) and socket location.

Frames are a 4-byte big-endian length then UTF-8 JSON. A request carries the protocol version,
the profile fingerprint, an operation (`ping`, `query`, `passages`), a request id and bounded
texts; a reply echoes the id with `ok` and either a result or an error code. Texts are never
logged; there is no network listener and no store access.
"""

import asyncio
import hashlib
import json
import os
import struct
import sys
from pathlib import Path
from typing import Any, Final

PROTOCOL_VERSION: Final[int] = 1
MAX_REQUEST_BYTES: Final[int] = 1 << 20
MAX_REPLY_BYTES: Final[int] = 64 << 20
_HEADER: Final[struct.Struct] = struct.Struct(">I")
MAX_SOCKET_PATH_BYTES: Final[int] = 103 if sys.platform == "darwin" else 107
"""Longest Unix socket path `bind`/`connect` accept (sun_path minus its terminating NUL)."""
SHORT_RUNTIME_PARENT: Final[Path] = Path("/tmp")  # noqa: S108 - private 0700 per-user subdirectory


class ProtocolError(Exception):
    """A frame is malformed, too large or truncated."""


class SocketPathTooLongError(ValueError):
    """No candidate socket directory gives a path short enough for a Unix socket."""


async def write_frame(writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
    """Send one JSON message."""
    payload: bytes = json.dumps(message, separators=(",", ":")).encode("utf-8")
    writer.write(_HEADER.pack(len(payload)) + payload)
    await writer.drain()


def encoded_size(message: dict[str, Any]) -> int:
    """Bytes the message takes on the wire (header excluded)."""
    return len(json.dumps(message, separators=(",", ":")).encode("utf-8"))


async def read_frame(reader: asyncio.StreamReader, *, max_bytes: int) -> dict[str, Any]:
    """Receive one JSON message of at most `max_bytes`.

    Raises:
        ProtocolError: Truncated, oversized or not a JSON object.
    """
    try:
        header: bytes = await reader.readexactly(_HEADER.size)
        (size,) = _HEADER.unpack(header)
        if size > max_bytes:
            raise ProtocolError(f"frame of {size} bytes exceeds {max_bytes}")
        payload: bytes = await reader.readexactly(size)
    except asyncio.IncompleteReadError as error:
        raise ProtocolError("connection closed mid-frame") from error
    try:
        message: Any = json.loads(payload)
    except ValueError as error:
        raise ProtocolError("frame is not JSON") from error
    if not isinstance(message, dict):
        raise ProtocolError("frame is not a JSON object")
    return message


def runtime_directory(runtime_root: Path | None, cache_root: Path) -> Path:
    """`$XDG_RUNTIME_DIR/noesis`, else a private `run` directory under the cache root."""
    return runtime_root / "noesis" if runtime_root is not None else cache_root / "run"


def short_runtime_directory(uid: int | None = None) -> Path:
    """`/tmp/noesis-<uid>`: the fallback when the preferred directory is too deep."""
    return SHORT_RUNTIME_PARENT / f"noesis-{os.getuid() if uid is None else uid}"


def socket_path(directory: Path, *, cache_root: Path, profile_hash: str) -> Path:
    """The socket of one cache and profile, so incompatible environments never share one."""
    namespace: str = hashlib.sha256(f"{cache_root.resolve()}|{profile_hash}".encode()).hexdigest()
    return directory / f"embedder-{namespace[:16]}.sock"


def fits_unix_socket(path: Path) -> bool:
    """Whether `path` is short enough to bind or connect a Unix socket."""
    return len(os.fsencode(path)) <= MAX_SOCKET_PATH_BYTES


def resolve_socket_path(runtime_root: Path | None, *, cache_root: Path, profile_hash: str) -> Path:
    """The socket under the preferred runtime directory, or under `/tmp/noesis-<uid>` when
    that path would exceed the Unix socket length limit (a deep cache or runtime directory).

    Both the server and every client resolve the same path from the same configuration.

    Raises:
        SocketPathTooLongError: Even the short fallback is too long.
    """
    candidates: tuple[Path, ...] = (
        runtime_directory(runtime_root, cache_root),
        short_runtime_directory(),
    )
    for directory in candidates:
        path: Path = socket_path(directory, cache_root=cache_root, profile_hash=profile_hash)
        if fits_unix_socket(path):
            return path
    raise SocketPathTooLongError(
        f"no embedder socket path fits the {MAX_SOCKET_PATH_BYTES}-byte Unix socket limit "
        f"(tried {', '.join(str(directory) for directory in candidates)})"
    )


def ensure_private_directory(directory: Path) -> None:
    """Create the socket directory with mode 0700 (and tighten an existing one we own).

    Raises:
        PermissionError: The directory belongs to another user.
    """
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink():  # a shared parent such as /tmp: never follow a planted link
        raise PermissionError(f"{directory} is a symbolic link")
    if directory.stat().st_uid != os.getuid():
        raise PermissionError(f"{directory} belongs to another user")
    directory.chmod(0o700)
