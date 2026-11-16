"""Loading corpora into a testcontainers Neo4j through C2's capture handlers (graph-owned text)."""

import random
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta

from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv, make_neo4j_env
from tests.support.knowledge_support import AGENT, DEFAULT_SPACE_KEY
from tests.support.retrieval.status_writer import set_status

from noesis.bounded_context.knowledge.application.handlers.commands.capture_experience_handler import (
    CaptureExperienceCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
    InitialiseStoreCommand,
)
from noesis.bounded_context.knowledge.application.services.inputs import (
    NewSourceInput,
    ProjectRef,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    ExperienceSubtypeEnum,
    Key,
    Slug,
    SourceKindEnum,
)
from noesis.interfaces.cli.bootstrap.retrieval_handlers_builder import RETRIEVAL_SCHEMA_STEPS
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

from .fixtures import FixtureRecord


@dataclass(slots=True)
class LoadResult:
    """Fixture key to record id, and how long creating the records took."""

    ids: dict[str, str] = field(default_factory=dict)
    capture_seconds: list[float] = field(default_factory=list)
    status_seconds: list[float] = field(default_factory=list)
    total_seconds: float = 0.0


async def open_env(settings: Neo4jConnectionSettings) -> Neo4jKnowledgeEnv:
    """Handlers over a fresh container after `store init`, with C5a's schema steps registered."""
    env = make_neo4j_env(settings, extra_steps=RETRIEVAL_SCHEMA_STEPS)
    await env.initialise_store.handle(InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY))
    return env


async def capture(env: Neo4jKnowledgeEnv, record: FixtureRecord) -> str:
    """Create one graph-owned record through the capture handlers; returns its id."""
    project = ProjectRef(key=Key(value=record.project)) if record.project else None
    sources = (NewSourceInput(kind=SourceKindEnum.COMMIT, locator=record.source_locator),)
    if record.kind == "knowledge":
        knowledge = await env.capture_knowledge.handle(
            CaptureKnowledgeCommand(
                idempotency_key=f"spike-{record.key}",
                space_key=DEFAULT_SPACE_KEY,
                title=record.title or record.key,
                body=record.body,
                subtype=Slug(value=record.subtype),
                actor=AGENT,
                project=project,
                sources=sources,
            )
        )
        return knowledge.record_id
    experience = await env.capture_experience.handle(
        CaptureExperienceCommand(
            idempotency_key=f"spike-{record.key}",
            space_key=DEFAULT_SPACE_KEY,
            subtype=ExperienceSubtypeEnum(record.subtype),
            body=record.body,
            actor=AGENT,
            project=project,
            sources=sources,
        )
    )
    return experience.record_id


async def load_records(
    env: Neo4jKnowledgeEnv,
    space_id: str,
    records: Sequence[FixtureRecord],
    *,
    status_share: float = 1.0,
    seed: int = 11,
) -> LoadResult:
    """Capture every record, then move knowledge to its target status with the test status writer.

    Capture always starts `proposed`; `accepted` and `superseded` are set through the test-only
    writer (C4 is not built). `status_share` limits how many non-proposed statuses are written.
    """
    result = LoadResult()
    rng = random.Random(seed)  # noqa: S311  # fixture sampling, not security
    started = time.monotonic()
    for record in records:
        env.clock.current += timedelta(seconds=1)
        began = time.monotonic()
        result.ids[record.key] = await capture(env, record)
        result.capture_seconds.append(time.monotonic() - began)
    for record in records:
        if record.status in (None, "proposed") or rng.random() > status_share:
            continue
        began = time.monotonic()
        await set_status(
            env.client,
            space_id=space_id,
            record_id=result.ids[record.key],
            status=record.status,
            occurred_at=env.clock.now(),
        )
        result.status_seconds.append(time.monotonic() - began)
    result.total_seconds = time.monotonic() - started
    return result


