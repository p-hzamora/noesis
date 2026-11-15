"""Temporary folder fixtures shaped like the observed Claude Code and Codex layouts (C6 adapters)."""

import json
from pathlib import Path


def touch(path: Path, text: str = "") -> Path:
    """Create `path` (and its parents) with `text`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_registry(config_dir: Path, content: str) -> Path:
    """Write `plugins/installed_plugins.json` verbatim."""
    return touch(config_dir / "plugins" / "installed_plugins.json", content)


def empty_registry(config_dir: Path) -> Path:
    """A registry with no plugins, as the shared `claude_home` fixture has it."""
    return write_registry(config_dir, json.dumps({"version": 2, "plugins": {}}))


def add_claude_plugin(
    config_dir: Path,
    plugin: str,
    marketplace: str,
    version: str,
    *,
    skills: tuple[str, ...] = (),
    agents: tuple[str, ...] = (),
    skill_dirs_without_file: tuple[str, ...] = (),
) -> Path:
    """Register `<plugin>@<marketplace>` at `version` and create its skill and agent files.

    Returns:
        The plugin's `installPath`.
    """
    registry_path: Path = config_dir / "plugins" / "installed_plugins.json"
    registry: dict[str, object] = (
        json.loads(registry_path.read_text()) if registry_path.exists() else {"version": 2}
    )
    plugins: dict[str, list[dict[str, str]]] = registry.setdefault("plugins", {})  # type: ignore[assignment]
    install: Path = config_dir / "plugins" / plugin
    plugins[f"{plugin}@{marketplace}"] = [
        {"scope": "user", "installPath": str(install), "version": version}
    ]
    write_registry(config_dir, json.dumps(registry))
    for skill in skills:
        touch(install / "skills" / skill / "SKILL.md", "# skill")
    for agent in agents:
        touch(install / "agents" / f"{agent}.md", "# agent")
    for skill in skill_dirs_without_file:
        (install / "skills" / skill).mkdir(parents=True, exist_ok=True)
    return install


def add_codex_plugin(
    codex_home: Path,
    plugin: str,
    marketplace: str,
    version: str,
    *,
    skills: tuple[str, ...] = (),
    extra_lines: tuple[str, ...] = (),
) -> None:
    """Add `[plugins."<plugin>@<marketplace>"]` to `config.toml` and cache its skills."""
    config: Path = codex_home / "config.toml"
    existing: str = config.read_text() if config.exists() else ""
    table: str = "\n".join([f'[plugins."{plugin}@{marketplace}"]', "enabled = true", *extra_lines])
    touch(config, f"{existing}\n{table}\n")
    for skill in skills:
        touch(
            codex_home
            / "plugins"
            / "cache"
            / marketplace
            / plugin
            / version
            / "skills"
            / skill
            / "SKILL.md",
            "# skill",
        )
