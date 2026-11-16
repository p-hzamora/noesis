"""The spike arms: L (no projection), A1 and A2 (Vectra, option A) and B (Neo4j vector index).

An arm that owns a projection returns it from `registered`, shaped as the registry's
`RegisteredProjections` (writers, candidate sources and, for option A, a local cursor store), so
the harness plugs it in exactly as C5b will (D-025): the in-process composition calls `registered`
directly and the CLI launcher (`launcher.py`) swaps it in for `registered_projections`.
Arm L registers nothing, so it runs through the production wiring unchanged. The other arms read
their working directory from `SPIKE_WORKDIR` (every process of a run shares it).
"""

import abc
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from noesis.core import Environment
from noesis.interfaces.cli.bootstrap.retrieval_handlers_builder import RegisteredProjections
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

from .neo4j_vector_arm import EmbedderProcess, Neo4jVectorKit, Neo4jVectorSource, Neo4jVectorWriter
from .vectra_arm import (
    FileCursorStore,
    FlushState,
    VectraCandidateSource,
    VectraIndexWriter,
    VectraSettings,
)

BGE: Final[str] = "BAAI/bge-small-en-v1.5"
MINILM: Final[str] = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIMENSION: Final[int] = 384


@dataclass(frozen=True, slots=True)
class ArmSpec:
    """What an arm is and what running it would need."""

    name: str
    description: str
    model_id: str | None
    store: str | None
    needs: str


class SpikeArm(abc.ABC):
    """One arm of the vector placement spike."""

    spec: ArmSpec

    @abc.abstractmethod
    def registered(
        self, client: Neo4jClient, environment: Environment
    ) -> RegisteredProjections | None:
        """The arm's projection and candidate source, or None when it owns none (arm L)."""


class LexicalGraphArm(SpikeArm):
    """Arm L: Knowledge's full-text index and graph expansion; no projection, cursor or sync."""

    spec = ArmSpec(
        name="L",
        description="lexical (knowledge_fulltext, standard analyser) and graph only",
        model_id=None,
        store=None,
        needs="nothing",
    )

    def registered(
        self, client: Neo4jClient, environment: Environment
    ) -> RegisteredProjections | None:
        """Arm L registers no projection."""
        return None


class VectraArm(SpikeArm):
    """Arms A1 and A2: one file per revision, `vectra sync`, `vectra search`."""

    def __init__(self, spec: ArmSpec) -> None:
        self.spec = spec
        self.flush: FlushState | None = None

    def settings(self) -> VectraSettings:
        """Vectra's settings under this run's working directory."""
        assert self.spec.model_id is not None  # noqa: S101
        return VectraSettings(
            workdir=Path(os.environ["SPIKE_WORKDIR"]) / "vectra-arm",
            model_id=self.spec.model_id,
            dimension=DIMENSION,
        )

    def registered(
        self, client: Neo4jClient, environment: Environment
    ) -> RegisteredProjections | None:
        """Writer, candidate source and the local cursor file."""
        settings = self.settings()
        settings.prepare()
        self.flush = FlushState(settings)
        return RegisteredProjections(
            writers=(VectraIndexWriter(self.flush),),
            candidate_sources=(VectraCandidateSource(settings),),
            cursors=FileCursorStore(self.flush),
        )


class Neo4jVectorArm(SpikeArm):
    """Arm B: `:IndexChunk` nodes with a Neo4j vector index and the multilingual model."""

    spec = ArmSpec(
        name="B",
        description="Neo4j vector index (cosine, 384) over :IndexChunk with the multilingual MiniLM; "
        "embedding in a resident helper of Vectra's interpreter",
        model_id=MINILM,
        store="Neo4j 5.26.33 community vector index in the test container",
        needs="the same cached model as A2; Vectra's interpreter as the embedding runtime",
    )

    def __init__(self) -> None:
        self.kit: Neo4jVectorKit | None = None

    def registered(
        self, client: Neo4jClient, environment: Environment
    ) -> RegisteredProjections | None:
        """Writer and candidate source over the process's client; the Neo4j cursor store."""
        embedder = EmbedderProcess(MINILM)
        writer = Neo4jVectorWriter(client, embedder, DIMENSION)
        source = Neo4jVectorSource(client, embedder, DIMENSION)
        self.kit = Neo4jVectorKit(embedder=embedder, writer=writer, source=source)
        return RegisteredProjections(writers=(writer,), candidate_sources=(source,))


ARMS: Final[dict[str, SpikeArm]] = {
    arm.spec.name: arm
    for arm in (
        LexicalGraphArm(),
        VectraArm(
            ArmSpec(
                name="A1",
                description="Vectra with its default BAAI/bge-small-en-v1.5; one .md per revision, "
                "`vectra sync`",
                model_id=BGE,
                store="Vectra/LanceDB under a temporary data dir",
                needs="model already cached; Vectra's own environment",
            )
        ),
        VectraArm(
            ArmSpec(
                name="A2",
                description="Vectra with paraphrase-multilingual-MiniLM-L12-v2; one .md per revision, "
                "`vectra sync`",
                model_id=MINILM,
                store="Vectra/LanceDB under a temporary data dir",
                needs="the approved 2026-11-15 download; Vectra's own environment",
            )
        ),
        Neo4jVectorArm(),
    )
}
