"""Specification pattern: a named, pure business rule that can be composed with others."""

import abc
from typing import Protocol


class ISpecification[T](Protocol):
    """A rule a candidate either satisfies or not."""

    def is_satisfied_by(self, candidate: T) -> bool:
        """Whether `candidate` satisfies the rule."""
        ...


class Specification[T](abc.ABC):
    """Base for concrete specifications; adds `and_`, `or_` and `not_` composition."""

    @abc.abstractmethod
    def is_satisfied_by(self, candidate: T) -> bool:
        """Whether `candidate` satisfies the rule."""

    def and_(self, other: Specification[T]) -> Specification[T]:
        """Both rules hold."""
        return _AndSpecification(self, other)

    def or_(self, other: Specification[T]) -> Specification[T]:
        """At least one rule holds."""
        return _OrSpecification(self, other)

    def not_(self) -> Specification[T]:
        """The rule does not hold."""
        return _NotSpecification(self)


class _AndSpecification[T](Specification[T]):
    def __init__(self, left: Specification[T], right: Specification[T]) -> None:
        self._left: Specification[T] = left
        self._right: Specification[T] = right

    def is_satisfied_by(self, candidate: T) -> bool:
        return self._left.is_satisfied_by(candidate) and self._right.is_satisfied_by(candidate)


class _OrSpecification[T](Specification[T]):
    def __init__(self, left: Specification[T], right: Specification[T]) -> None:
        self._left: Specification[T] = left
        self._right: Specification[T] = right

    def is_satisfied_by(self, candidate: T) -> bool:
        return self._left.is_satisfied_by(candidate) or self._right.is_satisfied_by(candidate)


class _NotSpecification[T](Specification[T]):
    def __init__(self, inner: Specification[T]) -> None:
        self._inner: Specification[T] = inner

    def is_satisfied_by(self, candidate: T) -> bool:
        return not self._inner.is_satisfied_by(candidate)
