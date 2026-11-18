"""Note-to-record mapping through the preview handler: header split, title, tags, sources.

The importer is a recording fake, so each test reads the request the handler built for the note
(the published contract) and the result row; no mapper class is assumed.
"""

import hashlib
import json
from typing import Any

import pytest
from tests.support.import_support import C1SHA, K1, K2, K7
from tests.support.interop_support import (
    FakeKnowledgeImporter,
    current_header,
    note,
    plan,
    row,
)

from noesis.bounded_context.knowledge.domain.value_objects import Tag
from noesis.exceptions import AppException

pytestmark = pytest.mark.unit

PATH = "repos/alpha/a.md"
LOCATOR = f"vault://fixture/{PATH}"


async def _map(
    data: bytes, *, path: str = PATH, update: bool = False
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """The request the handler sent for `path` (None when it never reached Knowledge) and the row."""
    importer = FakeKnowledgeImporter()
    result = await plan({path: data}, importer, update=update)
    requests = importer.requests("assess")
    request = requests.get(f"vault://fixture/{path}")
    return (request.model_dump(mode="json") if request else None), row(result, path)


def _header_with_sources(sources: object, record_id: str = K1) -> str:
    return (
        current_header(id=record_id, scope="repo:alpha", kind="concept")
        + f"\n  sources: {json.dumps(sources)}"
    )


async def test_current_layout_maps_every_request_field() -> None:
    raw: bytes = note(
        "# Ports\n\nText.",
        "tags: [architecture, Python]\n"
        + current_header(id=K1, scope="repo:alpha", kind="concept", origin="manual")
        + f"\n  updated: 2026-11-01\n  sources: [commit:{C1SHA}]",
    )

    request, result_row = await _map(raw)

    assert request == {
        "contract_version": 1,
        "space_key": "personal",
        "record_id": K1,
        "origin_tag": "origin:migrated",
        "title": "Ports",
        "body": "# Ports\n\nText.",
        "subtype": "concept",
        "project_key": "alpha",
        "tags": ["architecture", "python"],
        "source_locator": LOCATOR,
        "source_digest": f"sha256:{hashlib.sha256(raw).hexdigest()}",
        "header_sources": [{"kind": "commit", "locator": C1SHA}],
        "actor": {"kind": "user", "name": "tester", "session": None},
        "on_change": "report",
    }
    assert result_row["warnings"] == []


@pytest.mark.parametrize(("update", "expected"), [(False, "report"), (True, "update")])
async def test_on_change_follows_the_update_flag(update: bool, expected: str) -> None:
    request, _ = await _map(note("Text."), update=update)

    assert request is not None and request["on_change"] == expected


async def test_topic_scope_gives_a_topic_tag_and_no_project() -> None:
    request, _ = await _map(
        note("Text.", current_header(id=K1, scope="topic:python", kind="concept"))
    )

    assert request is not None
    assert request["project_key"] is None
    assert request["tags"] == ["topic:python"]


async def test_header_less_note_gets_defaults_from_its_file_name_and_no_warning() -> None:
    request, result_row = await _map(note("Prose only."), path="notes/my_note-name.md")

    assert request is not None
    assert (request["record_id"], request["subtype"], request["project_key"]) == (
        None,
        "note",
        None,
    )
    assert request["title"] == "my note name"
    assert request["tags"] == []
    assert result_row["warnings"] == []


@pytest.mark.parametrize(
    ("scope", "reason"),
    [
        ("team:core", "invalid_scope"),
        ("repo", "invalid_scope"),
        ("topic:Not A Slug", "invalid_scope"),
    ],
)
async def test_invalid_scope_blocks_the_note_before_knowledge(scope: str, reason: str) -> None:
    request, result_row = await _map(note("x", current_header(id=K1, scope=scope, kind="concept")))

    assert request is None
    assert (result_row["outcome"], result_row["reason"]) == ("blocked", reason)


async def test_project_name_that_is_not_a_key_is_left_to_knowledge() -> None:
    request, _ = await _map(note("x", current_header(id=K1, scope="repo:bad name", kind="concept")))

    assert request is not None and request["project_key"] == "bad name"


async def test_noesis_that_is_not_a_mapping_blocks_as_invalid_header() -> None:
    request, result_row = await _map(note("x", "noesis: text"))

    assert request is None
    assert (result_row["outcome"], result_row["reason"]) == ("blocked", "invalid_header")


async def test_invalid_ulid_blocks_as_invalid_id_and_reports_no_record_id() -> None:
    request, result_row = await _map(
        note("x", current_header(id="not-a-ulid", scope="repo:alpha", kind="concept"))
    )

    assert request is None
    assert (result_row["reason"], result_row["record_id"]) == ("invalid_id", None)


async def test_the_same_ulid_in_two_notes_blocks_both_and_the_others_still_go() -> None:
    header: str = current_header(id=K7, scope="repo:alpha", kind="concept")
    importer = FakeKnowledgeImporter()

    result = await plan(
        {"a.md": note("a", header), "b.md": note("b", header), "c.md": note("c")}, importer
    )

    assert [row(result, p)["reason"] for p in ("a.md", "b.md")] == ["duplicate_id"] * 2
    assert [row(result, p)["record_id"] for p in ("a.md", "b.md")] == [K7, K7]
    assert [locator for _, locator in importer.sequence()] == ["vault://fixture/c.md"]
    assert result["blocked_reasons"] == {"duplicate_id": 2}


@pytest.mark.parametrize(
    ("header", "kwargs"),
    [
        pytest.param(
            "type: learning\ntopic: python\narea: backend\ntags: [draft, two words]",
            {
                "subtype": "learning",
                "project_key": None,
                "tags": ["area:backend", "draft", "topic:python"],
            },
            id="topic-area-and-tags",
        ),
        pytest.param(
            "type: runbook\nproject: alpha\nrepo: beta",
            {"subtype": "runbook", "project_key": "alpha", "tags": []},
            id="project-wins-over-repo",
        ),
        pytest.param(
            "type: runbook\nrepo: beta",
            {"subtype": "runbook", "project_key": "beta", "tags": []},
            id="repo",
        ),
        pytest.param(
            "tags: single",
            {"subtype": "note", "project_key": None, "tags": ["single"]},
            id="tags-as-one-string",
        ),
        pytest.param(
            f"id: {K1}\ntype: general",
            {"subtype": "general", "project_key": None, "tags": []},
            id="top-level-id-is-ignored",
        ),
        pytest.param(
            f"type: learning\nsources: [commit:{C1SHA}]",
            {"subtype": "learning", "project_key": None, "tags": []},
            id="top-level-sources-are-not-read",
        ),
    ],
)
async def test_older_layout_mapping(header: str, kwargs: dict[str, Any]) -> None:
    request, result_row = await _map(note("# Old\n\nText.", header))

    assert request is not None
    assert request["record_id"] is None
    assert {key: request[key] for key in kwargs} == kwargs
    assert request["header_sources"] == []
    assert "legacy_header" in result_row["warnings"]


async def test_older_layout_drops_an_invalid_tag_with_a_warning_and_keeps_the_note() -> None:
    result = await plan({PATH: note("Text.", "type: learning\ntags: [draft, two words]")})

    assert result["warnings"] == {"legacy_header": 1, "dropped_tag": 1, "ignored_field": 0}
    assert sorted(row(result, PATH)["warnings"]) == ["dropped_tag:two words", "legacy_header"]


async def test_current_layout_warns_for_each_top_level_key_outside_the_block() -> None:
    header: str = (
        "title: T\ntags: [a]\ncommit: 965bc44\nrelated:\n- id: x\n  relation: part_of\n"
        + current_header(id=K1, scope="repo:alpha", kind="concept")
    )

    result = await plan({PATH: note("Text.", header)})

    assert row(result, PATH)["warnings"] == ["ignored_field:commit", "ignored_field:related"]
    assert result["warnings"]["ignored_field"] == 2


async def test_older_layout_warns_for_each_key_it_does_not_read() -> None:
    header: str = "type: index\nrepo: dafne\nid: dafne--index\ndate: 2026-10-12\ntags: [index]"

    request, result_row = await _map(note("Text.", header))

    assert request is not None and request["project_key"] == "dafne"
    assert result_row["warnings"] == ["legacy_header", "ignored_field:date", "ignored_field:id"]


async def test_older_layout_drops_a_topic_that_is_not_a_slug_with_a_warning() -> None:
    request, result_row = await _map(note("Text.", "type: learning\ntopic: Not A Slug"))

    assert request is not None and request["tags"] == []
    assert any(warning.startswith("dropped_tag:") for warning in result_row["warnings"])
    assert result_row["outcome"] != "blocked"


async def test_empty_header_is_an_older_layout_with_the_body_after_it() -> None:
    request, result_row = await _map(b"---\n---\nBody after.")

    assert request is not None and request["body"] == "Body after."
    assert result_row["warnings"] == ["legacy_header"]


async def test_tag_rule_agrees_with_the_knowledge_tag_on_a_fixed_list() -> None:
    values: list[str] = [
        "valid",
        "Upper",
        " spaced ",
        "with space",
        ".dotfiles",
        "pm_inma",
        "a__b",
        "a:b:c",
        "facet:",
        "area:core",
    ]
    accepted: list[str] = []
    rejected: list[str] = []
    for value in values:
        try:
            accepted.append(Tag(value=value).value)
        except AppException:
            rejected.append(value.strip().lower())
    header: str = (
        "tags: "
        + json.dumps(values)
        + "\n"
        + current_header(id=K1, scope="repo:alpha", kind="concept")
    )

    request, result_row = await _map(note("x", header))

    assert request is not None
    assert request["tags"] == sorted(set(accepted))
    assert sorted(w for w in result_row["warnings"] if w.startswith("dropped_tag:")) == sorted(
        f"dropped_tag:{value}" for value in rejected
    )
    assert rejected == ["with space", "a__b", "a:b:c", "facet:"]


@pytest.mark.parametrize(
    ("sources", "expected", "skipped"),
    [
        pytest.param([f"commit:{C1SHA}"], [{"kind": "commit", "locator": C1SHA}], 0, id="commit"),
        pytest.param(
            [f"commit:{C1SHA.upper()}"],
            [{"kind": "commit", "locator": C1SHA}],
            0,
            id="commit-uppercase-lowercased",
        ),
        pytest.param(["commit:abc123"], [], 1, id="six-char-commit-skipped"),
        pytest.param(
            ["commit:6876F8F"],
            [{"kind": "commit", "locator": "6876f8f"}],
            0,
            id="short-commit-lowercased",
        ),
        pytest.param(
            ["session:s-1"], [{"kind": "agent_session", "locator": "s-1"}], 0, id="session"
        ),
        pytest.param(
            ["url:https://x.y/z"],
            [{"kind": "url", "locator": "https://x.y/z"}],
            0,
            id="url-keeps-the-colon-text",
        ),
        pytest.param(
            ["work_brief:k1"], [{"kind": "work_brief", "locator": "k1"}], 0, id="work-brief"
        ),
        pytest.param(["file_version:x"], [], 1, id="file-version-skipped"),
        pytest.param(["bogus:x"], [], 1, id="unknown-prefix"),
        pytest.param(["nocolon"], [], 1, id="no-colon"),
        pytest.param(["commit:"], [], 1, id="empty-value"),
        pytest.param(
            ["session:s-1", "session:s-1"],
            [{"kind": "agent_session", "locator": "s-1"}],
            0,
            id="duplicates-collapse",
        ),
        pytest.param(
            ["url:https://a", "session:s", f"commit:{C1SHA}"],
            [
                {"kind": "url", "locator": "https://a"},
                {"kind": "agent_session", "locator": "s"},
                {"kind": "commit", "locator": C1SHA},
            ],
            0,
            id="header-order-is-kept",
        ),
        pytest.param("not-a-list", [], 1, id="string-instead-of-list"),
        pytest.param({"a": "b"}, [], 1, id="mapping-instead-of-list"),
        pytest.param(
            [5, "session:s"], [{"kind": "agent_session", "locator": "s"}], 1, id="non-string-entry"
        ),
    ],
)
async def test_header_sources_table(
    sources: object, expected: list[dict[str, str]], skipped: int
) -> None:
    importer = FakeKnowledgeImporter()
    result = await plan({PATH: note("x", _header_with_sources(sources))}, importer)

    request = importer.requests("assess")[LOCATOR].model_dump(mode="json")
    assert request["header_sources"] == expected
    assert result["sources_skipped"] == skipped


async def test_sources_skipped_adds_up_over_notes() -> None:
    files = {
        "a.md": note("a", _header_with_sources(["bogus:x"])),
        "b.md": note("b", _header_with_sources(["commit:1", "session:s"], K2)),
        "c.md": note("c"),
    }

    result = await plan(files)

    assert result["sources_skipped"] == 2


@pytest.mark.parametrize(
    ("data", "title"),
    [
        pytest.param(
            note("# Heading\n\nx", "title: Header title"), "Header title", id="header-title-wins"
        ),
        pytest.param(
            note("# Heading\n\nx", "title: '   '"), "Heading", id="blank-header-title-falls-to-h1"
        ),
        pytest.param(note("```\n# in fence\n```\n\nx"), "a", id="h1-in-a-fence-is-ignored"),
        pytest.param(note("# [[x|y]]\n\nbody"), "y", id="link-in-h1-becomes-its-text"),
        pytest.param(note("#   Spaced title  \n\nbody"), "Spaced title", id="h1-is-trimmed"),
        pytest.param(note("# \n\nbody"), "a", id="empty-h1-falls-to-the-stem"),
        pytest.param(note("## Level two\n\nbody"), "a", id="only-level-one-counts"),
        pytest.param(
            note("intro\n\n# Later heading\n\nbody"), "Later heading", id="first-h1-anywhere"
        ),
    ],
)
async def test_title_rule(data: bytes, title: str) -> None:
    request, _ = await _map(data, path="a.md")

    assert request is not None and request["title"] == title


@pytest.mark.parametrize(
    ("path", "title"),
    [
        ("learning/python/concepts/diseño-hexagonal.md", "diseño hexagonal"),
        ("README.md", "README"),
        ("a/under_score-dash.md", "under score dash"),
    ],
)
async def test_title_falls_back_to_the_file_stem_with_hyphens_and_underscores_as_spaces(
    path: str, title: str
) -> None:
    request, _ = await _map(note("no heading here"), path=path)

    assert request is not None and request["title"] == title


async def test_e10_header_removed_and_title_from_the_header() -> None:
    data: bytes = note("# Body heading\n\nText with [[x|y]].", "title: Header title\ntags: [demo]")

    request, _ = await _map(data)

    assert request is not None
    assert request["body"] == "# Body heading\n\nText with y."
    assert request["title"] == "Header title"
    assert request["tags"] == ["demo"]


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"---\ntitle: x\nBody without a closing line", id="no-closing-line"),
        pytest.param(b"---\n- a\n- b\n---\nBody", id="header-is-a-list"),
        pytest.param(b"---\ntitle: [unclosed\n---\nBody", id="yaml-error"),
        pytest.param(b"---\ntitle: x\n--- not closing\nBody", id="closing-line-with-text"),
    ],
)
async def test_unusable_header_blocks_as_invalid_header(data: bytes) -> None:
    request, result_row = await _map(data)

    assert request is None
    assert (result_row["outcome"], result_row["reason"]) == ("blocked", "invalid_header")


