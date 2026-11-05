"""Questions about the git checkout noesis was installed from."""

import abc
from pathlib import Path

from .checkout_snapshot import CheckoutSnapshot


class ICheckoutInspector(abc.ABC):
    """Looks at the checkout a package folder belongs to and at its origin."""

    @abc.abstractmethod
    async def inspect(self, package_dir: Path) -> CheckoutSnapshot:
        """What is known about the checkout of `package_dir` and its origin.

        Never raises: whatever cannot be read (no checkout, no origin, a timeout, an
        unreachable origin) is left as None in the snapshot.
        """
        ...
