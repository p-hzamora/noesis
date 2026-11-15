"""ReviseCatalogEntryHandler (FR-002; AC-008/AC-009 handler level; Q-009 partial update and no-op)."""

import pytest
from tests.support.catalog_support import (
    CatalogEnv,
    make_catalog_env,
    racing_catalog_factory,
    register_command,
    revise_command,
)
from tests.support.knowledge_support import NOW

from noesis.bounded_context.knowledge.application.dtos import CatalogWriteResultDto
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.revise_catalog_entry_handler import (
    ReviseCatalogEntryHandler,
)
from noesis.bounded_context.knowledge.application.services.inputs import NewSourceInput
from noesis.bounded_context.knowledge.domain.entities import CatalogEntry, KnowledgeSpace
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ActorKindEnum,
    CatalogEntryKindEnum,
    Key,
    SourceKindEnum,
)
from noesis.bounded_context.knowledge.domain.value_objects.catalog_ref import CatalogRef
from noesis.exceptions import (
    CatalogEntryNotFoundError,
    IdempotencyKeyReusedError,
    InvalidCatalogPrerequisiteError,
    InvalidRecordError,
    RevisionConflictError,
    SpaceNotFoundError,
    StoreNotInitialisedError,
)

pytestmark = pytest.mark.unit

REF: str = "cli_tool:gh"
LOCATION: str = "https://github.com/cli/cli"


async def registered(env: CatalogEnv) -> CatalogWriteResultDto:
    return await env.register.handle(
        register_command(
            "k1", purpose="P", version="1.0", prerequisites=("cli_tool:git",), location=LOCATION
        )
    )


def stored(env: CatalogEnv, record_id: str) -> CatalogEntry:
    return env.catalog.entries[record_id]


async def test_revise_purpose_only_appends_revision_two_and_keeps_the_rest() -> None:
    env: CatalogEnv = await make_catalog_env()
    first = await registered(env)
    env.base.clock.advance(60)
    newcomer: Actor = Actor(kind=ActorKindEnum.USER, name="pablo")

    result = await env.revise.handle(revise_command(REF, "r1", purpose="P2", actor=newcomer))

    entry: CatalogEntry = stored(env, first.id)
    assert isinstance(result, CatalogWriteResultDto)
    assert (result.id, result.kind, result.name) == (first.id, "cli_tool", "gh")
    assert (result.revision, result.replayed) == (2, False)
    assert [r.number for r in entry.revisions] == [1, 2]
    head = entry.head
    assert (head.purpose, head.version, head.location) == ("P2", "1.0", LOCATION)
    assert head.prerequisites == (CatalogRef.parse("cli_tool:git"),)
    assert (head.actor, head.created_at) == (newcomer, env.base.clock.now())
    ledger = env.store.ledger[(env.space_id.value, "r1")]
    assert (ledger.command, ledger.revision) == ("revise_catalog_entry", 2)
    assert entry.revisions[0].purpose == "P"


async def test_revise_resolves_an_id_and_a_kind_name_ref_with_a_qualified_name() -> None:
    env: CatalogEnv = await make_catalog_env()
    await env.register.handle(
        register_command(
            "k1", kind=CatalogEntryKindEnum.SKILL, name="python-suite:ddd", location="p@m"
        )
    )
    entry: CatalogEntry = next(iter(env.catalog.entries.values()))

    by_key = await env.revise.handle(
        revise_command("skill:python-suite:ddd", "r1", expected=1, purpose="one")
    )
    by_id = await env.revise.handle(revise_command(entry.id.value, "r2", expected=2, purpose="two"))

    assert (by_key.revision, by_id.revision) == (2, 3)
    assert stored(env, entry.id.value).head.purpose == "two"


@pytest.mark.parametrize(
    ("overrides", "version", "prerequisites"),
    [
        pytest.param({"version": ""}, None, ("cli_tool:git",), id="empty-version-clears"),
        pytest.param({"version": "2.0"}, "2.0", ("cli_tool:git",), id="version-replaces"),
        pytest.param({"prerequisites": ()}, "1.0", (), id="empty-requires-clears"),
        pytest.param(
            {"prerequisites": ("cli_tool:a", "cli_tool:b")},
            "1.0",
            ("cli_tool:a", "cli_tool:b"),
            id="requires-replaces-the-whole-list",
        ),
    ],
)
async def test_revise_applies_only_the_options_given(
    overrides: dict[str, object], version: str | None, prerequisites: tuple[str, ...]
) -> None:
    env: CatalogEnv = await make_catalog_env()
    first = await registered(env)

    result = await env.revise.handle(revise_command(REF, **overrides))

    head = stored(env, first.id).head
    assert result.revision == 2
    assert head.version == version
    assert head.prerequisites == tuple(CatalogRef.parse(p) for p in prerequisites)
    assert (head.purpose, head.location) == ("P", LOCATION)


async def test_revise_location_replaces_only_the_location() -> None:
    env: CatalogEnv = await make_catalog_env()
    first = await registered(env)

    await env.revise.handle(revise_command(REF, location="https://example.invalid/new"))

    head = stored(env, first.id).head
    assert (head.location, head.purpose, head.version) == (
        "https://example.invalid/new",
        "P",
        "1.0",
    )


