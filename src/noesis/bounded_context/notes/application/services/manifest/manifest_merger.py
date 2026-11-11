"""Merges a user manifest over the packaged default; pure data, no file or YAML knowledge."""

from collections.abc import Mapping
from typing import Any


def merge_manifest_data(default: Mapping[str, Any], user: Mapping[str, Any]) -> dict[str, Any]:
    """The effective manifest data.

    Rules: `kinds` merge by name (the user's entry replaces the default entry whole, new names
    are appended, defaults cannot be removed); `sources` is replaced as a whole list;
    `layout` merges per scope type. Anything else the user adds is kept so validation can
    reject it.

    Args:
        default: The packaged manifest data.
        user: The user's manifest data (may be empty).

    Returns:
        New data to validate with `Manifest`.
    """
    merged: dict[str, Any] = {**default, **{k: v for k, v in user.items() if k not in _MERGED}}
    if "sources" in user:
        merged["sources"] = user["sources"]
    merged["layout"] = _merge_layout(default.get("layout"), user.get("layout"))
    merged["kinds"] = _merge_kinds(default.get("kinds"), user.get("kinds"))
    return merged


_MERGED: frozenset[str] = frozenset({"sources", "layout", "kinds"})


def _merge_layout(default: object, user: object) -> object:
    if user is None:
        return default
    if isinstance(default, Mapping) and isinstance(user, Mapping):
        return {**default, **user}
    return user  # malformed: validation reports it


def _merge_kinds(default: object, user: object) -> object:
    if user is None:
        return default
    if not isinstance(default, list) or not isinstance(user, list):
        return user
    by_name: dict[object, object] = {
        entry.get("name") if isinstance(entry, Mapping) else id(entry): entry for entry in default
    }
    for entry in user:
        key: object = entry.get("name") if isinstance(entry, Mapping) else id(entry)
        by_name[key] = entry
    return list(by_name.values())
