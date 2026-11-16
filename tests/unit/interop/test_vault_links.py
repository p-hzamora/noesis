"""Pure parsing, resolution and grouping of links before normalisation."""

import pytest

from noesis.bounded_context.interop.domain.services.link_parser import LinkParser
from noesis.bounded_context.interop.domain.services.link_set_builder import LinkSetBuilder
from noesis.bounded_context.interop.domain.services.link_target_index import LinkTargetIndex
from noesis.bounded_context.interop.domain.value_objects.vault_link import VaultLink

pytestmark = pytest.mark.unit


def test_parse_wiki_markdown_and_code() -> None:
    links = LinkParser().parse("""[[note|alias]] ![[other\\|label]] [[note#Heading]] [[#^block]]
[x](../my%20note.md#^abc) [y](<my note.md> "title")
[z](x.md "title") [web](https://x/y.md) [mail](mailto:a.md) [anchor](#h)
`[[ignored]]` ``[ignored](x.md)``
~~~
[[ignored]]
~~~
## See also
- [[last]]
""")
    assert [
        (link.target, link.anchor, link.alias, link.embed, link.markdown) for link in links
    ] == [
        ("note", "", "alias", False, False),
        ("other", "", "label", True, False),
        ("note", "Heading", "", False, False),
        ("", "^block", "", False, False),
        ("../my note.md", "^abc", "", False, True),
        ("my note.md", "", "", False, True),
        ("x.md", "", "", False, True),
        ("last", "", "", False, False),
    ]


@pytest.mark.parametrize(
    ("target", "source", "markdown", "classification", "path"),
    [
        ("folder/café", "root.md", False, "resolved", "folder/cafe\u0301.md"),
        ("FOLDER/CAFÉ.MD", "root.md", False, "resolved", "folder/cafe\u0301.md"),
        ("café", "root.md", False, "resolved", "folder/cafe\u0301.md"),
        ("sub/x", "root.md", False, "resolved", "folder/sub/x.md"),
        ("dup", "a/source.md", False, "resolved", "a/dup.md"),
        ("dup", "root.md", False, "ambiguous", None),
        ("v1.2", "root.md", False, "resolved", "v1.2.md"),
        ("2024.01.05", "root.md", False, "resolved", "2024.01.05.md"),
        ("x.png", "root.md", False, "non_note", None),
        ("../root", "a/source.md", False, "resolved", "root.md"),
        ("./dup", "a/source.md", False, "resolved", "a/dup.md"),
        ("../root.md", "a/source.md", True, "resolved", "root.md"),
        ("../../root.md", "a/source.md", True, "dangling", None),
        ("../root", "root.md", False, "dangling", None),
        ("none", "root.md", False, "dangling", None),
        ("root", "root.md", False, "self", "root.md"),
        ("", "root.md", False, "self", None),
    ],
)
def test_resolution(target, source, markdown, classification, path) -> None:
    index = LinkTargetIndex(
        [
            "root.md",
            "folder/cafe\u0301.md",
            "folder/sub/x.md",
            "a/dup.md",
            "b/dup.md",
            "v1.2.md",
            "2024.01.05.md",
        ]
    )
    result = index.resolve(VaultLink(target=target, markdown=markdown), source=source)
    assert (result.classification, result.path) == (classification, path)
    if classification == "ambiguous":
        assert result.candidates == ("a/dup.md", "b/dup.md")


def test_partial_ambiguity_and_same_folder_case_collision() -> None:
    index = LinkTargetIndex(["a/sub/x.md", "b/sub/x.md", "a/dup.md", "a/DUP.md"])
    for target in ("sub/x", "dup"):
        result = index.resolve(VaultLink(target=target), source="a/source.md")
        assert result.classification == "ambiguous"
        assert result.candidates == tuple(sorted(result.candidates))


def test_group_counts_anchors_embeds_and_missing_imports() -> None:
    index = LinkTargetIndex(["a.md", "b.md", "c.md"])
    links = LinkParser().parse("[[b#Z]] [[b#A]] [[b#A]] ![[b]] [[c]] [[a]]")
    built = LinkSetBuilder().build(
        tuple(index.resolve(link, source="a.md") for link in links), {"b.md": "B"}
    )
    assert [
        (link.target_record_id, link.link_type, link.count, link.anchors) for link in built.links
    ] == [
        ("B", "embeds", 1, ()),
        ("B", "links_to", 3, ("A", "Z")),
    ]
    assert [item.classification for item in built.occurrences][-2:] == ["not_imported", "self"]
