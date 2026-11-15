"""AC-012 / NFR-001: `interop` has no code path that writes, renames or deletes a file.

Two checks: the read ports declare read methods only, and an AST scan of the whole context finds
no write-capable call. The scanner is itself tested on snippets, so a rule that stops matching
fails here instead of passing silently.
"""

import ast
from pathlib import Path

import pytest

from noesis.bounded_context.interop.application.ports import IFileReader, IVaultReader

pytestmark = pytest.mark.architecture

INTEROP_ROOT: Path = (
    Path(__file__).resolve().parents[2] / "src" / "noesis" / "bounded_context" / "interop"
)
WRITE_MODE_CHARACTERS: frozenset[str] = frozenset("wax+")
FORBIDDEN_METHODS: frozenset[str] = frozenset(
    {
        "write_text",
        "write_bytes",
        "unlink",
        "mkdir",
        "rmdir",
        "touch",
        "symlink_to",
        "hardlink_to",
        "chmod",
    }
)
FORBIDDEN_OS_CALLS: frozenset[str] = frozenset(
    {"remove", "unlink", "rename", "replace", "makedirs", "mkdir", "rmdir"}
)
FORBIDDEN_MODULES: frozenset[str] = frozenset({"shutil", "tempfile"})
INFRASTRUCTURE_ONLY_METHODS: frozenset[str] = frozenset({"rename", "replace"})


def _public_methods(port: type) -> set[str]:
    return {
        name for name, member in vars(port).items() if not name.startswith("_") and callable(member)
    }


def _open_mode(call: ast.Call, *, builtin: bool) -> ast.expr | None:
    """The `mode` argument of an `open` call: second positional for the builtin, else first."""
    for keyword in call.keywords:
        if keyword.arg == "mode":
            return keyword.value
    index: int = 1 if builtin else 0
    return call.args[index] if len(call.args) > index else None


def violations(source: str, *, infrastructure: bool) -> list[str]:
    """Write-capable constructs in `source`, as short descriptions."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [
                f"import {a.name}" for a in node.names if a.name.split(".")[0] in FORBIDDEN_MODULES
            ]
        elif isinstance(node, ast.ImportFrom):
            module: str = (node.module or "").split(".")[0]
            if module in FORBIDDEN_MODULES:
                found.append(f"from {node.module} import ...")
            if module == "os":
                found += [
                    f"from os import {a.name}" for a in node.names if a.name in FORBIDDEN_OS_CALLS
                ]
        elif isinstance(node, ast.Call):
            function: ast.expr = node.func
            if isinstance(function, ast.Name) and function.id == "open":
                found += _check_open(node, builtin=True)
            elif isinstance(function, ast.Attribute):
                name: str = function.attr
                if name == "open":
                    found += _check_open(node, builtin=False)
                if name in FORBIDDEN_METHODS:
                    found.append(f".{name}()")
                if (
                    isinstance(function.value, ast.Name)
                    and function.value.id == "os"
                    and name in FORBIDDEN_OS_CALLS
                ):
                    found.append(f"os.{name}()")
                if infrastructure and name in INFRASTRUCTURE_ONLY_METHODS:
                    found.append(f".{name}() in infrastructure")
    return found


def _check_open(call: ast.Call, *, builtin: bool) -> list[str]:
    mode: ast.expr | None = _open_mode(call, builtin=builtin)
    if mode is None:
        return []
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return ["open() for writing"] if WRITE_MODE_CHARACTERS & set(mode.value) else []
    return ["open() with a mode that is not a literal"]


def test_vault_reader_port_declares_exactly_list_notes_and_read() -> None:
    assert _public_methods(IVaultReader) == {"list_notes", "read"}


def test_file_reader_port_declares_exactly_resolve_and_read() -> None:
    assert _public_methods(IFileReader) == {"resolve", "read"}


def test_interop_sources_exist_so_the_scan_is_not_vacuous() -> None:
    assert len(list(INTEROP_ROOT.rglob("*.py"))) > 10


def test_interop_has_no_write_capable_call_or_import() -> None:
    problems: dict[str, list[str]] = {}
    for path in sorted(INTEROP_ROOT.rglob("*.py")):
        relative: str = path.relative_to(INTEROP_ROOT).as_posix()
        found: list[str] = violations(
            path.read_text(encoding="utf-8"), infrastructure=relative.startswith("infrastructure/")
        )
        if found:
            problems[relative] = found

    assert problems == {}


@pytest.mark.parametrize(
    ("source", "infrastructure", "expected"),
    [
        ("open('a', 'w')", False, ["open() for writing"]),
        ("open('a', mode='r+')", False, ["open() for writing"]),
        ("path.open('ab')", False, ["open() for writing"]),
        ("open('a', mode)", False, ["open() with a mode that is not a literal"]),
        ("open('a')", False, []),
        ("open('a', 'rb')", False, []),
        ("path.open('r')", False, []),
        ("path.write_text('x')", False, [".write_text()"]),
        ("path.write_bytes(b'x')", False, [".write_bytes()"]),
        ("path.unlink()", False, [".unlink()"]),
        ("path.mkdir()", False, [".mkdir()"]),
        ("path.chmod(0)", False, [".chmod()"]),
        ("path.symlink_to(other)", False, [".symlink_to()"]),
        ("os.remove('a')", False, ["os.remove()"]),
        ("os.makedirs('a')", False, ["os.makedirs()"]),
        ("os.rename('a', 'b')", False, ["os.rename()"]),
        ("import shutil", False, ["import shutil"]),
        ("from tempfile import mkdtemp", False, ["from tempfile import ..."]),
        ("from os import replace", False, ["from os import replace"]),
        ("path.rename('b')", True, [".rename() in infrastructure"]),
        ("path.replace('b')", True, [".replace() in infrastructure"]),
        ("path.rename('b')", False, []),
        ("text.replace('a', 'b')", False, []),
        ("os.path.join('a', 'b')", True, []),
    ],
)
def test_the_scanner_flags_what_the_rule_forbids_and_only_that(
    source: str, infrastructure: bool, expected: list[str]
) -> None:
    assert violations(source, infrastructure=infrastructure) == expected