async def test_revise_records_the_given_sources_on_the_new_revision() -> None:
    env: CatalogEnv = await make_catalog_env()
    first = await registered(env)
    other = NewSourceInput(kind=SourceKindEnum.URL, locator="https://example.invalid/other")

    await env.revise.handle(revise_command(REF, purpose="P2", sources=(other,)))

    head = stored(env, first.id).head
    assert [env.store.sources[s.value].locator for s in head.source_ids] == [other.locator]


async def test_revise_redacts_secrets_in_the_purpose() -> None:
    env: CatalogEnv = await make_catalog_env()
    first = await registered(env)

    await env.revise.handle(revise_command(REF, purpose="use sk-abcdefghijklmnopqrstuv"))

    assert "abcdefghijklmnopqrstuv" not in stored(env, first.id).head.purpose


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({}, id="nothing-given"),
        pytest.param(
            {
                "purpose": "P",
                "version": "1.0",
                "prerequisites": ("cli_tool:git",),
                "location": LOCATION,
            },
            id="head-values-repeated",
        ),
    ],
)
async def test_revise_with_unchanged_content_is_a_no_op_that_writes_nothing(
    overrides: dict[str, object],
) -> None:
    """Q-009: result is the head number; no revision, ledger entry or commit."""
    env: CatalogEnv = await make_catalog_env()
    first = await registered(env)
    state = env.state()

    result = await env.revise.handle(revise_command(REF, "r1", **overrides))

    assert (result.id, result.revision) == (first.id, 1)
    assert env.state() == state
    assert (env.space_id.value, "r1") not in env.store.ledger
    assert [r.number for r in stored(env, first.id).revisions] == [1]


