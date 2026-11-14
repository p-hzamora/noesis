"""Immutable revisions of a Knowledge record and the two shapes of their content."""

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from noesis.bounded_context.knowledge.domain.value_objects.actor import Actor
from noesis.bounded_context.knowledge.domain.value_objects.content_hash import ContentHash
from noesis.bounded_context.knowledge.domain.value_objects.record_id import RecordId
from noesis.exceptions import InvalidRecordError
from noesis.shared_kernel.domain.value_objects import ValueObject


def _not_blank(value: str, what: str) -> str:
    stripped: str = value.strip()
    if not stripped:
        raise InvalidRecordError(
            f"A revision's {what} cannot be blank.", next_steps=[f"Provide a {what}."]
        )
    return stripped


class GraphContent(ValueObject):
    """Text owned by the store, as authored (after redaction).

    Attributes:
        title: Short title.
        body: Full text.
    """

    title: str
    body: str

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _not_blank(value, "title")

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        return _not_blank(value, "body")


class FileContent(ValueObject):
    """A file-owned version: no text, only what identifies it.

    Attributes:
        content_hash: Hash of the file version.
        file_version_source_id: Id of the `file_version` Source naming that version.
        title: Title as read from the file.
    """

    content_hash: ContentHash
    file_version_source_id: RecordId
    title: str

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _not_blank(value, "title")


type RevisionContent = GraphContent | FileContent


class Revision(ValueObject):
    """One immutable version of a Knowledge record.

    Attributes:
        number: 1-based position; revisions are numbered without gaps.
        actor: Who made it.
        source_ids: Sources it rests on; at least one.
        created_at: When it was made.
        content: Graph text, or a file version's identity.
    """

    number: int = Field(ge=1)
    actor: Actor
    source_ids: tuple[RecordId, ...]
    created_at: datetime
    content: GraphContent | FileContent

    @model_validator(mode="after")
    def _grounded(self) -> Revision:
        if not self.source_ids:
            raise InvalidRecordError(
                "A revision needs at least one source.", next_steps=["Cite at least one source."]
            )
        if (
            isinstance(self.content, FileContent)
            and self.content.file_version_source_id not in self.source_ids
        ):
            raise InvalidRecordError(
                "A file-owned revision must cite its file_version source.",
                {"source_id": self.content.file_version_source_id.value},
            )
        return self
