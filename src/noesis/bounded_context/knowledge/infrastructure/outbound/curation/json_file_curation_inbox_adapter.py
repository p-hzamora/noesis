"""`ICurationInbox` over JSON files under one folder (`<state_dir>/knowledge/curation/`).

Per ticket: `<ticket>.json` (the submission, progress, step outcomes and times), `<ticket>.plan.json`
(the write-once plan) and `<ticket>.lock` (the lock file). A rejected apply payload is kept under
`rejected/`, outside any ticket. Every file is written atomically (a temporary file in the same
folder, then a rename), so a crash leaves the previous content intact.
"""

import asyncio
import fcntl
import os
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from noesis.bounded_context.knowledge.application.dtos import RelatedLookupDto
from noesis.bounded_context.knowledge.application.ports.curation import (
    CurationTicket,
    ICurationInbox,
    StepOutcome,
)
from noesis.bounded_context.knowledge.domain.services import (
    CaptureKeyPolicy,
    CurationProgressPolicy,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    CurationPlan,
    CurationProgress,
    CurationSubmission,
    sha256_hex,
)
from noesis.exceptions import CurationInboxFailedError
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.utils import FrozenObject

LOCK_WAIT_SECONDS: float = 10.0
"""How long a second holder waits for a ticket's lock before `KNOWLEDGE_142` (documented bound)."""

LOCK_POLL_SECONDS: float = 0.05
REJECTED_FOLDER: str = "rejected"
TICKET_PATTERN: re.Pattern[str] = re.compile(r"[0-9a-f]{1,64}")


class _StoredTicket(FrozenObject):
    """What `<ticket>.json` holds: a ticket without its plan."""

    ticket: str
    submission: CurationSubmission
    progress: CurationProgress
    related_lookup: RelatedLookupDto | None = None
    steps: tuple[StepOutcome, ...] = ()
    created_at: datetime
    updated_at: datetime
    parked_at: datetime | None = None


