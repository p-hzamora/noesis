"""Wires the vault import: interop's handlers over Knowledge's inbound adapter.

Interop never imports Knowledge; this is the one place that hands Knowledge's
`KnowledgeImporterAdapter` to interop as its `IKnowledgeImporter`. The importer is built with
the supersession proposer over C4's `assertion propose`, so an accepted record whose note
changed gets a new proposal linked to it by a proposed `supersedes` assertion.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from noesis.bounded_context.interop.application.handlers import (
    ImportFileHandler,
    PlanVaultImportHandler,
    RunVaultImportHandler,
)
from noesis.bounded_context.interop.domain.value_objects import ImportActor
from noesis.bounded_context.interop.infrastructure.outbound import (
    FilesystemFileReaderAdapter,
    FilesystemVaultReaderAdapter,
    YamlHeaderParserAdapter,
)
from noesis.bounded_context.knowledge.application.handlers.commands.import_knowledge_handler import (
    ImportKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.propose_assertion_handler import (
    ProposeAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.replace_link_set_handler import (
    ReplaceLinkSetHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.assess_import_knowledge_handler import (
    AssessImportKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.assess_link_set_handler import (
    AssessLinkSetHandler,
)
from noesis.bounded_context.knowledge.application.services.assertion_supersession_proposer import (
    AssertionSupersessionProposer,
)
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CORE_STEP,
    LINKS_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.import_contracts import (
    KnowledgeImporterAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence import (
    KnowledgePersistence,
    Neo4jImportCandidateReadRepositoryAdapter,
    build_knowledge_persistence,
)
from noesis.core import Environment
from noesis.exceptions import VaultNotConfiguredError
from noesis.interfaces.cli.actor import resolve_actor
from noesis.interfaces.cli.bootstrap.knowledge_handlers_builder import EXTRA_SCHEMA_STEPS
from noesis.shared_kernel.infrastructure.outbound.clock import SystemClockAdapter
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient


@dataclass(frozen=True, slots=True, kw_only=True)
class VaultImportHandlers:
    """The `import run` actions of one invocation.

    Attributes:
        plan: Preview (assess only).
        run: Apply.
    """

    plan: PlanVaultImportHandler
    run: RunVaultImportHandler


def _importer(client: Neo4jClient) -> KnowledgeImporterAdapter:
    """Knowledge's inbound adapter over `client`; opens no connection."""
    clock = SystemClockAdapter()
    persistence: KnowledgePersistence = build_knowledge_persistence(
        client, clock=clock, extra_steps=EXTRA_SCHEMA_STEPS
    )
    candidates = Neo4jImportCandidateReadRepositoryAdapter(client)
    proposer = AssertionSupersessionProposer(
        uow_factory=persistence.uow_factory,
        propose=ProposeAssertionHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
        ),
    )
    return KnowledgeImporterAdapter(
        link_replacer=ReplaceLinkSetHandler(uow_factory=persistence.uow_factory, clock=clock),
        link_assessor=AssessLinkSetHandler(uow_factory=persistence.uow_factory, clock=clock),
        importer=ImportKnowledgeHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
            candidates=candidates,
            proposer=proposer,
        ),
        assessor=AssessImportKnowledgeHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
            candidates=candidates,
            can_link_successor=True,
        ),
    )


def _actor(environment: Environment) -> ImportActor:
    actor = resolve_actor(environment.identity)
    return ImportActor(kind=actor.kind.value, name=actor.name, session=actor.session)


def require_vault_dir(environment: Environment) -> Path:
    """The vault folder to import from.

    Raises:
        VaultNotConfiguredError: `NOESIS_VAULT_DIR` is not set.
    """
    vault: Path | None = environment.vault_import.vault_dir
    if vault is None:
        raise VaultNotConfiguredError(
            "No vault folder is configured.",
            {"setting": "NOESIS_VAULT_DIR"},
            next_steps=["Set NOESIS_VAULT_DIR to the folder to import."],
        )
    return vault


@asynccontextmanager
async def open_vault_import(
    environment: Environment, *, apply: bool = False
) -> AsyncIterator[VaultImportHandlers]:
    """The `import run` handlers over a client that is closed when the block ends.

    Settings are checked before the client is built, so a missing folder or a bad key never
    reaches the store.

    Raises:
        VaultNotConfiguredError: `NOESIS_VAULT_DIR` is not set.
        InvalidConfigurationError: The vault key is invalid, or the Neo4j password is not set.
    """
    vault: Path = require_vault_dir(environment)
    vault_key: str = environment.vault_import.resolve_vault_key()
    connection = environment.knowledge.neo4j_connection()
    async with Neo4jClient(connection) as client:
        if apply:
            persistence = build_knowledge_persistence(
                client, clock=SystemClockAdapter(), extra_steps=EXTRA_SCHEMA_STEPS
            )
            await require_steps(persistence.schema, CORE_STEP, LINKS_STEP)
        importer: KnowledgeImporterAdapter = _importer(client)
        space_key: str = environment.knowledge.knowledge_space
        actor: ImportActor = _actor(environment)
        parser = YamlHeaderParserAdapter()
        reader = FilesystemVaultReaderAdapter(vault)
        yield VaultImportHandlers(
            plan=PlanVaultImportHandler(
                vault=reader,
                header_parser=parser,
                importer=importer,
                vault_key=vault_key,
                space_key=space_key,
                actor=actor,
            ),
            run=RunVaultImportHandler(
                vault=reader,
                header_parser=parser,
                importer=importer,
                vault_key=vault_key,
                space_key=space_key,
                actor=actor,
            ),
        )


@asynccontextmanager
async def open_file_import(environment: Environment) -> AsyncIterator[ImportFileHandler]:
    """The `import file` handler over a client that is closed when the block ends.

    Raises:
        InvalidConfigurationError: The Neo4j password is not set.
    """
    connection = environment.knowledge.neo4j_connection()
    async with Neo4jClient(connection) as client:
        yield ImportFileHandler(
            files=FilesystemFileReaderAdapter(),
            header_parser=YamlHeaderParserAdapter(),
            importer=_importer(client),
            space_key=environment.knowledge.knowledge_space,
            actor=_actor(environment),
        )
