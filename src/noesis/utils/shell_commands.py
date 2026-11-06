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


def commit_directory(command: str | None, cwd: Path) -> Path | None:
    """The directory a `git commit` in `command` runs in, when the command moves there itself.

    Follows `cd <dir> &&` chains and `git -C <dir>`, quote-aware and relative to `cwd`. It is
    a hint, not a verdict: forms it cannot read (subshells, `$VAR`, `pushd`) give None.

    Args:
        command: A full shell command line.
        cwd: Directory the command starts in.

    Returns:
        The resolved directory, or None when there is no commit or it runs in `cwd` itself.
    """
    current: Path = cwd
    moved: bool = False
    for part in split_commands(command or ""):
        try:
            tokens: list[str] = shlex.split(part)
        except ValueError:
            continue
        while tokens and tokens[0] == "sudo":
            tokens.pop(0)
        if tokens[:1] == ["cd"] and len(tokens) > 1 and not tokens[1].startswith("-"):
            if _unreadable(tokens[1]):
                return None
            current, moved = _join(current, tokens[1]), True
            continue
        if git_subcommand(part) == "commit":
            for value in _git_dash_c_values(tokens):
                if _unreadable(value):
                    return None
                current, moved = _join(current, value), True
            return current.resolve() if moved else None
    return None


def _unreadable(target: str) -> bool:
    """A path that needs the shell to expand it."""
    return "$" in target or "`" in target


def _join(base: Path, target: str) -> Path:
    path: Path = Path(target).expanduser()
    return path if path.is_absolute() else base / path


def _git_dash_c_values(tokens: list[str]) -> list[str]:
    """The `-C <dir>` values in front of git's sub-command, in order."""
    values: list[str] = []
    rest: list[str] = tokens[1:]
    while rest and rest[0].startswith("-"):
        if rest[0] == "-C" and len(rest) > 1:
            values.append(rest[1])
        rest = rest[2:] if rest[0] in GIT_FLAGS_WITH_VALUE else rest[1:]
    return values
