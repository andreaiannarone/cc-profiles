# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Launchers (the command that starts Claude Code in a profile)."""

import os
import re
import shutil

from .core import ApiError, HOME, LAUNCHER_DIR, LAUNCHER_MARK, pretty, write_text

# ---------------------------------------------------------------------------
# Launchers (the command that starts Claude Code in a profile)
# ---------------------------------------------------------------------------
# New profiles get a tiny script in ~/.local/bin instead of a shell alias: it works
# in every shell and right away, without editing rc files. Aliases written by
# older setups are still recognized when renaming or deleting a profile.
RC_FILES = [os.path.join(HOME, f) for f in (".zshrc", ".bashrc", ".bash_profile")]


def launcher_path(command):
    return os.path.join(LAUNCHER_DIR, command)


def launcher_script(dir_, label):
    d = '"$HOME' + dir_[1:] + '"' if dir_.startswith("~") else f'"{dir_}"'
    return (f"#!/bin/sh\n{LAUNCHER_MARK} (profile: {label}). Safe to delete.\n"
            f"CLAUDE_CONFIG_DIR={d} exec claude \"$@\"\n")


def is_our_launcher(path):
    try:
        with open(path) as f:
            return LAUNCHER_MARK in f.read(500)
    except OSError:
        return False


def write_launcher(command, dir_, label, bk):
    p = launcher_path(command)
    if os.path.lexists(p) and not is_our_launcher(p):
        raise ApiError(f"{pretty(p)} already exists and was not created by cc-profiles")
    bk.mkdir(LAUNCHER_DIR)
    bk.copy(p, f"launcher-{command}")
    write_text(p, launcher_script(dir_, label))
    os.chmod(p, 0o755)


def launcher_dir_in_path():
    return LAUNCHER_DIR in os.environ.get("PATH", "").split(":")


def rewrite_alias(old_cmd, new_line, bk):
    """Replace (new_line) or remove (None) an alias `old_cmd` in the shell rc files,
    with the '# Claude Code: …' comment line right above it. Returns whether found."""
    found_any = False
    pat = re.compile(r"^\s*alias\s+" + re.escape(old_cmd) + r"=")
    for rc in RC_FILES:
        if not os.path.exists(rc):
            continue
        lines = open(rc).read().split("\n")
        out, found = [], False
        for l in lines:
            if pat.match(l):
                found = True
                if new_line is None:
                    while out and out[-1].startswith("# Claude Code:"):
                        out.pop()
                    if out and out[-1] == "":  # the blank line that separated the block
                        out.pop()
                else:
                    out.append(new_line)
                continue
            out.append(l)
        if found:
            bk.copy(rc, os.path.basename(rc))
            write_text(rc, "\n".join(out))
            found_any = True
    return found_any


def command_conflict(command, others):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,40}", command):
        return "Invalid command: letters, digits, dashes and underscores only"
    if command == "claude" or any(p.get("command") == command for p in others):
        return f"The command {command} is already used"
    existing = shutil.which(command)
    if existing and not is_our_launcher(existing):
        return f"A program called {command} already exists: pick another name"
    return None


def alias_files(command):
    """The shell rc files that define an alias `command` (what rewrite_alias would touch)."""
    pat = re.compile(r"^\s*alias\s+" + re.escape(command) + r"=")
    out = []
    for rc in RC_FILES:
        try:
            with open(rc) as f:
                if any(pat.match(l) for l in f):
                    out.append(rc)
        except OSError:
            pass
    return out
