# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: choosing a folder."""

import os
import subprocess
import sys

from .core import HOME, ApiError, expand, find_tool, is_wsl, pretty, tool_env

# ---------------------------------------------------------------------------
# Choose a folder
# ---------------------------------------------------------------------------
# A browser never gives a page the full path of a folder the user picks, and relinking needs it.
# The server runs on the user's computer, so it opens the system's own folder dialog instead
# (osascript on macOS, zenity or kdialog on Linux) and returns the path. Where there is none
# (WSL, a Linux without them), the page browses folders through list_folders(). Both are
# read-only. CC_PROFILES_PICKER=none (the tests) turns the dialog off; =zenity or =kdialog forces one.
MAX_FOLDERS = 500


def start_folder(start):
    """The folder the dialog or the browser opens in: start, or its closest existing parent, or home."""
    p = expand((start or "").strip()) if (start or "").strip() else HOME
    if not os.path.isabs(p):
        p = HOME
    p = os.path.normpath(p)
    while not os.path.isdir(p) and p != os.path.dirname(p):
        p = os.path.dirname(p)
    return p if os.path.isdir(p) else HOME


def picker_command(start, prompt):
    """The argv of the system's folder dialog, or None when there is none."""
    forced = os.environ.get("CC_PROFILES_PICKER", "")
    if forced == "none" or is_wsl():
        return None
    if (forced == "osascript" or not forced and sys.platform == "darwin") and find_tool("osascript"):
        script = (f'POSIX path of (choose folder with prompt {applescript(prompt)} '
                  f'default location (POSIX file {applescript(start)}))')
        return [find_tool("osascript"), "-e", "activate", "-e", script]  # activate: in front of the browser
    if forced in ("", "zenity") and find_tool("zenity"):
        return [find_tool("zenity"), "--file-selection", "--directory", f"--title={prompt}",
                f"--filename={start.rstrip('/')}/"]
    if forced in ("", "kdialog") and find_tool("kdialog"):
        return [find_tool("kdialog"), "--getexistingdirectory", start, "--title", prompt]
    return None


def applescript(text):
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def pick_folder(start="", prompt="Choose a folder"):
    """Open the system's folder dialog and wait for the user. {native: false} when there is no
    dialog here (the page then shows its own browser), {cancelled: true} when it was closed."""
    begin = start_folder(start)
    cmd = picker_command(begin, prompt[:120])
    if not cmd:
        return {"native": False, "start": pretty(begin)}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900, env=tool_env())
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"native": False, "start": pretty(begin), "error": str(e)}
    path = r.stdout.strip()
    if r.returncode != 0 or not path:  # cancelled (osascript -128, zenity and kdialog 1)
        return {"native": True, "cancelled": True}
    path = os.path.normpath(path)
    return {"native": True, "cancelled": False, "path": pretty(path), "exists": os.path.isdir(path)}


def list_folders(path="", hidden=False):
    """The subfolders of a folder, for the page's own browser. Read-only."""
    p = start_folder(path)
    try:
        names = sorted((n for n in os.listdir(p) if (hidden or not n.startswith("."))
                        and os.path.isdir(os.path.join(p, n))), key=str.lower)
    except PermissionError:
        raise ApiError(f"{pretty(p)} cannot be read: pick another folder")
    parent = os.path.dirname(p)
    crumbs, cur = [], p  # from ~ when the folder is inside the home, else from /
    while True:
        at_home = os.path.normpath(cur) == os.path.normpath(HOME)
        crumbs.append({"name": "~" if at_home else os.path.basename(cur) or "/", "path": pretty(cur)})
        if at_home or cur == os.path.dirname(cur):
            break
        cur = os.path.dirname(cur)
    return {"path": pretty(p), "parent": pretty(parent) if parent != p else None, "home": pretty(HOME),
            "folders": names[:MAX_FOLDERS], "truncated": len(names) > MAX_FOLDERS, "crumbs": crumbs[::-1]}
