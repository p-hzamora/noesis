"""The git inspector against real repositories: a local bare repository stands in for origin."""

import stat
from pathlib import Path

import pytest
from tests.support.git_support import GitWorld, commit, git, isolate_git

from noesis.diagnostics.application.policies import assess_update
from noesis.diagnostics.application.ports.updates import CheckoutSnapshot
from noesis.diagnostics.infrastructure.outbound.updates import GitCheckoutInspectorAdapter

pytestmark = pytest.mark.integration

TIMEOUT = 10.0


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_git(monkeypatch)


@pytest.fixture
def world(tmp_path: Path) -> GitWorld:
    return GitWorld(tmp_path / "w")


def _adapter(timeout: float = TIMEOUT) -> GitCheckoutInspectorAdapter:
    return GitCheckoutInspectorAdapter(timeout_seconds=timeout)


async def test_up_to_date(world: GitWorld) -> None:
    snapshot = await _adapter().inspect(world.package_dir)

    assert snapshot.checkout == world.checkout.resolve()
    assert snapshot.branch == "main"
    assert snapshot.remote_url == str(world.origin)
    assert snapshot.remote_branch == "main"
    assert snapshot.local_sha == snapshot.remote_sha == world.base
    assert snapshot.dirty is False
    assert assess_update(snapshot).verdict == "up_to_date"


async def test_behind_fetches_only_objects_to_compare(world: GitWorld) -> None:
    remote_sha: str = world.publish("new.txt")  # not in the checkout's object store yet
    head_before: str = git(world.checkout, "rev-parse", "HEAD")
    refs_before: str = git(world.checkout, "for-each-ref")

    snapshot = await _adapter().inspect(world.package_dir)

    assert snapshot.local_sha == world.base and snapshot.remote_sha == remote_sha
    assert (snapshot.remote_contains_local, snapshot.local_contains_remote) == (True, False)
    assert assess_update(snapshot).verdict == "behind"
    assert git(world.checkout, "rev-parse", "HEAD") == head_before
    assert git(world.checkout, "status", "--porcelain") == ""
    assert git(world.checkout, "for-each-ref") == refs_before
    assert not (world.checkout / ".git/FETCH_HEAD").exists()
    assert not (world.checkout / "new.txt").exists()


async def test_ahead(world: GitWorld) -> None:
    local_sha: str = commit(world.checkout, "mine.txt")

    snapshot = await _adapter().inspect(world.package_dir)

    assert snapshot.local_sha == local_sha and snapshot.remote_sha == world.base
    assert (snapshot.remote_contains_local, snapshot.local_contains_remote) == (False, True)
    assert assess_update(snapshot).verdict == "ahead"


async def test_diverged(world: GitWorld) -> None:
    world.publish("theirs.txt")
    commit(world.checkout, "mine.txt")

    snapshot = await _adapter().inspect(world.package_dir)

    assert (snapshot.remote_contains_local, snapshot.local_contains_remote) == (False, False)
    assert assess_update(snapshot).verdict == "diverged"


async def test_dirty_tree_is_reported(world: GitWorld) -> None:
    (world.checkout / "src/noesis/__init__.py").write_text("changed", encoding="utf-8")

    snapshot = await _adapter().inspect(world.package_dir)

    assert snapshot.dirty is True
    assert assess_update(snapshot).verdict == "up_to_date"


async def test_no_origin_is_unknown(tmp_path: Path) -> None:
    repo: Path = tmp_path / "solo"
    (repo / "src/noesis").mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    commit(repo, "src/noesis/__init__.py")

    snapshot = await _adapter().inspect(repo / "src/noesis")

    assert snapshot.checkout == repo.resolve() and snapshot.local_sha
    assert snapshot.remote_url is None and snapshot.remote_sha is None
    assert "origin" in assess_update(snapshot).reason


async def test_not_a_checkout_is_unknown(tmp_path: Path) -> None:
    package: Path = tmp_path / "site-packages/noesis"
    package.mkdir(parents=True)

    snapshot = await _adapter().inspect(package)

    assert snapshot == CheckoutSnapshot()
    assert "not a git checkout" in assess_update(snapshot).reason


async def test_a_package_inside_some_other_repository_is_not_its_checkout(tmp_path: Path) -> None:
    repo: Path = tmp_path / "project"
    package: Path = repo / ".venv/lib/site-packages/noesis"
    package.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")

    assert await _adapter().inspect(package) == CheckoutSnapshot()


async def test_a_missing_package_dir_is_unknown(tmp_path: Path) -> None:
    assert await _adapter().inspect(tmp_path / "gone/noesis") == CheckoutSnapshot()


async def test_unreachable_origin_is_unknown(world: GitWorld, tmp_path: Path) -> None:
    git(world.checkout, "remote", "set-url", "origin", str(tmp_path / "nowhere.git"))

    snapshot = await _adapter().inspect(world.package_dir)

    assert snapshot.remote_url == str(tmp_path / "nowhere.git")
    assert snapshot.local_sha and snapshot.remote_sha is None
    assert "could not read" in assess_update(snapshot).reason


async def test_a_failed_fetch_leaves_the_histories_uncompared(world: GitWorld) -> None:
    world.publish("new.txt")
    shim: Path = world.checkout.parent / "git-no-fetch"
    shim.write_text(
        '#!/bin/sh\nfor a in "$@"; do [ "$a" = fetch ] && exit 1; done\nexec git "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)

    snapshot = await GitCheckoutInspectorAdapter(
        timeout_seconds=TIMEOUT, git_bin=str(shim)
    ).inspect(world.package_dir)

    assert snapshot.remote_sha is not None
    assert snapshot.remote_contains_local is None and snapshot.local_contains_remote is None
    assert assess_update(snapshot).verdict == "unknown"


async def test_a_git_that_hangs_times_out_without_raising(tmp_path: Path) -> None:
    slow: Path = tmp_path / "slow-git"
    slow.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
    slow.chmod(slow.stat().st_mode | stat.S_IEXEC)

    snapshot = await GitCheckoutInspectorAdapter(timeout_seconds=0.3, git_bin=str(slow)).inspect(
        tmp_path
    )

    assert snapshot == CheckoutSnapshot()


async def test_a_missing_git_binary_does_not_raise(tmp_path: Path) -> None:
    adapter = GitCheckoutInspectorAdapter(timeout_seconds=TIMEOUT, git_bin="no-such-git-binary")

    assert await adapter.inspect(tmp_path) == CheckoutSnapshot()
