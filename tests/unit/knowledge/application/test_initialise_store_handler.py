"""InitialiseStoreHandler (FR-014, FR-018; AC-011, AC-020)."""

import pytest
from tests.support.knowledge_commands import racing_factory
from tests.support.knowledge_support import (
    DEFAULT_SPACE_KEY,
    FakeStoreSchema,
    KnowledgeEnv,
    make_env,
)

from noesis.bounded_context.knowledge.application.dtos import StoreInitialisedDto
from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
    InitialiseStoreCommand,
    InitialiseStoreHandler,
)
from noesis.bounded_context.knowledge.application.services.schema_steps import require_steps
from noesis.bounded_context.knowledge.domain.value_objects import Key
from noesis.exceptions import StoreNotInitialisedError

pytestmark = pytest.mark.unit

COMMAND: InitialiseStoreCommand = InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY)


async def test_first_run_applies_steps_and_creates_default_space() -> None:
    env: KnowledgeEnv = await make_env(initialised=False, steps=("core",))

    result: StoreInitialisedDto = await env.initialise_store.handle(
        InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY, default_space_name="Main")
    )

    assert isinstance(result, StoreInitialisedDto)
    assert result.applied_steps == ("core",)
    assert result.already_applied_steps == ()
    assert (result.default_space.key, result.default_space.name, result.default_space.created) == (
        "default",
        "Main",
        True,
    )
    assert list(env.store.spaces) == [result.default_space.id]
    assert await env.schema.applied_steps() == {"core"}


async def test_space_name_defaults_to_key() -> None:
    env: KnowledgeEnv = await make_env(initialised=False)

    result = await env.initialise_store.handle(COMMAND)

    assert result.default_space.name == "default"


async def test_second_run_applies_nothing_and_keeps_one_default_space() -> None:
    """AC-011: init twice leaves one space and each step applied once."""
    env: KnowledgeEnv = await make_env(initialised=False)

    first = await env.initialise_store.handle(COMMAND)
    second = await env.initialise_store.handle(COMMAND)

    assert second.applied_steps == ()
    assert second.already_applied_steps == ("core",)
    assert second.default_space.created is False
    assert second.default_space.id == first.default_space.id
    assert len(env.store.spaces) == 1
    assert env.store.commits == 1


async def test_second_registered_step_is_applied_once_across_two_runs() -> None:
    """AC-020."""
    env: KnowledgeEnv = await make_env(initialised=True, steps=("core",))
    env.schema = FakeStoreSchema(("core", "vectors"))
    env.schema.applied.add("core")

    first = await env.initialise_store.handle(COMMAND)
    second = await env.initialise_store.handle(COMMAND)

    assert first.applied_steps == ("vectors",)
    assert first.already_applied_steps == ("core",)
    assert second.applied_steps == ()
    assert second.already_applied_steps == ("core", "vectors")
    assert await env.schema.applied_steps() == {"core", "vectors"}
    assert len(env.store.spaces) == 1


async def test_steps_are_applied_in_registration_order() -> None:
    env: KnowledgeEnv = await make_env(initialised=False)
    env.schema = FakeStoreSchema(("core", "b", "a"))

    result = await env.initialise_store.handle(COMMAND)

    assert result.applied_steps == ("core", "b", "a")
    assert env.schema.apply_calls == ["core", "b", "a"]


async def test_result_exposes_no_numeric_schema_version() -> None:
    assert not any("version" in name for name in StoreInitialisedDto.model_fields)


async def test_racing_default_space_creation_reuses_the_winner() -> None:
    env: KnowledgeEnv = await make_env(initialised=False)

    async def compete() -> None:
        await env.initialise_store.handle(COMMAND)

    loser = InitialiseStoreHandler(
        uow_factory=racing_factory(env.store, compete),
        clock=env.clock,
        ids=env.ids,
        schema=env.schema,
    )

    result = await loser.handle(COMMAND)

    assert len(env.store.spaces) == 1
    assert result.default_space.created is False
    assert result.default_space.id in env.store.spaces


async def test_require_steps_names_every_missing_step_in_order() -> None:
    schema = FakeStoreSchema(("core",))
    schema.applied.add("core")

    await require_steps(schema, "core")
    with pytest.raises(StoreNotInitialisedError) as error:
        await require_steps(schema, "core", "vectors", "extra")

    assert error.value.metadata == {"missing_steps": ["vectors", "extra"]}
    assert "vectors, extra" in error.value.message


async def test_distinct_default_space_keys_create_distinct_spaces() -> None:
    env: KnowledgeEnv = await make_env()

    other = await env.initialise_store.handle(
        InitialiseStoreCommand(default_space_key=Key(value="second"))
    )

    assert other.default_space.created is True
    assert len(env.store.spaces) == 2
