"""repos.json: id to folder, written only on change, safe under concurrent writers."""

import asyncio
import json
from pathlib import Path

import pytest

from noesis.bounded_context.capture.domain.value_objects import RepoId
from noesis.bounded_context.capture.infrastructure.outbound.registry import (
    JsonFileRepoRegistryAdapter,
)

pytestmark = pytest.mark.integration


def _registry(tmp_path: Path) -> JsonFileRepoRegistryAdapter:
    return JsonFileRepoRegistryAdapter(tmp_path / "capture" / "repos.json", lock_timeout_seconds=2)


def _stored(tmp_path: Path) -> dict[str, str]:
    return json.loads((tmp_path / "capture" / "repos.json").read_text())["repos"]


async def test_a_repository_is_recorded_with_its_folder(tmp_path: Path) -> None:
    repo = RepoId.derive("billing", "/w/billing/.git")

    await _registry(tmp_path).register(repo, Path("/w/billing"))

    assert _stored(tmp_path) == {repo.value: "/w/billing"}


async def test_registering_the_same_mapping_again_does_not_rewrite_the_file(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    repo = RepoId.derive("billing", "/w/billing/.git")
    await registry.register(repo, Path("/w/billing"))
    file = tmp_path / "capture" / "repos.json"
    before = file.stat().st_mtime_ns

    await registry.register(repo, Path("/w/billing"))

    assert file.stat().st_mtime_ns == before


async def test_concurrent_registrations_of_different_repositories_all_land(
    tmp_path: Path,
) -> None:
    repos = [RepoId.derive(f"r{index}", f"/w/r{index}/.git") for index in range(8)]

    await asyncio.gather(
        *(_registry(tmp_path).register(repo, Path(f"/w/{repo.name}")) for repo in repos)
    )

    assert set(_stored(tmp_path)) == {repo.value for repo in repos}


async def test_a_corrupt_registry_is_rebuilt_not_fatal(tmp_path: Path) -> None:
    (tmp_path / "capture").mkdir()
    (tmp_path / "capture" / "repos.json").write_text("not json")
    repo = RepoId.derive("billing", "/w/billing/.git")

    await _registry(tmp_path).register(repo, Path("/w/billing"))

    assert _stored(tmp_path) == {repo.value: "/w/billing"}
