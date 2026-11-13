"""Manifest merge and validation, kind catalog, path resolver, rank fusion."""

import pytest
from pydantic import ValidationError

from noesis.bounded_context.notes.application.dtos import NoteSummaryDto
from noesis.bounded_context.notes.application.services.manifest import (
    KindCatalog,
    Manifest,
    NotePathResolver,
    SourceRoleEnum,
    merge_manifest_data,
)
from noesis.bounded_context.notes.application.services.recall import RankedNotes, fuse_rankings
from noesis.bounded_context.notes.domain.value_objects import (
    NoteKind,
    NoteScope,
    NoteSlug,
)
from noesis.exceptions import InvalidManifestError, UnknownNoteKindError

pytestmark = pytest.mark.unit

DEFAULT: dict[str, object] = {
    "sources": [{"name": "vault", "type": "filesystem", "path": ".", "role": "primary"}],
    "layout": {
        "repo": "repos/{name}/{kind_folder}/{slug}.md",
        "topic": "learning/{name}/{kind_folder}/{slug}.md",
    },
    "kinds": [
        {"name": "decision", "folder": "decisions", "description": "d", "sections": ["Decision"]},
        {"name": "gotcha", "folder": "gotchas", "description": "g", "recall_weight": 1.0},
    ],
}


def _manifest(user: dict[str, object] | None = None) -> Manifest:
    return Manifest.model_validate(merge_manifest_data(DEFAULT, user or {}))


def test_default_alone_is_a_valid_manifest() -> None:
    manifest = _manifest()
    assert [kind.name for kind in manifest.kinds] == ["decision", "gotcha"]
    assert [s.role for s in manifest.sources] == [SourceRoleEnum.PRIMARY]


def test_merge_kinds_by_name_sources_whole_layout_per_key() -> None:
    user: dict[str, object] = {
        "kinds": [
            {"name": "decision", "folder": "adr", "description": "mine"},
            {"name": "recipe", "folder": "recipes", "description": "r"},
        ],
        "sources": [
            {"name": "main", "type": "filesystem", "path": "/notes", "role": "primary"},
            {"name": "ref", "type": "filesystem", "path": "/ref", "role": "read"},
        ],
        "layout": {"topic": "topics/{name}/{slug}.md"},
    }
    manifest = _manifest(user)
    by_name = {kind.name: kind for kind in manifest.kinds}
    assert list(by_name) == ["decision", "gotcha", "recipe"]  # defaults stay, new appended
    assert (by_name["decision"].folder, by_name["decision"].description) == ("adr", "mine")
    assert by_name["decision"].sections == ()  # the user's entry replaces the default whole
    assert [s.name for s in manifest.sources] == ["main", "ref"]  # list replaced, not merged
    assert manifest.layout.repo == "repos/{name}/{kind_folder}/{slug}.md"  # untouched key
    assert manifest.layout.topic == "topics/{name}/{slug}.md"  # overridden key


@pytest.mark.parametrize(
    "sources",
    [
        [],
        [
            {"name": "a", "type": "filesystem", "path": "/a", "role": "read"},
            {"name": "b", "type": "filesystem", "path": "/b", "role": "read"},
        ],
        [
            {"name": "a", "type": "filesystem", "path": "/a", "role": "primary"},
            {"name": "b", "type": "filesystem", "path": "/b", "role": "primary"},
        ],
    ],
)
def test_exactly_one_primary_source(sources: list[dict[str, str]]) -> None:
    with pytest.raises(InvalidManifestError):
        _manifest({"sources": sources})


def test_source_names_and_kind_names_must_be_unique() -> None:
    twice = {"name": "a", "type": "filesystem", "path": "/a", "role": "primary"}
    with pytest.raises(InvalidManifestError):
        _manifest({"sources": [twice, {**twice, "role": "read"}]})
    with pytest.raises(InvalidManifestError):
        Manifest.model_validate(
            {**DEFAULT, "kinds": [*DEFAULT["kinds"], DEFAULT["kinds"][0]]}  # type: ignore[index, misc]
        )


def test_layout_template_needs_a_slug_and_markdown_suffix() -> None:
    with pytest.raises(InvalidManifestError):
        _manifest({"layout": {"repo": "repos/{name}/note.md"}})
    with pytest.raises(InvalidManifestError):
        _manifest({"layout": {"repo": "repos/{name}/{slug}.txt"}})


def test_catalog_validates_kind_membership_and_resolves_specs() -> None:
    catalog: KindCatalog = _manifest().catalog()
    assert catalog.require(NoteKind(value="decision")).sections == ("Decision",)
    assert catalog.names() == ("decision", "gotcha")
    assert catalog.recall_weights() == {"decision": 0.8, "gotcha": 1.0}
    with pytest.raises(UnknownNoteKindError):
        catalog.require(NoteKind(value="poem"))
    assert catalog.find(NoteKind(value="poem")) is None


