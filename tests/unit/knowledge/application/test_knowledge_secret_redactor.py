"""SecretRedactor: the patterns Knowledge masks before storing (FR-012, AC-010)."""

import pytest

from noesis.bounded_context.knowledge.application.services.secret_redactor import (
    REDACTED,
    SecretRedactor,
)
from noesis.bounded_context.retrieval.application.services.briefing_redactor import BriefingRedactor

type Redactor = type[SecretRedactor] | type[BriefingRedactor]

pytestmark = [
    pytest.mark.unit,
    pytest.mark.parametrize("redactor", [SecretRedactor, BriefingRedactor]),
]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("key sk-abcdefghijklmnopqrstuv end", f"key {REDACTED} end"),
        ("gh ghp_abcdefghijklmnopqrstuvwxyz end", f"gh {REDACTED} end"),
        ("github_pat_abcdefghijklmnopqrstuvwxyz", REDACTED),
        ("aws AKIAABCDEFGHIJKLMNOP", f"aws {REDACTED}"),
        ("slack xoxb-1234567890-abc", f"slack {REDACTED}"),
        ("Authorization: Bearer abcdefghijklmnop1234", f"Authorization: Bearer {REDACTED}"),
        ("PASSWORD=hunter2hunter2", f"PASSWORD={REDACTED}"),
        ("client-secret: 'abcdefghij'", f"client-secret: {REDACTED}'"),
        ("db_token = abcdefgh12345678", f"db_token = {REDACTED}"),
    ],
)
def test_redact_masks_known_shapes_keeping_context(
    text: str, expected: str, redactor: Redactor
) -> None:
    redacted, count = redactor.redact(text)

    assert redacted == expected
    assert count == 1


def test_redact_masks_whole_private_key_block_even_when_unterminated(redactor: Redactor) -> None:
    complete, n1 = redactor.redact(
        "a\n-----BEGIN PRIVATE KEY-----\nAAA\n-----END PRIVATE KEY-----\nb"
    )
    truncated, n2 = redactor.redact("a\n-----BEGIN OPENSSH PRIVATE KEY-----\nAAA")

    assert complete == f"a\n{REDACTED}\nb"
    assert truncated == f"a\n{REDACTED}"
    assert (n1, n2) == (1, 1)


@pytest.mark.parametrize(
    "text",
    [
        "no secrets here",
        "password = ${PASSWORD}",
        "token: <your-token-here>",
        "secret=short",
        "sk-short",
    ],
)
def test_redact_leaves_placeholders_and_plain_text(text: str, redactor: Redactor) -> None:
    assert redactor.redact(text) == (text, 0)


def test_redact_counts_every_secret(redactor: Redactor) -> None:
    text = "sk-abcdefghijklmnopqrstuv and password=hunter2hunter2"

    redacted, count = redactor.redact(text)

    assert count == 2
    assert redacted.count(REDACTED) == 2
