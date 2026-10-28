#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
# Install cc-profiles, add the /cc-profiles command to Claude Code and, on macOS, the Mac app.
#
#   curl -fsSL https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/install.sh | sh
#
# Running it again updates cc-profiles, with the tool that installed it (pipx, uv or Homebrew),
# and restarts it if it is running. It never uses sudo; besides your home folder it writes
# only through Homebrew, when that is the only installer you have.
set -eu

SOURCE="${CC_PROFILES_SOURCE:-cc-profiles}"
ADD_COMMAND=1
ADD_APP=1
PORT="${CC_PROFILES_PORT:-4777}"

usage() {
    cat <<'EOF'
Install or update cc-profiles, add the /cc-profiles command to Claude Code and,
on macOS, the Mac app (~/Applications/cc-profiles.app).

Usage:
  curl -fsSL https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/install.sh | sh
  curl -fsSL …/install.sh | sh -s -- --no-command

Options:
  --no-command   install the app only, do not touch your Claude Code profiles
  --no-app       macOS: do not add the Mac app
  -h, --help     show this help

Environment:
  CC_PROFILES_SOURCE   what to install (default: cc-profiles from PyPI);
                       a local folder, or git+https://github.com/andreaiannarone/cc-profiles.git@branch
EOF
}

for arg in "$@"; do
    case "$arg" in
        --no-command) ADD_COMMAND=0 ;;
        --no-app) ADD_APP=0 ;;
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

has() { command -v "$1" >/dev/null 2>&1; }

case "$SOURCE" in
    git+*) has git || fail "git is required to install from GitHub: install it, then run this script again." ;;
esac

# Update with the tool that installed it: another one would add a second copy.
METHOD=""
if [ "$SOURCE" = cc-profiles ] && has brew && brew list --formula cc-profiles >/dev/null 2>&1; then
    METHOD=brew
elif has pipx && pipx list --short 2>/dev/null | grep -q '^cc-profiles '; then
    METHOD=pipx
elif has uv && uv tool list 2>/dev/null | grep -q '^cc-profiles '; then
    METHOD=uv
elif has pipx; then
    METHOD=pipx
elif has uv; then
    METHOD=uv
elif [ "$SOURCE" = cc-profiles ] && has brew; then
    METHOD=brew
else
    fail "pipx, uv or Homebrew is required. Install one of them (macOS: brew install pipx; Linux: python3 -m pip install --user pipx; uv: https://docs.astral.sh/uv/), then run this script again."
fi

if [ "$METHOD" = pipx ]; then  # uv and Homebrew bring their own Python
    has python3 || fail "Python 3.9 or later is required: install it, then run this script again."
    python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
        || fail "Python 3.9 or later is required, found $(python3 --version 2>&1)."
fi

version() { cc-profiles --version 2>/dev/null | awk '{print $2}' || true; }
OLD="$(version)"

case "$METHOD" in
    pipx)  # --force also rebuilds an environment whose Python was removed by an update
        say "Installing cc-profiles with pipx…"
        pipx install --force "$SOURCE" ;;
    uv)  # --reinstall: the latest version, and a fresh environment
        say "Installing cc-profiles with uv…"
        uv tool install --force --reinstall "$SOURCE" ;;
    brew)
        if brew list --formula cc-profiles >/dev/null 2>&1; then
            say "Updating cc-profiles with Homebrew…"
            brew upgrade cc-profiles || brew reinstall cc-profiles
        else
            say "Installing cc-profiles with Homebrew (no pipx or uv found)…"
            brew install andreaiannarone/cc-profiles/cc-profiles
        fi ;;
esac

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

if [ "$ADD_APP" = 1 ] && [ "$(uname -s)" = Darwin ]; then
    say ""
    say "Adding the Mac app…"
    "$BIN" install-app || say "Note: the Mac app was not added. Try again later with: cc-profiles install-app"
fi

NEW="$(version)"
if [ -n "$OLD" ] && [ "$OLD" != "$NEW" ] \
    && curl -s -m 2 -o /dev/null -D - "http://127.0.0.1:$PORT/" 2>/dev/null | grep -qi '^server: cc-profiles/'; then
    say ""
    say "Restarting cc-profiles, which was running ${OLD}…"
    if "$BIN" restart --port "$PORT" >/dev/null; then
        say "Reload its page to see $NEW."
    else
        say "Note: restart it yourself with: cc-profiles restart"
    fi
fi

say ""
if [ -z "$OLD" ]; then
    say "Done: cc-profiles $NEW is installed. Start it with: cc-profiles"
elif [ "$OLD" = "$NEW" ]; then
    say "Done: cc-profiles $NEW is up to date."
else
    say "Done: cc-profiles is updated from $OLD to $NEW."
fi
if [ "$ADD_COMMAND" = 1 ]; then
    say "Type /cc-profiles inside Claude Code to open it."
fi
case ":$ORIG_PATH:" in
    *":$(dirname "$BIN"):"*) ;;
    *) say "Note: $(dirname "$BIN") is not in your PATH yet. Run: pipx ensurepath (or: uv tool update-shell), then open a new terminal." ;;
esac
