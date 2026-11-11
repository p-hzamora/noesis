"""`INoteRepository` over Obsidian's MCP server: stage on `save`, send on `flush`.

Tools used (names and shapes of the `obsidian` MCP server):

* `vault_read {path}` -> JSON with the file's `content`; a missing file is a tool error.
* `vault_list {path}` -> JSON with `files`, the folder's entries; a missing folder is a tool error.
* `vault_write {path, content}` -> creates or overwrites the file (and its folders); the answer
  is plain text, not JSON.

Only `NoteStorageError` leaves this adapter. One MCP session serves one operation (one `get`,
one `flush`), so a failure while handling an answer is never mistaken for an unreachable server.
"""

from pathlib import PurePosixPath

import yaml

from noesis.bounded_context.notes.domain.entities import Note
from noesis.bounded_context.notes.domain.repositories import INoteRepository
from noesis.bounded_context.notes.domain.value_objects import NotePath
from noesis.exceptions import NoteStorageError, ObsidianMcpError, ObsidianMcpToolError
from noesis.shared_kernel.domain import JsonValue
from noesis.shared_kernel.infrastructure.outbound.mcp import ObsidianMcpClient, ObsidianMcpSession

from .mappers import NoteMapper

BACKEND: str = "mcp"
WRITER_NEXT_STEPS: tuple[str, ...] = (
    "Start Obsidian with its MCP server, or check NOESIS_OBSIDIAN_MCP_URL and "
    "NOESIS_OBSIDIAN_MCP_TOKEN (`noesis doctor`).",
)


class _ExistingNoteUnreadableError(Exception):
    """The current text of a staged note could not be read, so its header cannot be kept."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason: str = reason


class McpNoteRepositoryAdapter(INoteRepository):
    """Reads notes with `vault_read`; stages writes until `flush` sends them with `vault_write`."""

    def __init__(self, client: ObsidianMcpClient, mapper: NoteMapper) -> None:
        self._client: ObsidianMcpClient = client
        self._mapper: NoteMapper = mapper
        self._staged: dict[str, Note] = {}

    async def get(self, path: NotePath) -> Note | None:
        """The note at `path`, preferring a staged version.

        A file the server says it does not have (a tool error, and the file is not listed in
        its folder) is `None`.

        Raises:
            NoteStorageError: The server is unreachable, or the file exists but cannot be read.
        """
        if path.value in self._staged:
            return self._staged[path.value]
        content: str | None = await self._read(path.value)
        return None if content is None else self._mapper.to_entity(content, path)

    async def exists(self, path: NotePath) -> bool:
        """Whether a staged note or a file of the vault occupies `path`."""
        return path.value in self._staged or await self._read(path.value) is not None

    async def _read(self, path: str) -> str | None:
        try:
            async with self._client.session() as session:
                try:
                    answer: JsonValue = await session.call("vault_read", {"path": path})
                except ObsidianMcpToolError:
                    if not await self._is_listed(session, path):
                        return None
                    raise
        except ObsidianMcpError as error:
            raise NoteStorageError(
                f"Cannot read {path} through the Obsidian MCP: {error.message}",
                {"path": path, "backend": BACKEND},
                next_steps=WRITER_NEXT_STEPS,
            ) from error
        content: JsonValue = answer.get("content") if isinstance(answer, dict) else None
        if not isinstance(content, str):
            raise NoteStorageError(
                f"Cannot read {path} through the Obsidian MCP: the answer has no content.",
                {"path": path, "backend": BACKEND},
            )
        return content

    @staticmethod
    async def _is_listed(session: ObsidianMcpSession, path: str) -> bool:
        """Whether the file's folder lists it (a missing folder lists nothing)."""
        pure: PurePosixPath = PurePosixPath(path)
        try:
            answer: JsonValue = await session.call("vault_list", {"path": str(pure.parent)})
        except ObsidianMcpToolError:
            return False
        files: JsonValue = answer.get("files") if isinstance(answer, dict) else None
        return isinstance(files, list) and pure.name in files

    async def save(self, note: Note) -> None:
        """Stage `note`; nothing is sent until `flush`."""
        self._staged[note.path.value] = note

    async def flush(self) -> None:
        """Send every staged note, one at a time, then clear the stage.

        Every note is rendered first and nothing is sent when one cannot be. After the first
        send the write is best effort, not atomic: a failure stops the sending and reports what
        was written and what was not; a retry overwrites them all.

        Raises:
            NoteStorageError: A note cannot be rendered, or the server failed. The metadata
                lists the `written` and `not_written` paths.
        """
        try:
            rendered: dict[str, str] = await self._render_all()
        except _ExistingNoteUnreadableError as error:
            raise NoteStorageError(
                f"Cannot write {len(self._staged)} note(s) through the Obsidian MCP: {error.reason}",
                {"backend": BACKEND, "written": [], "not_written": list[JsonValue](self._staged)},
                next_steps=WRITER_NEXT_STEPS,
            ) from error
        paths: list[JsonValue] = list(rendered)
        written: list[JsonValue] = []
        failure: ObsidianMcpError | None = None
        try:
            async with self._client.session() as session:
                for path, markdown in rendered.items():
                    try:
                        await session.call_text("vault_write", {"path": path, "content": markdown})
                    except ObsidianMcpError as error:
                        failure = error
                        break
                    written.append(path)
        except ObsidianMcpError as error:
            failure = error
        if failure is not None:
            total: int = len(paths)
            reason: str = failure.message
            message: str = (
                f"Wrote {len(written)} of {total} note(s) through the Obsidian MCP before it "
                f"failed: {reason}"
                if written
                else f"Cannot write {total} note(s) through the Obsidian MCP: {reason}"
            )
            raise NoteStorageError(
                message,
                {
                    "backend": BACKEND,
                    "written": written,
                    "not_written": paths[len(written) :],
                },
                next_steps=WRITER_NEXT_STEPS,
            ) from failure
        self._staged.clear()

    async def _render_all(self) -> dict[str, str]:
        """Markdown of every staged note, in staging order.

        A note that already exists keeps the header keys that are not its `noesis:` block.

        Raises:
            NoteStorageError: A note cannot be rendered or renders blank, or an existing one
                cannot be read; nothing is sent.
        """
        rendered: dict[str, str] = {}
        for path, note in self._staged.items():
            reason: str | None = None
            try:
                existing: str | None = await self._read(path)
            except NoteStorageError as error:
                raise _ExistingNoteUnreadableError(error.message) from error
            try:
                markdown: str = self._mapper.to_markdown(note, existing)
            except (yaml.YAMLError, ValueError, TypeError) as error:
                reason = str(error) or type(error).__name__
            else:
                if not markdown.strip():
                    reason = "the rendered note is blank"
                rendered[path] = markdown
            if reason is not None:
                raise NoteStorageError(
                    f"Refusing to send any note: {path} cannot be rendered ({reason}).",
                    {
                        "backend": BACKEND,
                        "written": [],
                        "not_written": list[JsonValue](self._staged),
                        "invalid": path,
                    },
                )
        return rendered

    def discard(self) -> None:
        """Forget staged notes without sending them."""
        self._staged.clear()
