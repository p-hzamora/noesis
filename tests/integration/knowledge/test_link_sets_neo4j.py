"""Backfill, concurrent link writers and origin isolation over a testcontainer."""

import asyncio
import shutil
from pathlib import Path

import pytest
from tests.support.import_support import K1, K2, K3, K6, file_snapshot, graph_digest, graph_session
from tests.support.interop_support import ACTOR
from tests.support.noesis_process_support import run_noesis, store_environment

from noesis.bounded_context.interop.application.handlers import (
    RunVaultImportCommand,
    RunVaultImportHandler,
)
from noesis.bounded_context.interop.infrastructure.outbound import (
    FilesystemVaultReaderAdapter,
    YamlHeaderParserAdapter,
)
from noesis.exceptions import GraphStoreBusyError
from noesis.interfaces.cli.bootstrap.import_handlers_builder import _importer
from noesis.shared_kernel.contracts.knowledge import ImportActorContract
from noesis.shared_kernel.contracts.knowledge.import_link_set_contract import (
    ImportLinkContract,
    ImportLinkSetOutcomeContract,
    ImportLinkSetRequestContract,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]


@pytest.fixture
def link_store(tmp_path, neo4j_settings):
    root = tmp_path / "vault"
    shutil.copytree(Path(__file__).parents[2] / "fixtures/vault_links", root)
    env = store_environment(
        tmp_path / "child",
        "personal",
        neo4j_settings,
        NOESIS_VAULT_DIR=str(root),
        NOESIS_IMPORT_VAULT_KEY="links",
    )
    assert run_noesis(["store", "init"], env).code == 0
    return root, env


def runner(root, importer):
    return RunVaultImportHandler(
        vault=FilesystemVaultReaderAdapter(root),
        header_parser=YamlHeaderParserAdapter(),
        importer=importer,
        vault_key="links",
        space_key="personal",
        actor=ACTOR,
    )


def request(source=K1, target=K2, count=1, origin="origin:migrated"):
    return ImportLinkSetRequestContract(
        space_key="personal",
        source_record_id=source,
        origin_tag=origin,
        links=(ImportLinkContract(target_record_id=target, link_type="links_to", count=count),),
        actor=ImportActorContract(kind="user", name="tester"),
    )


async def test_backfill_no_record_changes_or_retrieval_work(link_store, neo4j_settings):
    root, env = link_store
    async with Neo4jClient(neo4j_settings) as client:
        real = _importer(client)

        class WithoutLinks:
            assess = real.assess
            apply = real.apply

            async def assess_links(self, request):
                return ImportLinkSetOutcomeContract(
                    outcome="unchanged", source_record_id=request.source_record_id, edges=0
                )

            replace_links = assess_links

        snapshot = file_snapshot(root)
        first = await runner(root, WithoutLinks()).handle(RunVaultImportCommand())
        assert first.totals.created == 8
        with graph_session(neo4j_settings) as session:
            assert session.run("MATCH (n:LinkSet) RETURN count(n) AS n").single()["n"] == 0
        # Index the record pass before backfilling; link-only work must not enqueue revisions.
        sync = run_noesis(["index", "sync"], env)
        assert sync.code == 0, sync.stdout
        second = await runner(root, real).handle(RunVaultImportCommand())
        assert second.totals.unchanged == 8 and second.link_sets["created"] == 4
        assert file_snapshot(root) == snapshot
        with graph_session(neo4j_settings) as session:
            assert session.run("MATCH (n:Change) RETURN count(n) AS n").single()["n"] == 8
            digest = graph_digest(session)
            await runner(root, real).handle(RunVaultImportCommand())
            assert graph_digest(session) == digest
        sync = run_noesis(["index", "sync"], env)
        assert sync.code == 0, sync.stdout
        assert all(item["applied"] == 0 for item in sync.result["projections"])


@pytest.mark.parametrize("same", [True, False])
@pytest.mark.parametrize("existing", [True, False])
async def test_parallel_same_source_serializes_versions(link_store, neo4j_settings, same, existing):
    _root, env = link_store
    assert run_noesis(["import", "run", "--yes"], env).code == 0
    async with Neo4jClient(neo4j_settings) as client:
        adapter = _importer(client)
        source = K1 if existing else K6
        first = request(source=source, count=2)
        second = first if same else request(source=source, count=3)
        results = await asyncio.gather(adapter.replace_links(first), adapter.replace_links(second))
        with graph_session(neo4j_settings) as session:
            assert session.run(
                "MATCH (s:LinkSet {source_record_id: $id}) RETURN s.version AS v", id=source
            ).single()["v"] == (int(existing) + (1 if same else 2))
            rows = session.run(
                "MATCH (:Knowledge {id: $id})-[r:LINKS_TO|EMBEDS]->() RETURN r.count AS count",
                id=source,
            ).data()
            assert len(rows) == 1 and rows[0]["count"] in ({2} if same else {2, 3})
        assert sum(result.outcome in {"created", "replaced"} for result in results) == (
            1 if same else 2
        )


async def test_overlapping_targets_rerun_converges_and_other_origins_survive(
    link_store, neo4j_settings
):
    _root, env = link_store
    assert run_noesis(["import", "run", "--yes"], env).code == 0
    async with Neo4jClient(neo4j_settings) as client:
        adapter = _importer(client)
        # Another origin's edge is written through the sole edge-owning adapter too.
        await adapter.replace_links(request(origin="origin:other"))
        tasks = [request(source=K1, target=K3), request(source=K2, target=K3)]
        answers = await asyncio.gather(
            *(adapter.replace_links(item) for item in tasks), return_exceptions=True
        )
        assert all(
            not isinstance(answer, BaseException) or isinstance(answer, GraphStoreBusyError)
            for answer in answers
        )
        for item in tasks:
            await adapter.replace_links(item)
        with graph_session(neo4j_settings) as session:
            rows = session.run(
                "MATCH (:Knowledge {id: $source})-[r:LINKS_TO]->(t) RETURN r.origin AS origin, t.id AS target",
                source=K1,
            ).data()
            assert {tuple(row.values()) for row in rows} == {("other", K2), ("migrated", K3)}
