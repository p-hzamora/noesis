"""AC-030 and the `20` edge: bodies reach Retrieval only through `IIndexableRecordReader`."""

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.knowledge_support import AGENT, NOW
from tests.support.retrieval.retrieval_neo4j_support import (
    capture_experience,
    capture_knowledge,
    revise_knowledge,
    space_id_of,
)

from noesis.bounded_context.knowledge.domain.entities import Knowledge, Source
from noesis.bounded_context.knowledge.domain.value_objects import (
    Applicability,
    ContentHash,
    FileContent,
    OwnershipEnum,
    Slug,
    SourceKindEnum,
    SpaceId,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_indexable_record_reader_adapter import (
    Neo4jIndexableRecordReaderAdapter,
)
from noesis.exceptions import RecordNotFoundError
from noesis.shared_kernel.contracts.knowledge.indexable_record_contract import (
    IndexableRecordContract,
    RecordBodyMissingError,
)

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]


async def test_ac030(env: Neo4jKnowledgeEnv) -> None:
    """Each requested revision carries its own title and body; an Experience has no title."""
    space_id: str = await space_id_of(env)
    knowledge_id: str = await capture_knowledge(env, "k", "t1", body="b1")
    await revise_knowledge(env, knowledge_id, "k-rev", expected=1, title="t2", body="b2")
    experience_id: str = await capture_experience(env, "e", "e1")
    reader = Neo4jIndexableRecordReaderAdapter(env.client)

    first = await reader.get(knowledge_id, 1, space_id=space_id)
    second = await reader.get(knowledge_id, 2, space_id=space_id)
    experience = await reader.get(experience_id, None, space_id=space_id)

    assert (first.title, first.body, first.revision, first.head_revision) == ("t1", "b1", 1, 2)
    assert (second.title, second.body, second.revision) == ("t2", "b2", 2)
    assert (experience.title, experience.body) == (None, "e1")


def test_ac030_the_contract_has_a_mandatory_body_and_no_file_fields() -> None:
    fields = IndexableRecordContract.model_fields

    assert fields["body"].annotation is str
    assert fields["body"].is_required()
    assert "content_hash" not in fields
    assert "file_locator" not in fields


async def test_a_file_owned_revision_has_no_body_and_is_not_served(env: Neo4jKnowledgeEnv) -> None:
    """C2's unused file-owned variant: the reader raises instead of inventing a body."""
    space_id: str = await space_id_of(env)
    version = Source.create(
        id=env.persistence.ids.new_record_id(),
        space_id=SpaceId(value=space_id),
        kind=SourceKindEnum.FILE_VERSION,
        locator="vault://main/decisions/neo4j.md",
        digest=None,
        now=NOW,
    )
    knowledge = Knowledge.create(
        id=env.persistence.ids.new_record_id(),
        space_id=SpaceId(value=space_id),
        ownership=OwnershipEnum.FILE,
        subtype=Slug(value="decision"),
        applicability=Applicability(),
        actor=AGENT,
        source_ids=(version.id,),
        content=FileContent(
            content_hash=ContentHash(value="sha256:" + "c" * 64),
            file_version_source_id=version.id,
            title="Use Neo4j",
        ),
        now=NOW,
    )
    async with env.uow() as uow:
        await uow.sources.add(version)
        await uow.knowledge.add(knowledge)
        await uow.commit()

    with pytest.raises(RecordBodyMissingError):
        await Neo4jIndexableRecordReaderAdapter(env.client).get(
            knowledge.id.value, 1, space_id=space_id
        )


async def test_a_missing_record_or_revision_raises_the_typed_not_found_error(
    env: Neo4jKnowledgeEnv,
) -> None:
    space_id: str = await space_id_of(env)
    knowledge_id: str = await capture_knowledge(env, "k", "t1", body="b1")
    reader = Neo4jIndexableRecordReaderAdapter(env.client)

    with pytest.raises(RecordNotFoundError) as raised:
        await reader.get(knowledge_id, 9, space_id=space_id)

    assert raised.value.error_code == "KNOWLEDGE_201_RECORD_NOT_FOUND"
    assert raised.value.metadata == {
        "record_id": knowledge_id,
        "revision": 9,
        "space_id": space_id,
    }
