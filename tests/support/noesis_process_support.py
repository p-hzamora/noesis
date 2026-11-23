"""Run `python -m noesis` as a real child process with an explicit, minimal environment.

The parent test run may live inside a coding-agent harness and may have a user profile; a child
therefore never inherits `os.environ`: it gets a base built here, the Neo4j connection of the
container under test and whatever the test adds (NFR-004, AC-015).
"""

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

COMMAND_TIMEOUT_SECONDS: Final[float] = 120.0

_PTY_MASTERS: dict[int, int] = {}
"""Parent end of each pseudo-terminal handed to a child as standard input, by child pid."""


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """What one finished `noesis` process left behind."""

    code: int
    stdout: str
    stderr: str
    seconds: float

    @property
    def envelope(self) -> dict[str, object]:
        """The `--json` envelope printed on stdout."""
        parsed: object = json.loads(self.stdout)
        assert isinstance(parsed, dict), self.stdout
        return parsed

    @property
    def result(self) -> dict[str, object]:
        """`envelope["result"]` of a successful command."""
        assert self.envelope["ok"] is True, self.envelope
        result: object = self.envelope["result"]
        assert isinstance(result, dict)
        return result

    @property
    def error(self) -> dict[str, object]:
        """`envelope["error"]` of a failed command."""
        assert self.envelope["ok"] is False, self.envelope
        error: object = self.envelope["error"]
        assert isinstance(error, dict)
        return error


def base_environment(home: Path, space: str) -> dict[str, str]:
    """A minimal child environment: PATH, an isolated HOME/XDG tree and the knowledge space."""
    home.mkdir(parents=True, exist_ok=True)
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "CLAUDE_CONFIG_DIR": str(home / ".claude"),
        "USER": "e2e-user",
        "LOGNAME": "e2e-user",
        "NOESIS_KNOWLEDGE_SPACE": space,
    }


def store_environment(
    home: Path, space: str, settings: Neo4jConnectionSettings, **extra: str
) -> dict[str, str]:
    """`base_environment` plus the Neo4j connection of `settings`."""
    return {
        **base_environment(home, space),
        "NOESIS_NEO4J_URI": settings.uri,
        "NOESIS_NEO4J_USER": settings.user,
        "NOESIS_NEO4J_PASSWORD": settings.password.get_secret_value(),
        "NOESIS_NEO4J_DATABASE": settings.database,
        **extra,
    }


def _command(args: list[str], env_file: Path, *, json_output: bool) -> list[str]:
    tail: list[str] = ["--json"] if json_output else []
    return [sys.executable, "-m", "noesis", "--env-file", str(env_file), *args, *tail]


def start_noesis(
    args: list[str], env: dict[str, str], *, json_output: bool = True, tty: bool = False
) -> subprocess.Popen[str]:
    """Start a child without waiting, so several can race; collect it with `finish`.

    Args:
        args: The `noesis` arguments (without `--json`).
        env: The child's whole environment.
        json_output: Append `--json`.
        tty: Attach standard input to a pseudo-terminal (`pty.openpty()`, Linux and macOS only)
            so the child sees an interactive terminal; otherwise standard input is `/dev/null`.
    """
    home: Path = Path(env["HOME"])
    env_file: Path = home / "empty.env"
    env_file.touch()
    command: list[str] = _command(args, env_file, json_output=json_output)
    if not tty:
        return subprocess.Popen(
            command,
            env=env,
            cwd=home,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    import pty  # not available on Windows; imported only when a terminal is asked for

    master, slave = pty.openpty()
    try:
        process: subprocess.Popen[str] = subprocess.Popen(
            command,
            env=env,
            cwd=home,
            stdin=slave,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except BaseException:
        os.close(master)
        raise
    finally:
        os.close(slave)
    _PTY_MASTERS[process.pid] = master
    return process


def finish(process: subprocess.Popen[str], started: float) -> ProcessResult:
    """Wait for a child started by `start_noesis`."""
    try:
        stdout, stderr = process.communicate(timeout=COMMAND_TIMEOUT_SECONDS)
    finally:
        master: int | None = _PTY_MASTERS.pop(process.pid, None)
        if master is not None:
            os.close(master)
    return ProcessResult(process.returncode, stdout, stderr, time.monotonic() - started)


def run_noesis(
    args: list[str], env: dict[str, str], *, json_output: bool = True, tty: bool = False
) -> ProcessResult:
    """Run one `noesis` command to completion in its own process (`tty`: see `start_noesis`)."""
    started: float = time.monotonic()
    return finish(start_noesis(args, env, json_output=json_output, tty=tty), started)


def remember_command(
    key: str,
    *,
    title: str = "Retry policy",
    body: str = "Use retries.",
    record_type: str = "knowledge",
) -> list[str]:
    """A valid `remember` command line (without `--json`)."""
    source: list[str] = ["--source", "commit:" + "a" * 40]
    if record_type == "experience":
        return [
            "remember",
            "--as",
            "experience",
            "--body",
            body,
            "--subtype",
            "outcome",
            "--project",
            "demo",
            *source,
            "--idempotency-key",
            key,
        ]
    return [
        "remember",
        "--as",
        "knowledge",
        "--title",
        title,
        "--body",
        body,
        "--subtype",
        "decision",
        "--project",
        "demo",
        "--tag",
        "area:retries",
        *source,
        "--idempotency-key",
        key,
    ]
