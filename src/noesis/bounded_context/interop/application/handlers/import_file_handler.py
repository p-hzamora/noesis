"""Register one file as a record (`import file`)."""

import shlex
from collections.abc import Mapping

from noesis.bounded_context.interop.application.dtos import ImportFileResultDto
from noesis.bounded_context.interop.application.ports import (
    IFileReader,
    IHeaderParser,
    IKnowledgeImporter,
)
from noesis.bounded_context.interop.application.services import (
    ImportPayload,
    KnowledgeAnswer,
    KnowledgeImportTranslator,
    digest_of,
)
from noesis.bounded_context.interop.domain.services import (
    NoteMapper,
    NoteSplitter,
    TextNormaliser,
    TitleRule,
)
from noesis.bounded_context.interop.domain.value_objects import (
    ImportActor,
    NoteBlockReasonEnum,
    NoteMapping,
    NoteOutcomeEnum,
    SplitNote,
)
from noesis.exceptions import FileNotImportableError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject

ORIGIN_TAG: str = "origin:imported"
EMPTY_BODY: str = "empty_body"


class ImportFileCommand(FrozenObject):
    """Register a file.

    Attributes:
        path: The file, anywhere on disk.
        title: `--title`, else the title rule decides.
        subtype: `--subtype`, else the header kind, else `note`.
        project_key: `--project`, else the header, else none.
        tags: `--tag` values, added to the header tags.
        dry_run: Assess instead of apply.
    """

    path: str
    title: str | None = None
    subtype: str | None = None
    project_key: str | None = None
    tags: tuple[str, ...] = ()
    dry_run: bool = False


class ImportFileHandler(IHandler[ImportFileCommand, ImportFileResultDto]):
    """Reads a file once, never writes it, and asks Knowledge to record it."""

    def __init__(
        self,
        *,
        files: IFileReader,
        header_parser: IHeaderParser,
        importer: IKnowledgeImporter,
        space_key: str,
        actor: ImportActor,
    ) -> None:
        self._files: IFileReader = files
        self._parser: IHeaderParser = header_parser
        self._knowledge: KnowledgeImportTranslator = KnowledgeImportTranslator(
            importer=importer, space_key=space_key, actor=actor
        )
        self._splitter: NoteSplitter = NoteSplitter()
        self._mapper: NoteMapper = NoteMapper()
        self._titles: TitleRule = TitleRule()
        self._normaliser: TextNormaliser = TextNormaliser()

    async def handle(self, action: ImportFileCommand) -> ImportFileResultDto:
        """Register the file.

        Raises:
            FileReadFailedError: The path is missing, not a file, or unreadable.
            FileNotImportableError: Not text, bad header, no body, or Knowledge blocked it.
        """
        path: str = self._files.resolve(action.path)
        data: bytes = self._files.read(path)
        split: SplitNote = self._splitter.split(data)
        if split.failure is not None:
            raise self._refusal(path, split.failure.value)
        header: Mapping[str, object] | None = None
        if split.header_text is not None:
            header = self._parser.parse(split.header_text)
            if header is None:
                raise self._refusal(path, NoteBlockReasonEnum.INVALID_HEADER.value)
        body: str = self._normaliser.normalise(split.body)
        if not body:
            raise self._refusal(path, EMPTY_BODY)
        title: str = action.title or self._titles.resolve(
            header or {}, split.body, path.rsplit("/", 1)[-1]
        )
        mapped: NoteMapping | NoteBlockReasonEnum = self._mapper.map_file(
            header,
            title=title,
            subtype=action.subtype,
            project_key=action.project_key,
            tags=action.tags,
        )
        if isinstance(mapped, NoteBlockReasonEnum):
            raise self._refusal(path, mapped.value)
        payload: ImportPayload = ImportPayload(
            mapping=mapped,
            origin_tag=ORIGIN_TAG,
            body=body,
            source_locator=path,
            source_digest=digest_of(data),
            on_change="update",
        )
        answer: KnowledgeAnswer = (
            await self._knowledge.assess(payload)
            if action.dry_run
            else await self._knowledge.apply(payload)
        )
        if answer.outcome is NoteOutcomeEnum.BLOCKED:
            raise self._refusal(path, answer.block_reason or "", answer.detail)
        return ImportFileResultDto(
            applied=not action.dry_run,
            path=path,
            source_locator=path,
            outcome=answer.outcome.value,
            record_id=answer.record_id,
            revision=answer.revision,
            status=answer.status,
            title=mapped.title,
            subtype=mapped.subtype,
            project_key=mapped.project_key,
            tags=tuple(sorted({*mapped.tags, ORIGIN_TAG})),
            target_record_id=answer.target_record_id,
            assertion_id=answer.assertion_id,
            reason=answer.reason,
            warnings=mapped.warnings,
            next_steps=self._next_steps(path, action) if action.dry_run else (),
        )

    def _refusal(self, path: str, reason: str, detail: str | None = None) -> FileNotImportableError:
        return FileNotImportableError(
            f"{path} cannot be imported: {reason}.",
            {"path": path, "reason": reason, "detail": detail},
            next_steps=["Fix the file or the options and run `noesis import file` again."],
        )

    def _next_steps(self, path: str, action: ImportFileCommand) -> tuple[str, ...]:
        parts: list[str] = ["noesis", "import", "file", path]
        if action.title is not None:
            parts += ["--title", action.title]
        if action.subtype is not None:
            parts += ["--subtype", action.subtype]
        if action.project_key is not None:
            parts += ["--project", action.project_key]
        for tag in action.tags:
            parts += ["--tag", tag]
        return (" ".join(shlex.quote(part) for part in parts),)
