"""TextNormaliser: wiki links to text, links-only sections removed, code untouched (AC-019, FR-014)."""

import pytest

from noesis.bounded_context.interop.domain.services import TextNormaliser

pytestmark = pytest.mark.unit


def _lines(*parts: str) -> str:
    return "\n".join(parts)


E1_IN = (
    "See [[howto-capture]], [[guides/howto-capture#Steps]], [[glossary-ulid|ULID]], "
    "![[diagram.png]], [[note#^step1]], [[#Local]], [[#^b1]], [[folder/plan.md|]] and [[a/b/c.MD]]."
)
E1_OUT = "See howto-capture, howto-capture, ULID, diagram.png, note, Local, , plan and c."

E2_IN = _lines(
    "| Term | Link |",
    "| --- | --- |",
    r"| ULID | [[glossary-ulid\|the ULID note]] |",
)
E2_OUT = _lines("| Term | Link |", "| --- | --- |", "| ULID | the ULID note |")

E3_IN = _lines(
    "Use `[[inline-code]]` here and [[real]].",
    "",
    "```python",
    'x = "[[in-fence]]"',
    "# not a heading",
    "```",
)
E3_OUT = _lines(
    "Use `[[inline-code]]` here and real.",
    "",
    "```python",
    'x = "[[in-fence]]"',
    "# not a heading",
    "```",
)

E4_IN = _lines(
    "# Ports", "", "Text.", "", "## Related", "", "- [[a]]", "- [[b|B]]", "", "## Next", "More."
)
E4_OUT = _lines("# Ports", "", "Text.", "", "## Next", "More.")

E5_IN = _lines(
    "# Decision",
    "",
    "Chosen.",
    "",
    "## Related",
    "",
    "- [[ports]]: the boundary this decision protects",
)
E5_OUT = _lines(
    "# Decision",
    "",
    "Chosen.",
    "",
    "## Related",
    "",
    "- ports: the boundary this decision protects",
)

E6_IN = _lines("Intro.", "", "## See also", "", "[[a]], [[b]] · [[c]]")
E6_OUT = "Intro."

E7_IN = _lines(
    "# Topic",
    "",
    "Body.",
    "",
    "## Links",
    "",
    "### Notes",
    "",
    "- [[a]]",
    "",
    "### Runs",
    "",
    "- [[b]]",
    "",
    "## End",
    "",
    "Done.",
)
E7_OUT = _lines("# Topic", "", "Body.", "", "## End", "", "Done.")

E8_IN = _lines(
    "# Index", "", "## Projects", "", "- [[repos/alpha/index|Alpha]]", "- [[repos/beta/index|Beta]]"
)

E9_IN = _lines("Intro.", "", "## Example", "", "```text", "see [[x]]", "```")

E11_IN = _lines("Text [[a]].", "", "```", "code [[b]]", "## not a heading")
E11_OUT = _lines("Text a.", "", "```", "code [[b]]", "## not a heading")

E12_IN = _lines("Preamble [[a|A]].", "", "## Notes", "", "Prose.", "", "## Empty")
E12_OUT = _lines("Preamble A.", "", "## Notes", "", "Prose.")

E13_IN = _lines("Text.", "", "## Refs", "", "- [[a]]; [[b|B]]")
E14_IN = _lines("Text.", "", "## Nav", "", "[[prev]] | [[index]] | [[next]]")
E15_IN = _lines("Text.", "", "## Refs", "", "[[a]], see [[b]]")
E15_OUT = _lines("Text.", "", "## Refs", "", "a, see b")

# E10 is the full-file example: its body part is normalised here, the header split and the
# title in `test_vault_import_mapping.py::test_e10_header_removed_and_title_from_the_header`.
E10_BODY_IN = _lines("# Body heading", "", "Text with [[x|y]].")
E10_BODY_OUT = _lines("# Body heading", "", "Text with y.")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(E1_IN, E1_OUT, id="E1"),
        pytest.param(E2_IN, E2_OUT, id="E2"),
        pytest.param(E3_IN, E3_OUT, id="E3"),
        pytest.param(E4_IN, E4_OUT, id="E4"),
        pytest.param(E5_IN, E5_OUT, id="E5"),
        pytest.param(E6_IN, E6_OUT, id="E6"),
        pytest.param(E7_IN, E7_OUT, id="E7"),
        pytest.param(E8_IN, "", id="E8"),
        pytest.param(E9_IN, E9_IN, id="E9"),
        pytest.param(E10_BODY_IN, E10_BODY_OUT, id="E10"),
        pytest.param(E11_IN, E11_OUT, id="E11"),
        pytest.param(E12_IN, E12_OUT, id="E12"),
        pytest.param(E13_IN, "Text.", id="E13"),
        pytest.param(E14_IN, "Text.", id="E14"),
        pytest.param(E15_IN, E15_OUT, id="E15"),
    ],
)
def test_ac019_worked_examples(text: str, expected: str) -> None:
    assert TextNormaliser().normalise(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("a [[]] b", "a [[]] b", id="empty-link-is-not-a-token"),
        pytest.param(
            "``a ` [[b]]`` and [[c]]",
            "``a ` [[b]]`` and c",
            id="two-backtick-span-holding-a-backtick-and-a-link",
        ),
        pytest.param("a `` unmatched [[b]]", "a `` unmatched b", id="unmatched-backtick-run"),
        pytest.param(
            "Text.\n\n## S\n\n1) [[a]]", "Text.", id="ordered-item-with-paren-is-link-only"
        ),
        pytest.param(
            "Text.\n\n## S\n\n> [[a]]", "Text.\n\n## S\n\n> a", id="blockquote-is-not-link-only"
        ),
        pytest.param(
            "# T\n\nIntro.\n\n## A\n\n### B\n\n- [[x]]",
            "# T\n\nIntro.",
            id="nested-heading-with-links-only-below",
        ),
        pytest.param(
            "Text.\n\n## S\n\n| --- |\n\n[[a]]",
            "Text.\n\n## S\n\n| --- |\n\na",
            id="table-delimiter-row-is-prose",
        ),
        pytest.param(
            "[Text](path.md) and [[a]]", "[Text](path.md) and a", id="markdown-links-stay"
        ),
        pytest.param("#tag is not a heading [[a]]", "#tag is not a heading a", id="hash-tag-line"),
        pytest.param(
            "\n\n  a  \n\n\nb\n\n", "  a  \n\n\nb", id="only-edge-blank-lines-are-trimmed"
        ),
        pytest.param("~~~\n[[a]]\n~~~", "~~~\n[[a]]\n~~~", id="tilde-fence"),
        pytest.param("[[a|]] and [[ b ]]", "a and b", id="empty-alias-falls-back-to-target"),
        pytest.param("[[a]]\n- [[b]]", "a\n- b", id="no-heading-links-only-body-kept"),
    ],
)
def test_normaliser_edge_cases(text: str, expected: str) -> None:
    assert TextNormaliser().normalise(text) == expected


def test_normaliser_is_deterministic_and_idempotent_on_its_output() -> None:
    normaliser: TextNormaliser = TextNormaliser()
    once: str = normaliser.normalise(E4_IN)

    assert normaliser.normalise(E4_IN) == once
    assert normaliser.normalise(once) == once
