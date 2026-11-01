"""Live publisher: starts `noesis knowledge curate` as a detached process and returns at once.

The hook must never wait for a model run. The child lives in its own process session,
writes its JSON result next to the brief, and is not killed when the hook exits.
"""

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from noesis.bounded_context.capture.application.dtos import PublicationDto
from noesis.bounded_context.capture.application.ports.publishing import IWorkBriefPublisher
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.contracts import WorkBriefContract

from .brief_files import BriefFiles

RECURSION_GUARD: Mapping[str, str] = {"NOESIS_HOOK": "1"}


class DetachedProcessWorkBriefPublisherAdapter(IWorkBriefPublisher):
    """Writes the brief file, then spawns `<command> knowledge curate --brief-file <file> --json`."""

    def __init__(
        self,
        *,
        files: BriefFiles,
        command: Sequence[str],
        environment: Mapping[str, str],
        clock: IClock,
    ) -> None:
        self._files: BriefFiles = files
        self._command: tuple[str, ...] = tuple(command)
        self._environment: Mapping[str, str] = environment
        self._clock: IClock = clock

    async def publish(self, brief: WorkBriefContract) -> PublicationDto:
        """Start the curator process; `published` is False when it cannot start."""
        try:
            brief_file: Path = self._files.write(brief, now=self._clock.now())
            _spawn_detached(
                [*self._command, "knowledge", "curate", "--brief-file", str(brief_file), "--json"],
                environment={**self._environment, **RECURSION_GUARD},
                stdout=BriefFiles.result_of(brief_file),
                stderr=BriefFiles.log_of(brief_file),
            )
        except OSError as error:
            return PublicationDto(published=False, detail=f"could not start the curator: {error}")
        return PublicationDto(published=True, reference=str(brief_file), detail="curator started")


def _spawn_detached(
    argv: Sequence[str], *, environment: Mapping[str, str], stdout: Path, stderr: Path
) -> None:
    """Start `argv` in a new session with stdin from /dev/null and output to files; do not wait.

    `os.posix_spawn` leaves no `Popen` handle behind, so nothing warns or waits when the hook
    process exits before the child does.

    Raises:
        OSError: The executable is missing or cannot be started.
    """
    executable: str | None = argv[0] if os.sep in argv[0] else shutil.which(argv[0])
    if executable is None:
        raise FileNotFoundError(f"{argv[0]} not found on PATH")
    descriptors: list[int] = [
        os.open(os.devnull, os.O_RDONLY),
        os.open(stdout, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644),
        os.open(stderr, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644),
    ]
    try:
        try:
            os.posix_spawn(
                executable,
                list(argv),
                dict(environment),
                file_actions=[
                    (os.POSIX_SPAWN_DUP2, descriptor, target)
                    for target, descriptor in enumerate(descriptors)
                ],
                setsid=True,
            )
        except NotImplementedError:
            # Some Python builds (e.g. python-build-standalone) lack posix_spawn's setsid.
            _popen_detached(executable, argv, environment, descriptors)
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def _popen_detached(
    executable: str,
    argv: Sequence[str],
    environment: Mapping[str, str],
    descriptors: Sequence[int],
) -> None:
    """Fallback for `_spawn_detached`: same contract, via `Popen(start_new_session=True)`.

    The handle is released at once so nothing waits on, or warns about, the running child.
    """
    process = subprocess.Popen(  # noqa: S603  # argv is built from our own fixed command
        [executable, *argv[1:]],
        env=dict(environment),
        stdin=descriptors[0],
        stdout=descriptors[1],
        stderr=descriptors[2],
        start_new_session=True,
    )
    process.returncode = 0  # detach on purpose: suppresses the "still running" ResourceWarning
