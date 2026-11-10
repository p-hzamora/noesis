"""Debug entry for any `noesis` command: splits one command-line string like a shell would.

Used by the "noesis CLI (any command)" launch configuration so breakpoints work for every command.
"""

import shlex
import sys

from noesis.interfaces.cli.app import run

if __name__ == "__main__":
    command_line: str = sys.argv[1] if len(sys.argv) > 1 else "--help"
    sys.exit(run(shlex.split(command_line)))