async def test_a_no_op_never_touches_the_aggregate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The no-op is detected before `revise`: no revision n+1, no pending event."""
    env: CatalogEnv = await make_catalog_env()
    first = await registered(env)
    calls: list[int] = []
    original = CatalogEntry.revise

    def spy(self: CatalogEntry, **kwargs: object) -> object:
        calls.append(1)
        return original(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(CatalogEntry, "revise", spy)

    result = await env.revise.handle(revise_command(REF, "r1"))

    assert result.revision == 1
    assert calls == []
    assert [r.number for r in stored(env, first.id).revisions] == [1]


async def test_a_no_op_leaves_its_key_free_for_a_later_real_revise() -> None:
    env: CatalogEnv = await make_catalog_env()
    await registered(env)
    await env.revise.handle(revise_command(REF, "r1"))

    result = await env.revise.handle(revise_command(REF, "r1", purpose="P2"))

    assert (result.revision, result.replayed) == (2, False)


async def test_a_stale_no_op_is_still_a_revision_conflict() -> None:
    """Q-009: the stale check comes first."""
    env: CatalogEnv = await make_catalog_env()
    await registered(env)
    await env.revise.handle(revise_command(REF, "r1", purpose="P2"))
    state = env.state()

    with pytest.raises(RevisionConflictError) as error:
        await env.revise.handle(revise_command(REF, "r2", expected=1, purpose="P2"))

    assert error.value.error_code == "KNOWLEDGE_202_REVISION_CONFLICT"
    assert env.state() == state


async def test_revise_stale_expected_revision_conflicts_with_metadata_and_adds_nothing() -> None:
    env: CatalogEnv = await make_catalog_env()
    first = await registered(env)
    await env.revise.handle(revise_command(REF, "r1", expected=1, purpose="P2"))
    state = env.state()

    with pytest.raises(RevisionConflictError) as error:
        await env.revise.handle(revise_command(REF, "r2", expected=1, purpose="P3"))

    assert error.value.metadata == {
        "record_id": first.id,
        "expected_revision": 1,
        "actual_revision": 2,
    }
    assert error.value.next_steps
    assert env.state() == state


@pytest.mark.parametrize("ref", ["cli_tool:nope", "skill:gh", "0" * 25 + "9"])
async def test_revise_unknown_ref_is_261_with_the_list_command_as_next_step(ref: str) -> None:
    env: CatalogEnv = await make_catalog_env()
    await registered(env)
    state = env.state()

    with pytest.raises(CatalogEntryNotFoundError) as error:
        await env.revise.handle(revise_command(ref, purpose="x"))

    assert error.value.error_code == "KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND"
    assert any("catalog list" in step for step in error.value.next_steps)
    assert env.state() == state


async def test_revise_entry_of_another_space_is_261() -> None:
    env: CatalogEnv = await make_catalog_env()
    first = await registered(env)
    other = KnowledgeSpace.create(
        id=env.base.ids.new_space_id(), key=Key(value="other"), name="other", now=NOW
    )
    env.store.spaces[other.id.value] = other

    for ref in (REF, first.id):
        with pytest.raises(CatalogEntryNotFoundError):
            await env.revise.handle(revise_command(ref, purpose="x", space_key=Key(value="other")))

    assert [r.number for r in stored(env, first.id).revisions] == [1]


async def test_revise_unknown_space_fails() -> None:
    env: CatalogEnv = await make_catalog_env()
    await registered(env)

    with pytest.raises(SpaceNotFoundError):
        await env.revise.handle(revise_command(REF, purpose="x", space_key=Key(value="x")))


async def test_revise_self_prerequisite_is_062_and_appends_nothing() -> None:
    env: CatalogEnv = await make_catalog_env()
    await registered(env)
    state = env.state()

    with pytest.raises(InvalidCatalogPrerequisiteError):
        await env.revise.handle(revise_command(REF, prerequisites=("cli_tool:gh",)))

    assert env.state() == state


@pytest.mark.parametrize("requires", [("gh",), ("plugin:x",)])
async def test_revise_malformed_prerequisite_is_062(requires: tuple[str, ...]) -> None:
    env: CatalogEnv = await make_catalog_env()
    await registered(env)

    with pytest.raises(InvalidCatalogPrerequisiteError):
        await env.revise.handle(revise_command(REF, prerequisites=requires))


async def test_revise_replay_returns_the_same_result_and_writes_nothing() -> None:
    env: CatalogEnv = await make_catalog_env()
    first = await registered(env)
    await env.revise.handle(revise_command(REF, purpose="P2"))
    state = env.state()

    again = await env.revise.handle(revise_command(REF, purpose="P2"))

    assert (again.id, again.revision, again.replayed) == (first.id, 2, True)
    assert env.state() == state


async def test_revise_same_key_different_request_is_203() -> None:
    env: CatalogEnv = await make_catalog_env()
    await registered(env)
    await env.revise.handle(revise_command(REF, purpose="P2"))
    state = env.state()

    with pytest.raises(IdempotencyKeyReusedError):
        await env.revise.handle(revise_command(REF, purpose="other"))

    assert env.state() == state


async def test_revise_key_reused_from_register_is_203() -> None:
    env: CatalogEnv = await make_catalog_env()
    await registered(env)

    with pytest.raises(IdempotencyKeyReusedError):
        await env.revise.handle(revise_command(REF, "k1", purpose="P2"))


def racing_revise(env: CatalogEnv, hook: object) -> ReviseCatalogEntryHandler:
    return ReviseCatalogEntryHandler(
        uow_factory=racing_catalog_factory(env.store, env.catalog, hook),  # type: ignore[arg-type]
        clock=env.base.clock,
        ids=env.base.ids,
        schema=env.base.schema,
    )


async def test_racing_identical_revises_yield_one_revision_and_the_same_result() -> None:
    env: CatalogEnv = await make_catalog_env()
    first = await registered(env)
    command = revise_command(REF, "r1", purpose="P2")
    competitor: list[CatalogWriteResultDto] = []

    async def compete() -> None:
        competitor.append(await env.revise.handle(command))

    result = await racing_revise(env, compete).handle(command)

    assert [r.number for r in stored(env, first.id).revisions] == [1, 2]
    assert (result.revision, result.replayed) == (2, True)
    assert competitor[0].replayed is False


async def test_racing_different_revises_on_the_same_head_conflict() -> None:
    """AC-009 (handler level): the second writer loses with expected 1, actual 2."""
    env: CatalogEnv = await make_catalog_env()
    first = await registered(env)

    async def compete() -> None:
        await env.revise.handle(revise_command(REF, "ka", purpose="A"))

    with pytest.raises(RevisionConflictError) as error:
        await racing_revise(env, compete).handle(revise_command(REF, "kb", purpose="B"))

    assert error.value.metadata["expected_revision"] == 1
    assert error.value.metadata["actual_revision"] == 2
    entry = stored(env, first.id)
    assert [r.number for r in entry.revisions] == [1, 2]
    assert entry.head.purpose == "A"
    assert (env.space_id.value, "kb") not in env.store.ledger


async def test_revise_without_the_catalog_step_names_it_and_writes_nothing() -> None:
    env: CatalogEnv = await make_catalog_env(steps=("core",))
    state = env.state()

    with pytest.raises(StoreNotInitialisedError) as error:
        await env.revise.handle(revise_command(REF, purpose="x"))

    assert error.value.metadata == {"missing_steps": ["catalog"]}
    assert env.state() == state


@pytest.mark.parametrize("ref", ["gh", "plugin:x", "not a ref"])
async def test_revise_a_ref_that_is_neither_an_id_nor_kind_name_is_261(ref: str) -> None:
    env: CatalogEnv = await make_catalog_env()
    await registered(env)
    state = env.state()

    with pytest.raises(CatalogEntryNotFoundError) as error:
        await env.revise.handle(revise_command(ref, purpose="x"))

    assert error.value.error_code == "KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND"
    assert any("catalog list" in step for step in error.value.next_steps)
    assert env.state() == state


async def test_revise_without_a_source_is_rejected_and_writes_nothing() -> None:
    env: CatalogEnv = await make_catalog_env()
    await registered(env)
    state = env.state()

    with pytest.raises(InvalidRecordError):
        await env.revise.handle(revise_command(REF, purpose="P2", sources=()))

    assert env.state() == state
