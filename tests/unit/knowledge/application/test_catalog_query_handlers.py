"""ListCatalogEntriesHandler and GetCatalogEntryHandler (FR-003; other-space and revision rows)."""

import pytest
from tests.support.catalog_support import (
    CLI_TOOL,
    SKILL,
    CatalogEnv,
    make_catalog_env,
    register_command,
    revise_command,
)
from tests.support.knowledge_support import AGENT, DEFAULT_SPACE_KEY, NOW

from noesis.bounded_context.knowledge.application.handlers.queries.catalog import (
    GetCatalogEntryQuery,
    ListCatalogEntriesQuery,
)
from noesis.bounded_context.knowledge.domain.entities import KnowledgeSpace
from noesis.bounded_context.knowledge.domain.value_objects import Key
from noesis.exceptions import CatalogEntryNotFoundError, SpaceNotFoundError

pytestmark = pytest.mark.unit


async def seeded(env: CatalogEnv) -> dict[str, str]:
    """Three entries; returns their ids by name."""
    ids: dict[str, str] = {}
    for key, kind, name in (
        ("k1", CLI_TOOL, "gh"),
        ("k2", CLI_TOOL, "git"),
        ("k3", SKILL, "python-suite:ddd"),
    ):
        result = await env.register.handle(
            register_command(key, kind=kind, name=name, location="somewhere")
        )
        ids[name] = result.id
    return ids


async def add_other_space(env: CatalogEnv) -> KnowledgeSpace:
    other = KnowledgeSpace.create(
        id=env.base.ids.new_space_id(), key=Key(value="other"), name="other", now=NOW
    )
    env.store.spaces[other.id.value] = other
    return other


async def test_list_returns_every_entry_of_the_space() -> None:
    env: CatalogEnv = await make_catalog_env()
    ids = await seeded(env)

    result = await env.list_entries.handle(ListCatalogEntriesQuery(space_key=DEFAULT_SPACE_KEY))

    assert {e.name: e.id for e in result} == ids


@pytest.mark.parametrize(
    ("filters", "names"),
    [
        pytest.param({"kind": CLI_TOOL}, {"gh", "git"}, id="kind"),
        pytest.param({"name_prefix": "g"}, {"gh", "git"}, id="prefix"),
        pytest.param({"name_prefix": "python-suite:"}, {"python-suite:ddd"}, id="qualified-prefix"),
        pytest.param({"kind": SKILL, "name_prefix": "g"}, set(), id="kind-and-prefix"),
        pytest.param({"name_prefix": "G"}, set(), id="prefix-is-case-sensitive"),
    ],
)
async def test_list_narrows_by_kind_and_name_prefix(
    filters: dict[str, object], names: set[str]
) -> None:
    env: CatalogEnv = await make_catalog_env()
    await seeded(env)

    result = await env.list_entries.handle(
        ListCatalogEntriesQuery(space_key=DEFAULT_SPACE_KEY, **filters)  # type: ignore[arg-type]
    )

    assert {e.name for e in result} == names


async def test_list_shows_head_content_and_prerequisites_as_kind_name_text() -> None:
    env: CatalogEnv = await make_catalog_env()
    first = await env.register.handle(
        register_command(version="1.0", prerequisites=("cli_tool:git",))
    )
    await env.revise.handle(revise_command("cli_tool:gh", purpose="Newer purpose"))

    (entry,) = await env.list_entries.handle(ListCatalogEntriesQuery(space_key=DEFAULT_SPACE_KEY))

    assert (entry.id, entry.head_revision, entry.purpose) == (first.id, 2, "Newer purpose")
    assert (entry.declared_version, list(entry.prerequisites)) == ("1.0", ["cli_tool:git"])


async def test_list_of_another_space_is_empty() -> None:
    env: CatalogEnv = await make_catalog_env()
    await seeded(env)
    await add_other_space(env)

    result = await env.list_entries.handle(ListCatalogEntriesQuery(space_key=Key(value="other")))

    assert list(result) == []


async def test_list_by_space_id_needs_no_space_key() -> None:
    env: CatalogEnv = await make_catalog_env()
    ids = await seeded(env)

    result = await env.list_entries.handle(ListCatalogEntriesQuery(space_id=env.space_id))

    assert {e.id for e in result} == set(ids.values())


async def test_list_in_an_unknown_space_fails() -> None:
    env: CatalogEnv = await make_catalog_env()

    with pytest.raises(SpaceNotFoundError):
        await env.list_entries.handle(ListCatalogEntriesQuery(space_key=Key(value="nowhere")))


