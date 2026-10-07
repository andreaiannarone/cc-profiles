#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
# Install cc-profiles and add the /cc-profiles command to Claude Code.
#
#   curl -fsSL https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/install.sh | sh
#
# Running it again updates cc-profiles and the command. It never uses sudo and
# writes only in your home folder.
set -eu

SOURCE="${CC_PROFILES_SOURCE:-cc-profiles}"
ADD_COMMAND=1

usage() {
    cat <<'EOF'
Install cc-profiles and add the /cc-profiles command to Claude Code.

Usage:
  curl -fsSL https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/install.sh | sh
  curl -fsSL …/install.sh | sh -s -- --no-command

Options:
  --no-command   install the app only, do not touch your Claude Code profiles
  -h, --help     show this help

Environment:
  CC_PROFILES_SOURCE   what to install (default: cc-profiles from PyPI);
                       a local folder, or git+https://github.com/andreaiannarone/cc-profiles.git@branch
EOF
}

for arg in "$@"; do
    case "$arg" in
        --no-command) ADD_COMMAND=0 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $arg (use --help)" >&2; exit 2 ;;
    esac
done

say() { printf '%s\n' "$*"; }
fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }

case "$(uname -s)" in
    Darwin|Linux) ;;
    *) fail "cc-profiles supports macOS and Linux only for now." ;;
esac

# Look for tools also where installers put them: a fresh terminal may not have these folders yet.
ORIG_PATH="$PATH"
PATH="$PATH:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin"
export PATH

command -v python3 >/dev/null 2>&1 || fail "Python 3.9 or later is required: install it, then run this script again."
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
    || fail "Python 3.9 or later is required, found $(python3 --version 2>&1)."

case "$SOURCE" in
    git+*) command -v git >/dev/null 2>&1 || fail "git is required to install from GitHub: install it, then run this script again." ;;
esac

if command -v pipx >/dev/null 2>&1; then
    say "Installing cc-profiles with pipx…"
    pipx install --force "$SOURCE"
elif command -v uv >/dev/null 2>&1; then
    say "Installing cc-profiles with uv…"
    uv tool install --force "$SOURCE"
else
    fail "pipx or uv is required. Install one of them (macOS: brew install pipx; Linux: python3 -m pip install --user pipx; uv: https://docs.astral.sh/uv/), then run this script again."
fi

BIN="$(command -v cc-profiles 2>/dev/null || true)"
[ -n "$BIN" ] || BIN="$HOME/.local/bin/cc-profiles"
[ -x "$BIN" ] || fail "cc-profiles was installed but its command was not found. Run: pipx ensurepath (or: uv tool update-shell), open a new terminal, then run this script again."

if [ "$ADD_COMMAND" = 1 ]; then
    say ""
    say "Adding the /cc-profiles command to Claude Code…"
    "$BIN" install-command
else
    # remembered in ~/.cc-profiles/config.json, or the app would add it the first time it starts
    "$BIN" install-command --off >/dev/null || say "Note: could not record --no-command; the app may add /cc-profiles when it starts."
fi

say ""
say "Done. Start cc-profiles with: cc-profiles"
if [ "$ADD_COMMAND" = 1 ]; then
    say "Or type /cc-profiles inside Claude Code."
fi
case ":$ORIG_PATH:" in
    *":$(dirname "$BIN"):"*) ;;
    *) say "Note: $(dirname "$BIN") is not in your PATH yet. Run: pipx ensurepath (or: uv tool update-shell), then open a new terminal." ;;
esac
