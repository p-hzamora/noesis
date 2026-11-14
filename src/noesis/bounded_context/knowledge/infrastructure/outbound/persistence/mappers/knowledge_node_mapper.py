"""`Knowledge` <-> `:Record:Knowledge` node plus its head `:Revision` node.

A graph-owned revision stores `title` and `body`; a file-owned one stores `content_hash`,
`file_version_source_id` and `title`, and has no `body` property at all (AC-009).
"""

from noesis.bounded_context.knowledge.domain.entities import Knowledge
from noesis.bounded_context.knowledge.domain.value_objects import (
    Applicability,
    ContentHash,
    FileContent,
    GraphContent,
    OwnershipEnum,
    RecordId,
    RecordStatusEnum,
    Revision,
    RevisionContent,
    Slug,
    SpaceId,
    Tag,
)

from .actor_properties import to_actor, to_actor_properties
from .node_keys import revision_key
from .node_properties import NodeProperties, without_nulls


class KnowledgeNodeMapper:
    """Maps knowledge and its revisions to node properties and back."""

    @staticmethod
    def to_properties(knowledge: Knowledge) -> NodeProperties:
        """Properties of the `:Record:Knowledge` node (head number, never the text)."""
        project_id: RecordId | None = knowledge.applicability.project_id
        return without_nulls(
            {
                "id": knowledge.id.value,
                "space_id": knowledge.space_id.value,
                "ownership": knowledge.ownership.value,
                "subtype": knowledge.subtype.value,
                "status": knowledge.status.value,
                "head_revision": knowledge.head_number,
                "project_id": project_id.value if project_id else None,
                "tags": [tag.value for tag in knowledge.applicability.sorted_tags],
                "created_at": knowledge.created_at,
                "updated_at": knowledge.updated_at,
            }
        )

    @staticmethod
    def to_revision_properties(record_id: RecordId, revision: Revision) -> NodeProperties:
        """Properties of one `:Revision` node."""
        content: RevisionContent = revision.content
        shape: NodeProperties = (
            {"title": content.title, "body": content.body}
            if isinstance(content, GraphContent)
            else {
                "title": content.title,
                "content_hash": content.content_hash.value,
                "file_version_source_id": content.file_version_source_id.value,
            }
        )
        return without_nulls(
            {
                "revision_key": revision_key(record_id, revision.number),
                "record_id": record_id.value,
                "number": revision.number,
                "source_ids": [source_id.value for source_id in revision.source_ids],
                "created_at": revision.created_at,
                **to_actor_properties(revision.actor),
                **shape,
            }
        )

    @staticmethod
    def to_revision(node: NodeProperties) -> Revision:
        """The revision a `:Revision` node stores."""
        content: RevisionContent = (
            FileContent(
                content_hash=ContentHash(value=node["content_hash"]),
                file_version_source_id=RecordId(value=node["file_version_source_id"]),
                title=node["title"],
            )
            if "content_hash" in node
            else GraphContent(title=node["title"], body=node["body"])
        )
        return Revision(
            number=node["number"],
            actor=to_actor(node),
            source_ids=tuple(RecordId(value=source_id) for source_id in node["source_ids"]),
            created_at=node["created_at"],
            content=content,
        )

    @staticmethod
    def to_entity(node: NodeProperties, head: NodeProperties) -> Knowledge:
        """The knowledge a node and its head revision store (no pending events)."""
        project_id: str | None = node.get("project_id")
        return Knowledge(
            id=RecordId(value=node["id"]),
            space_id=SpaceId(value=node["space_id"]),
            ownership=OwnershipEnum(node["ownership"]),
            subtype=Slug(value=node["subtype"]),
            applicability=Applicability(
                project_id=RecordId(value=project_id) if project_id else None,
                tags=frozenset(Tag(value=tag) for tag in node.get("tags", [])),
            ),
            status=RecordStatusEnum(node["status"]),
            head=KnowledgeNodeMapper.to_revision(head),
            created_at=node["created_at"],
            updated_at=node["updated_at"],
        )
