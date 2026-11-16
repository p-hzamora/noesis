"""`noesis` with a spike arm's projection registered (spike only, D-025).

Run as `python scripts/retrieval_spike/launcher.py <noesis arguments>` with `SPIKE_ARM` set. It
replaces `registered_projections` with the arm's `registered`, then runs the CLI. Arm L needs no
launcher (production wiring registers nothing). Arms A1, A2 and B are implemented
(`vectra_arm.py`, `neo4j_vector_arm.py`); `staged.py` drives them in short stages.
"""

import os
import sys
from pathlib import Path
from typing import Final

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
for _entry in (REPOSITORY_ROOT / "src", REPOSITORY_ROOT):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


def main() -> None:
    """Swap in the arm's registry, then run the CLI with this process's arguments."""
    from scripts.retrieval_spike.arms import ARMS

    from noesis.core import Environment
    from noesis.interfaces.cli.app import main as noesis_main
    from noesis.interfaces.cli.bootstrap import retrieval_handlers_builder as builder
    from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

    arm = ARMS[os.environ["SPIKE_ARM"]]

    def registry(client: Neo4jClient, environment: Environment) -> builder.RegisteredProjections:
        return arm.registered(client, environment) or builder.RegisteredProjections(
            writers=(), candidate_sources=()
        )

    builder.registered_projections = registry
    noesis_main()


if __name__ == "__main__":
    main()
