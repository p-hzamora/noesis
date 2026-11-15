"""Folder fixtures, child environments and argv builders for the `noesis catalog` process tests.

Implements the "Shared fixtures" of `90-verification.md` (`claude_home`, `codex_home`, `project`,
`bin`, `no_session`, `down`, `src`) on top of C2's `noesis_process_support`, without changing it:

- the folders all live under one `root` inside `tmp_path`; nothing here touches a real home;
- `codex_home` is the folder exported as `HOME` (its `.codex` is the Codex home, `CODEX_HOME`
  stays unset), `claude_home` is exported as `CLAUDE_CONFIG_DIR`, `bin` is the only `PATH` entry;
- the child's working directory is `project` (C2's `start_noesis` uses `HOME` as the working
  directory, so this module starts the child itself and reuses `finish` and `ProcessResult`);
- a child environment never inherits `os.environ`, so `no_session` holds by construction: no
  `CODEX_*`, `NOESIS_SESSION_ID` or Claude Code marker is set unless a test passes it as `extra`.
"""

import json
import stat
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from tests.support.knowledge_cli_support import closed_port
from tests.support.knowledge_neo4j_support import query
from tests.support.noesis_process_support import (
    ProcessResult,
    finish,
    store_environment,
)

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

SPACE: str = "e2e"
CLOSED_PORT_TIMEOUT_SECONDS: str = "2"
EMPTY_REGISTRY: dict[str, object] = {"version": 2, "plugins": {}}


@dataclass(frozen=True, slots=True)
class CatalogWorld:
    """The temporary folders one scenario runs in.

    Attributes:
        root: Parent of every other folder.
        claude_home: Exported as `CLAUDE_CONFIG_DIR`; `plugins/installed_plugins.json` exists.
        home: Exported as `HOME` (the `codex_home` fixture); `.codex/config.toml` exists, empty.
        project: Working directory and project root of the child.
        bin: The only `PATH` entry of the child.
        env_file: An empty `--env-file` kept outside `home`.
    """

    root: Path
    claude_home: Path
    home: Path
    project: Path
    bin: Path
    env_file: Path

    @property
    def codex_dir(self) -> Path:
        """`<HOME>/.codex`."""
        return self.home / ".codex"

    @property
    def registry(self) -> Path:
        """`<claude_home>/plugins/installed_plugins.json`."""
        return self.claude_home / "plugins" / "installed_plugins.json"


def make_world(root: Path) -> CatalogWorld:
    """Create the folders with an empty Claude plugin registry and an empty Codex config."""
    world: CatalogWorld = CatalogWorld(
        root=root,
        claude_home=root / "claude_home",
        home=root / "codex_home",
        project=root / "project",
        bin=root / "bin",
        env_file=root / "empty.env",
    )
    for folder in (world.claude_home / "plugins", world.codex_dir, world.project, world.bin):
        folder.mkdir(parents=True, exist_ok=True)
    world.registry.write_text(json.dumps(EMPTY_REGISTRY), encoding="utf-8")
    (world.codex_dir / "config.toml").write_text("", encoding="utf-8")
    world.env_file.touch()
    return world


