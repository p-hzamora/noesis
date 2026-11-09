"""Decides which parts of note text are secrets, and masks them before the text leaves for a model."""

import re

REDACTED: str = "[REDACTED]"

_PRIVATE_KEY: re.Pattern[str] = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.DOTALL
)
_TOKEN_SHAPES: re.Pattern[str] = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{16}|xox[abprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,})"
)
_BEARER: re.Pattern[str] = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{16,}")
_ASSIGNED: re.Pattern[str] = re.compile(
    r"(?i)\b((?:[\w-]*(?:password|passwd|secret|token|api[_-]?key|private[_-]?key|credential)[\w-]*)"
    r"\s*[:=]\s*)(?![\[<{$])[\"']?[^\s\"',;]{8,}"
)


class SecretRedactor:
    """Masks secrets in text."""

    @staticmethod
    def redact(text: str) -> tuple[str, int]:
        """`text` with private keys, well-known token shapes, bearer tokens and secret-looking
        `name = value` assignments masked.

        This is a safety net against common leaks, not a guarantee: a secret with no recognisable
        shape or name passes through.

        Returns:
            The masked text and how many secrets were masked.
        """
        count: int = 0

        def mask(match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            prefix: str = match.group(1) if match.lastindex else ""
            return f"{prefix}{REDACTED}"

        for pattern in (_PRIVATE_KEY, _TOKEN_SHAPES, _BEARER, _ASSIGNED):
            text = pattern.sub(mask, text)
        return text, count
