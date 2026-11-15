"""One module per command group; each exposes a Typer sub-application or command."""

from .assertion_commands import assertion_app
from .capture_commands import capture_app
from .catalog_commands import catalog_app
from .config_commands import config_app
from .doctor_commands import doctor
from .hook_commands import hook_app
from .import_commands import import_app
from .index_commands import index_app
from .integrate_commands import integrate_app
from .notes_commands import notes_app
from .record_commands import record_app
from .review_commands import review_app
from .search_commands import search
from .skills_commands import skills_app
from .store_commands import store_app
from .update_commands import update_app
from .vault_commands import vault_app

__all__ = [
    "assertion_app",
    "capture_app",
    "catalog_app",
    "config_app",
    "doctor",
    "hook_app",
    "import_app",
    "index_app",
    "integrate_app",
    "notes_app",
    "record_app",
    "review_app",
    "search",
    "skills_app",
    "store_app",
    "update_app",
    "vault_app",
]