def _touch(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def install_claude_plugin(
    world: CatalogWorld,
    plugin: str,
    marketplace: str,
    version: str,
    *,
    skills: Sequence[str] = (),
    agents: Sequence[str] = (),
    register: bool = True,
) -> Path:
    """Add `<plugin>@<marketplace>` to the registry and create its files; returns `installPath`."""
    install_path: Path = world.root / "plugins" / plugin
    if register:
        registry: dict[str, Any] = json.loads(world.registry.read_text(encoding="utf-8"))
        registry["plugins"][f"{plugin}@{marketplace}"] = [
            {"scope": "user", "installPath": str(install_path), "version": version}
        ]
        world.registry.write_text(json.dumps(registry), encoding="utf-8")
    for skill in skills:
        _touch(install_path / "skills" / skill / "SKILL.md", f"# {skill}\n")
    for agent in agents:
        _touch(install_path / "agents" / f"{agent}.md", f"# {agent}\n")
    return install_path


def add_installed_skill(install_path: Path, skill: str) -> Path:
    """Create `<installPath>/skills/<skill>/SKILL.md` (a skill that becomes installed later)."""
    skill_file: Path = install_path / "skills" / skill / "SKILL.md"
    _touch(skill_file, f"# {skill}\n")
    return skill_file


def corrupt_claude_registry(world: CatalogWorld) -> None:
    """Make the registry unparseable (`{not json`)."""
    world.registry.write_text("{not json", encoding="utf-8")


def install_codex_plugin(
    world: CatalogWorld,
    plugin: str,
    marketplace: str,
    version: str,
    *,
    skills: Sequence[str] = (),
) -> None:
    """Add a `[plugins."<p>@<m>"]` table to `config.toml` and the cached skill files."""
    config: Path = world.codex_dir / "config.toml"
    config.write_text(
        config.read_text(encoding="utf-8") + f'[plugins."{plugin}@{marketplace}"]\n',
        encoding="utf-8",
    )
    for skill in skills:
        _touch(
            world.codex_dir
            / "plugins/cache"
            / marketplace
            / plugin
            / version
            / "skills"
            / skill
            / "SKILL.md",
            f"# {skill}\n",
        )


def add_project_skill(world: CatalogWorld, skill: str) -> None:
    """`<project>/.claude/skills/<skill>/SKILL.md`."""
    _touch(world.project / ".claude/skills" / skill / "SKILL.md", f"# {skill}\n")


def write_tool(world: CatalogWorld, name: str, *, marker: Path) -> Path:
    """An executable `bin/<name>` that creates `marker` when it is executed."""
    tool: Path = world.bin / name
    tool.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return tool


def world_environment(
    world: CatalogWorld, settings: Neo4jConnectionSettings, *, space: str = SPACE, **extra: str
) -> dict[str, str]:
    """C2's `store_environment` with the `claude_home`, `codex_home` and `bin` fixtures applied.

    `extra` wins over every default (session markers, another `CLAUDE_CONFIG_DIR`, ...).
    """
    return store_environment(
        world.home,
        space,
        settings,
        **{"PATH": str(world.bin), "CLAUDE_CONFIG_DIR": str(world.claude_home), **extra},
    )


def down_environment(world: CatalogWorld, *, space: str = SPACE, **extra: str) -> dict[str, str]:
    """The `down` fixture: `NOESIS_NEO4J_URI` is a closed local port."""
    closed: Neo4jConnectionSettings = Neo4jConnectionSettings(
        uri=f"bolt://127.0.0.1:{closed_port()}", user="neo4j", password=SecretStr("never-sent")
    )
    return world_environment(
        world,
        closed,
        space=space,
        **{"NOESIS_NEO4J_CONNECT_TIMEOUT_SECONDS": CLOSED_PORT_TIMEOUT_SECONDS, **extra},
    )


def start_catalog(
    world: CatalogWorld, args: Sequence[str], env: dict[str, str], *, json_output: bool = True
) -> subprocess.Popen[str]:
    """Start `python -m noesis ...` with `project` as working directory, without waiting."""
    command: list[str] = [
        sys.executable,
        "-m",
        "noesis",
        "--env-file",
        str(world.env_file),
        *args,
        *(["--json"] if json_output else []),
    ]
    return subprocess.Popen(
        command,
        env=env,
        cwd=world.project,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def run_catalog(
    world: CatalogWorld, args: Sequence[str], env: dict[str, str], *, json_output: bool = True
) -> ProcessResult:
    """Run one command to completion."""
    started: float = time.monotonic()
    return finish(start_catalog(world, args, env, json_output=json_output), started)


def _source_for(label: str) -> str:
    return f"url:https://example.invalid/{label}"


def register_argv(
    *,
    kind: str,
    name: str,
    key: str | None,
    purpose: str = "A test capability",
    location: str = "https://example.invalid/location",
    version: str | None = None,
    requires: Sequence[str] = (),
    sources: Sequence[str] | None = None,
) -> list[str]:
    """`catalog register ...` without `--json`; `key=None` omits `--idempotency-key`,
    `sources=None` is the `src` fixture and `sources=()` passes none."""
    argv: list[str] = [
        "catalog",
        "register",
        "--kind",
        kind,
        "--name",
        name,
        "--purpose",
        purpose,
        "--location",
        location,
    ]
    if version is not None:
        argv += ["--declared-version", version]
    for requirement in requires:
        argv += ["--requires", requirement]
    for source in [_source_for(name)] if sources is None else sources:
        argv += ["--source", source]
    if key is not None:
        argv += ["--idempotency-key", key]
    return argv


def revise_argv(
    ref: str,
    *,
    key: str | None,
    expected: int | str | None = 1,
    purpose: str | None = None,
    version: str | None = None,
    requires: Sequence[str] | None = None,
    location: str | None = None,
    sources: Sequence[str] | None = None,
) -> list[str]:
    """`catalog revise <ref> ...`; an option left at `None` is omitted (`""` is passed as given)."""
    argv: list[str] = ["catalog", "revise", ref]
    if expected is not None:
        argv += ["--expected-revision", str(expected)]
    for option, value in (
        ("--purpose", purpose),
        ("--declared-version", version),
        ("--location", location),
    ):
        if value is not None:
            argv += [option, value]
    for requirement in requires or ():
        argv += ["--requires", requirement]
    for source in [_source_for(ref)] if sources is None else sources:
        argv += ["--source", source]
    if key is not None:
        argv += ["--idempotency-key", key]
    return argv


def check_argv(*refs: str, kind: str | None = None, runtimes: Sequence[str] = ()) -> list[str]:
    """`catalog check [<ref>...] [--kind] [--runtime ...]`."""
    argv: list[str] = ["catalog", "check", *refs]
    if kind is not None:
        argv += ["--kind", kind]
    for runtime in runtimes:
        argv += ["--runtime", runtime]
    return argv


def scan_argv(runtimes: Sequence[str] = ()) -> list[str]:
    """`catalog scan [--runtime ...]`."""
    return ["catalog", "scan", *(part for runtime in runtimes for part in ("--runtime", runtime))]


def list_argv(*, kind: str | None = None, name_prefix: str | None = None) -> list[str]:
    """`catalog list [--kind] [--name-prefix]`."""
    argv: list[str] = ["catalog", "list"]
    if kind is not None:
        argv += ["--kind", kind]
    if name_prefix is not None:
        argv += ["--name-prefix", name_prefix]
    return argv


def show_argv(ref: str, *, revision: int | None = None) -> list[str]:
    """`catalog show <ref> [--revision N]`."""
    return ["catalog", "show", ref, *(["--revision", str(revision)] if revision else [])]


def blocks(result: ProcessResult) -> list[dict[str, Any]]:
    """`result.runtimes` of a `check` or `scan`."""
    runtimes: object = result.result["runtimes"]
    assert isinstance(runtimes, list)
    return runtimes


def file_snapshot(*roots: Path) -> dict[str, tuple[int, int]]:
    """Every file under `roots` with its size and mtime in nanoseconds."""
    return {
        str(path): (path.stat().st_size, path.stat().st_mtime_ns)
        for root in roots
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def graph_counts(settings: Neo4jConnectionSettings) -> tuple[int, int]:
    """How many nodes and relationships the whole graph holds."""
    nodes: int = query(settings, "MATCH (n) RETURN count(n) AS total")[0]["total"]
    relationships: int = query(settings, "MATCH ()-[r]->() RETURN count(r) AS total")[0]["total"]
    return nodes, relationships


def count_label(settings: Neo4jConnectionSettings, label: str) -> int:
    """How many nodes carry `label` (a fixed label of this suite, never user input)."""
    rows: list[dict[str, Any]] = query(
        settings, "MATCH (n) WHERE $label IN labels(n) RETURN count(n) AS total", label=label
    )
    return int(rows[0]["total"])


def space_id_of(settings: Neo4jConnectionSettings, key: str = SPACE) -> str:
    """The id of the space with `key`."""
    rows: list[dict[str, Any]] = query(
        settings, "MATCH (s:Space {key: $key}) RETURN s.id AS id", key=key
    )
    return str(rows[0]["id"])


def ledger_keys(settings: Neo4jConnectionSettings) -> list[str]:
    """The caller-chosen key of every idempotency ledger entry (the `<space_id>:` prefix removed)."""
    rows: list[dict[str, Any]] = query(settings, "MATCH (n:IdempotencyKey) RETURN n.key AS key")
    return sorted(str(row["key"]).split(":", 1)[1] for row in rows)
