"""Downloads one pinned artifact file over HTTPS (used only by `index model prepare`)."""

import shutil
import urllib.request
from pathlib import Path

FETCH_TIMEOUT_SECONDS: float = 60.0


def https_fetch(url: str, target: Path) -> None:
    """Stream `url` into `target`; the caller verifies size and digest.

    Raises:
        ValueError: `url` is not HTTPS.
        OSError: The download failed.
    """
    if not url.startswith("https://"):
        raise ValueError("model artifacts are fetched over HTTPS only")
    request = urllib.request.Request(url, headers={"User-Agent": "noesis-model-prepare"})  # noqa: S310  # https only, checked above
    with (
        urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response,  # noqa: S310
        target.open("wb") as handle,
    ):
        shutil.copyfileobj(response, handle, length=1 << 20)
