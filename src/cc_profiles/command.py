# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Slash command (/cc-profiles inside Claude Code)."""

import os

from .core import Backup, pretty, profiles, write_text
from .sharing import primary, share_state

# ---------------------------------------------------------------------------
# Slash command (/cc-profiles inside Claude Code)
# ---------------------------------------------------------------------------
# A personal command in <profile>/commands/, so the name is just /cc-profiles
# (plugin commands always get a "plugin:" prefix). The mark is a YAML comment in
# the frontmatter: Claude Code does not show it to the model, and only files with
# it may be rewritten. plugin/commands/open.md is the same text without the mark.
COMMAND_MARK = "# managed by cc-profiles"
COMMAND_NAME = "cc-profiles.md"
COMMAND_TEXT = f"""---
{COMMAND_MARK}
description: Open the cc-profiles web UI to manage your Claude Code profiles
allowed-tools: Bash(cc-profiles open:*)
---
!`cc-profiles open`

Tell the user, in one short line, what the output above says: the URL where cc-profiles is open, or why it did not start.

If the `cc-profiles` command was not found, say that this command only opens the app and does not install it, and give this install command:

```sh
curl -fsSL https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/install.sh | sh
```
"""


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
    return "current" if open(path).read() == COMMAND_TEXT else "outdated"


def write_command(dir_abs, bk, label):
    """Write /cc-profiles into a profile folder, inside an open backup. When the
    profile shares `commands`, the file is written through the link, into the source."""
    path = os.path.join(dir_abs, "commands", COMMAND_NAME)
    bk.mkdir(os.path.dirname(path))
    bk.copy(path, f"command-{label}")
    write_text(path, COMMAND_TEXT)
    bk.note(f"/cc-profiles command: {pretty(path)}")


def install_command():
    """Write /cc-profiles into every profile that does not get it through sharing.
    Returns (lines to print, backup path or None)."""
    src, lines, bk = primary(), [], None
    for p in profiles():
        if p["id"] != src["id"] and share_state(p, "commands", "dir")["shared"]:
            lines.append(f"{p['label']}: shares commands with {src['label']}")
            continue
        if not os.path.isdir(p["dir_abs"]):
            lines.append(f"{p['label']}: skipped, {pretty(p['dir_abs'])} does not exist")
            continue
        path = os.path.join(p["dir_abs"], "commands", COMMAND_NAME)
        state = command_state(p["dir_abs"])
        if state == "foreign":
            lines.append(f"{p['label']}: skipped, {pretty(path)} exists and was not created by cc-profiles")
            continue
        if state == "current":
            lines.append(f"{p['label']}: already up to date")
            continue
        if bk is None:
            bk = Backup("slash-command", "Add the /cc-profiles command")
        write_command(p["dir_abs"], bk, p["id"])
        lines.append(f"{p['label']}: added {pretty(path)}")
    return lines, (bk.close() if bk else None)
