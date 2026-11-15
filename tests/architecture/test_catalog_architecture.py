"""C6 structural rules the import contracts cannot express (NFR-004, D-009, FR-012).

Read with `ast`; nothing is imported or executed.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

KNOWLEDGE: Path = Path(__file__).resolve().parents[2] / "src/noesis/bounded_context/knowledge"
FORBIDDEN_TOP_LEVEL: frozenset[str] = frozenset(
    {"os", "pathlib", "shutil", "tomllib", "neo4j", "pydantic_settings"}
)
FORBIDDEN_PREFIX: str = "noesis.diagnostics"
CATALOG_WORDS: tuple[str, ...] = ("catalog", "availability", "runtime", "host_tool")
FORBIDDEN_DOMAIN_TYPE_WORDS: tuple[str, ...] = ("observation", "inventory", "availability")
ALLOWED_UOW_MEMBERS: frozenset[str] = frozenset({"catalog_entries", "ledger", "commit", "changes"})
EXPECTED_CATALOG_MODULES: tuple[str, ...] = (
    "domain/value_objects/catalog_name.py",
    "domain/value_objects/catalog_ref.py",
    "domain/value_objects/catalog_revision.py",
    "domain/entities/catalog_entry.py",
    "domain/repositories/i_catalog_entry_repository.py",
    "application/dtos/catalog_entry_dto.py",
    "application/dtos/catalog_write_result_dto.py",
    "application/dtos/availability_report_dto.py",
    "application/dtos/runtime_enum.py",
    "application/dtos/availability_status_enum.py",
    "application/dtos/availability_reason_enum.py",
    "application/ports/runtime/i_runtime_inventory_probe.py",
    "application/ports/runtime/i_host_tool_probe.py",
    "application/ports/read_repositories/i_catalog_entry_read_repository.py",
)


def modules(layer: str) -> list[Path]:
    return sorted(p for p in (KNOWLEDGE / layer).rglob("*.py") if p.name != "__init__.py")


def is_catalog_module(path: Path) -> bool:
    relative: str = path.relative_to(KNOWLEDGE).as_posix()
    return any(word in relative for word in CATALOG_WORDS)


def imported_modules(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


def violates(module: str) -> bool:
    return module.split(".")[0] in FORBIDDEN_TOP_LEVEL or (
        module == FORBIDDEN_PREFIX or module.startswith(f"{FORBIDDEN_PREFIX}.")
    )


def test_catalog_layer_imports() -> None:
    """Catalog modules of domain and application stay free of I/O, driver and diagnostics imports."""
    missing: list[str] = [m for m in EXPECTED_CATALOG_MODULES if not (KNOWLEDGE / m).is_file()]
    catalog_modules: list[Path] = [
        p for p in [*modules("domain"), *modules("application")] if is_catalog_module(p)
    ]

    offenders: dict[str, list[str]] = {
        p.relative_to(KNOWLEDGE).as_posix(): sorted(m for m in imported_modules(p) if violates(m))
        for p in catalog_modules
        if any(violates(m) for m in imported_modules(p))
    }

    assert not missing, f"catalog modules not found: {missing}"
    assert offenders == {}


def test_no_observation_or_inventory_type_lives_in_the_domain() -> None:
    """Availability is application-side (D-002): domain defines no such class and imports no such DTO."""
    classes: list[str] = []
    imports_of_application_dtos: list[str] = []
    for path in modules("domain"):
        tree: ast.Module = ast.parse(path.read_text())
        classes += [
            f"{path.name}:{node.name}"
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            and any(word in node.name.lower() for word in FORBIDDEN_DOMAIN_TYPE_WORDS)
        ]
        imports_of_application_dtos += [
            f"{path.name}:{m}" for m in imported_modules(path) if "application" in m.split(".")
        ]

    assert classes == []
    assert imports_of_application_dtos == []


def own_uow_members(path: Path) -> set[str]:
    return {
        node.attr
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "uow"
    }


def test_catalog_handler_dependencies() -> None:
    """D-009: command handlers touch only catalog_entries, ledger, commit (and changes); check and scan touch no write side."""
    command_handlers: list[Path] = sorted(
        (KNOWLEDGE / "application/handlers/commands/catalog").glob("*_handler.py")
    )
    query_handlers: list[Path] = sorted(
        p
        for p in (KNOWLEDGE / "application/handlers/queries/catalog").glob("*.py")
        if any(word in p.stem for word in ("check", "scan"))
    )

    assert {p.stem for p in command_handlers} >= {
        "register_catalog_entry_handler",
        "revise_catalog_entry_handler",
    }
    assert len(query_handlers) >= 2, "expected check and scan handler modules"
    for path in command_handlers:
        extra: set[str] = own_uow_members(path) - ALLOWED_UOW_MEMBERS
        assert extra == set(), f"{path.name} uses uow members {sorted(extra)}"

    forbidden_words: tuple[str, ...] = ("uow", "unit_of_work", "unitofwork", "ledger")
    for path in query_handlers:
        names: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
            elif isinstance(node, ast.ImportFrom | ast.Import):
                names.update(a.asname or a.name.split(".")[-1] for a in node.names)
        write_side: list[str] = sorted(
            n
            for n in names
            if any(word in n.lower() for word in forbidden_words)
            or (n.endswith("Repository") and "Read" not in n)
        )
        assert write_side == [], f"{path.name} depends on write-side names {write_side}"