async def test_closing_line_may_carry_trailing_spaces_and_tabs() -> None:
    request, _ = await _map(b"---\ntitle: T\n---  \t\nBody")

    assert request is not None and request["body"] == "Body" and request["title"] == "T"


async def test_bom_and_crlf_give_the_body_of_the_lf_file_and_the_digest_of_the_raw_bytes() -> None:
    lf: bytes = note("# H\n\nLine two.", "title: T")
    crlf: bytes = b"\xef\xbb\xbf" + note("# H\n\nLine two.", "title: T", newline="\r\n")
    lone_cr: bytes = note("a\n\nb", None, newline="\r")

    plain, _ = await _map(lf)
    odd, _ = await _map(crlf)
    cr_request, _ = await _map(lone_cr)

    assert plain is not None and odd is not None and cr_request is not None
    assert odd["body"] == plain["body"] == "# H\n\nLine two."
    assert odd["title"] == "T"
    assert odd["source_digest"] == f"sha256:{hashlib.sha256(crlf).hexdigest()}"
    assert odd["source_digest"] != plain["source_digest"]
    assert cr_request["body"] == "a\n\nb"


async def test_bytes_that_are_not_utf8_block_as_not_text() -> None:
    request, result_row = await _map(b"\xff\xfe\x00\x01")

    assert request is None
    assert (result_row["outcome"], result_row["reason"]) == ("blocked", "not_text")


