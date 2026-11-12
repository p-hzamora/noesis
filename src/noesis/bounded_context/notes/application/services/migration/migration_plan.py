"""A migration plan: the list of entries a vault restructure applies, validated as a whole."""

import json
from collections import Counter
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Self

from pydantic import ValidationError

from noesis.bounded_context.notes.domain.value_objects import NoteKind, NoteScope
from noesis.exceptions import DomainException, InvalidMigrationPlanError, UnknownNoteKindError
from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject

from ..manifest import KindCatalog
from .migration_action_enum import MigrationActionEnum
from .migration_entry import MigrationEntry

NOTE_SUFFIX: str = ".md"


def _unsafe(path: str) -> bool:
    parts: tuple[str, ...] = PurePosixPath(path).parts
    return (
        not path
        or path.startswith("/")
        or "\\" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or not parts
    )


class MigrationPlan(FrozenObject):
    """Every file the plan decides about.

    Attributes:
        entries: The plan's lines, in file order.
    """

    entries: tuple[MigrationEntry, ...]

    @classmethod
    def parse(cls, text: str) -> Self:
        """Read a plan: a JSON list of entries, or an object with an `entries` list.

        Raises:
            InvalidMigrationPlanError: The text is not JSON or an entry is malformed.
        """
        try:
            loaded: object = json.loads(text)
        except json.JSONDecodeError as error:
            raise InvalidMigrationPlanError(
                f"The plan is not valid JSON: {error}", next_steps=["Regenerate the plan file."]
            ) from error
        raw: object = loaded.get("entries") if isinstance(loaded, dict) else loaded
        if not isinstance(raw, list):
            raise InvalidMigrationPlanError(
                "The plan must be a list of entries or an object with an `entries` list.",
                next_steps=["Regenerate the plan file."],
            )
        try:
            return cls(entries=tuple(MigrationEntry.model_validate(item) for item in raw))
        except ValidationError as error:
            first = error.errors()[0]
            where: str = ".".join(str(part) for part in first["loc"])
            raise InvalidMigrationPlanError(
                f"Invalid plan entry {where}: {first['msg']}",
                {
                    "errors": [
                        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()
                    ]
                },
            ) from error

    def validate_against(self, catalog: KindCatalog) -> None:
        """Check the plan on its own: paths, scopes, kinds and collisions between entries.

        Raises:
            InvalidMigrationPlanError: Every problem found, listed in the metadata.
        """
        problems: list[str] = []
        for entry in self.entries:
            problems += self._problems(entry, catalog)
        problems += [f"old path listed twice: {p}" for p in _repeated(e.old for e in self.entries)]
        problems += [
            f"target listed twice: {p}"
            for p in _repeated(
                e.target for e in self.entries if e.action is not MigrationActionEnum.KEEP
            )
        ]
        if problems:
            raise InvalidMigrationPlanError(
                f"The plan has {len(problems)} problem(s); first: {problems[0]}",
                {"problems": list[JsonValue](problems[:50])},
                next_steps=["Fix the plan generator and regenerate the plan."],
            )

    @staticmethod
    def _problems(entry: MigrationEntry, catalog: KindCatalog) -> list[str]:
        problems: list[str] = [
            f"unsafe path: {p!r}" for p in (entry.old, entry.target) if _unsafe(p)
        ]
        if entry.action is MigrationActionEnum.MOVE and entry.target == entry.old:
            problems.append(f"move to itself: {entry.old}")
        if entry.action is not MigrationActionEnum.NOTE:
            return problems
        if not entry.old.endswith(NOTE_SUFFIX) or not entry.target.endswith(NOTE_SUFFIX):
            problems.append(f"a note must be a Markdown file: {entry.old}")
        try:
            NoteScope.parse(entry.scope or "")
        except DomainException:
            problems.append(f"invalid scope {entry.scope!r}: {entry.old}")
        try:
            catalog.require(NoteKind(value=entry.kind or ""))
        except DomainException, UnknownNoteKindError:
            problems.append(f"kind {entry.kind!r} is not in the catalog: {entry.old}")
        return problems

    def counts(self) -> dict[str, int]:
        """Entries per action."""
        tally: Counter[str] = Counter(entry.action.value for entry in self.entries)
        return {action.value: tally[action.value] for action in MigrationActionEnum}


def _repeated(paths: Iterable[str]) -> list[str]:
    counted: Counter[str] = Counter(paths)
    return sorted(path for path, count in counted.items() if count > 1)
