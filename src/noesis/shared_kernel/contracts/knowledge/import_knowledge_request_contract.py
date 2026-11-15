"""What the vault import hands to Knowledge about one note or file (JSON-native, versioned)."""

from typing import Literal

from noesis.utils import FrozenObject

IMPORT_KNOWLEDGE_CONTRACT_VERSION: Literal[1] = 1


class ImportActorContract(FrozenObject):
    """Who runs the import.

    Attributes:
        kind: `user` or `agent`.
        name: Display name.
        session: Harness session id, when known.
    """

    kind: str
    name: str
    session: str | None = None


class ImportHeaderSourceContract(FrozenObject):
    """An extra Source a note's header cites.

    Attributes:
        kind: A Knowledge Source kind other than `file_version`.
        locator: Where to find it.
    """

    kind: str
    locator: str


class ImportKnowledgeRequestContract(FrozenObject):
    """Version 1 of the request to import one note or file as a graph-owned record.

    Attributes:
        contract_version: Schema version of this payload.
        space_key: Active space key.
        record_id: The note's ULID; None for a note without one and always for `import file`.
        origin_tag: `origin:migrated` or `origin:imported`; added to the record's tags and used
            by the rerun lookup.
        title: Mapped title, not redacted.
        body: Normalised body, not redacted, not blank.
        subtype: Subtype slug.
        project_key: Project key; None means space-wide.
        tags: Tags without the origin tag, sorted and de-duplicated.
        source_locator: `vault://<vault_key>/<relative path>` or the resolved absolute path.
        source_digest: `sha256:<hex>` of the raw file bytes.
        header_sources: Extra Sources from the note's header, in header order, de-duplicated.
        actor: Who runs the import.
        on_change: `report` or `update`.
    """

    contract_version: Literal[1] = IMPORT_KNOWLEDGE_CONTRACT_VERSION
    space_key: str
    record_id: str | None = None
    origin_tag: str
    title: str
    body: str
    subtype: str
    project_key: str | None = None
    tags: tuple[str, ...] = ()
    source_locator: str
    source_digest: str
    header_sources: tuple[ImportHeaderSourceContract, ...] = ()
    actor: ImportActorContract
    on_change: str
