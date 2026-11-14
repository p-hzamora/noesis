"""The ULID shape shared by record ids and space ids."""

import re

ULID_PATTERN: re.Pattern[str] = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
