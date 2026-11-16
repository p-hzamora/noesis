"""Optional C3b timing harness; copy an explicitly supplied vault to a testcontainer."""

import json
import shutil
import time
from unittest.mock import AsyncMock

import pytest
from tests.support.import_support import file_snapshot
from tests.support.interop_support import ACTOR
from tests.support.neo4j_container import wipe_database
from tests.support.noesis_process_support import run_noesis, store_environment

from noesis.bounded_context.interop.application.handlers import (
    RunVaultImportCommand,
    RunVaultImportHandler,
)
from noesis.bounded_context.interop.infrastructure.outbound import (
    FilesystemVaultReaderAdapter,
    YamlHeaderParserAdapter,
)
from noesis.interfaces.cli.bootstrap.import_handlers_builder import _importer
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

pytestmark = [pytest.mark.measurement, pytest.mark.integration, pytest.mark.neo4j]


async def test_measure_link_pass_delta(
    vault_source, tmp_path, neo4j_settings, record_property, monkeypatch
):
    """Measure first apply and unchanged rerun, with and without link writes."""
    before = file_snapshot(vault_source)
    root = tmp_path / "vault"
    shutil.copytree(vault_source, root, symlinks=True)
    snapshot = file_snapshot(root)
    timings: dict[str, list[float]] = {}
    for mode in ("without_links", "with_links"):
        wipe_database(neo4j_settings)
        env = store_environment(tmp_path / mode, "personal", neo4j_settings)
        assert run_noesis(["store", "init"], env).code == 0
        async with Neo4jClient(neo4j_settings) as client:
            real = _importer(client)

            handler = RunVaultImportHandler(
                vault=FilesystemVaultReaderAdapter(root),
                header_parser=YamlHeaderParserAdapter(),
                importer=real,
                vault_key="measurement",
                space_key="personal",
                actor=ACTOR,
            )
            durations = []
            with monkeypatch.context() as patch:
                if mode == "without_links":
                    patch.setattr(handler._pipeline, "_links", AsyncMock())
                    patch.setattr(
                        "noesis.bounded_context.interop.domain.services.link_parser.LinkParser.parse",
                        lambda self, body: (),
                    )
                for _ in range(2):
                    started = time.perf_counter()
                    await handler.handle(RunVaultImportCommand())
                    durations.append(time.perf_counter() - started)
            timings[mode] = durations
    deltas = [
        with_links - without
        for with_links, without in zip(timings["with_links"], timings["without_links"], strict=True)
    ]
    report = {
        "seconds": timings,
        "delta_first_apply": deltas[0],
        "delta_unchanged": deltas[1],
        "budgets_seconds": [5, 2],
    }
    record_property("link_measurement", json.dumps(report))
    (tmp_path / "link-measurement.json").write_text(json.dumps(report, indent=2))
    assert file_snapshot(vault_source) == before and file_snapshot(root) == snapshot
