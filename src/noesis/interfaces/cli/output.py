"""One output path for every command: a JSON envelope for machines, text for people.

Success: `{"ok": true, "result": {...}}` on stdout.
Failure: `{"ok": false, "error": {"code", "title", "message", "metadata", "next_steps"}}`
on stdout with `--json`, or a short text block on stderr otherwise.
"""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

from noesis.exceptions import AppException
from noesis.utils import FrozenObject

from .responses import ErrorDetail, ErrorResponse, IRenderableResponse, SuccessResponse

_JSON_MODE: ContextVar[bool] = ContextVar("noesis_json_mode", default=False)


def _dump(response: FrozenObject) -> str:
    """Serialise an envelope; `serialize_as_any` keeps the concrete result's fields."""
    return response.model_dump_json(indent=2, serialize_as_any=True) + "\n"


@contextmanager
def output_scope() -> Iterator[None]:
    """Start one invocation in text mode and restore the previous mode afterwards.

    Without this, a `--json` flag from one in-process invocation (tests, embedding) would
    leak into the next one.
    """
    token: Token[bool] = _JSON_MODE.set(False)
    try:
        yield
    finally:
        _JSON_MODE.reset(token)


def remember_json_mode(enabled: bool) -> bool:
    """Typer option callback: record whether this invocation asked for `--json`.

    Args:
        enabled: The parsed `--json` flag.

    Returns:
        The flag unchanged, so Typer still passes it to the command.
    """
    if enabled:
        _JSON_MODE.set(True)
    return enabled


def json_mode() -> bool:
    """Whether the current invocation asked for JSON output."""
    return _JSON_MODE.get()


def emit(result: IRenderableResponse) -> None:
    """Print a successful result as the JSON envelope or as its own `render()` text.

    Args:
        result: The command's response; it serialises for machines and renders for people.
    """
    if json_mode():
        sys.stdout.write(_dump(SuccessResponse(result=result)))
    else:
        sys.stdout.write(result.render().rstrip("\n") + "\n")


def emit_error(error: AppException) -> None:
    """Print a deliberate error as the JSON envelope (stdout) or as text (stderr).

    Args:
        error: The error to report.
    """
    if json_mode():
        response = ErrorResponse(
            error=ErrorDetail(
                code=error.error_code,
                title=error.error_title(),
                message=error.message,
                metadata=error.metadata,
                next_steps=list(error.next_steps),
            )
        )
        sys.stdout.write(_dump(response))
        return
    lines: list[str] = [f"error [{error.error_code}]: {error.message}"]
    for key, value in error.metadata.items():
        if isinstance(value, list):
            lines += [f"  {key}: {item}" for item in value]
        else:
            lines.append(f"  {key}: {value}")
    lines += [f"  next: {step}" for step in error.next_steps]
    sys.stderr.write("\n".join(lines) + "\n")
