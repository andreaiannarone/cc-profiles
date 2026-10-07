# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Slash command (/cc-profiles inside Claude Code)."""

import os
import sys

from .core import CONFIG_FILE, Backup, find_tool, load_config, pretty, profiles, write_json, write_text
from .sharing import primary, share_state

# ---------------------------------------------------------------------------
# Slash command (/cc-profiles inside Claude Code)
# ---------------------------------------------------------------------------
# A personal command in <profile>/commands/, so the name is just /cc-profiles
# (plugin commands always get a "plugin:" prefix). The mark is a YAML comment in
# the frontmatter: Claude Code does not show it to the model, and only files with
# it may be rewritten. plugin/commands/open.md is the same text, without the mark
# and with plain `cc-profiles`. Claude Code puts the arguments (/cc-profiles restart)
# in place of $ARGUMENTS before it runs the ! line.
COMMAND_MARK = "# managed by cc-profiles"
COMMAND_NAME = "cc-profiles.md"
COMMAND_TEMPLATE = """---
{mark}description: Open the cc-profiles web UI to manage your Claude Code profiles
argument-hint: "[restart|stop]"
allowed-tools: Bash({exe} open:*)
---
!`{exe} open $ARGUMENTS`

Tell the user, in one short line, what the output above says: the URL where cc-profiles is open; that it was restarted, and that they should reload the page; that it was stopped or was not running; or why it did not start or stop.

If the output says the action is unknown, say that this command accepts nothing, `restart` or `stop`.

If the command was not found, cc-profiles was moved or uninstalled. Say that running `cc-profiles` once in a terminal fixes this command, and that if it is not installed, this installs it:

```sh
curl -fsSL https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/install.sh | sh
```
"""


def command_text(exe, mark=True):
    return COMMAND_TEMPLATE.format(mark=COMMAND_MARK + "\n" if mark else "", exe=exe)


def command_exe():
    """How /cc-profiles starts cc-profiles. Claude Code runs the ! line with the PATH of the
    terminal it was started from, which may not have the folder pipx, uv, pip --user or
    Homebrew put cc-profiles in: so an absolute path. A launcher found on PATH or in the usual
    folders comes first (~/.local/bin/cc-profiles, /opt/homebrew/bin/cc-profiles: they stay
    put across updates); else this Python with -m (pip --user, a checkout). The server
    rewrites the command at start when the answer changes. A path with spaces could not be
    matched by allowed-tools: plain `cc-profiles` then."""
    exe = find_tool("cc-profiles") or f"{sys.executable} -m cc_profiles"
    return exe if " " not in exe.replace(" -m cc_profiles", "") else "cc-profiles"


def is_our_command(path):
    try:
        with open(path) as f:
            return COMMAND_MARK in f.read(200)
    except OSError:
        return False


def command_state(dir_abs):
    """"missing", "outdated", "current" or "foreign" (a cc-profiles.md cc-profiles did not write)."""
    path = os.path.join(dir_abs, "commands", COMMAND_NAME)
    if not os.path.lexists(path):
        return "missing"
    if not is_our_command(path):
        return "foreign"
    with open(path) as f:
        return "current" if f.read() == command_text(command_exe()) else "outdated"


def write_command(dir_abs, bk, label):
    """Write /cc-profiles into a profile folder, inside an open backup. When the
    profile shares `commands`, the file is written through the link, into the source."""
    path = os.path.join(dir_abs, "commands", COMMAND_NAME)
    bk.mkdir(os.path.dirname(path))
    bk.copy(path, f"command-{label}")
    write_text(path, command_text(command_exe()))
    bk.note(f"/cc-profiles command: {pretty(path)}")


def command_wanted():
    """Whether cc-profiles adds /cc-profiles to profiles: "slash_command" in config.json is
    false after `cc-profiles install-command --off` (or install.sh --no-command)."""
    return load_config().get("slash_command") is not False


def ensure_command():
    """At every start of the server. The first time (no "slash_command" in config.json yet)
    /cc-profiles goes into every profile, as `install-command` does; after that only the
    copies cc-profiles wrote and an older version left behind are rewritten, so a command
    the user deleted stays deleted. Nothing happens with "slash_command": false.
    Returns (lines to print, backup path or None)."""
    setting = load_config().get("slash_command")
    if setting is False:
        return [], None
    return install_command(add_missing=setting is None, remember=setting is None, quiet=True)


def set_command_off():
    """`cc-profiles install-command --off`: stop adding and updating /cc-profiles. The files
    already written stay (see the Uninstall page to remove them)."""
    cfg = load_config()
    if cfg.get("slash_command") is False:
        return None
    bk = Backup("slash-command-off", "Stop adding the /cc-profiles command")
    bk.copy(CONFIG_FILE, "config.json")
    cfg["slash_command"] = False
    write_json(CONFIG_FILE, cfg)
    return bk.close()


def install_command(add_missing=True, remember=True, quiet=False):
    """Write /cc-profiles into every profile that does not get it through sharing: missing
    copies only with add_missing, outdated ones always. With remember, config.json records
    "slash_command": true. Returns (lines to print, backup path or None); quiet leaves out
    the profiles where nothing changed."""
    src, lines, bk = primary(), [], None
    skip = (lambda text: None) if quiet else lines.append  # a profile where nothing changes
    cfg = load_config()
    if remember and cfg.get("slash_command") is not True:
        bk = Backup("slash-command", "Add the /cc-profiles command")
        bk.copy(CONFIG_FILE, "config.json")
        cfg["slash_command"] = True
        write_json(CONFIG_FILE, cfg)
    for p in profiles():
        if p["id"] != src["id"] and share_state(p, "commands", "dir")["shared"]:
            skip(f"{p['label']}: shares commands with {src['label']}")
            continue
        if not os.path.isdir(p["dir_abs"]):
            skip(f"{p['label']}: skipped, {pretty(p['dir_abs'])} does not exist")
            continue
        path = os.path.join(p["dir_abs"], "commands", COMMAND_NAME)
        state = command_state(p["dir_abs"])
        if state == "foreign":
            skip(f"{p['label']}: skipped, {pretty(path)} exists and was not created by cc-profiles")
            continue
        if state == "current" or (state == "missing" and not add_missing):
            skip(f"{p['label']}: already up to date")
            continue
        if bk is None:
            bk = Backup("slash-command", "Update the /cc-profiles command" if state == "outdated" and not add_missing
                        else "Add the /cc-profiles command")
        write_command(p["dir_abs"], bk, p["id"])
        lines.append(f"{p['label']}: {'updated' if state == 'outdated' else 'added'} {pretty(path)}")
    return lines, (bk.close() if bk else None)
