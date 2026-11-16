"""Parsed links and their resolution within one vault scan."""

from dataclasses import dataclass
from typing import Literal

type LinkClass = Literal["resolved", "dangling", "ambiguous", "non_note", "not_imported", "self"]
type LinkType = Literal["links_to", "embeds"]


@dataclass(frozen=True, slots=True, kw_only=True)
class VaultLink:
    """One occurrence before text normalisation."""

    target: str
    anchor: str = ""
    alias: str = ""
    embed: bool = False
    markdown: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedLink:
    """A classified occurrence, with sorted candidates when ambiguous."""

    link: VaultLink
    classification: LinkClass
    path: str | None = None
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportedLink:
    """An outgoing edge grouped by target record and kind."""

    target_record_id: str
    link_type: LinkType
    count: int
    anchors: tuple[str, ...]