class JsonFileCurationInboxAdapter(ICurationInbox):
    """Keeps tickets as JSON files; a per-ticket file lock serialises concurrent runs.

    Args:
        root: The inbox folder; created on first write.
        clock: Stamps `created_at`, `updated_at` and `parked_at`.
        lock_wait_seconds: How long `locked` waits for a busy ticket.
    """

    def __init__(
        self, root: Path, *, clock: IClock, lock_wait_seconds: float = LOCK_WAIT_SECONDS
    ) -> None:
        self._root: Path = root
        self._clock: IClock = clock
        self._lock_wait_seconds: float = lock_wait_seconds

    async def stage(self, submission: CurationSubmission) -> CurationTicket:
        """Keep the submission under its derived ticket; an existing ticket is reused."""
        ticket: str = CaptureKeyPolicy.ticket_of(submission.submission_key)
        existing: _StoredTicket | None = self._load(ticket)
        if existing is not None:
            return self._full(existing)
        now: datetime = self._clock.now()
        stored = _StoredTicket(
            ticket=ticket,
            submission=submission,
            progress=CurationProgressPolicy.initial(),
            created_at=now,
            updated_at=now,
        )
        self._store(stored)
        return self._full(stored)

    async def save_plan(
        self, ticket: str, plan: CurationPlan, *, related_lookup: RelatedLookupDto | None = None
    ) -> None:
        """Create the plan file only if it is absent; an identical plan is a no-op."""
        stored: _StoredTicket = self._require(ticket)
        path: Path = self._plan_path(ticket)
        text: str = plan.model_dump_json(indent=2)
        try:
            self._create_exclusive(path, text)
        except FileExistsError:
            if self._read_plan(path) != plan:
                raise CurationInboxFailedError(
                    "A different plan was already saved for this ticket.",
                    {"ticket": ticket, "path": str(path)},
                    next_steps=["The plan is write-once; retry the ticket instead."],
                ) from None
        if related_lookup is not None and stored.related_lookup is None:
            self._store(stored.model_copy(update={"related_lookup": related_lookup}))

    async def advance(
        self, ticket: str, expected: CurationProgress, to: CurationProgress
    ) -> CurationTicket:
        """Set the progress to `to` if it is still `expected`."""
        stored: _StoredTicket = self._require(ticket)
        if stored.progress != expected:
            raise CurationInboxFailedError(
                "The ticket changed since it was read.",
                {
                    "ticket": ticket,
                    "expected": expected.stage.value,
                    "found": stored.progress.stage.value,
                },
                next_steps=["Retry the command."],
            )
        now: datetime = self._clock.now()
        updated: _StoredTicket = stored.model_copy(
            update={
                "progress": to,
                "updated_at": now,
                "parked_at": now if to.is_failed else None,
            }
        )
        self._store(updated)
        return self._full(updated)

    async def record_step(self, ticket: str, outcome: StepOutcome) -> None:
        """Record a step outcome, replacing an earlier one of the same step."""
        stored: _StoredTicket = self._require(ticket)
        steps: tuple[StepOutcome, ...] = (
            *(
                item
                for item in stored.steps
                if (item.ordinal, item.step) != (outcome.ordinal, outcome.step)
            ),
            outcome,
        )
        self._store(stored.model_copy(update={"steps": steps, "updated_at": self._clock.now()}))

    async def get(self, ticket: str) -> CurationTicket | None:
        """The ticket with its plan, or None."""
        stored: _StoredTicket | None = self._load(ticket)
        return None if stored is None else self._full(stored)

    async def list_parked(self) -> tuple[CurationTicket, ...]:
        """Every failed ticket, oldest failure first."""
        try:
            names: list[str] = sorted(
                path.stem
                for path in self._root.glob("*.json")
                if not path.name.endswith(".plan.json")
            )
        except OSError as error:
            raise self._unusable("list the inbox", self._root, error) from error
        parked: list[CurationTicket] = []
        for name in names:
            stored: _StoredTicket | None = self._load(name)
            if stored is not None and stored.progress.is_failed:
                parked.append(self._full(stored))
        return tuple(sorted(parked, key=lambda item: item.parked_at or item.updated_at))

    @asynccontextmanager
    async def locked(self, ticket: str) -> AsyncIterator[None]:
        """Hold the ticket's file lock; wait up to the bound for a busy one."""
        if not TICKET_PATTERN.fullmatch(ticket):
            yield  # no such ticket can exist; the caller's `get` finds nothing
            return
        path: Path = self._root / f"{ticket}.lock"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor: int = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        except OSError as error:
            raise self._unusable("open the lock", path, error) from error
        try:
            deadline: float = time.monotonic() + self._lock_wait_seconds
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise CurationInboxFailedError(
                            f"The ticket {ticket} is busy: another run holds its lock.",
                            {"ticket": ticket, "waited_seconds": self._lock_wait_seconds},
                            next_steps=["Wait for the other run to finish, then retry."],
                        ) from None
                    await asyncio.sleep(LOCK_POLL_SECONDS)
                except OSError as error:
                    raise self._unusable("lock", path, error) from error
            try:
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    async def keep_rejected(self, payload_text: str) -> str:
        """Keep a rejected payload (already redacted) as `rejected/<time>-<hash>.json`."""
        stamp: str = self._clock.now().strftime("%Y%m%dT%H%M%S")
        path: Path = self._root / REJECTED_FOLDER / f"{stamp}-{sha256_hex(payload_text)[:8]}.json"
        self._write(path, payload_text)
        return str(path)

    async def remove(self, ticket: str) -> None:
        """Delete the ticket's files."""
        if not TICKET_PATTERN.fullmatch(ticket):
            return
        for path in (self._ticket_path(ticket), self._plan_path(ticket)):
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                raise self._unusable("remove", path, error) from error

    # ----- files -----

    def _ticket_path(self, ticket: str) -> Path:
        return self._root / f"{ticket}.json"

    def _plan_path(self, ticket: str) -> Path:
        return self._root / f"{ticket}.plan.json"

    def _load(self, ticket: str) -> _StoredTicket | None:
        if not TICKET_PATTERN.fullmatch(ticket):
            return None
        path: Path = self._ticket_path(ticket)
        try:
            return _StoredTicket.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValidationError, UnicodeDecodeError) as error:
            raise self._unusable("read", path, error) from error

    def _require(self, ticket: str) -> _StoredTicket:
        stored: _StoredTicket | None = self._load(ticket)
        if stored is None:
            raise CurationInboxFailedError(
                f"The ticket {ticket} is not in the inbox.",
                {"ticket": ticket},
                next_steps=["Run `noesis curate parked` to list the tickets."],
            )
        return stored

    def _full(self, stored: _StoredTicket) -> CurationTicket:
        path: Path = self._plan_path(stored.ticket)
        return CurationTicket(
            **dict(stored),
            plan=self._read_plan(path) if path.is_file() else None,
        )

    def _read_plan(self, path: Path) -> CurationPlan:
        try:
            return CurationPlan.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, UnicodeDecodeError) as error:
            raise self._unusable("read", path, error) from error

    def _store(self, stored: _StoredTicket) -> None:
        self._write(self._ticket_path(stored.ticket), stored.model_dump_json(indent=2))

    def _write(self, path: Path, text: str) -> None:
        """Write `text` to `path` atomically: a temporary file, then a rename."""
        temporary: Path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(text, encoding="utf-8")
            temporary.replace(path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise self._unusable("write", path, error) from error

    def _create_exclusive(self, path: Path, text: str) -> None:
        """Create `path` with `text` only if it does not exist (a hard link is atomic).

        Raises:
            FileExistsError: `path` exists.
        """
        temporary: Path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(text, encoding="utf-8")
            os.link(temporary, path)
        except FileExistsError:
            raise
        except OSError as error:
            raise self._unusable("write", path, error) from error
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _unusable(action: str, path: Path, error: Exception) -> CurationInboxFailedError:
        return CurationInboxFailedError(
            f"Cannot {action} {path}: {error}",
            {"path": str(path)},
            next_steps=["Check the state folder and its permissions, then retry."],
        )
