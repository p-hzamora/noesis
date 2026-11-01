"""One module per command group; each exposes a Typer sub-application or command."""

from noesis.interfaces.cli.commands.capture_commands import (
    capture_app,
)
from noesis.interfaces.cli.commands.config_commands import (
    config_app,
)
from noesis.interfaces.cli.commands.doctor_commands import (
    doctor,
)
from noesis.interfaces.cli.commands.hook_commands import (
    hook_app,
)
from noesis.interfaces.cli.commands.integrate_commands import (
    integrate_app,
)
from noesis.interfaces.cli.commands.knowledge_commands import (
    knowledge_app,
)
from noesis.interfaces.cli.commands.skills_commands import (
    skills_app,
)

__all__ = [
    "capture_app",
    "config_app",
    "doctor",
    "hook_app",
    "integrate_app",
    "knowledge_app",
    "skills_app",
]
