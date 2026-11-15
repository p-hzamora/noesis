"""`noesis record` and `noesis store` output."""

from datetime import datetime

from pydantic import AliasChoices, Field, computed_field

from noesis.utils import FrozenObject

from .i_renderable_response import IRenderableResponse


class RecordCaptureResponse(IRenderableResponse):
    """`noesis record capture`: the record created, or the one an identical earlier call created.

    Attributes:
        record_id: The record's id.
        record_type: `knowledge` or `experience`.
        revision: Head revision (knowledge); None for an experience.
        status: `proposed` (knowledge); None for an experience.
        space_id: Space it lives in.
        project_id: Its project, when any.
        replayed: True when the idempotency key was already used and nothing was written.
    """

    record_id: str
    record_type: str
    revision: int | None = None
    status: str | None = None
    space_id: str
    project_id: str | None = None
    replayed: bool = False

    def render(self) -> str:
        head: str = f"{self.record_type} {self.record_id}"
        if self.revision is not None:
            head += f" revision {self.revision} ({self.status})"
        note: str = " (replayed: nothing written)" if self.replayed else ""
        return f"captured {head}{note}"


class RecordReviseResponse(IRenderableResponse):
    """`noesis record revise`: the new head revision.

    Attributes:
        record_id: The revised record.
        revision: The new head revision number.
        status: Status of the record.
        space_id: Space it lives in.
        replayed: True when the idempotency key was already used and nothing was written.
    """

    record_id: str
    revision: int
    status: str
    space_id: str
    replayed: bool = False

    def render(self) -> str:
        note: str = " (replayed: nothing written)" if self.replayed else ""
        return f"revised {self.record_id} to revision {self.revision} ({self.status}){note}"


class RecordActorResponse(FrozenObject):
    """Who acted.

    Attributes:
        kind: `user` or `agent`.
        name: Display name.
        session: Harness session id, when known.
    """

    kind: str
    name: str
    session: str | None = None


class RecordApplicabilityResponse(FrozenObject):
    """Where a record applies.

    Attributes:
        project_id: Project id; None means space-wide.
        tags: Tags, sorted.
    """

    project_id: str | None = None
    tags: tuple[str, ...] = ()


class RecordSourceResponse(FrozenObject):
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


class RecordRevisionResponse(FrozenObject):
    """One revision of a knowledge record.

    Attributes:
        number: Revision number.
        actor: Who made it.
        created_at: When.
        title: Title.
        body: Text of a graph-owned revision.
        content_hash: Hash of a file-owned revision.
        file_version_source_id: file_version Source of a file-owned revision.
        sources: Sources it cites.
    """

    number: int
    actor: RecordActorResponse
    created_at: datetime
    title: str
    body: str | None = None
    content_hash: str | None = None
    file_version_source_id: str | None = None
    sources: tuple[RecordSourceResponse, ...] = ()


class RecordSupersededByResponse(FrozenObject):
    """The accepted `supersedes` assertion that targets a record.

    Attributes:
        assertion_id: The `supersedes` assertion.
        record_id: Its subject, the successor.
    """

    assertion_id: str
    record_id: str


class RecordEndpointResponse(FrozenObject):
    """One end of an assertion.

    Attributes:
        id: Record id.
        at_revision: Revision judged; None for types without revisions.
    """

    id: str
    at_revision: int | None = None


class RecordResponse(IRenderableResponse):
    """`noesis record get`: a record with the content of one revision.

    Fields that do not apply to the record's type stay null.

    Attributes:
        id: Record id.
        type: `knowledge`, `experience`, `source`, `project`, ...
        space_id: Owning space.
        project_id: Project the record belongs to, when any.
        subtype: Knowledge or experience subtype.
        status: Knowledge status.
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
        effective_status: Derived status (knowledge, assertion): `superseded` once an accepted
            `supersedes` assertion targets it, whatever `status` says.
        superseded_by: That assertion and its subject, or None.
        predicate: Assertion predicate.
        subject: Assertion subject and the revision judged.
        object: Assertion object and the revision judged.
        evidence: Assertion evidence record ids.
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
    applicability: RecordApplicabilityResponse | None = None
    actor: RecordActorResponse | None = None
    revision: RecordRevisionResponse | None = None
    sources: tuple[RecordSourceResponse, ...] = ()
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
    superseded_by: RecordSupersededByResponse | None = None
    predicate: str | None = None
    subject: RecordEndpointResponse | None = None
    object: RecordEndpointResponse | None = None
    evidence: tuple[str, ...] | None = Field(
        default=None, validation_alias=AliasChoices("evidence", "evidence_ids")
    )
    rationale: str | None = None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def space(self) -> str | None:
        """The space of an assertion (the documented assertion shape); null for other types."""
        return self.space_id if self.type == "assertion" else None

    def render(self) -> str:
        lines: list[str] = [f"{self.type} {self.id}"]
        for label, value in (
            ("subtype", self.subtype),
            ("status", self.status),
            ("effective status", self.effective_status),
            ("ownership", self.ownership),
            ("head revision", self.head_revision),
            ("space", self.space_id),
            ("project", self.project_id),
            ("key", self.key),
            ("name", self.name),
            ("occurred", self.occurred_at),
            ("session", self.session),
            ("environment", self.environment),
            ("source", f"{self.source_kind}:{self.locator}" if self.source_kind else None),
            ("predicate", self.predicate),
            ("subject", self.subject.id if self.subject else None),
            ("object", self.object.id if self.object else None),
            ("rationale", self.rationale),
        ):
            if value is not None:
                lines.append(f"{label}: {value}")
        if self.applicability is not None and self.applicability.tags:
            lines.append(f"tags: {', '.join(self.applicability.tags)}")
        if self.superseded_by is not None:
            lines.append(
                f"superseded by: {self.superseded_by.record_id} "
                f"(assertion {self.superseded_by.assertion_id})"
            )
        if self.actor is not None:
            lines.append(f"actor: {self.actor.kind} {self.actor.name}")
        if self.revision is not None:
            lines += [f"revision {self.revision.number}: {self.revision.title}"]
            if self.revision.body:
                lines += ["", self.revision.body]
        if self.body:
            lines += ["", self.body]
        lines += [
            f"source: {source.kind}:{source.locator} ({source.id})" for source in self.sources
        ]
        lines.append(f"created: {self.created_at.isoformat()}")
        return "\n".join(lines)


class StoreSpaceResponse(FrozenObject):
    """A knowledge space.

    Attributes:
        id: Space id.
        key: Space key.
        name: Display name.
        created: True when this call created it.
    """

    id: str
    key: str
    name: str
    created: bool


class StoreInitResponse(IRenderableResponse):
    """`noesis store init`: the schema steps applied and the default space.

    Attributes:
        applied_steps: Steps this call applied.
        already_applied_steps: Steps that were applied before.
        default_space: The configured default space.
    """

    applied_steps: tuple[str, ...]
    already_applied_steps: tuple[str, ...]
    default_space: StoreSpaceResponse

    def render(self) -> str:
        space: StoreSpaceResponse = self.default_space
        return "\n".join(
            [
                f"applied steps: {', '.join(self.applied_steps) or 'none'}",
                f"already applied: {', '.join(self.already_applied_steps) or 'none'}",
                f"default space: {space.key} ({'created' if space.created else 'exists'})",
            ]
        )
