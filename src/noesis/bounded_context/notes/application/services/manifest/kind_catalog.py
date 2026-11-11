"""The kinds a manifest declares: the one place that knows which kinds exist."""

from noesis.bounded_context.notes.domain.value_objects import NoteKind
from noesis.exceptions import UnknownNoteKindError
from noesis.utils import FrozenObject

from .kind_spec import KindSpec


class KindCatalog(FrozenObject):
    """Looks kinds up by name or folder and validates `NoteKind` membership.

    Attributes:
        kinds: The kinds, in manifest order.
    """

    kinds: tuple[KindSpec, ...]

    def names(self) -> tuple[str, ...]:
        """Kind names, in manifest order."""
        return tuple(kind.name for kind in self.kinds)

    def find(self, kind: NoteKind) -> KindSpec | None:
        """The spec of `kind`, or None when the catalog does not list it."""
        return next((spec for spec in self.kinds if spec.name == kind.value), None)

    def require(self, kind: NoteKind) -> KindSpec:
        """The spec of `kind`.

        Raises:
            UnknownNoteKindError: The catalog does not list the kind.
        """
        spec: KindSpec | None = self.find(kind)
        if spec is None:
            raise UnknownNoteKindError(
                f"Unknown note kind {kind.value!r}.",
                {"kind": kind.value, "known": list(self.names())},
                next_steps=[f"Use one of: {', '.join(self.names())}."],
            )
        return spec

    def by_folder(self, folder: str) -> KindSpec | None:
        """The spec stored in `folder`, or None."""
        return next((spec for spec in self.kinds if spec.folder == folder), None)

    def recall_weights(self) -> dict[str, float]:
        """Recall weight per kind name."""
        return {spec.name: spec.recall_weight for spec in self.kinds}