def test_path_resolver_uses_layout_and_suffixes_on_collision() -> None:
    manifest = _manifest()
    resolver = NotePathResolver(manifest.layout, manifest.catalog())
    scope, kind, slug = NoteScope.parse("repo:demo"), NoteKind(value="gotcha"), NoteSlug(value="x")
    paths = resolver.candidates(scope, kind, slug)
    assert [next(paths).value for _ in range(3)] == [
        "repos/demo/gotchas/x.md",
        "repos/demo/gotchas/x-2.md",
        "repos/demo/gotchas/x-3.md",
    ]
    topic = next(resolver.candidates(NoteScope.parse("topic:rust"), kind, slug))
    assert topic.value == "learning/rust/gotchas/x.md"


GROUPS: dict[str, object] = {
    "acme": {
        "root": "company/acme",
        "match": {"remotes": ["gitlab.com/acme/*"], "repos": ["legacy"]},
    },
    "other": {"root": "company/other", "match": {"remotes": ["gitlab.com/*"]}},
}


def _grouped() -> Manifest:
    return _manifest({"groups": GROUPS})


def test_a_grouped_repository_goes_under_its_group_root_and_others_stay_put() -> None:
    manifest = _grouped()
    resolver = NotePathResolver(manifest.layout, manifest.catalog(), manifest.groups)
    kind, slug = NoteKind(value="gotcha"), NoteSlug(value="x")

    def first(scope: str, remote: str | None) -> str:
        return next(resolver.candidates(NoteScope.parse(scope), kind, slug, remote)).value

    assert first("repo:svc", "gitlab.com/acme/svc") == "company/acme/repos/svc/gotchas/x.md"
    assert first("repo:legacy", None) == "company/acme/repos/legacy/gotchas/x.md"
    assert first("repo:svc", "gitlab.com/else/svc") == "company/other/repos/svc/gotchas/x.md"
    assert first("repo:svc", "github.com/me/svc") == "repos/svc/gotchas/x.md"
    assert first("repo:svc", None) == "repos/svc/gotchas/x.md"
    assert first("topic:rust", "gitlab.com/acme/svc") == "learning/rust/gotchas/x.md"


def test_the_first_matching_group_wins_in_manifest_order() -> None:
    swapped = _manifest({"groups": dict(reversed(list(GROUPS.items())))})  # type: ignore[arg-type]
    resolver = NotePathResolver(swapped.layout, swapped.catalog(), swapped.groups)
    scope, kind, slug = NoteScope.parse("repo:svc"), NoteKind(value="gotcha"), NoteSlug(value="x")
    path = next(resolver.candidates(scope, kind, slug, "gitlab.com/acme/svc"))
    assert path.value == "company/other/repos/svc/gotchas/x.md"


def test_the_grouped_template_can_be_overridden() -> None:
    manifest = _manifest(
        {"groups": GROUPS, "layout": {"grouped_repo": "{root}/{name}/{kind_folder}/{slug}.md"}}
    )
    resolver = NotePathResolver(manifest.layout, manifest.catalog(), manifest.groups)
    scope, kind, slug = (
        NoteScope.parse("repo:legacy"),
        NoteKind(value="gotcha"),
        NoteSlug(value="x"),
    )
    assert next(resolver.candidates(scope, kind, slug)).value == "company/acme/legacy/gotchas/x.md"


@pytest.mark.parametrize("root", ["/abs", "../out", "a/../../b", "", "/", "a\\b"])
def test_a_group_root_must_be_relative_and_inside_the_vault(root: str) -> None:
    with pytest.raises(InvalidManifestError):
        _manifest({"groups": {"g": {"root": root}}})


@pytest.mark.parametrize("name", ["Acme", "a b", "-a", "a/b"])
def test_a_group_name_must_be_a_plain_slug(name: str) -> None:
    with pytest.raises(InvalidManifestError):
        _manifest({"groups": {name: {"root": "company/x"}}})


def test_a_group_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        _manifest({"groups": {"g": {"root": "company/x", "remotes": ["a"]}}})


def _hit(note_id: str, path: str) -> NoteSummaryDto:
    return NoteSummaryDto(
        id=note_id, scope="repo:demo", path=path, title=path, kind="decision",
        origin="manual", updated=None, snippet="",
    )  # fmt: skip


def test_rank_fusion_dedups_by_id_and_primary_wins() -> None:
    primary = RankedNotes(primary=True, notes=(_hit("A", "p/a.md"), _hit("B", "p/b.md")))
    other = RankedNotes(primary=False, notes=(_hit("C", "o/c.md"), _hit("A", "o/a.md")))
    fused = fuse_rankings([other, primary], limit=10)
    assert [n.id for n in fused] == ["A", "C", "B"]  # A is ranked by both lists
    assert next(n.path for n in fused if n.id == "A") == "p/a.md"
    assert len(fuse_rankings([other, primary], limit=2)) == 2
