"""Start `noesis` through the probe launcher, the way `start_noesis` starts the production CLI."""

import subprocess
import sys
import time
from pathlib import Path
from typing import Final

from tests.support.noesis_process_support import ProcessResult, finish

LAUNCHER: Final[Path] = Path(__file__).with_name("noesis_with_probe.py")
DELAY_VARIABLE: Final[str] = "NOESIS_TEST_PROBE_DELAY_MS"


def start_noesis_with_probe(
    args: list[str], env: dict[str, str], *, delay_ms: int = 0, json_output: bool = True
) -> subprocess.Popen[str]:
    """Start `python <launcher> --env-file <f> <args> [--json]` without waiting.

    The child gets `env` (never the parent's environment) plus the probe delay; the working
    directory is the child's home, as for `start_noesis`.
    """
    home: Path = Path(env["HOME"])
    env_file: Path = home / "empty.env"
    env_file.touch()
    tail: list[str] = ["--json"] if json_output else []
    return subprocess.Popen(
        [sys.executable, str(LAUNCHER), "--env-file", str(env_file), *args, *tail],
        env={**env, DELAY_VARIABLE: str(delay_ms)},
        cwd=home,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def run_noesis_with_probe(
    args: list[str], env: dict[str, str], *, delay_ms: int = 0, json_output: bool = True
) -> ProcessResult:
    """Run one command through the probe launcher to completion."""
    started: float = time.monotonic()
    return finish(
        start_noesis_with_probe(args, env, delay_ms=delay_ms, json_output=json_output), started
    )
