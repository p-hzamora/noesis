"""Ports to the agent runtimes and the host (what is installed)."""

from .i_host_tool_probe import IHostToolProbe
from .i_runtime_inventory_probe import IRuntimeInventoryProbe

__all__ = ["IHostToolProbe", "IRuntimeInventoryProbe"]
