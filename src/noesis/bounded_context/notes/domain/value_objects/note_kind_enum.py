"""What a note records; each kind has its folder and its required sections."""

from enum import StrEnum


class NoteKindEnum(StrEnum):
    """The four kinds of durable knowledge noesis keeps."""

    DECISION = "decision"
    GOTCHA = "gotcha"
    RUN = "run"
    GLOSSARY = "glossary"

    @property
    def folder(self) -> str:
        """Folder name inside an area (`decisions`, `gotchas`, `runs`, `glossary`)."""
        return "glossary" if self is NoteKindEnum.GLOSSARY else f"{self.value}s"

    @property
    def required_sections(self) -> tuple[str, ...]:
        """Headings every note of this kind has, in order."""
        return _REQUIRED_SECTIONS[self]

    @classmethod
    def from_folder(cls, folder: str) -> NoteKindEnum | None:
        """The kind stored in `folder`, or None when the folder holds no kind."""
        return next((kind for kind in cls if kind.folder == folder), None)


_REQUIRED_SECTIONS: dict[NoteKindEnum, tuple[str, ...]] = {
    NoteKindEnum.DECISION: ("Decision", "Rationale", "Consequences", "Alternatives rejected"),
    NoteKindEnum.GOTCHA: ("Symptom", "Cause", "Fix or workaround"),
    NoteKindEnum.RUN: ("Outcome", "Delivered", "Remaining work"),
    NoteKindEnum.GLOSSARY: ("Definition", "Avoid"),
}
