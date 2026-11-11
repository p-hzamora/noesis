#!/bin/sh
# Install the `noesis` command.
#
#   curl -LsSf https://raw.githubusercontent.com/p-hzamora/noesis/main/install.sh | sh
#   ./install.sh                 # from a checkout: installs that checkout
#   ./install.sh --uninstall
#
# It uses the first installer it finds: uv, then pipx, then a private virtual environment
# built with Python 3.14+. Environment variables:
#   NOESIS_SOURCE       what to install: a git URL or a local path (default: this checkout
#                       when run from one, else the GitHub repository)
#   NOESIS_REF          git branch, tag or commit for a git source (default: main)
#   NOESIS_INSTALLER    force one of: uv, pipx, venv
#   NOESIS_HOME         venv installer only: where the venv lives (default: ~/.local/share/noesis)
#   NOESIS_BIN_DIR      venv installer only: where the launcher goes (default: ~/.local/bin)
set -eu

REPO_URL="https://github.com/p-hzamora/noesis"
NOESIS_REF="${NOESIS_REF:-main}"
NOESIS_HOME="${NOESIS_HOME:-$HOME/.local/share/noesis}"
NOESIS_BIN_DIR="${NOESIS_BIN_DIR:-$HOME/.local/bin}"

say() { printf 'noesis-install: %s\n' "$*"; }
die() { printf 'noesis-install: error: %s\n' "$*" >&2; exit 1; }
has() { command -v "$1" >/dev/null 2>&1; }

# Default source: the checkout this script sits in, otherwise the repository at NOESIS_REF.
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" 2>/dev/null && pwd) || script_dir=""
if [ -z "${NOESIS_SOURCE:-}" ]; then
    if [ -n "$script_dir" ] && grep -qs '^name = "noesis"' "$script_dir/pyproject.toml"; then
        NOESIS_SOURCE="$script_dir"
    else
        NOESIS_SOURCE="$REPO_URL"
    fi
fi

case "$NOESIS_SOURCE" in
    http://* | https://* | git@* | ssh://*) spec="git+${NOESIS_SOURCE}@${NOESIS_REF}" ;;
    *) [ -f "$NOESIS_SOURCE/pyproject.toml" ] || die "no pyproject.toml in $NOESIS_SOURCE"
       spec="$NOESIS_SOURCE" ;;
esac

find_python() {
    for candidate in python3.14 python3 python; do
        if has "$candidate" && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 14))' 2>/dev/null; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

pick_installer() {
    if [ -n "${NOESIS_INSTALLER:-}" ]; then
        echo "$NOESIS_INSTALLER"
    elif has uv; then
        echo uv
    elif has pipx && find_python >/dev/null; then
        echo pipx
    else
        echo venv
    fi
}

uninstall() {
    removed=0
    if has uv && uv tool list 2>/dev/null | grep -q '^noesis '; then
        uv tool uninstall noesis && removed=1
    fi
    if has pipx && pipx list --short 2>/dev/null | grep -q '^noesis '; then
        pipx uninstall noesis && removed=1
    fi
    if [ -d "$NOESIS_HOME/venv" ]; then
        rm -rf "$NOESIS_HOME/venv"
        [ -L "$NOESIS_BIN_DIR/noesis" ] && rm -f "$NOESIS_BIN_DIR/noesis"
        removed=1
    fi
    [ "$removed" = 1 ] && say "noesis removed (config in ~/.config/noesis and your notes are kept)" \
        || say "noesis is not installed"
}

install() {
    has git || case "$spec" in git+*) die "git is required to install from $NOESIS_SOURCE" ;; esac
    installer=$(pick_installer)
    say "installing $spec with $installer"
    case "$installer" in
        uv)
            # uv downloads Python 3.14 itself when the system has none.
            uv tool install --force --python '>=3.14' "$spec"
            ;;
        pipx)
            python=$(find_python) || die "pipx needs Python 3.14+; install it or use uv"
            pipx install --force --python "$python" "$spec"
            ;;
        venv)
            python=$(find_python) || die "Python 3.14+ not found. Install it, or install uv: https://docs.astral.sh/uv/"
            mkdir -p "$NOESIS_HOME" "$NOESIS_BIN_DIR"
            rm -rf "$NOESIS_HOME/venv"
            "$python" -m venv "$NOESIS_HOME/venv"
            "$NOESIS_HOME/venv/bin/python" -m pip install --quiet --upgrade pip
            "$NOESIS_HOME/venv/bin/python" -m pip install --quiet "$spec"
            ln -sf "$NOESIS_HOME/venv/bin/noesis" "$NOESIS_BIN_DIR/noesis"
            ;;
        *) die "unknown installer '$installer' (use uv, pipx or venv)" ;;
    esac

    if [ "$installer" = venv ]; then
        say "installed $("$NOESIS_BIN_DIR/noesis" --version)"
    fi
    if ! has noesis; then
        say "installed, but 'noesis' is not on your PATH. Add this to your shell profile:"
        say "  export PATH=\"\$HOME/.local/bin:\$PATH\"   (or the bin dir your installer printed)"
    fi
    say "next: noesis config init --vault-dir ~/notes && noesis doctor"
}

case "${1:-}" in
    --uninstall) uninstall ;;
    "") install ;;
    -h | --help) sed -n '2,16p' "$0" 2>/dev/null || say "see $REPO_URL" ;;
    *) die "unknown option '$1' (use --uninstall or --help)" ;;
esac
