"""Prerequisites before the resources that need them, bounded and cycle-safe."""

from collections.abc import Mapping, Sequence

from ..value_objects.load_order import LoadOrder

MAX_DEPTH = 3
MAX_ADDED = 10


class LoadOrderPolicy:
    """Topological order of selected roots and their prerequisites.

    Expansion stops at depth `MAX_DEPTH` from a root and after `MAX_ADDED` refs beyond the
    roots; a revisit on the current path is a cycle. Each stop is reported as a warning.
    """

    def order(self, roots: Sequence[str], prerequisites: Mapping[str, Sequence[str]]) -> LoadOrder:
        """Every ref after its prerequisites; roots keep their relative order."""
        root_set = frozenset(roots)
        done: set[str] = set()
        path: list[str] = []
        added: list[str] = []
        order: list[str] = []
        warnings: list[str] = []

        def visit(ref: str, depth: int) -> None:
            path.append(ref)
            for child in prerequisites.get(ref, ()):
                if child in path:
                    warnings.append(f"prerequisite cycle stopped at {child}")
                elif child in done:
                    continue
                elif depth + 1 > MAX_DEPTH:
                    warnings.append(f"prerequisite depth limit reached; truncated {child}")
                elif child not in root_set and len(added) >= MAX_ADDED:
                    warnings.append(f"prerequisite limit reached; truncated {child}")
                else:
                    if child not in root_set:
                        added.append(child)
                    visit(child, depth + 1)
            path.pop()
            done.add(ref)
            order.append(ref)

        for root in roots:
            if root not in done:
                visit(root, 0)
        return LoadOrder(
            order=tuple(order), added=tuple(added), warnings=tuple(dict.fromkeys(warnings))
        )
