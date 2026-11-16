"""Retrieval's structural rules that import-linter cannot express (AC-018, AC-030)."""

import ast
import inspect
from pathlib import Path
from typing import get_type_hints

import pytest

from noesis.bounded_context.retrieval.application.handlers.queries.find_similar_records_handler import (
    FindSimilarRecordsHandler,
)
from noesis.bounded_context.retrieval.application.handlers.queries.search_records_handler import (
    SearchRecordsHandler,
)
from noesis.bounded_context.retrieval.application.services.record_searcher import RecordSearcher
from noesis.bounded_context.retrieval.infrastructure.inbound.knowledge.related_record_finder_adapter import (
    RelatedRecordFinderAdapter,
)

pytestmark = pytest.mark.architecture

SRC: Path = Path(__file__).resolve().parents[2] / "src" / "noesis"
RETRIEVAL: Path = SRC / "bounded_context" / "retrieval"
FILE_READING_ATTRIBUTES: frozenset[str] = frozenset({"read_bytes", "read_text"})


def python_files(root: Path) -> list[Path]:
    files: list[Path] = sorted(root.rglob("*.py"))
    assert files, f"no Python module under {root}"
    return files


@pytest.mark.parametrize(
    "consumer", [SearchRecordsHandler, FindSimilarRecordsHandler, RelatedRecordFinderAdapter]
)
def test_search_consumers_take_the_record_searcher_and_nothing_else(consumer: type) -> None:
    """AC-018: no consumer repeats a pipeline step, so none holds a port of its own."""
    parameters = [
        name for name in inspect.signature(consumer.__init__).parameters if name != "self"
    ]
    hints = get_type_hints(consumer.__init__)

    assert len(parameters) == 1
    assert hints[parameters[0]] is RecordSearcher


def test_no_file_reading() -> None:
    """AC-030: Retrieval reads no file; every body arrives through `IIndexableRecordReader`."""
    offenders: list[str] = []
    for path in python_files(RETRIEVAL):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if (isinstance(function, ast.Name) and function.id == "open") or (
                isinstance(function, ast.Attribute) and function.attr in FILE_READING_ATTRIBUTES
            ):
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")

    assert offenders == []
    assert not (RETRIEVAL / "application" / "ports" / "sources").exists()


def test_no_module_under_src_imports_the_test_support() -> None:
    """The `probe` projection and fakes live in `tests/support` and never reach production."""
    offenders: list[str] = []
    for path in python_files(SRC):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules = [node.module]
            if any(module == "tests" or module.startswith("tests.") for module in modules):
                offenders.append(str(path.relative_to(SRC)))

    assert offenders == []
