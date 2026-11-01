"""Naming of the files a published brief leaves behind."""

from datetime import datetime
from pathlib import Path

from noesis.shared_kernel.contracts import WorkBriefContract
from noesis.shared_kernel.infrastructure.outbound.persistence import write_json_atomic

RESULT_SUFFIX: str = ".result.json"
LOG_SUFFIX: str = ".log"


class BriefFiles:
    """`<folder>/<session>/<time>-<head>.json`, with `.result.json` and `.log` siblings."""

    def __init__(self, folder: Path) -> None:
        self._folder: Path = folder

    def write(self, brief: WorkBriefContract, *, now: datetime) -> Path:
        """Store the brief and return its file."""
        path: Path = self._folder / brief.session_id / f"{now:%Y%m%dT%H%M%S}-{brief.head[:8]}.json"
        write_json_atomic(path, brief.model_dump(mode="json"))
        return path

    @staticmethod
    def result_of(brief_file: Path) -> Path:
        """Where the curation result of `brief_file` is written."""
        return brief_file.with_name(brief_file.stem + RESULT_SUFFIX)

    @staticmethod
    def log_of(brief_file: Path) -> Path:
        """Where the curator process's stderr goes."""
        return brief_file.with_name(brief_file.stem + LOG_SUFFIX)
