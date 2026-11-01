"""Specification composition."""

import pytest

from noesis.shared_kernel.domain.specifications import Specification

pytestmark = pytest.mark.unit


class _AtLeast(Specification[int]):
    def __init__(self, minimum: int) -> None:
        self._minimum: int = minimum

    def is_satisfied_by(self, candidate: int) -> bool:
        return candidate >= self._minimum


class _Even(Specification[int]):
    def is_satisfied_by(self, candidate: int) -> bool:
        return candidate % 2 == 0


@pytest.mark.parametrize(
    ("candidate", "expected_and", "expected_or", "expected_not"),
    [
        (4, True, True, False),
        (3, False, True, False),
        (2, False, True, True),
        (1, False, False, True),
    ],
)
def test_specifications_compose_with_and_or_not(
    candidate: int, expected_and: bool, expected_or: bool, expected_not: bool
) -> None:
    at_least_three: Specification[int] = _AtLeast(3)
    even: Specification[int] = _Even()

    assert at_least_three.and_(even).is_satisfied_by(candidate) is expected_and
    assert at_least_three.or_(even).is_satisfied_by(candidate) is expected_or
    assert at_least_three.not_().is_satisfied_by(candidate) is expected_not
