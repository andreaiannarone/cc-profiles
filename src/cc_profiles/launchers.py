# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Launchers (the command that starts Claude Code in a profile)."""

import os
import re
import shutil
import sys

from .byfolder import SHELL_MARK, SHELLS, pick, profile_dir, resolve, shell_line
from .core import ApiError, Backup, HOME, LAUNCHER_DIR, LAUNCHER_MARK, find_tool, load_config, pretty, write_text
from .projects import list_projects

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


# ---------------------------------------------------------------------------
# Profile by folder: one marked line in the shell rc files (see byfolder.py)
# ---------------------------------------------------------------------------
def user_shell():
    """zsh, bash or another shell's name: $SHELL, else the login shell."""
    name = os.path.basename(os.environ.get("SHELL", ""))
    if not name:
        try:
            import pwd
            name = os.path.basename(pwd.getpwuid(os.getuid()).pw_shell)
        except (ImportError, KeyError):
            name = ""
    return name


def has_shell_line(rc):
    try:
        with open(rc) as f:
            return any(l.rstrip().endswith(SHELL_MARK) for l in f)
    except OSError:
        return False


def shell_targets():
    """(rc file, shell) pairs that turning it on writes, among the files rewrite_alias
    knows: ~/.zshrc when it exists or the shell is zsh; with bash, ~/.bashrc and
    ~/.bash_profile when they exist (when neither does, the one bash reads at login
    on this system is created)."""
    zshrc, bashrc, bash_profile = RC_FILES
    sh, out = user_shell(), []
    if sh == "zsh" or os.path.exists(zshrc):
        out.append((zshrc, "zsh"))
    if sh == "bash":
        found = [f for f in (bashrc, bash_profile) if os.path.exists(f)]
        out += [(f, "bash") for f in found or [bash_profile if sys.platform == "darwin" else bashrc]]
    return out


def shell_state():
    """GET /api/shell: where the line is, where it would go, the rules and the profile
    `cc-profiles which` gives each project the app knows. Read-only."""
    cfg = load_config()
    labels = {p["id"]: p["label"] for p in cfg["profiles"]}
    rules = [{"text": r.get("exact") or r.get("match"), "exact": "exact" in r, "profile": r["profile"],
              "label": "every profile" if r["profile"] == "shared" else labels.get(r["profile"], r["profile"])}
             for r in cfg["rules"] if r.get("exact") or r.get("match")]
    projects = []
    for row in list_projects():
        if row["path"]:
            pid, p = pick(cfg, row["path"])
            projects.append({"path": row["pretty"], "rule": pid,
                             "profile": p["id"] if p else None, "label": p["label"] if p else None})
    return {"installed": [pretty(f) for f in RC_FILES if has_shell_line(f)],
            "targets": [{"file": pretty(f), "shell": sh, "line": shell_line(sh)} for f, sh in shell_targets()],
            "shell": user_shell(), "lines": {sh: shell_line(sh) for sh in SHELLS},
            "on_path": bool(find_tool("cc-profiles")), "rules": rules, "projects": projects}


def shell_which(path):
    """GET /api/shell/which: the profile `claude` would get in a folder. Read-only."""
    path = (path or "").strip()
    if not path:
        raise ApiError("Type a folder, e.g. ~/code/work/api")
    if not os.path.isabs(os.path.expanduser(path)):
        raise ApiError("Use an absolute folder, or one starting with ~")
    full = resolve(path)
    pid, p = pick(load_config(), full)
    return {"path": pretty(full), "exists": os.path.isdir(full), "rule": pid,
            "profile": p["id"] if p else None, "label": p["label"] if p else None,
            "dir": pretty(profile_dir(p)) if p else None,
            "default": bool(p) and profile_dir(p) == os.path.join(HOME, ".claude")}


def op_shell(install):
    """POST /api/shell: add the marked line to the shell rc files, or remove it.
    Only that line is touched, and every file is backed up first."""
    if not install:
        return remove_shell_line()
    targets = shell_targets()
    if not targets:
        raise ApiError(f"Your shell is {user_shell() or 'unknown'}, not zsh or bash: add the output of "
                       "cc-profiles shell-init bash to its startup file by hand")
    todo = [(rc, sh) for rc, sh in targets if not has_shell_line(rc)]
    if not todo:
        return {"message": "Already on: claude picks the profile from the folder"}
    bk = Backup("shell-on", "Pick the profile from the folder when running claude")
    for rc, sh in todo:
        bk.copy(rc, os.path.basename(rc))
        text = open(rc).read() if os.path.exists(rc) else ""
        if text and not text.endswith("\n"):
            text += "\n"
        write_text(rc, text + shell_line(sh) + "\n")
        bk.note(f"Added to {pretty(rc)}: {shell_line(sh)}")
    files = ", ".join(pretty(rc) for rc, _ in todo)
    return {"message": f"On: added one line to {files}. Open a new terminal to use it", "backup": bk.close()}


def remove_shell_line():
    found = [rc for rc in RC_FILES if has_shell_line(rc)]
    if not found:
        return {"message": "Already off: no shell file has the line"}
    bk = Backup("shell-off", "Stop picking the profile from the folder")
    for rc in found:
        bk.copy(rc, os.path.basename(rc))
        lines = open(rc).read().split("\n")
        write_text(rc, "\n".join(l for l in lines if not l.rstrip().endswith(SHELL_MARK)))
        bk.note(f"Removed the line from {pretty(rc)}")
    files = ", ".join(pretty(rc) for rc in found)
    return {"message": f"Off: removed the line from {files}. Open a new terminal to use plain claude",
            "backup": bk.close()}
