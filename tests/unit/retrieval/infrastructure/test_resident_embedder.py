"""Q-201 / AC-212: the resident embedder's socket, protocol, bounds and degradation."""

import asyncio
import os
import stat
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from tests.support.retrieval.fake_embedding import PROFILE, FakeEngine

from noesis.bounded_context.retrieval.application.ports.embedding import EmbedderUnavailableError
from noesis.bounded_context.retrieval.infrastructure.inbound.embedder_runtime.unix_socket_embedder_server import (
    InferenceGate,
    SocketInUseError,
    UnixSocketEmbedderServer,
    claim_socket_path,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding import (
    socket_text_embedder,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.embedder_protocol import (
    PROTOCOL_VERSION,
    ProtocolError,
    fits_unix_socket,
    read_frame,
    resolve_socket_path,
    runtime_directory,
    short_runtime_directory,
    socket_path,
    write_frame,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.socket_text_embedder import (
    SocketTextEmbedder,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.vector_checks import (
    validate_vector,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def short_dir() -> Any:
    """A short private directory: Unix socket paths are limited to ~100 bytes."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="nse-") as name:
        yield Path(name)


@pytest.fixture
async def served(short_dir: Path) -> AsyncIterator[tuple[UnixSocketEmbedderServer, FakeEngine]]:
    engine = FakeEngine()
    server = UnixSocketEmbedderServer(engine, short_dir / "run" / "e.sock")
    await server.start()
    try:
        yield server, engine
    finally:
        await server.close()


async def test_query_and_passages_round_trip(
    served: tuple[UnixSocketEmbedderServer, FakeEngine],
) -> None:
    server, engine = served
    client = SocketTextEmbedder(PROFILE, server.socket_path)

    vector = await client.embed_query("lease renewal")
    passages = await client.embed_passages(["one two three", ""])

    assert vector == engine.embed_query("lease renewal")
    assert passages[0].token_count == 3
    assert passages[1].chunks == ()
    assert (await client.ping())["ok"]


async def test_more_than_32_passages_are_split_into_bounded_requests(
    served: tuple[UnixSocketEmbedderServer, FakeEngine],
) -> None:
    server, engine = served
    client = SocketTextEmbedder(PROFILE, server.socket_path)

    found = await client.embed_passages([f"text {i}" for i in range(70)])

    assert len(found) == 70
    assert len(engine.passages) == 70


async def test_the_socket_is_private(served: tuple[UnixSocketEmbedderServer, FakeEngine]) -> None:
    server, _ = served

    assert stat.S_IMODE(server.socket_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(server.socket_path.parent.stat().st_mode) == 0o700


async def test_no_runtime_means_unavailable_fast_and_nothing_started(short_dir: Path) -> None:
    client = SocketTextEmbedder(PROFILE, short_dir / "absent.sock")

    with pytest.raises(EmbedderUnavailableError, match="not running"):
        await client.embed_query("x")
    assert not (short_dir / "absent.sock").exists()


async def test_a_profile_mismatch_is_refused(
    served: tuple[UnixSocketEmbedderServer, FakeEngine],
) -> None:
    server, _ = served
    other = PROFILE.model_copy(update={"chunk_policy": "other"})

    with pytest.raises(EmbedderUnavailableError, match="profile_mismatch"):
        await SocketTextEmbedder(other, server.socket_path).embed_query("x")


async def test_an_engine_failure_is_reported_as_unavailable(
    served: tuple[UnixSocketEmbedderServer, FakeEngine],
) -> None:
    server, engine = served
    engine.fail = True

    with pytest.raises(EmbedderUnavailableError, match="inference_failed"):
        await SocketTextEmbedder(PROFILE, server.socket_path).embed_passages(["a"])


async def test_a_too_long_query_is_refused_before_any_io(short_dir: Path) -> None:
    with pytest.raises(EmbedderUnavailableError, match="32000"):
        await SocketTextEmbedder(PROFILE, short_dir / "x.sock").embed_query("x" * 32_001)


async def test_a_too_large_request_is_refused_locally(short_dir: Path) -> None:
    with pytest.raises(EmbedderUnavailableError, match="1 MiB"):
        await SocketTextEmbedder(PROFILE, short_dir / "x.sock").embed_passages(["x" * 1_100_000])


async def _raw_server(
    short_dir: Path, answer: Callable[[dict[str, Any]], dict[str, Any] | None]
) -> tuple[asyncio.Server, Path]:
    path = short_dir / "raw.sock"

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await read_frame(reader, max_bytes=1 << 20)
        reply = answer(request)
        if reply is not None:
            await write_frame(writer, reply)
        else:
            await asyncio.sleep(3)
        writer.close()

    return await asyncio.start_unix_server(handle, path=str(path)), path


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (lambda r: {"protocol": PROTOCOL_VERSION, "id": "other", "ok": True}, "mismatched"),
        (
            lambda r: {"protocol": PROTOCOL_VERSION, "id": r["id"], "ok": True, "vector": [1.0]},
            "malformed",
        ),
        (
            lambda r: {"protocol": PROTOCOL_VERSION, "id": r["id"], "ok": True, "vector": "x"},
            "no vector",
        ),
        (
            lambda r: {
                "protocol": PROTOCOL_VERSION,
                "id": r["id"],
                "ok": False,
                "error": "overloaded",
            },
            "overloaded",
        ),
    ],
)
async def test_malformed_or_refused_replies_degrade(
    short_dir: Path, reply: Callable[[dict[str, Any]], dict[str, Any]], message: str
) -> None:
    server, path = await _raw_server(short_dir, reply)
    try:
        with pytest.raises(EmbedderUnavailableError, match=message):
            await SocketTextEmbedder(PROFILE, path).embed_query("x")
    finally:
        server.close()
        await server.wait_closed()


async def test_a_slow_runtime_times_out(short_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket_text_embedder, "QUERY_DEADLINE_SECONDS", 0.2)
    server, path = await _raw_server(short_dir, lambda r: None)
    try:
        with pytest.raises(EmbedderUnavailableError, match="timed out"):
            await SocketTextEmbedder(PROFILE, path).embed_query("x")
    finally:
        server.close()
        await server.wait_closed()


async def test_bad_passage_replies_degrade(short_dir: Path) -> None:
    server, path = await _raw_server(
        short_dir,
        lambda r: {"protocol": PROTOCOL_VERSION, "id": r["id"], "ok": True, "passages": [{}]},
    )
    try:
        with pytest.raises(EmbedderUnavailableError, match="malformed"):
            await SocketTextEmbedder(PROFILE, path).embed_passages(["a"])
        with pytest.raises(EmbedderUnavailableError, match="passage count"):
            await SocketTextEmbedder(PROFILE, path).embed_passages(["a", "b"])
    finally:
        server.close()
        await server.wait_closed()


async def test_a_live_socket_is_never_taken_over(
    served: tuple[UnixSocketEmbedderServer, FakeEngine],
) -> None:
    server, _ = served
    second = UnixSocketEmbedderServer(FakeEngine(), server.socket_path)

    with pytest.raises(SocketInUseError):
        await second.start()


async def test_a_stale_socket_of_ours_is_cleaned(short_dir: Path) -> None:
    import socket

    path = short_dir / "s.sock"
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(path))
    stale.close()  # the file stays, nobody listens
    server = UnixSocketEmbedderServer(FakeEngine(), path)

    await server.start()
    try:
        assert (await SocketTextEmbedder(PROFILE, path).ping())["ok"]
    finally:
        await server.close()
    assert not path.exists()


async def test_a_regular_file_at_the_socket_path_is_refused(short_dir: Path) -> None:
    path = short_dir / "f.sock"
    path.write_text("not a socket")

    with pytest.raises(PermissionError):
        await UnixSocketEmbedderServer(FakeEngine(), path).start()


async def test_serve_until_stops_and_removes_the_socket(short_dir: Path) -> None:
    server = UnixSocketEmbedderServer(FakeEngine(), short_dir / "u.sock")
    stop = asyncio.Event()
    task = asyncio.create_task(server.serve_until(stop))
    for _ in range(50):
        if server.socket_path.exists():
            break
        await asyncio.sleep(0.01)
    stop.set()
    await task

    assert not server.socket_path.exists()


async def test_bad_requests_are_answered_with_codes(
    served: tuple[UnixSocketEmbedderServer, FakeEngine],
) -> None:
    server, _ = served

    async def ask(message: dict[str, Any]) -> dict[str, Any]:
        reader, writer = await asyncio.open_unix_connection(str(server.socket_path))
        await write_frame(writer, message)
        reply = await read_frame(reader, max_bytes=1 << 20)
        writer.close()
        await writer.wait_closed()
        return reply

    fingerprint = PROFILE.fingerprint()
    assert (await ask({"protocol": 99}))["error"] == "protocol_mismatch"
    base = {"protocol": PROTOCOL_VERSION, "profile": fingerprint, "id": "1"}
    assert (await ask({**base, "op": "query", "texts": [1]}))["error"] == "bad_request"
    assert (await ask({**base, "op": "query", "texts": ["a", "b"]}))["error"] == "bad_request"
    assert (await ask({**base, "op": "query", "texts": ["x" * 32_001]}))["error"] == (
        "inference_failed"
    )
    assert (await ask({**base, "op": "nope", "texts": []}))["error"] == "bad_request"


async def test_a_garbage_frame_closes_the_connection(
    served: tuple[UnixSocketEmbedderServer, FakeEngine],
) -> None:
    server, _ = served
    reader, writer = await asyncio.open_unix_connection(str(server.socket_path))
    writer.write(b"\x00\x00\x00\x02{]")
    await writer.drain()

    assert await reader.read() == b""
    writer.close()
    await writer.wait_closed()


async def test_the_gate_puts_queries_before_waiting_passages() -> None:
    gate = InferenceGate(max_waiting=8)
    order: list[str] = []

    async def work(name: str, *, query: bool) -> None:
        async with gate.turn(query=query):
            order.append(name)
            await asyncio.sleep(0.01)

    first = asyncio.create_task(work("p1", query=False))
    await asyncio.sleep(0)
    later = [
        asyncio.create_task(work("p2", query=False)),
        asyncio.create_task(work("q1", query=True)),
    ]
    await asyncio.gather(first, *later)

    assert order == ["p1", "q1", "p2"]


async def test_the_gate_refuses_beyond_its_queue() -> None:
    gate = InferenceGate(max_waiting=1)
    started = asyncio.Event()
    release = asyncio.Event()

    async def hold() -> None:
        async with gate.turn(query=True):
            started.set()
            await release.wait()

    async def wait_turn() -> None:
        async with gate.turn(query=True):
            pass

    holder = asyncio.create_task(hold())
    await started.wait()
    waiter = asyncio.create_task(wait_turn())
    await asyncio.sleep(0)

    assert not gate.admit()
    release.set()
    await asyncio.gather(holder, waiter)
    assert gate.admit()


async def test_an_overloaded_server_refuses_at_once(short_dir: Path) -> None:
    release = asyncio.Event()

    async def slow(function: Callable[..., Any], *args: Any) -> Any:
        await release.wait()
        return function(*args)

    server = UnixSocketEmbedderServer(
        FakeEngine(), short_dir / "o.sock", run_blocking=slow, max_waiting=1
    )
    await server.start()
    client = SocketTextEmbedder(PROFILE, server.socket_path)
    try:
        busy = asyncio.create_task(client.embed_query("one"))
        await asyncio.sleep(0.05)
        queued = asyncio.create_task(client.embed_query("two"))
        await asyncio.sleep(0.05)
        with pytest.raises(EmbedderUnavailableError, match="overloaded"):
            await client.embed_query("three")
        release.set()
        await asyncio.gather(busy, queued)
    finally:
        await server.close()


def test_socket_paths_are_namespaced_by_cache_and_profile(tmp_path: Path) -> None:
    directory = runtime_directory(tmp_path / "xdg", tmp_path / "cache")
    first = socket_path(directory, cache_root=tmp_path / "cache", profile_hash="p1")
    other_profile = socket_path(directory, cache_root=tmp_path / "cache", profile_hash="p2")
    other_cache = socket_path(directory, cache_root=tmp_path / "cache2", profile_hash="p1")

    assert directory == tmp_path / "xdg" / "noesis"
    assert len({first, other_profile, other_cache}) == 3
    assert runtime_directory(None, tmp_path / "cache") == tmp_path / "cache" / "run"


async def test_frames_reject_oversize_and_non_objects() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"\x00\x00\x00\x10")
    reader.feed_eof()
    with pytest.raises(ProtocolError, match="exceeds"):
        await read_frame(reader, max_bytes=8)

    reader = asyncio.StreamReader()
    reader.feed_data(b"\x00\x00\x00\x02[]")
    reader.feed_eof()
    with pytest.raises(ProtocolError, match="object"):
        await read_frame(reader, max_bytes=8)

    reader = asyncio.StreamReader()
    reader.feed_data(b"\x00\x00\x00\x05ab")
    reader.feed_eof()
    with pytest.raises(ProtocolError, match="mid-frame"):
        await read_frame(reader, max_bytes=8)


@pytest.mark.parametrize(
    "vector",
    [[0.0] * 384, [float("nan")] + [0.0] * 383, [1.0] * 10, [2.0] + [0.0] * 383, ["x"] * 384],
)
def test_received_vectors_must_be_finite_unit_and_384_wide(vector: list[Any]) -> None:
    with pytest.raises(EmbedderUnavailableError):
        validate_vector(vector, 384)


def test_the_socket_directory_of_another_user_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from noesis.bounded_context.retrieval.infrastructure.outbound.embedding import (
        embedder_protocol,
    )

    monkeypatch.setattr(os, "getuid", lambda: 999_999)

    with pytest.raises(PermissionError):
        embedder_protocol.ensure_private_directory(tmp_path / "d")


def test_a_symlinked_socket_directory_is_refused(short_dir: Path) -> None:
    target = short_dir / "elsewhere"
    target.mkdir(mode=0o700)
    link = short_dir / "run"
    link.symlink_to(target)

    with pytest.raises(PermissionError, match="symbolic link"):
        claim_socket_path(link / "e.sock")


def test_claiming_removes_a_stale_socket_of_ours(short_dir: Path) -> None:
    import socket as sockets

    path = short_dir / "run" / "e.sock"
    path.parent.mkdir(mode=0o700)
    stale = sockets.socket(sockets.AF_UNIX, sockets.SOCK_STREAM)
    stale.bind(str(path))
    stale.close()  # bound, never listening: nobody answers

    claim_socket_path(path)

    assert not path.exists()


def test_the_short_fallback_is_private_per_user() -> None:
    assert short_runtime_directory(uid=4242).name == "noesis-4242"
    assert fits_unix_socket(Path("/run/x.sock"))
    assert not fits_unix_socket(Path("/" + "a" * 200))


def test_a_deep_runtime_root_resolves_under_the_short_fallback(tmp_path: Path) -> None:
    deep = tmp_path / ("d" * 120)

    found = resolve_socket_path(deep, cache_root=tmp_path, profile_hash="p1")
    preferred = resolve_socket_path(tmp_path, cache_root=tmp_path, profile_hash="p1")

    assert found.parent == short_runtime_directory()
    assert found.name == preferred.name  # same namespace, only the directory changes
