"""Steps 2..7 of `import run`, shared by the preview and the apply handlers."""

import hashlib
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field

from noesis.bounded_context.interop.application.dtos import (
    ImportNoteRowDto,
    ImportTotalsDto,
    ImportWarningCountsDto,
    VaultImportResultDto,
)
from noesis.bounded_context.interop.application.dtos.vault_import_result_dto import AmbiguousLinkDto
from noesis.bounded_context.interop.application.ports import (
    IHeaderParser,
    IKnowledgeImporter,
    IVaultReader,
)
from noesis.bounded_context.interop.application.services.knowledge_import_translator import (
    ImportPayload,
    KnowledgeAnswer,
    KnowledgeImportTranslator,
)
from noesis.bounded_context.interop.domain.services import (
    NoteMapper,
    NoteSplitter,
    TextNormaliser,
    TitleRule,
)
from noesis.bounded_context.interop.domain.services.link_parser import LinkParser
from noesis.bounded_context.interop.domain.services.link_set_builder import LinkSetBuilder
from noesis.bounded_context.interop.domain.services.link_target_index import LinkTargetIndex
from noesis.bounded_context.interop.domain.value_objects import (
    ImportActor,
    NoteBlockReasonEnum,
    NoteMapping,
    NoteOutcomeEnum,
    NoteWarningEnum,
    SplitNote,
)
from noesis.bounded_context.interop.domain.value_objects.vault_link import VaultLink
from noesis.exceptions import BlockingFindingsError

LINK_CLASSES: tuple[str, ...] = (
    "resolved",
    "dangling",
    "ambiguous",
    "non_note",
    "not_imported",
    "self",
)

ORIGIN_TAG: str = "origin:migrated"
APPLY_COMMAND: str = "noesis import run --yes"
VERBOSE_COMMAND: str = "noesis import run --verbose"
WRITING_OUTCOMES: frozenset[NoteOutcomeEnum] = frozenset(
    {NoteOutcomeEnum.CREATED, NoteOutcomeEnum.REVISED, NoteOutcomeEnum.SUCCESSOR_PROPOSED}
)


