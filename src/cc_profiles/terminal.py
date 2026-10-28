# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: open a project in a terminal, with Claude Code in a profile (macOS)."""

import os
import shlex
import subprocess
import sys
import time

from .byfolder import pick
from .core import (CONFIG_FILE, DATA_DIR, HOME, ApiError, Backup, load_config, pretty, profile, profiles,
                   write_json, write_text)
from .projects import list_projects

# ---------------------------------------------------------------------------
# Open in Terminal
# ---------------------------------------------------------------------------
# A small script in ~/.cc-profiles/terminal/ goes into the project's folder and starts Claude
# Code in the profile: CLAUDE_CONFIG_DIR set (unset for ~/.claude) and `command claude`, so the
# profile by folder shell function does not pick another one. It runs in a login shell, which
# has the user's PATH, and leaves that shell open when Claude Code exits. The terminal opens it
# as a document (`open -a`), so no permission to control another app is needed. The script
# deletes itself when it starts. Terminals are a fixed list: nothing the page sends is run.
TERMINALS = {
    "Terminal": ["/System/Applications/Utilities/Terminal.app", "/Applications/Utilities/Terminal.app"],
    "iTerm": ["/Applications/iTerm.app"],
    "Ghostty": ["/Applications/Ghostty.app"],
}
SCRIPT_DIR = os.path.join(DATA_DIR, "terminal")


def terminal_apps():
    """The terminals installed: name -> app path (also in ~/Applications)."""
    out = {}
    for name, paths in TERMINALS.items():
        paths = paths + [os.path.join(HOME, "Applications", os.path.basename(paths[0]))]
        found = next((p for p in paths if os.path.isdir(p)), None)
        if found:
            out[name] = found
    return out


def supported():
    return sys.platform == "darwin" or bool(os.environ.get("CC_PROFILES_TERMINAL_DRYRUN"))


def chosen_terminal(apps=None):
    apps = terminal_apps() if apps is None else apps
    want = load_config().get("terminal")
    return want if want in apps else next(iter(apps), None)


def terminal_status():
    """GET /api/terminal: the terminals installed and the one projects open in."""
    if not supported():
        return {"supported": False}
    apps = terminal_apps()
    return {"supported": bool(apps), "terminal": chosen_terminal(apps), "choices": list(apps)}


def op_set_terminal(name):
    if name not in terminal_apps():
        raise ApiError(f"{name} is not installed: pick one of {', '.join(terminal_apps()) or 'none'}")
    cfg = load_config()
    if cfg.get("terminal") == name:
        return {"message": f"Projects already open in {name}.", "backup": None}
    bk = Backup("terminal", f"Open projects in {name}")
    bk.copy(CONFIG_FILE, "config.json")
    cfg["terminal"] = name
    write_json(CONFIG_FILE, cfg)
    return {"message": f"Projects open in {name}.", "backup": bk.close()}


def launch_script(folder, prof):
    """The script that starts Claude Code in the profile, in the folder."""
    default = os.path.realpath(prof["dir_abs"]) == os.path.realpath(os.path.join(HOME, ".claude"))
    env = "unset CLAUDE_CONFIG_DIR" if default else f"export CLAUDE_CONFIG_DIR={shlex.quote(prof['dir_abs'])}"
    shell = '"${SHELL:-/bin/zsh}"'
    return (f"#!/bin/sh\n# cc-profiles: Claude Code in {prof['label']}, in {pretty(folder)}\n"
            f'rm -f "$0"\ncd {shlex.quote(folder)} || exit 1\n{env}\n'
            f"exec {shell} -lic 'command claude; exec {shell} -l'\n")


def folder_profile(path, row=None):
    """The profile a folder opens in when none is picked: the one the rules give it (as with
    profile by folder), else the one its project is in, else the first (the source profile)."""
    pid = pick(load_config(), path)[0]
    ids = [p["id"] for p in profiles()]
    if pid in ids:
        return pid
    known = [i for i in ids if i in ((row or {}).get("in") or {})]
    return (known or ids or ["default"])[0]


def op_open_terminal(project, pid, path=None):
    """POST /api/terminal/open: a project's folder, or any folder (`path`, from the Mac app's
    Finder menu), in the chosen terminal with Claude Code in pid (picked as folder_profile()
    does when empty)."""
    if not supported():
        raise ApiError("Opening a terminal works on macOS only")
    projects = list_projects()
    if path:
        folder = os.path.realpath(os.path.expanduser(path))
        if not os.path.isdir(folder):
            raise ApiError(f"Folder does not exist: {pretty(folder)}")
        row = next((r for r in projects if r.get("path") == folder), None)
    else:
        row = next((r for r in projects if r["name"] == project), None)
        if not row or not row.get("path"):
            raise ApiError(f"Project not found: {project}", 404)
        folder = row["path"]
        if not os.path.isdir(folder):
            raise ApiError(f"Folder does not exist: {pretty(folder)}. Relink the project first")
    prof = profile(pid or folder_profile(folder, row))
    apps = terminal_apps()
    name = chosen_terminal(apps)
    if not name:
        raise ApiError("No terminal found: install Terminal, iTerm or Ghostty")
    os.makedirs(SCRIPT_DIR, exist_ok=True)
    for old in os.listdir(SCRIPT_DIR):  # scripts a terminal never ran, after a day
        p = os.path.join(SCRIPT_DIR, old)
        if os.path.getmtime(p) < time.time() - 86400:
            os.unlink(p)
    script = os.path.join(SCRIPT_DIR, f"claude-{prof['id']}-{int(time.time() * 1000)}.command")
    write_text(script, launch_script(folder, prof))
    os.chmod(script, 0o700)
    cmd = (["/usr/bin/open", "-na", apps[name], "--args", "-e", script] if name == "Ghostty"
           else ["/usr/bin/open", "-a", apps[name], script])
    msg = f"Opening {pretty(folder)} in {name}, with Claude Code in {prof['label']}."
    if os.environ.get("CC_PROFILES_TERMINAL_DRYRUN"):  # tests: the script is written, nothing opens
        return {"message": msg, "command": cmd, "script": script, "profile": prof["id"]}
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise ApiError(f"{name} did not open: {(r.stderr or r.stdout).strip()}")
    return {"message": msg, "profile": prof["id"]}
