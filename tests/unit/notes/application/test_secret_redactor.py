"""Secrets are masked before note text goes to a model."""

import pytest

from noesis.bounded_context.notes.application.services.recall import SecretRedactor

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-abcdefghijklmnopqrstuvwx",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "AKIAABCDEFGHIJKLMNOP",
        "xoxb-1234567890-abcdefghij",
        "Bearer abcdefghijklmnop1234567890",
    ],
)
def test_well_known_token_shapes_are_masked(secret: str) -> None:
    text, count = SecretRedactor.redact(f"before {secret} after")

    assert secret not in text
    assert "[REDACTED]" in text
    assert (count, text.startswith("before "), text.endswith(" after")) == (1, True, True)


def test_assigned_secrets_keep_their_name_and_lose_their_value() -> None:
    text, count = SecretRedactor.redact(
        "API_KEY=hunter2hunter2\npassword: 'correct-horse-battery'\nCV_SECRET_KEY = abcdefgh12345678"
    )

    assert "hunter2" not in text
    assert "correct-horse" not in text
    assert "abcdefgh12345678" not in text
    assert "API_KEY=[REDACTED]" in text
    assert count == 3


def test_private_key_blocks_are_masked_whole() -> None:
    block = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg\nkqhkiG9w0BAQEF\n-----END PRIVATE KEY-----"

    text, count = SecretRedactor.redact(f"key:\n{block}\ndone")

    assert "MIIEvQ" not in text
    assert (count, text.endswith("done")) == (1, True)


def test_prose_and_placeholders_are_left_alone() -> None:
    original = (
        "The token expires after an hour.\nSet API_KEY=<your key>.\n"
        "password: [REDACTED]\nThe secret is rotated nightly."
    )

    text, count = SecretRedactor.redact(original)

    assert (text, count) == (original, 0)
