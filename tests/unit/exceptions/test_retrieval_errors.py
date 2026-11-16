"""Error classes of the Retrieval context (spec 30, Errors)."""

import inspect
import re

import pytest

import noesis.exceptions as exceptions
from noesis.exceptions import (
    ApplicationException,
    IndexNotInitialisedError,
    IndexRebuildRequiredError,
    IndexSyncInProgressError,
    InfrastructureException,
    SemanticIndexUnavailableError,
    retrieval_errors,
)
from noesis.exceptions.exit_code_enum import ExitCodeEnum

pytestmark = pytest.mark.unit

CASES: list[tuple[type[Exception], str, type[Exception]]] = [
    (
        SemanticIndexUnavailableError,
        "RETRIEVAL_101_SEMANTIC_INDEX_UNAVAILABLE",
        InfrastructureException,
    ),
    (IndexNotInitialisedError, "RETRIEVAL_201_INDEX_NOT_INITIALISED", ApplicationException),
    (IndexRebuildRequiredError, "RETRIEVAL_202_INDEX_REBUILD_REQUIRED", ApplicationException),
    (IndexSyncInProgressError, "RETRIEVAL_203_INDEX_SYNC_IN_PROGRESS", ApplicationException),
]


@pytest.mark.parametrize(("error_class", "code", "base"), CASES)
def test_error_has_stable_code_failure_exit_code_and_layer(
    error_class: type[Exception], code: str, base: type[Exception]
) -> None:
    error = error_class("boom", {"k": "v"}, next_steps=["do this"])  # type: ignore[call-arg]

    assert error.error_code == code  # type: ignore[attr-defined]
    assert error.exit_code is ExitCodeEnum.FAILURE  # type: ignore[attr-defined]
    assert isinstance(error, base)
    assert error.metadata == {"k": "v"}  # type: ignore[attr-defined]
    assert error.next_steps == ("do this",)  # type: ignore[attr-defined]


def test_module_defines_only_the_four_codes() -> None:
    defined = {
        cls.__error_code__
        for _, cls in inspect.getmembers(retrieval_errors, inspect.isclass)
        if cls.__module__ == retrieval_errors.__name__
    }

    assert defined == {code for _, code, _ in CASES}


@pytest.mark.parametrize("name", [cls.__name__ for cls, _, _ in CASES])
def test_errors_are_re_exported_from_the_package(name: str) -> None:
    assert getattr(exceptions, name) is getattr(retrieval_errors, name)


@pytest.mark.parametrize(("first", "last"), [(102, 109), (204, 209)])
def test_module_docstring_names_the_reserved_blocks(first: int, last: int) -> None:
    docstring: str = retrieval_errors.__doc__ or ""

    assert re.search(rf"{first}\s*(\.\.|-|to)\s*{last}", docstring), docstring
