"""A fake Obsidian MCP server (streamable HTTP) over a folder, for adapter and CLI tests.

Speaks the real MCP protocol through the official SDK's `FastMCP`, with the three tools
noesis uses (`search_simple`, `vault_read`, `vault_list`), shaped like the `obsidian` server's
answers. Records every tool call and every `Authorization` header.
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
    ) -> None:
        self.truncation_note: bool = truncation_note  # like the real server's second text block
        self.garbage: bool = garbage
        self.vault: Path = vault
        self.token: str | None = token
        self.canned: list[tuple[str, float]] | None = canned
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.authorizations: list[str | None] = []
        self.port: int = free_port()
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
        mcp: FastMCP = FastMCP("obsidian", stateless_http=True, json_response=True)

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
                if score:
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
) -> Iterator[FakeObsidianMcp]:
    """Run a fake server for the duration of the block."""
    fake: FakeObsidianMcp = FakeObsidianMcp(
        vault, token=token, canned=canned, truncation_note=truncation_note, garbage=garbage
    )
    fake.start()
    try:
        yield fake
    finally:
        fake.stop()
