# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: uninstall and reinstall cc-profiles itself."""

import os
import shutil
import subprocess
import sys

from .core import DATA_DIR, Backup, find_tool, load_config, pretty, profiles, tool_env, write_json, CONFIG_FILE
from .command import COMMAND_NAME, is_our_command
from .launchers import RC_FILES, has_shell_line, remove_shell_line
from .updater import install_kind

# ---------------------------------------------------------------------------
# Uninstall and reinstall
# ---------------------------------------------------------------------------
# `cc-profiles uninstall` removes what cc-profiles added to Claude Code (the /cc-profiles command,
# the profile by folder line) and then the package itself, with the tool it was installed with;
# `cc-profiles reinstall` installs the package again from scratch, for when something is broken.
# Neither touches the profiles: their conversations, memories, settings and logins stay.
# The commands are fixed per install kind, like UPDATE_COMMANDS: nothing comes from outside.
UNINSTALL_COMMANDS = {"pipx": ["pipx", "uninstall", "cc-profiles"], "uv": ["uv", "tool", "uninstall", "cc-profiles"],
                      "brew": ["brew", "uninstall", "cc-profiles"],
                      "pip": [sys.executable, "-m", "pip", "uninstall", "-y", "cc-profiles"]}
REINSTALL_COMMANDS = {"pipx": ["pipx", "install", "--force", "cc-profiles"],
                      "uv": ["uv", "tool", "install", "--force", "--reinstall", "cc-profiles"],
                      "brew": ["brew", "reinstall", "cc-profiles"],
                      "pip": [sys.executable, "-m", "pip", "install", "--force-reinstall", "cc-profiles"]}
UNINSTALL_PAGE = "https://cc-profiles.andreaia.com/uninstall.html"


def our_commands():
    """The /cc-profiles files cc-profiles wrote, once each (a shared commands folder is one file)."""
    out, seen = [], set()
    for p in profiles():
        path = os.path.join(p["dir_abs"], "commands", COMMAND_NAME)
        real = os.path.realpath(path)
        if real not in seen and os.path.isfile(path) and is_our_command(path):
            seen.add(real)
            out.append(real)
    return out


def package_command(table):
    """The fixed command for this install, or None (a source checkout), and why it cannot run."""
    kind = install_kind()
    cmd = table.get(kind)
    if not cmd:
        return kind, None, "this copy runs from a source checkout: remove or update the folder yourself"
    if not (os.path.isabs(cmd[0]) or find_tool(cmd[0])):
        return kind, None, f"{cmd[0]} is not installed, though cc-profiles was installed with it"
    return kind, cmd, None


def uninstall_plan():
    kind, cmd, why = package_command(UNINSTALL_COMMANDS)
    return {"kind": kind, "command": cmd, "why": why, "commands": our_commands(),
            "shell": [rc for rc in RC_FILES if has_shell_line(rc)], "data": DATA_DIR}


def remove_traces():
    """Stop adding /cc-profiles, remove the copies cc-profiles wrote and the profile by folder line,
    in one backup (kept in ~/.cc-profiles unless that is removed too). Returns (lines, backup)."""
    plan, lines, backup = uninstall_plan(), [], None
    cfg = load_config()
    if cfg.get("slash_command") is False and not plan["commands"]:
        bk = None
    else:
        bk = Backup("uninstall", "Uninstall cc-profiles: the /cc-profiles command")
    if bk and cfg.get("slash_command") is not False:
        bk.copy(CONFIG_FILE, "config.json")
        cfg["slash_command"] = False
        write_json(CONFIG_FILE, cfg)
    for path in plan["commands"]:
        bk.stash(path)
        lines.append(f"removed {pretty(path)}")
    if bk:
        backup = bk.close()
    if plan["shell"]:
        r = remove_shell_line()
        lines.append(r["message"])
    return lines, backup


def run_package(cmd):
    """Run an install command, showing its output; returns the exit code."""
    exe = cmd[0] if os.path.isabs(cmd[0]) else find_tool(cmd[0])
    try:
        return subprocess.run([exe] + cmd[1:], env=tool_env()).returncode
    except OSError as e:
        print(f"{' '.join(cmd)} could not start: {e}")
        return 1


def purge_data():
    shutil.rmtree(DATA_DIR, ignore_errors=True)