async def test_list_works_on_a_store_without_the_catalog_step() -> None:
    env: CatalogEnv = await make_catalog_env(steps=("core",))

    result = await env.list_entries.handle(ListCatalogEntriesQuery(space_key=DEFAULT_SPACE_KEY))

    assert list(result) == []


@pytest.mark.parametrize("by", ["id", "key"])
async def test_get_returns_the_head_revision_with_actor_time_and_sources(by: str) -> None:
    env: CatalogEnv = await make_catalog_env()
    ids = await seeded(env)
    ref: str = ids["gh"] if by == "id" else "cli_tool:gh"

    detail = await env.get_entry.handle(GetCatalogEntryQuery(space_key=DEFAULT_SPACE_KEY, ref=ref))

    assert (detail.id, detail.kind, detail.name) == (ids["gh"], "cli_tool", "gh")
    assert (detail.number, detail.head_revision) == (1, 1)
    assert (detail.purpose, detail.location) == ("GitHub CLI", "somewhere")
    assert (detail.actor_kind, detail.actor_name, detail.actor_session) == (
        AGENT.kind.value,
        AGENT.name,
        AGENT.session,
    )
    assert detail.created_at is not None
    assert len(detail.source_ids) == 1


async def test_get_resolves_a_qualified_name_by_the_first_colon() -> None:
    env: CatalogEnv = await make_catalog_env()
    ids = await seeded(env)

    detail = await env.get_entry.handle(
        GetCatalogEntryQuery(space_key=DEFAULT_SPACE_KEY, ref="skill:python-suite:ddd")
    )

    assert detail.id == ids["python-suite:ddd"]


async def test_get_a_given_revision_shows_that_revisions_content() -> None:
    env: CatalogEnv = await make_catalog_env()
    await seeded(env)
    await env.revise.handle(revise_command("cli_tool:gh", purpose="Second purpose"))

    first = await env.get_entry.handle(
        GetCatalogEntryQuery(space_key=DEFAULT_SPACE_KEY, ref="cli_tool:gh", revision=1)
    )
    head = await env.get_entry.handle(
        GetCatalogEntryQuery(space_key=DEFAULT_SPACE_KEY, ref="cli_tool:gh")
    )

    assert (first.number, first.purpose, first.head_revision) == (1, "GitHub CLI", 2)
    assert (head.number, head.purpose) == (2, "Second purpose")


@pytest.mark.parametrize("revision", [3, 99])
async def test_get_a_missing_revision_is_261(revision: int) -> None:
    env: CatalogEnv = await make_catalog_env()
    await seeded(env)
    await env.revise.handle(revise_command("cli_tool:gh", purpose="Second purpose"))

    with pytest.raises(CatalogEntryNotFoundError):
        await env.get_entry.handle(
            GetCatalogEntryQuery(space_key=DEFAULT_SPACE_KEY, ref="cli_tool:gh", revision=revision)
        )


@pytest.mark.parametrize("ref", ["cli_tool:nope", "skill:gh", "0" * 25 + "9"])
async def test_get_unknown_ref_is_261_with_the_list_command_as_next_step(ref: str) -> None:
    env: CatalogEnv = await make_catalog_env()
    await seeded(env)

    with pytest.raises(CatalogEntryNotFoundError) as error:
        await env.get_entry.handle(GetCatalogEntryQuery(space_key=DEFAULT_SPACE_KEY, ref=ref))

    assert error.value.error_code == "KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND"
    assert any("catalog list" in step for step in error.value.next_steps)


@pytest.mark.parametrize("by", ["id", "key"])
async def test_get_an_entry_of_another_space_is_261(by: str) -> None:
    env: CatalogEnv = await make_catalog_env()
    ids = await seeded(env)
    await add_other_space(env)
    ref: str = ids["gh"] if by == "id" else "cli_tool:gh"

    with pytest.raises(CatalogEntryNotFoundError):
        await env.get_entry.handle(GetCatalogEntryQuery(space_key=Key(value="other"), ref=ref))


@pytest.mark.parametrize("ref", ["gh", "plugin:x", "not a ref"])
async def test_get_a_ref_that_is_neither_an_id_nor_kind_name_is_261(ref: str) -> None:
    env: CatalogEnv = await make_catalog_env()
    await seeded(env)

    with pytest.raises(CatalogEntryNotFoundError) as error:
        await env.get_entry.handle(GetCatalogEntryQuery(space_key=DEFAULT_SPACE_KEY, ref=ref))

    assert error.value.error_code == "KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND"
    assert any("catalog list" in step for step in error.value.next_steps)
