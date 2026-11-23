"""Ports are abstract base classes, so adapters inherit a real interface.

Outbound ports under `application/ports/` and the cross-context ports under
`shared_kernel/contracts/ports/` extend `abc.ABC`, never `typing.Protocol`. The only Protocols left
in `src/` shape third-party objects (and the specification pattern). Kernel ports import no
bounded context, so every context can depend on them.
"""

import ast
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.architecture

SRC_ROOT: Final[Path] = Path(__file__).resolve().parents[2] / "src" / "noesis"
KERNEL_PORTS: Final[Path] = SRC_ROOT / "shared_kernel" / "contracts" / "ports"
ALLOWED_PROTOCOLS: Final[frozenset[str]] = frozenset(
    {"EngineLike", "EncodingLike", "TokenizerLike", "SessionLike", "ISpecification"}
)


def _is_protocol(base: ast.expr) -> bool:
    """Whether a base expression is `Protocol`, `typing.Protocol` or `Protocol[...]`."""
    if isinstance(base, ast.Subscript):
        base = base.value
    return (isinstance(base, ast.Name) and base.id == "Protocol") or (
        isinstance(base, ast.Attribute) and base.attr == "Protocol"
    )


def _protocol_classes(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and any(_is_protocol(base) for base in node.bases)
    ]


def _port_files() -> list[Path]:
    files = [path for path in SRC_ROOT.rglob("*.py") if "application/ports/" in path.as_posix()]
    return [*files, *KERNEL_PORTS.rglob("*.py")]


def test_no_port_declares_protocol() -> None:
    offenders = [
        f"{path.relative_to(SRC_ROOT)}:{name}"
        for path in _port_files()
        for name in _protocol_classes(path)
    ]
    assert offenders == []


def test_only_third_party_shapes_and_specification_stay_protocol() -> None:
    found = {name for path in SRC_ROOT.rglob("*.py") for name in _protocol_classes(path)}
    assert found == ALLOWED_PROTOCOLS


def test_kernel_ports_import_no_bounded_context() -> None:
    files = list(KERNEL_PORTS.rglob("i_*.py"))
    assert files
    offenders: list[str] = []
    for path in files:
        for node in ast.walk(ast.parse(path.read_text())):
            modules = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            offenders += [
                f"{path.relative_to(SRC_ROOT)}: {module}"
                for module in modules
                if module.startswith("noesis.bounded_context")
            ]
    assert offenders == []
