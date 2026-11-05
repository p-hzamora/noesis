"""One module per command group; each exposes a Typer sub-application or command."""

from .capture_commands import capture_app
from .config_commands import config_app
from .doctor_commands import doctor
from .hook_commands import hook_app
from .integrate_commands import integrate_app
from .notes_commands import notes_app
from .skills_commands import skills_app
from .update_commands import update_app

__all__ = [
    "capture_app",
    "config_app",
    "doctor",
    "hook_app",
    "integrate_app",
    "notes_app",
    "skills_app",
    "update_app",
]