def digest_of(data: bytes) -> str:
    """`sha256:<hex>` of raw bytes."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


@dataclass(slots=True, kw_only=True)
class _Note:
    """A note on its way through the run."""

    path: str
    parsed_links: tuple[VaultLink, ...] = ()
    link_counts: dict[str, int] = field(default_factory=dict)
    link_outcome: str | None = None
    link_block_reason: str | None = None
    ambiguous: tuple[AmbiguousLinkDto, ...] = ()
    mapping: NoteMapping | None = None
    block_reason: str | None = None
    skipped_empty: bool = False
    payload: ImportPayload | None = None
    answer: KnowledgeAnswer | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def outcome(self) -> NoteOutcomeEnum:
        """What the note finally is."""
        if self.answer is not None:
            return self.answer.outcome
        if self.block_reason is not None:
            return NoteOutcomeEnum.BLOCKED
        return NoteOutcomeEnum.SKIPPED_EMPTY


class VaultImportPipeline:
    """Reads, maps and normalises every note, then assesses and optionally applies them."""

    def __init__(
        self,
        *,
        vault: IVaultReader,
        header_parser: IHeaderParser,
        importer: IKnowledgeImporter,
        vault_key: str,
        space_key: str,
        actor: ImportActor,
    ) -> None:
        self._vault: IVaultReader = vault
        self._parser: IHeaderParser = header_parser
        self._vault_key: str = vault_key
        self._knowledge: KnowledgeImportTranslator = KnowledgeImportTranslator(
            importer=importer, space_key=space_key, actor=actor
        )
        self._splitter: NoteSplitter = NoteSplitter()
        self._mapper: NoteMapper = NoteMapper()
        self._titles: TitleRule = TitleRule()
        self._normaliser: TextNormaliser = TextNormaliser()

    async def run(self, *, update: bool, strict: bool, apply: bool) -> VaultImportResultDto:
        """Steps 2..6, and step 7 when `apply`.

        Raises:
            VaultReadFailedError: The vault or a note cannot be read.
            BlockingFindingsError: `strict` and a note is blocked.
        """
        notes: list[_Note] = self._analyse(update=update)
        if strict:
            self._refuse_blocked(notes)
        for note in notes:
            if note.payload is not None:
                note.answer = await self._knowledge.assess(note.payload)
        if strict:
            self._refuse_blocked(notes)
        if apply:
            for note in notes:
                if note.payload is not None and note.outcome in WRITING_OUTCOMES:
                    note.answer = await self._knowledge.apply(note.payload)
        await self._links(notes, apply=apply)
        return self._report(notes, update=update, applied=apply)

    def _analyse(self, *, update: bool) -> list[_Note]:
        paths: list[str] = self._vault.list_notes()
        contents: dict[str, bytes] = {path: self._vault.read(path) for path in paths}
        notes: list[_Note] = [self._note(path, contents[path], update=update) for path in paths]
        holders: Counter[str] = Counter(
            note.mapping.record_id
            for note in notes
            if note.mapping is not None and note.mapping.record_id and note.block_reason is None
        )
        for note in notes:
            if (
                note.mapping is not None
                and note.block_reason is None
                and note.mapping.record_id is not None
                and holders[note.mapping.record_id] > 1
            ):
                note.block_reason = NoteBlockReasonEnum.DUPLICATE_ID.value
                note.payload = None
                note.skipped_empty = False
        return notes

    def _note(self, path: str, data: bytes, *, update: bool) -> _Note:
        note: _Note = _Note(path=path)
        split: SplitNote = self._splitter.split(data)
        if split.failure is not None:
            note.block_reason = split.failure.value
            return note
        note.parsed_links = LinkParser().parse(split.body)
        header: Mapping[str, object] | None = None
        if split.header_text is not None:
            header = self._parser.parse(split.header_text)
            if header is None:
                note.block_reason = NoteBlockReasonEnum.INVALID_HEADER.value
                return note
        title: str = self._titles.resolve(header or {}, split.body, path.rsplit("/", 1)[-1])
        mapped: NoteMapping | NoteBlockReasonEnum = self._mapper.map_vault_note(header, title=title)
        if isinstance(mapped, NoteBlockReasonEnum):
            note.block_reason = mapped.value
            return note
        note.mapping = mapped
        note.warnings = mapped.warnings
        body: str = self._normaliser.normalise(split.body)
        if not body:
            note.skipped_empty = True
            return note
        note.payload = ImportPayload(
            mapping=mapped,
            origin_tag=ORIGIN_TAG,
            body=body,
            source_locator=f"vault://{self._vault_key}/{path}",
            source_digest=digest_of(data),
            on_change="update" if update else "report",
        )
        return note

    async def _links(self, notes: list[_Note], *, apply: bool) -> None:
        """Step 8: outgoing source set differs from the incoming target map."""
        index = LinkTargetIndex([note.path for note in notes])
        targets: dict[str, str] = {}
        pending: set[str] = set()
        for note in notes:
            answer = note.answer
            if answer is None:
                continue
            is_pending: bool = not apply and note.outcome in {
                NoteOutcomeEnum.CREATED,
                NoteOutcomeEnum.SUCCESSOR_PROPOSED,
            }
            if is_pending:
                pending.add(note.path)
            target: str | None = answer.target_record_id or answer.record_id
            if answer.target_record_id:
                targets[note.path] = answer.target_record_id
            elif is_pending:
                targets[note.path] = f"pending:{note.path}"
            elif target is not None:
                targets[note.path] = target
        for note in notes:
            built = LinkSetBuilder().build(
                tuple(index.resolve(link, source=note.path) for link in note.parsed_links), targets
            )
            counts: Counter[str] = Counter(item.classification for item in built.occurrences)
            note.link_counts = {name: counts[name] for name in LINK_CLASSES}
            note.ambiguous = tuple(
                AmbiguousLinkDto(target=item.link.target, candidates=item.candidates)
                for item in built.occurrences
                if item.classification == "ambiguous"
            )
            if note.outcome is NoteOutcomeEnum.CHANGED_IN_VAULT:
                note.link_outcome = "deferred"
            elif note.outcome in {NoteOutcomeEnum.BLOCKED, NoteOutcomeEnum.SKIPPED_EMPTY}:
                # Header-only notes have no link set to account for.
                note.link_outcome = "no_record" if note.parsed_links else None
            elif note.path in pending:
                note.link_outcome = "planned" if built.links else None
            elif any(link.target_record_id.startswith("pending:") for link in built.links):
                note.link_outcome = "planned"
            elif note.answer is not None and note.answer.record_id is not None:
                outcome, reason = await self._knowledge.links(
                    note.answer.record_id, built.links, apply=apply
                )
                note.link_outcome = (
                    "planned" if not apply and outcome in {"created", "replaced"} else outcome
                )
                note.link_block_reason = reason
                if outcome == "unchanged" and not built.links:
                    # Empty stored sets and absent sets both need no reported work.
                    note.link_outcome = None

    def _refuse_blocked(self, notes: list[_Note]) -> None:
        blocked: list[ImportNoteRowDto] = [
            row for row in self._rows(notes) if row.outcome == NoteOutcomeEnum.BLOCKED.value
        ]
        if blocked:
            reasons: Counter[str] = Counter(row.reason or "" for row in blocked)
            raise BlockingFindingsError(
                f"{len(blocked)} note(s) are blocked; nothing was written.",
                {"blocked_reasons": dict(reasons), "paths": [row.path for row in blocked]},
                next_steps=[
                    "Fix the notes listed in 'paths', or run again without --strict.",
                    VERBOSE_COMMAND,
                ],
            )

    def _rows(self, notes: list[_Note]) -> list[ImportNoteRowDto]:
        return [self._row(note) for note in notes]

    def _row(self, note: _Note) -> ImportNoteRowDto:
        mapping: NoteMapping | None = note.mapping
        answer: KnowledgeAnswer | None = note.answer
        blocked: bool = answer is not None and answer.outcome is NoteOutcomeEnum.BLOCKED
        return ImportNoteRowDto(
            path=note.path,
            outcome=note.outcome.value,
            record_id=answer.record_id if answer else (mapping.record_id if mapping else None),
            revision=answer.revision if answer else None,
            status=answer.status if answer else None,
            title=mapping.title if mapping else None,
            subtype=mapping.subtype if mapping else None,
            project_key=mapping.project_key if mapping else None,
            tags=tuple(sorted({*mapping.tags, ORIGIN_TAG})) if mapping else (),
            target_record_id=answer.target_record_id if answer else None,
            assertion_id=answer.assertion_id if answer else None,
            reason=(
                (answer.block_reason if blocked else answer.reason) if answer else note.block_reason
            ),
            detail=answer.detail if answer else None,
            warnings=note.warnings,
            links={
                **note.link_counts,
                "outcome": note.link_outcome,
                **({"block_reason": note.link_block_reason} if note.link_block_reason else {}),
            },
            ambiguous=note.ambiguous,
        )

    def _report(self, notes: list[_Note], *, update: bool, applied: bool) -> VaultImportResultDto:
        rows: list[ImportNoteRowDto] = self._rows(notes)
        counts: Counter[str] = Counter(row.outcome for row in rows)
        reasons: Counter[str] = Counter(
            row.reason or "" for row in rows if row.outcome == NoteOutcomeEnum.BLOCKED.value
        )
        warnings: list[str] = [warning for note in notes for warning in note.warnings]
        totals: ImportTotalsDto = ImportTotalsDto(
            notes=len(rows), **{outcome.value: counts[outcome.value] for outcome in NoteOutcomeEnum}
        )
        link_sets: Counter[str] = Counter(note.link_outcome for note in notes if note.link_outcome)
        return VaultImportResultDto(
            links={
                name: sum(
                    note.link_counts.get(name, 0)
                    for note in notes
                    if note.outcome not in {NoteOutcomeEnum.SKIPPED_EMPTY, NoteOutcomeEnum.BLOCKED}
                )
                for name in LINK_CLASSES
            },
            link_sets={
                name: link_sets[name]
                for name in (("created", "replaced") if applied else ("planned",))
                + ("unchanged", "deferred", "no_record", "blocked")
            },
            applied=applied,
            update=update,
            vault_key=self._vault_key,
            totals=totals,
            blocked_reasons=dict(reasons),
            warnings=ImportWarningCountsDto(
                legacy_header=warnings.count(NoteWarningEnum.LEGACY_HEADER.value),
                dropped_tag=sum(
                    warning.startswith(f"{NoteWarningEnum.DROPPED_TAG.value}:")
                    for warning in warnings
                ),
                ignored_field=sum(
                    warning.startswith(f"{NoteWarningEnum.IGNORED_FIELD.value}:")
                    for warning in warnings
                ),
            ),
            sources_skipped=sum(
                note.mapping.sources_skipped
                for note in notes
                if note.mapping is not None and note.payload is not None
            ),
            complete=totals.blocked == 0,
            notes=tuple(rows),
            next_steps=tuple(self._next_steps(totals, update=update, applied=applied)),
        )

    def _next_steps(self, totals: ImportTotalsDto, *, update: bool, applied: bool) -> list[str]:
        if not applied:
            return [f"{APPLY_COMMAND} --update" if update else APPLY_COMMAND]
        steps: list[str] = []
        if totals.changed_in_vault:
            steps.append(f"{APPLY_COMMAND} --update")
        if totals.blocked:
            steps.append(VERBOSE_COMMAND)
        return steps
