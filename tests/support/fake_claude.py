"""A fake `claude` executable for curator tests: prints a canned JSON envelope."""

import json
from pathlib import Path

from noesis.shared_kernel.domain import (
    JsonObject,
)


def write_fake_claude(
    folder: Path,
    *,
    envelope: JsonObject | None = None,
    raw: str | None = None,
    exit_code: int = 0,
    sleep_seconds: float = 0,
) -> Path:
    """Create an executable that records its stdin and argv, then prints `envelope` (or `raw`).

    Args:
        folder: Where to create the script (`claude`) and its records (`stdin.txt`, `argv.txt`).
        envelope: JSON to print, mimicking `claude -p --output-format json`.
        raw: Text to print instead of JSON.
        exit_code: Exit status of the fake.
        sleep_seconds: Delay before answering, to test timeouts.

    Returns:
        Path of the executable.
    """
    output: str = raw if raw is not None else json.dumps(envelope or {})
    script: Path = folder / "claude"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys, time\n"
        f"pathlib.Path({str(folder / 'stdin.txt')!r}).write_text(sys.stdin.read())\n"
        f"pathlib.Path({str(folder / 'argv.txt')!r}).write_text('\\n'.join(sys.argv[1:]))\n"
        f"time.sleep({sleep_seconds})\n"
        f"sys.stdout.write({output!r})\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def success_envelope(decisions: list[JsonObject]) -> JsonObject:
    """What a successful `claude -p --json-schema` run prints."""
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "",
        "structured_output": {"decisions": decisions},
        "total_cost_usd": 0.001,
    }


TTL_DECISION: JsonObject = {
    "action": "create",
    "candidate": "ttl cache",
    "reason": "rationale only in the conversation",
    "kind": "decision",
    "slug": "use-ttl-cache",
    "title": "Use a TTL cache",
    "sections": [
        {"heading": "Decision", "body": "In-process TTL cache (8e6d3b5f)."},
        {"heading": "Rationale", "body": "Single instance."},
    ],
}
