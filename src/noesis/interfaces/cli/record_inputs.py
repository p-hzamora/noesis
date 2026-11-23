"""Option parsing shared by the commands that take a record's text, time or subtype."""

import sys
from datetime import UTC, datetime
from typing import Final

import typer

from noesis.bounded_context.knowledge.domain.value_objects import ExperienceSubtypeEnum

STDIN_MARKER: Final[str] = "-"


def usage(context: typer.Context, message: str, hint: str) -> typer.BadParameter:
    """A usage error (exit 2) naming the option at fault."""
    return typer.BadParameter(message, ctx=context, param_hint=hint)


def read_body(context: typer.Context, body: str | None, *, required: bool) -> str | None:
    """The text from `--body`; `-` reads stdin (never read implicitly, so nothing can block)."""
    if body is None:
        if required:
            raise usage(context, "Give the text with --body (use `-` for stdin).", "--body")
        return None
    return sys.stdin.read() if body == STDIN_MARKER else body


def parse_occurred(context: typer.Context, occurred: str | None) -> datetime | None:
    """The ISO 8601 `--occurred` time, UTC when it names no zone."""
    if occurred is None:
        return None
    try:
        moment: datetime = datetime.fromisoformat(occurred)
    except ValueError:
        raise usage(
            context, f"Expected an ISO 8601 time, got {occurred!r}.", "--occurred"
        ) from None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def required(context: typer.Context, value: str | None, option: str) -> str:
    """`value`, or a usage error when `option` was left out or blank."""
    if value is None or not value.strip():
        raise usage(context, f"{option} is required for this record type.", option)
    return value


def experience_subtype(context: typer.Context, subtype: str | None) -> ExperienceSubtypeEnum:
    """The experience subtype of `--subtype` (default observation)."""
    try:
        return ExperienceSubtypeEnum(subtype or ExperienceSubtypeEnum.OBSERVATION.value)
    except ValueError:
        allowed: str = ", ".join(item.value for item in ExperienceSubtypeEnum)
        raise usage(
            context, f"Unknown experience subtype {subtype!r}; use one of: {allowed}.", "--subtype"
        ) from None
