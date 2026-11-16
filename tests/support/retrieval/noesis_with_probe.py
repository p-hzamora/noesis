"""`noesis` with the Neo4j `probe` projection registered (tests only, D-025).

Run as `python <this file> <noesis arguments>`. C5a's production wiring registers no projection,
so every subprocess scenario about sync, cursor, lock, rebuild races and kill-and-rerun starts the
CLI through this launcher: it replaces `retrieval_handlers_builder.registered_projections` with a
function that returns one `Neo4jProbeProjection` and the Neo4j cursor store, then calls the
`noesis` entry point. The per-upsert delay comes from `NOESIS_TEST_PROBE_DELAY_MS` (read here only,
default 0). Nothing under `src/` imports this module.
"""

import os
import sys
from pathlib import Path
from typing import Final

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DELAY_VARIABLE: Final[str] = "NOESIS_TEST_PROBE_DELAY_MS"

# the launcher's own folder is sys.path[0]; put this checkout's `tests` package and `src` first
for _entry in (REPOSITORY_ROOT / "src", REPOSITORY_ROOT):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


def main() -> None:
    """Swap in the probe registry, then run the CLI with this process's arguments."""
    from tests.support.retrieval.probe_projection import Neo4jProbeProjection

    from noesis.bounded_context.retrieval.infrastructure.outbound.persistence.neo4j_index_cursor_store_adapter import (
        Neo4jIndexCursorStoreAdapter,
    )
    from noesis.core import Environment
    from noesis.interfaces.cli.app import main as noesis_main
    from noesis.interfaces.cli.bootstrap import retrieval_handlers_builder
    from noesis.shared_kernel.infrastructure.outbound.clock import SystemClockAdapter
    from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

    delay_ms: int = int(os.environ.get(DELAY_VARIABLE, "0"))

    def probe_registry(
        client: Neo4jClient, environment: Environment
    ) -> retrieval_handlers_builder.RegisteredProjections:
        return retrieval_handlers_builder.RegisteredProjections(
            writers=(Neo4jProbeProjection(client, delay_ms=delay_ms),),
            candidate_sources=(),
            cursors=Neo4jIndexCursorStoreAdapter(client, SystemClockAdapter()),
        )

    retrieval_handlers_builder.registered_projections = probe_registry
    noesis_main()


if __name__ == "__main__":
    main()