async def test_secrets_are_not_redacted_by_interop() -> None:
    request, _ = await _map(note("api_key = abcdefghijklmnop1234"))

    assert request is not None and "abcdefghijklmnop1234" in request["body"]


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"", id="zero-bytes"),
        pytest.param(b"---\ntitle: x\n---\n", id="header-only"),
        pytest.param(note("# Index\n\n## Projects\n\n- [[a]]\n- [[b]]"), id="links-only-hub"),
        pytest.param(note("  \n\t\n"), id="whitespace-only"),
    ],
)
async def test_a_note_with_no_body_is_skipped_empty_without_a_knowledge_call(data: bytes) -> None:
    importer = FakeKnowledgeImporter()

    result = await plan({PATH: data}, importer)

    assert row(result, PATH)["outcome"] == "skipped_empty"
    assert importer.calls == []
    assert result["totals"]["skipped_empty"] == 1


async def test_skipped_empty_reports_the_declared_ulid_only() -> None:
    declared = note("", current_header(id=K1, scope="repo:alpha", kind="concept"))

    result = await plan({"declared.md": declared, "none.md": b""})

    assert row(result, "declared.md")["record_id"] == K1
    assert row(result, "none.md")["record_id"] is None


async def test_warnings_count_notes_that_are_then_skipped_empty() -> None:
    result = await plan({"hub.md": note("# Index\n\n- [[a]]", "type: index\ntopic: python")})

    assert row(result, "hub.md")["outcome"] == "skipped_empty"
    assert result["warnings"]["legacy_header"] == 1


@pytest.mark.parametrize(
    ("header", "record_id", "reason", "subtype"),
    [
        pytest.param(f"noesis:\n  id: {K1}\n  kind:", K1, None, "note", id="null-kind-is-note"),
        pytest.param("noesis:\n  id:", None, None, "note", id="null-id-is-absent"),
        pytest.param('noesis:\n  id: ""', None, "invalid_id", None, id="blank-id-is-invalid"),
        pytest.param('noesis:\n  kind: ""', None, None, "", id="blank-kind-is-passed-through"),
        pytest.param("type:", None, None, "note", id="null-type-is-note"),
        pytest.param('type: ""', None, None, "", id="blank-type-is-passed-through"),
    ],
)
async def test_null_is_absent_and_a_blank_string_is_validated_as_written(
    header: str, record_id: str | None, reason: str | None, subtype: str | None
) -> None:
    request, result_row = await _map(note("Text.", header))

    if reason is not None:
        assert request is None and result_row["reason"] == reason
        return
    assert request is not None
    assert (request["record_id"], request["subtype"]) == (record_id, subtype)
