"""RegisterCatalogEntryHandler (FR-001, FR-002; AC-008 unit part, edge rows for names and prerequisites)."""

import pytest
from tests.support.catalog_support import (
    CATALOG_SOURCE,
    CLI_TOOL,
    MCP_SERVER,
    SKILL,
    CatalogEnv,
    make_catalog_env,
    racing_catalog_factory,
    register_command,
)
from tests.support.knowledge_support import AGENT, DEFAULT_SPACE_KEY, NOW

from noesis.bounded_context.knowledge.application.dtos import CatalogWriteResultDto
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.register_catalog_entry_handler import (
    RegisterCatalogEntryHandler,
)
from noesis.bounded_context.knowledge.domain.entities import CatalogEntry, KnowledgeSpace
from noesis.bounded_context.knowledge.domain.value_objects import Key
from noesis.bounded_context.knowledge.domain.value_objects.catalog_ref import CatalogRef
from noesis.exceptions import (
    CatalogEntryAlreadyExistsError,
    IdempotencyKeyReusedError,
    InvalidCatalogNameError,
    InvalidCatalogPrerequisiteError,
    SpaceNotFoundError,
    StoreNotInitialisedError,
)

pytestmark = pytest.mark.unit


def only_entry(env: CatalogEnv) -> CatalogEntry:
    (entry,) = env.catalog.entries.values()
    return entry


async def test_register_creates_revision_one_ledger_entry_and_the_result() -> None:
    env: CatalogEnv = await make_catalog_env()

    result: CatalogWriteResultDto = await env.register.handle(
        register_command(version="2.0.0", prerequisites=("cli_tool:git",))
    )

    entry: CatalogEntry = only_entry(env)
    assert isinstance(result, CatalogWriteResultDto)
    assert (result.id, result.kind, result.name) == (entry.id.value, "cli_tool", "gh")
    assert (result.revision, result.space_id, result.replayed) == (1, env.space_id.value, False)
    assert entry.catalog_key == f"{env.space_id.value}:cli_tool:gh"
    head = entry.head
    assert (head.purpose, head.version, head.location) == (
        "GitHub CLI",
        "2.0.0",
        "https://github.com/cli/cli",
    )
    assert head.prerequisites == (CatalogRef.parse("cli_tool:git"),)
    assert (head.actor, head.created_at) == (AGENT, env.base.clock.now())
    assert len(head.source_ids) == 1
    assert env.store.sources[head.source_ids[0].value].locator == CATALOG_SOURCE.locator
    ledger = env.store.ledger[(env.space_id.value, "k1")]
    assert (ledger.command, ledger.revision, ledger.record_id) == (
        "register_catalog_entry",
        1,
        entry.id,
    )


async def test_register_redacts_secrets_in_the_purpose_before_storage() -> None:
    env: CatalogEnv = await make_catalog_env()

    await env.register.handle(register_command(purpose="use sk-abcdefghijklmnopqrstuv for auth"))

    assert "abcdefghijklmnopqrstuv" not in only_entry(env).head.purpose


async def test_register_keeps_the_name_as_typed_so_case_makes_two_entries() -> None:
    env: CatalogEnv = await make_catalog_env()

    await env.register.handle(register_command("k1", name="gh"))
    await env.register.handle(register_command("k2", name="Gh"))

    assert sorted(e.name.value for e in env.catalog.entries.values()) == ["Gh", "gh"]


async def test_register_same_name_with_another_kind_is_a_different_entry() -> None:
    env: CatalogEnv = await make_catalog_env()

    await env.register.handle(register_command("k1", kind=CLI_TOOL, name="docs"))
    await env.register.handle(register_command("k2", kind=MCP_SERVER, name="docs"))

    assert len(env.catalog.entries) == 2


async def test_register_duplicate_kind_and_name_with_a_new_key_is_262() -> None:
    """AC-008 (a)."""
    env: CatalogEnv = await make_catalog_env()
    await env.register.handle(register_command("k1"))
    state = env.state()

    with pytest.raises(CatalogEntryAlreadyExistsError) as error:
        await env.register.handle(register_command("k2"))

    assert error.value.error_code == "KNOWLEDGE_262_CATALOG_ENTRY_ALREADY_EXISTS"
    assert any("catalog revise" in step for step in error.value.next_steps)
    assert env.state() == state
    assert (env.space_id.value, "k2") not in env.store.ledger


async def test_register_replay_returns_the_stored_result_and_writes_nothing() -> None:
    """AC-008 (b)."""
    env: CatalogEnv = await make_catalog_env()
    first = await env.register.handle(register_command("k1"))
    state = env.state()

    again = await env.register.handle(register_command("k1"))

    assert (again.id, again.revision, again.replayed) == (first.id, 1, True)
    assert first.replayed is False
    assert env.state() == state


async def test_register_same_key_with_another_purpose_is_203_before_any_ensure() -> None:
    """AC-008 (c)."""
    env: CatalogEnv = await make_catalog_env()
    await env.register.handle(register_command("k1"))
    state, sources = env.state(), len(env.store.sources)

    with pytest.raises(IdempotencyKeyReusedError) as error:
        await env.register.handle(register_command("k1", purpose="different"))

    assert error.value.error_code == "KNOWLEDGE_203_IDEMPOTENCY_KEY_REUSED"
    assert env.state() == state
    assert len(env.store.sources) == sources