_EN_SUBJECTS = (
    "the ledger exporter",
    "the session gateway",
    "the image resizer",
    "the audit trail writer",
    "the quota service",
    "the report scheduler",
    "the search indexer",
    "the mail dispatcher",
    "the cache warmer",
    "the permission checker",
    "the invoice renderer",
    "the sync agent",
    "the metrics collector",
    "the export wizard",
    "the config loader",
    "the upload handler",
    "the billing reconciler",
    "the tenant provisioner",
    "the feed aggregator",
    "the churn model",
)
_EN_PROBLEMS = (
    "leaks file handles under sustained load",
    "returns stale rows right after a deploy",
    "doubles its memory use on large batches",
    "stalls when the upstream answers slowly",
    "drops messages that arrive out of order",
    "logs the same warning thousands of times",
    "fails on names with accented characters",
    "takes a coarse lock that serialises workers",
    "ignores the configured timeout",
    "crashes when the input file is empty",
    "reads configuration only at start up",
    "uses the wrong unit for durations",
)
_EN_ACTIONS = (
    "Add a bounded retry and log the attempt number",
    "Move the work into a background job",
    "Validate the input at the boundary and fail early",
    "Cache the result for a short, fixed time",
    "Split the batch into smaller chunks",
    "Write a regression test before the fix",
    "Expose the setting as an environment variable",
    "Replace the global lock with a per-key lock",
    "Document the limit in the runbook",
    "Prefer a streaming read over loading everything",
)
_ES_SUBJECTS = (
    "el exportador de libros",
    "la pasarela de sesiones",
    "el redimensionador de imágenes",
    "el registro de auditoría",
    "el servicio de cuotas",
    "el planificador de informes",
    "el indexador de búsqueda",
    "el despachador de correo",
    "el calentador de caché",
    "el comprobador de permisos",
    "el generador de facturas",
    "el agente de sincronización",
    "el recolector de métricas",
    "el asistente de exportación",
    "el cargador de configuración",
    "el gestor de subidas",
    "el conciliador de cobros",
    "el aprovisionador de inquilinos",
    "el agregador de novedades",
    "el modelo de abandono",
)
_ES_PROBLEMS = (
    "pierde manejadores de archivo bajo carga sostenida",
    "devuelve filas antiguas justo tras un despliegue",
    "duplica la memoria con lotes grandes",
    "se queda parado cuando el origen responde despacio",
    "pierde mensajes que llegan desordenados",
    "repite el mismo aviso miles de veces",
    "falla con nombres que llevan tildes",
    "toma un bloqueo grueso que serializa a los trabajadores",
    "ignora el tiempo máximo configurado",
    "se cae cuando el archivo de entrada está vacío",
    "lee la configuración solo al arrancar",
    "usa la unidad equivocada para las duraciones",
)
_ES_ACTIONS = (
    "Añadir un reintento acotado y registrar el número de intento",
    "Mover el trabajo a una tarea en segundo plano",
    "Validar la entrada en el borde y fallar pronto",
    "Guardar el resultado en caché durante un tiempo corto y fijo",
    "Dividir el lote en trozos más pequeños",
    "Escribir una prueba de regresión antes de arreglarlo",
    "Exponer el ajuste como variable de entorno",
    "Sustituir el bloqueo global por uno por clave",
    "Documentar el límite en el manual de operación",
    "Preferir una lectura en flujo a cargarlo todo",
)


def generate_records(count: int, *, seed: int = 7, projects: int = 60) -> list[FixtureRecord]:
    """`count` synthetic graph-owned records for the scale run (half Spanish, 20% experiences).

    Every record names a unique component token (`svc-0042`), so the corpus is volume and noise,
    not judged content. Projects are `scale-00..`; one in twelve is space-wide.
    """
    rng = random.Random(seed)  # noqa: S311  # deterministic corpus, not security
    records: list[FixtureRecord] = []
    for index in range(count):
        spanish = index % 2 == 1
        subjects, problems, actions = (
            (_ES_SUBJECTS, _ES_PROBLEMS, _ES_ACTIONS)
            if spanish
            else (_EN_SUBJECTS, _EN_PROBLEMS, _EN_ACTIONS)
        )
        subject, problem, action = rng.choice(subjects), rng.choice(problems), rng.choice(actions)
        token = f"svc-{index:04d}"
        is_experience = index % 5 == 4
        sentence = (
            f"{subject.capitalize()} {problem} (componente {token})."
            if spanish
            else (f"{subject.capitalize()} {problem} (component {token}).")
        )
        body = f"{sentence} {action}."
        records.append(
            FixtureRecord(
                key=f"X{index:04d}",
                cluster="scale",
                kind="experience" if is_experience else "knowledge",
                subtype=rng.choice(("observation", "outcome", "failure"))
                if is_experience
                else rng.choice(("decision", "convention", "gotcha")),
                status=None
                if is_experience
                else rng.choice(("accepted", "proposed", "superseded")),
                project=None if index % 12 == 0 else f"scale-{rng.randrange(projects):02d}",
                lang="es" if spanish else "en",
                title=None if is_experience else f"{subject.capitalize()} {token}",
                body=body,
                source_locator=f"{index:040x}",
            )
        )
    return records
