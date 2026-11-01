"""noesis: capture finished agent work, curate what is worth keeping, store it as notes."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__: str = version("noesis")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"
