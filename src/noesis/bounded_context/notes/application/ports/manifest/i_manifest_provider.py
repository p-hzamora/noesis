"""Where the effective manifest comes from."""

import abc

from noesis.bounded_context.notes.application.services.manifest import Manifest


class IManifestProvider(abc.ABC):
    """Loads the manifest: the packaged default with the user's `noesis.yaml` merged on top."""

    @abc.abstractmethod
    async def load(self) -> Manifest:
        """The validated effective manifest.

        Raises:
            InvalidManifestError: The user manifest cannot be read or breaks a rule.
        """
        ...
