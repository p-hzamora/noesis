"""A persisted record read back, with the content of one revision."""

from datetime import datetime

from noesis.shared_kernel.application.dtos import BaseDto


class ActorDto(BaseDto):
    """Who acted.

    Attributes:
        kind: `user` or `agent`.
        name: Display name.
        session: Harness session id, when known.
    """

    kind: str
    name: str
    session: str | None = None


class ApplicabilityDto(BaseDto):
    """Where a record applies.

    Attributes:
        project_id: Project id; None means space-wide.
        tags: Normalised tags, sorted.
    """

    project_id: str | None = None
    tags: tuple[str, ...] = ()


class SourceDto(BaseDto):
    """A cited source.

    Attributes:
        id: Source record id.
        kind: Source kind.
        locator: Where to find it.
        digest: Content hash, when known.
    """

    id: str
    kind: str
    locator: str
    digest: str | None = None


class RevisionDto(BaseDto):
    """One revision of a Knowledge record.

    Attributes:
        number: Revision number.
        actor: Who made it.
        created_at: When.
        title: Title (as authored, or as read from the file).
        body: Text of a graph-owned revision; None for file-owned.
        content_hash: Hash of a file-owned revision; None for graph-owned.
        file_version_source_id: file_version Source of a file-owned revision.
        sources: Sources it cites.
    """

    number: int
    actor: ActorDto
    created_at: datetime
    title: str
    body: str | None = None
    content_hash: str | None = None
    file_version_source_id: str | None = None
    sources: tuple[SourceDto, ...] = ()


class SupersededByDto(BaseDto):
    """The accepted `supersedes` assertion that targets a record.

    Attributes:
        assertion_id: The `supersedes` assertion.
        record_id: Its subject, the successor.
    """

    assertion_id: str
    record_id: str


class AssertionEndpointDto(BaseDto):
    """One end of an assertion and the revision judged.

    Attributes:
        id: Record id.
        at_revision: Revision judged; None for types without revisions.
    """

    id: str
    at_revision: int | None = None


class RecordDto(BaseDto):
    """Any record by id. Fields that do not apply to the type stay None.

    Attributes:
        id: Record id.
        type: `knowledge`, `experience`, `source`, `project`, ...
        space_id: Owning space.
        project_id: Project the record belongs to, when any.
        subtype: Knowledge or experience subtype.
        status: Knowledge or assertion status.
        ownership: `file` or `graph` (knowledge).
        head_revision: Head revision number (knowledge).
        applicability: Project and tags (knowledge).
        actor: Who recorded it (experience).
        revision: The requested revision's content; the head by default (knowledge).
        sources: Sources of the content shown.
        key: Project key.
        name: Project name.
        body: Experience text.
        occurred_at: When an experience happened.
        session: Experience session.
        environment: Experience environment.
        source_kind: Kind of a Source record.
        locator: Locator of a Source record.
        digest: Digest of a Source record.
        effective_status: Derived status (knowledge, assertion): `superseded` when an accepted
            `supersedes` assertion targets it.
        superseded_by: That assertion and its subject, or None.
        predicate: Assertion predicate.
        subject: Assertion subject and the revision judged.
        object: Assertion object and the revision judged.
        evidence_ids: Assertion evidence ids.
        rationale: Why the assertion holds.
        created_at: When the record was created.
        updated_at: When it last changed.
    """

    id: str
    type: str
    space_id: str
    project_id: str | None = None
    subtype: str | None = None
    status: str | None = None
    ownership: str | None = None
    head_revision: int | None = None
    applicability: ApplicabilityDto | None = None
    actor: ActorDto | None = None
    revision: RevisionDto | None = None
    sources: tuple[SourceDto, ...] = ()
    key: str | None = None
    name: str | None = None
    body: str | None = None
    occurred_at: datetime | None = None
    session: str | None = None
    environment: str | None = None
    source_kind: str | None = None
    locator: str | None = None
    digest: str | None = None
    effective_status: str | None = None
    superseded_by: SupersededByDto | None = None
    predicate: str | None = None
    subject: AssertionEndpointDto | None = None
    object: AssertionEndpointDto | None = None
    evidence_ids: tuple[str, ...] = ()
    rationale: str | None = None
    created_at: datetime
    updated_at: datetime
