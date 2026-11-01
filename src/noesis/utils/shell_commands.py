"""Recognise git sub-commands inside shell command lines (chains, flags, quoted messages)."""

import shlex
from pathlib import Path

GIT_FLAGS_WITH_VALUE: frozenset[str] = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
)
SEPARATORS: str = ";\n|&"
QUOTES: str = "'\""


def split_commands(command: str) -> list[str]:
    """Split on `&&`, `||`, `|`, `;` and newlines, but never inside quotes.

    Commit messages routinely contain newlines inside quotes; a naive split would cut the
    message in half and leave an unbalanced quote.

    Args:
        command: A full shell command line.

    Returns:
        The simple commands it chains, in order.
    """
    parts: list[str] = []
    current: list[str] = []
    quote: str = ""
    index: int = 0
    while index < len(command):
        char: str = command[index]
        if char == "\\" and quote != "'" and index + 1 < len(command):
            current.append(command[index : index + 2])
            index += 2
            continue
        if quote:
            quote = "" if char == quote else quote
        elif char in QUOTES:
            quote = char
        elif char in SEPARATORS:
            parts.append("".join(current))
            current = []
            index += 2 if command[index : index + 2] in ("&&", "||") else 1
            continue
        current.append(char)
        index += 1
    parts.append("".join(current))
    return parts


def git_subcommand(simple_command: str) -> str | None:
    """git's sub-command in one simple command (`sudo git -C x commit -m y` -> `commit`).

    Args:
        simple_command: One command without chaining operators.

    Returns:
        The sub-command, or None when this is not a git invocation (or cannot be parsed).
    """
    try:
        tokens: list[str] = shlex.split(simple_command)
    except ValueError:
        return None
    while tokens and tokens[0] == "sudo":
        tokens.pop(0)
    if not tokens or Path(tokens[0]).name != "git":
        return None
    tokens.pop(0)
    while tokens and tokens[0].startswith("-"):
        tokens = tokens[2:] if tokens[0] in GIT_FLAGS_WITH_VALUE else tokens[1:]
    return tokens[0] if tokens else None


def is_git_commit(command: str | None) -> bool:
    """Whether some chained part of `command` runs `git [flags] commit` (`echo "git commit"` does not)."""
    return bool(command) and any(
        git_subcommand(part) == "commit" for part in split_commands(command or "")
    )