async def test_register_racing_identical_requests_yield_one_entry_and_the_same_result() -> None:
    env: CatalogEnv = await make_catalog_env()
    command = register_command("k1")
    competitor: list[CatalogWriteResultDto] = []

    async def compete() -> None:
        competitor.append(await env.register.handle(command))

    loser = RegisterCatalogEntryHandler(
        uow_factory=racing_catalog_factory(env.store, env.catalog, compete),
        clock=env.base.clock,
        ids=env.base.ids,
        schema=env.base.schema,
    )

    result = await loser.handle(command)

    assert len(env.catalog.entries) == 1
    assert (result.id, result.replayed) == (competitor[0].id, True)
    assert competitor[0].replayed is False


async def test_register_losing_the_catalog_key_race_with_another_key_is_262() -> None:
    """Two concurrent first registers of the same kind and name: one commits, one gets 262."""
    env: CatalogEnv = await make_catalog_env()

    async def compete() -> None:
        await env.register.handle(register_command("winner"))

    loser = RegisterCatalogEntryHandler(
        uow_factory=racing_catalog_factory(env.store, env.catalog, compete),
        clock=env.base.clock,
        ids=env.base.ids,
        schema=env.base.schema,
    )

    with pytest.raises(CatalogEntryAlreadyExistsError):
        await loser.handle(register_command("loser"))

    assert len(env.catalog.entries) == 1
    assert (env.space_id.value, "loser") not in env.store.ledger


@pytest.mark.parametrize("name", ["Bad Name!", "", "-x", ".x", ":x", "ñame", "a" * 129])
async def test_register_invalid_name_is_061_and_stores_nothing(name: str) -> None:
    env: CatalogEnv = await make_catalog_env()
    state = env.state()

    with pytest.raises(InvalidCatalogNameError) as error:
        await env.register.handle(register_command(name=name))

    assert error.value.error_code == "KNOWLEDGE_061_INVALID_CATALOG_NAME"
    assert env.state() == state


@pytest.mark.parametrize(
    "requires",
    [
        pytest.param(("cli_tool:gh",), id="self-reference"),
        pytest.param(("gh",), id="no-colon"),
        pytest.param(("plugin:x",), id="unknown-kind"),
        pytest.param(("cli_tool:Bad Name!",), id="invalid-name"),
        pytest.param(("cli_tool:git", "cli_tool:gh"), id="self-reference-among-others"),
    ],
)
async def test_register_self_or_malformed_prerequisite_is_062_and_stores_nothing(
    requires: tuple[str, ...],
) -> None:
    env: CatalogEnv = await make_catalog_env()
    state = env.state()

    with pytest.raises(InvalidCatalogPrerequisiteError) as error:
        await env.register.handle(register_command(prerequisites=requires))

    assert error.value.error_code == "KNOWLEDGE_062_INVALID_CATALOG_PREREQUISITE"
    assert env.state() == state


async def test_register_allows_the_same_name_as_a_prerequisite_of_another_kind() -> None:
    env: CatalogEnv = await make_catalog_env()

    await env.register.handle(
        register_command(kind=SKILL, name="a", prerequisites=("cli_tool:a",), location="p@m")
    )

    assert only_entry(env).head.prerequisites == (CatalogRef.parse("cli_tool:a"),)


async def test_register_may_name_a_prerequisite_that_is_not_cataloged() -> None:
    env: CatalogEnv = await make_catalog_env()

    await env.register.handle(register_command(prerequisites=("skill:never-registered",)))

    assert len(env.catalog.entries) == 1


async def test_register_without_the_catalog_step_names_it_and_writes_nothing() -> None:
    env: CatalogEnv = await make_catalog_env(steps=("core",))
    state = env.state()

    with pytest.raises(StoreNotInitialisedError) as error:
        await env.register.handle(register_command())

    assert error.value.metadata == {"missing_steps": ["catalog"]}
    assert "noesis store init" in " ".join(error.value.next_steps)
    assert env.state() == state


async def test_register_in_an_unknown_space_fails() -> None:
    env: CatalogEnv = await make_catalog_env()

    with pytest.raises(SpaceNotFoundError):
        await env.register.handle(register_command(space_key=Key(value="nowhere")))

    assert env.catalog.entries == {}


async def test_register_in_another_space_is_independent_of_the_default_space() -> None:
    env: CatalogEnv = await make_catalog_env()
    other = KnowledgeSpace.create(
        id=env.base.ids.new_space_id(), key=Key(value="other"), name="other", now=NOW
    )
    env.store.spaces[other.id.value] = other
    await env.register.handle(register_command("k1", space_key=DEFAULT_SPACE_KEY))

    result = await env.register.handle(register_command("k2", space_key=Key(value="other")))

    assert result.space_id == other.id.value
    assert len(env.catalog.entries) == 2
