"""Which stored session id a command runs under."""

from pathlib import Path

import pytest
from tests.support.capture_support import REPO, FakeIdentitySource, FakeVcs

from noesis.bounded_context.capture.application.handlers.queries import (
    ResolveSessionIdentityHandler,
    ResolveSessionIdentityQuery,
)
from noesis.bounded_context.capture.application.services.identity import SessionIdentityResolver
from noesis.bounded_context.capture.domain.services import SessionIdGenerator
from noesis.exceptions import InvalidSessionIdError, SessionIdentityMissingError

pytestmark = pytest.mark.unit


class _World:
    def __init__(self, ambient: str | None = None) -> None:
        self.identity = FakeIdentitySource(ambient)
        self.vcs = FakeVcs()
        self.resolver = SessionIdentityResolver(
            identity=self.identity,
            vcs=self.vcs,
            generator=SessionIdGenerator(),
        )


async def test_an_explicit_hint_beats_the_ambient_id() -> None:
    world = _World(ambient="from-harness")

    hinted = await world.resolver.resolve(hint="explicit", cwd=REPO, allow_fresh=False)
    ambient = await world.resolver.resolve(hint=None, cwd=REPO, allow_fresh=False)

    assert hinted.session_id != ambient.session_id
    assert hinted.session_id.startswith(hinted.repo_id)
    assert (hinted.generated, ambient.generated) == (False, False)


async def test_the_cli_and_the_hook_derive_the_same_id_from_the_same_raw_value() -> None:
    world = _World()

    from_cli = await world.resolver.resolve(hint="claude-uuid", cwd=REPO, allow_fresh=False)
    from_hook = await world.resolver.resolve(
        hint="claude-uuid", cwd=REPO / "src", allow_fresh=False
    )

    assert from_cli.session_id == from_hook.session_id


async def test_a_printed_id_passed_back_is_stable() -> None:
    world = _World()
    first = await world.resolver.resolve(hint=None, cwd=REPO, allow_fresh=True)

    again = await world.resolver.resolve(hint=first.session_id, cwd=REPO, allow_fresh=False)

    assert again.session_id == first.session_id


async def test_without_any_identity_a_fresh_id_is_chosen_only_when_allowed() -> None:
    world = _World()

    fresh = await world.resolver.resolve(hint=None, cwd=REPO, allow_fresh=True)

    assert (fresh.generated, world.identity.fresh_calls) == (True, 1)
    with pytest.raises(SessionIdentityMissingError):
        await world.resolver.resolve(hint=None, cwd=REPO, allow_fresh=False)
    assert world.identity.fresh_calls == 1


async def test_a_blank_hint_is_rejected_not_replaced_by_the_ambient_id() -> None:
    world = _World(ambient="from-harness")

    with pytest.raises(InvalidSessionIdError):
        await world.resolver.resolve(hint="  ", cwd=REPO, allow_fresh=True)
    with pytest.raises(InvalidSessionIdError):
        await world.resolver.resolve(hint="", cwd=REPO, allow_fresh=True)
    assert world.identity.fresh_calls == 0


async def test_the_resolved_identity_names_the_repository_and_its_main_worktree() -> None:
    world = _World()

    resolved = await world.resolver.resolve(hint="x", cwd=REPO, allow_fresh=False)

    assert (resolved.repo_id.startswith("demo-"), resolved.repository_path) == (True, str(REPO))


async def test_outside_a_repository_nothing_is_registered_but_an_id_is_still_derived() -> None:
    world = _World()
    world.vcs.location = None

    resolved = await world.resolver.resolve(hint="x", cwd=Path("/tmp/nowhere"), allow_fresh=False)  # noqa: S108

    assert (resolved.repo_id, resolved.repository_path) == ("", "")
    assert resolved.session_id.startswith("no-repo-")


async def test_the_handler_delegates_to_the_resolver() -> None:
    world = _World()
    handler = ResolveSessionIdentityHandler(resolver=world.resolver)

    resolved = await handler.handle(ResolveSessionIdentityQuery(hint="x", cwd=REPO))

    assert resolved.session_id.startswith("demo-")


async def test_a_blank_ambient_value_counts_as_absent() -> None:
    world = _World(ambient="   ")

    with pytest.raises(SessionIdentityMissingError):
        await world.resolver.resolve(hint=None, cwd=REPO, allow_fresh=False)
    fresh = await world.resolver.resolve(hint=None, cwd=REPO, allow_fresh=True)
    assert fresh.generated is True


async def test_a_sub_agent_does_not_inherit_the_harness_id_of_its_parent() -> None:
    world = _World(ambient="parents-harness-id")

    child = await world.resolver.resolve(hint=None, cwd=REPO, allow_fresh=True, use_ambient=False)
    parent = await world.resolver.resolve(hint=None, cwd=REPO, allow_fresh=True)

    assert (child.generated, parent.generated) == (True, False)
    assert child.session_id != parent.session_id
