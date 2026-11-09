"""A fake Obsidian MCP server (streamable HTTP) over a folder, for adapter and CLI tests.

Speaks the real MCP protocol through the official SDK's `FastMCP`, with the three tools
noesis uses (`search_simple`, `vault_read`, `vault_list`), shaped like the `obsidian` server's
answers, plus `vault_write`, which writes into the folder and answers PLAIN TEXT (not JSON), and
`vault_delete`.
A missing file or folder is a tool error (`isError`). Records every tool call and every
`Authorization` header.
"""

import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send


def free_port() -> int:
    """A TCP port nothing listens on (right now)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class FakeObsidianMcp:
    """Serves `vault`; `canned` replaces the search with fixed `(path, score)` hits.

    Attributes:
        calls: `(tool, arguments)` of every call, in order.
        authorizations: `Authorization` header of every HTTP request (None when absent).
    """

    def __init__(
        self,
        vault: Path,
        *,
        token: str | None = None,
        canned: list[tuple[str, float]] | None = None,
        truncation_note: bool = False,
        garbage: bool = False,
        fail_write_after: int | None = None,
        reject_writes: bool = False,
        read_without_content: bool = False,
        all_words: bool = False,
        port: int | None = None,
    ) -> None:
        self.all_words: bool = all_words  # like Obsidian: a note must contain EVERY query word
        self.fail_write_after: int | None = fail_write_after  # the (N+1)-th write is a tool error
        self.reject_writes: bool = reject_writes  # every write is a tool error
        self.read_without_content: bool = read_without_content  # `vault_read` omits `content`
        self.writes_done: int = 0
        self.truncation_note: bool = truncation_note  # like the real server's second text block
        self.garbage: bool = garbage
        self.vault: Path = vault
        self.token: str | None = token
        self.canned: list[tuple[str, float]] | None = canned
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.authorizations: list[str | None] = []
        self.port: int = port if port is not None else free_port()
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp/"

    def _maybe_note(self, hits: list[dict[str, Any]]) -> str | list[TextContent]:
        body: str = json.dumps(hits)
        if not self.truncation_note:
            return body
        return [
            TextContent(type="text", text=body),
            TextContent(type="text", text="3 more files not shown."),
        ]

    def _build(self) -> ASGIApp:
        mcp = FastMCP("obsidian", stateless_http=True, json_response=True)

        @mcp.tool()
        def search_simple(query: str) -> str | list[TextContent]:
            self.calls.append(("search_simple", {"query": query}))
            if self.garbage:
                return "not json at all"
            if self.canned is not None:
                hits = [
                    {"filename": path, "score": score, "matches": []} for path, score in self.canned
                ]
                return self._maybe_note(hits)
            words: list[str] = query.lower().split()
            hits = []
            for path in sorted(self.vault.rglob("*.md")):
                text: str = path.read_text(encoding="utf-8").lower()
                score: int = sum(text.count(word) for word in words)
                if score and (not self.all_words or all(word in text for word in words)):
                    hits.append(
                        {
                            "filename": path.relative_to(self.vault).as_posix(),
                            "score": score,
                            "matches": [],
                        }
                    )
            return self._maybe_note(hits)

        @mcp.tool()
        def vault_read(path: str) -> str:
            self.calls.append(("vault_read", {"path": path}))
            if self.read_without_content:
                return json.dumps({"path": path})
            return json.dumps(
                {"path": path, "content": (self.vault / path).read_text(encoding="utf-8")}
            )

        @mcp.tool()
        def vault_list(path: str = "") -> str:
            self.calls.append(("vault_list", {"path": path}))
            folder: Path = self.vault / path
            names: list[str] = [
                entry.name + ("/" if entry.is_dir() else "") for entry in sorted(folder.iterdir())
            ]
            return json.dumps({"files": names})

        @mcp.tool()
        def vault_write(path: str, content: str) -> str:
            self.calls.append(("vault_write", {"path": path, "content": content}))
            if self.reject_writes:
                raise PermissionError("the vault is read-only")
            if self.fail_write_after is not None and self.writes_done >= self.fail_write_after:
                raise OSError("disk full")
            target: Path = self.vault / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            self.writes_done += 1
            return f"Wrote {path}"  # plain text on purpose: the real server does not answer JSON

        @mcp.tool()
        def vault_delete(path: str, permanent: bool = False) -> str:
            self.calls.append(("vault_delete", {"path": path, "permanent": permanent}))
            (self.vault / path).unlink()
            return json.dumps({"message": "OK"})

        app: ASGIApp = mcp.streamable_http_app()

        async def guarded(scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "http":
                header: str | None = (
                    dict(scope["headers"]).get(b"authorization", b"").decode() or None
                )
                self.authorizations.append(header)
                if self.token is not None and header != f"Bearer {self.token}":
                    await PlainTextResponse("unauthorized", status_code=401)(scope, receive, send)
                    return
            await app(scope, receive, send)

        return guarded

    def start(self) -> None:
        config: uvicorn.Config = uvicorn.Config(
            self._build(), host="127.0.0.1", port=self.port, log_level="critical", lifespan="on"
        )
        server: uvicorn.Server = uvicorn.Server(config)
        self._server = server
        self._thread = threading.Thread(target=server.run, daemon=True)
        self._thread.start()
        deadline: float = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("fake Obsidian MCP did not start")
            time.sleep(0.01)

    def stop(self) -> None:
        if self._server and self._thread:
            self._server.should_exit = True
            self._thread.join(timeout=10)


@contextmanager
def fake_obsidian_mcp(
    vault: Path,
    *,
    token: str | None = None,
    canned: list[tuple[str, float]] | None = None,
    truncation_note: bool = False,
    garbage: bool = False,
    fail_write_after: int | None = None,
    reject_writes: bool = False,
    read_without_content: bool = False,
    all_words: bool = False,
    port: int | None = None,
) -> Iterator[FakeObsidianMcp]:
    """Run a fake server for the duration of the block (on `port`, to bring a server back)."""
    fake = FakeObsidianMcp(
        vault,
        token=token,
        canned=canned,
        truncation_note=truncation_note,
        garbage=garbage,
        fail_write_after=fail_write_after,
        reject_writes=reject_writes,
        read_without_content=read_without_content,
        all_words=all_words,
        port=port,
    )
    fake.start()
    try:
        yield fake
    finally:
        fake.stop()
