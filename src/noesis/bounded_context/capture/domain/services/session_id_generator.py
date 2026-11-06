"""Derives the stored session id from whatever identity a harness provides."""

import hashlib
import re

from noesis.bounded_context.capture.domain.value_objects import RepoId, SessionId
from noesis.exceptions import InvalidSessionIdError

DIGEST_LENGTH: int = 12
_DERIVED_SUFFIX: re.Pattern[str] = re.compile(rf"-([0-9a-f]{{{DIGEST_LENGTH}}})$")


class SessionIdGenerator:
    """Session id = `<repo id>-<12 hex of sha256(repo id + ':' + raw)>`.

    The derivation is idempotent: an id that already has exactly that shape for this repository
    passes through, so a printed `result.session_id` can be passed back. Any other value,
    however odd, is hashed, so it can never reach a file name unsanitized.
    """

    def derive(self, repo: RepoId, raw: str) -> SessionId:
        """The session id for `raw` inside `repo`.

        Raises:
            InvalidSessionIdError: `raw` is blank.
        """
        if not raw.strip():
            raise InvalidSessionIdError(
                "A session id cannot be blank.",
                {"session_id": raw},
                next_steps=["Pass a non-empty --session, or omit it and let noesis choose."],
            )
        if re.fullmatch(rf"{re.escape(repo.value)}-[0-9a-f]{{{DIGEST_LENGTH}}}", raw):
            return SessionId(value=raw)
        digest: str = hashlib.sha256(f"{repo.value}:{raw}".encode()).hexdigest()[:DIGEST_LENGTH]
        return SessionId(value=f"{repo.value}-{digest}")

    def label(self, session_id: SessionId) -> str:
        """A short provenance label: the digest of a derived id, else its first characters."""
        match: re.Match[str] | None = _DERIVED_SUFFIX.search(session_id.value)
        return match.group(1) if match else session_id.short
